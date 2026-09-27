"""SystemLens CI/PR Integration Module.

Provides:
1. Git diff parsing to identify changed files between branches or commits.
2. Cross-referencing changed files with graph.json to detect affected tables.
3. Automated blast radius impact analysis on all affected tables.
4. Markdown and JSON report generation suitable for GitHub Actions PR comments.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from systemlens.models import EdgeType, NodeType
from systemlens.query.impact import ImpactEngine, ImpactResult


@dataclass
class CISummary:
    """Summary metrics of the CI impact analysis."""
    total_changed_files: int
    total_affected_tables: int
    total_impacted_entities: int
    max_blast_radius: int
    high_risk_changes: list[str]  # Tables with blast_radius >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_changed_files": self.total_changed_files,
            "total_affected_tables": self.total_affected_tables,
            "total_impacted_entities": self.total_impacted_entities,
            "max_blast_radius": self.max_blast_radius,
            "high_risk_changes": self.high_risk_changes,
        }


@dataclass
class CIDiffReport:
    """Complete report of a CI diff impact run."""
    changed_files: list[str]
    affected_tables: list[str]
    impact_results: list[ImpactResult]
    summary: CISummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "affected_tables": self.affected_tables,
            "impact_results": [r.to_dict() for r in self.impact_results],
            "summary": self.summary.to_dict(),
        }


def parse_diff_output(diff_text: str) -> list[str]:
    """Parse output from git diff --name-only into normalized relative file paths."""
    files: list[str] = []
    for line in diff_text.strip().splitlines():
        cleaned = line.strip().replace("\\", "/").lstrip("./")
        if cleaned:
            files.append(cleaned)
    return files


def parse_git_diff(
    base: str = "origin/main",
    head: str = "HEAD",
    cwd: Optional[str] = None,
) -> list[str]:
    """
    Run `git diff --name-only` to identify changed files between base and head refs.

    Tries `base...head` (merge-base) first. If that fails (e.g. shallow clone
    or disconnected refs), falls back to `base..head`.

    Args:
        base: Git base ref or commit SHA (e.g. origin/main, HEAD~1).
        head: Git head ref or commit SHA (e.g. HEAD, PR commit).
        cwd: Optional working directory for git process.

    Returns:
        List of normalized changed file paths.
    """
    # 1. Try triple-dot diff (merge-base)
    cmd = ["git", "diff", "--name-only", f"{base}...{head}"]
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return parse_diff_output(res.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 2. Try two-dot diff
    cmd_fallback = ["git", "diff", "--name-only", base, head]
    try:
        res = subprocess.run(
            cmd_fallback,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return parse_diff_output(res.stdout)
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.strip() if e.stderr else str(e)
        raise RuntimeError(f"Git diff failed for {base}..{head}: {stderr_msg}") from e
    except FileNotFoundError as e:
        raise RuntimeError("git executable not found in PATH") from e


def _normalize_path(p: str) -> str:
    """Normalize a path to lower-case POSIX style without leading './'."""
    return p.strip().replace("\\", "/").lstrip("./").lower()


def _paths_match(path_a: str, path_b: str) -> bool:
    """Check if two file paths refer to the same file (exact or path suffix match)."""
    a = _normalize_path(path_a)
    b = _normalize_path(path_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return a.endswith(f"/{b}") or b.endswith(f"/{a}")


def detect_affected_tables(
    changed_files: list[str],
    graph_data: dict[str, Any],
    root_dir: Optional[str] = None,
) -> list[str]:
    """
    Cross-reference changed files with graph.json to identify all affected database tables.

    Detection mechanisms:
    1. Python files: Match functions located in changed files, then follow outgoing
       SQL/ORM edges from those functions to database tables.
    2. Structural edges: `func -> file:path` mapped to changed files.
    3. SQL files: Read SQL content or filenames to match table names in the schema.
    4. Direct metadata: Table/view nodes whose metadata points to a changed file.

    Args:
        changed_files: List of file paths modified in the commit or PR.
        graph_data: Parsed graph.json dictionary containing nodes and edges.
        root_dir: Optional project root to read changed .sql files from disk.

    Returns:
        Sorted list of affected table names (e.g. ['orders', 'users']).
    """
    if not changed_files or not graph_data:
        return []

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    node_map = {n["id"]: n for n in nodes}
    table_nodes = [
        n for n in nodes
        if n.get("type") in (NodeType.TABLE.value, NodeType.VIEW.value)
    ]

    # Map table_id to friendly table name
    table_names_by_id: dict[str, str] = {}
    for t in table_nodes:
        name = t.get("name", t["id"].replace("table:", ""))
        if name != "<unresolved_dynamic_query>":
            table_names_by_id[t["id"]] = name

    all_table_names = set(table_names_by_id.values())

    affected_tables: set[str] = set()

    # Step 1: Identify all function nodes that belong to any changed file
    changed_func_ids: set[str] = set()

    for node in nodes:
        if node.get("type") != NodeType.FUNCTION.value:
            continue

        func_id = node["id"]
        # Check metadata file
        meta_file = (
            node.get("metadata", {}).get("file")
            or node.get("metadata", {}).get("filepath")
            or node.get("metadata", {}).get("path")
        )
        if meta_file and any(_paths_match(meta_file, cf) for cf in changed_files):
            changed_func_ids.add(func_id)
            continue

        # Check func ID format `func:<filepath>:<func_name>`
        parts = func_id.split(":")
        if len(parts) >= 3:
            file_part = parts[1]
            if any(_paths_match(file_part, cf) for cf in changed_files):
                changed_func_ids.add(func_id)

    # Also check structural edges (func -> file:path)
    for edge in edges:
        if edge.get("type") == EdgeType.STRUCTURAL_BELONGS_TO.value:
            target = edge["target"]
            file_path = target.replace("file:", "")
            if any(_paths_match(file_path, cf) for cf in changed_files):
                changed_func_ids.add(edge["source"])

    # Step 2: Trace outgoing edges from changed functions to database tables
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")

        if source in changed_func_ids:
            # Check if target is a table
            if target in table_names_by_id:
                affected_tables.add(table_names_by_id[target])
            elif target and target.startswith("table:"):
                raw_name = target.replace("table:", "").split(".")[-1]
                if raw_name in all_table_names:
                    affected_tables.add(raw_name)

    # Step 3: Handle .sql files (migrations, queries, DDL)
    sql_files = [cf for cf in changed_files if cf.endswith(".sql")]
    for sql_file in sql_files:
        sql_content = ""
        full_path = Path(root_dir) / sql_file if root_dir else Path(sql_file)
        if full_path.exists():
            try:
                sql_content = full_path.read_text(encoding="utf-8")
            except Exception:
                sql_content = ""

        # Search for each known table name in the SQL file or in the SQL filename
        # Use lookbehind/lookahead excluding alphanumerics so tokens like '001_create_users.sql' match 'users'
        for tbl_name in all_table_names:
            tbl_regex = re.compile(
                rf"(?<![a-zA-Z0-9]){re.escape(tbl_name)}(?![a-zA-Z0-9])",
                re.IGNORECASE,
            )
            if tbl_regex.search(sql_file) or (sql_content and tbl_regex.search(sql_content)):
                affected_tables.add(tbl_name)

    # Step 4: Handle direct file-to-table metadata mapping
    for t_node in table_nodes:
        t_meta_file = t_node.get("metadata", {}).get("file")
        if t_meta_file and any(_paths_match(t_meta_file, cf) for cf in changed_files):
            name = t_node.get("name", t_node["id"].replace("table:", ""))
            if name != "<unresolved_dynamic_query>":
                affected_tables.add(name)

    return sorted(list(affected_tables))


def run_ci_impact(
    changed_files: list[str],
    graph_data: dict[str, Any],
    max_depth: int = 2,
    min_confidence: float = 0.0,
    high_risk_threshold: int = 5,
    root_dir: Optional[str] = None,
) -> CIDiffReport:
    """
    Run full impact analysis for changed files in CI.

    Args:
        changed_files: List of files changed in the PR or diff.
        graph_data: Unified cross-layer graph data.
        max_depth: Traversal depth for blast radius query (default 2).
        min_confidence: Minimum path confidence threshold (default 0.0).
        high_risk_threshold: Blast radius count to trigger high-risk flag.
        root_dir: Project root directory.

    Returns:
        CIDiffReport with all impact details, blast radius, and summary.
    """
    affected_tables = detect_affected_tables(
        changed_files=changed_files,
        graph_data=graph_data,
        root_dir=root_dir,
    )

    engine = ImpactEngine(graph_data)
    impact_results: list[ImpactResult] = []

    for table in affected_tables:
        res = engine.blast_radius(
            target=table,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )
        impact_results.append(res)

    total_impacted = sum(r.total_impacted for r in impact_results)
    max_blast = max((r.total_impacted for r in impact_results), default=0)
    high_risk = [
        r.target_name
        for r in impact_results
        if r.total_impacted >= high_risk_threshold
    ]

    summary = CISummary(
        total_changed_files=len(changed_files),
        total_affected_tables=len(affected_tables),
        total_impacted_entities=total_impacted,
        max_blast_radius=max_blast,
        high_risk_changes=high_risk,
    )

    return CIDiffReport(
        changed_files=changed_files,
        affected_tables=affected_tables,
        impact_results=impact_results,
        summary=summary,
    )


def format_markdown_report(
    report: CIDiffReport,
    high_risk_threshold: int = 5,
) -> str:
    """
    Format a CIDiffReport into a GitHub-friendly markdown comment.
    """
    lines: list[str] = []
    lines.append("## 🔍 SystemLens Impact Analysis\n")

    if not report.changed_files:
        lines.append("ℹ️ **No changed files detected between base and head refs.**\n")
        return "\n".join(lines)

    lines.append(f"### Changed Files ({len(report.changed_files)})")
    for f in report.changed_files[:15]:
        lines.append(f"- `{f}`")
    if len(report.changed_files) > 15:
        lines.append(f"- *...and {len(report.changed_files) - 15} more files*")
    lines.append("")

    if not report.affected_tables:
        lines.append("✅ **No database tables or downstream dependencies affected by this change.**\n")
        return "\n".join(lines)

    summary = report.summary
    lines.append("### 📊 Blast Radius Summary")
    lines.append(f"- **Affected Tables:** `{summary.total_affected_tables}`")
    lines.append(f"- **Total Impacted Entities:** `{summary.total_impacted_entities}`")
    lines.append(f"- **Max Blast Radius:** `{summary.max_blast_radius}`")

    if summary.high_risk_changes:
        tables_str = ", ".join(f"`{t}`" for t in summary.high_risk_changes)
        lines.append(
            f"- ⚠️ **High Risk Changes (≥{high_risk_threshold} entities):** {tables_str}"
        )
    lines.append("")

    lines.append(f"### 🗄️ Affected Tables ({len(report.affected_tables)})\n")

    for res in report.impact_results:
        t_name = res.target_name
        lines.append(f"#### 🗄️ `{t_name}` — Blast Radius: {res.total_impacted} entities\n")

        if not res.ranked_items:
            lines.append("*No downstream code or relational dependencies detected.*\n")
            continue

        lines.append("| Type | Name | Confidence | Hop | Evidence / Location |")
        lines.append("|:---|:---|:---:|:---:|:---|")

        type_icons = {
            NodeType.FUNCTION.value: "⚡ Function",
            NodeType.FILE.value: "📄 File",
            NodeType.TABLE.value: "🗄️ Table",
            NodeType.VIEW.value: "👁️ View",
            NodeType.PARTITION.value: "📦 Partition",
        }

        # Show top 12 ranked items
        displayed_items = res.ranked_items[:12]
        for item in displayed_items:
            icon_type = type_icons.get(item.node_type, item.node_type.capitalize())
            conf_str = f"{item.confidence * 100:.1f}%"
            location = ""
            if item.metadata.get("file"):
                lineno = f":{item.metadata.get('lineno')}" if item.metadata.get("lineno") else ""
                location = f"`{item.metadata.get('file')}{lineno}`"
            elif item.evidence_chain:
                location = f"`{item.evidence_chain[-1]}`"

            lines.append(f"| {icon_type} | `{item.name}` | {conf_str} | {item.depth} | {location} |")

        if len(res.ranked_items) > 12:
            lines.append(f"\n<details><summary>View {len(res.ranked_items) - 12} more impacted entities...</summary>\n")
            lines.append("| Type | Name | Confidence | Hop | Evidence / Location |")
            lines.append("|:---|:---|:---:|:---:|:---|")
            for item in res.ranked_items[12:]:
                icon_type = type_icons.get(item.node_type, item.node_type.capitalize())
                conf_str = f"{item.confidence * 100:.1f}%"
                location = ""
                if item.metadata.get("file"):
                    lineno = f":{item.metadata.get('lineno')}" if item.metadata.get("lineno") else ""
                    location = f"`{item.metadata.get('file')}{lineno}`"
                elif item.evidence_chain:
                    location = f"`{item.evidence_chain[-1]}`"
                lines.append(f"| {icon_type} | `{item.name}` | {conf_str} | {item.depth} | {location} |")
            lines.append("\n</details>\n")
        else:
            lines.append("")

    # Aggregate blind spots
    seen_blind_spots = set()
    unique_blind_spots: list[dict[str, Any]] = []
    for res in report.impact_results:
        for bs in res.blind_spots:
            msg = bs.get("message", "")
            if msg and msg not in seen_blind_spots:
                seen_blind_spots.add(msg)
                unique_blind_spots.append(bs)

    if unique_blind_spots:
        lines.append("### ⚠️ Blind Spots (Honesty Layer)")
        for bs in unique_blind_spots:
            severity = bs.get("severity", "info").upper()
            msg = bs.get("message", "")
            icon = "🔴" if severity == "HIGH" else "🟡" if severity == "MEDIUM" else "ℹ️"
            lines.append(f"- {icon} **[{severity}]** {msg}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def format_json_report(report: CIDiffReport) -> str:
    """Format a CIDiffReport into formatted JSON string."""
    return json.dumps(report.to_dict(), indent=2)
