"""JavaScript and TypeScript Static Analysis Adapter for SystemLens.

Performs static analysis of JS/TS codebases (.js, .jsx, .ts, .tsx, .mjs, .cjs) using
robust regex pattern matching to extract:
1. Function and file nodes (NodeType.FUNCTION, NodeType.FILE).
2. Structural ownership edges (function -> file, confidence=1.0).
3. Raw SQL literal detections (query, execute, template literals) via sqlparse (confidence=0.85).
4. ORM calls for Prisma, Sequelize, Knex (confidence=0.80).
5. Dynamic unresolved queries (confidence=0.15).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from systemlens.adapters.base import SourceAdapter
from systemlens.adapters.python_ast import IGNORED_DIRS, extract_tables_from_sql
from systemlens.inference.naming import pluralize
from systemlens.models import BASE_WEIGHTS, Edge, EdgeType, Node, NodeType

JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


class JavaScriptASTAdapter(SourceAdapter):
    """
    Static analyzer for JavaScript and TypeScript codebases.
    Extracts database dependencies across raw SQL clients (pg, mysql2),
    query builders (Knex), and ORMs (Prisma, Sequelize).
    """

    # Regex patterns for JavaScript/TypeScript function declarations
    FUNCTION_PATTERNS = [
        # function foo(...) or async function foo(...)
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\("),
        # const foo = (...) => or const foo = async (...) =>
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>"),
        # const foo = function(...) or const foo = async function(...)
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s+)?function\b"),
        # Class or object method: foo(...) { or async foo(...) {
        re.compile(r"^\s*(?:async\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*\{"),
    ]

    # Knex query builder: knex('users') or knex("orders")
    KNEX_PATTERN = re.compile(r"\bknex\s*\(\s*['\"]([a-zA-Z0-9_]+)['\"]\s*\)")

    # Prisma Client: prisma.user.findMany(...) or prisma.order.create(...)
    PRISMA_PATTERN = re.compile(
        r"\bprisma\.([a-zA-Z0-9_]+)\.(?:findMany|findUnique|findFirst|create|createMany|update|updateMany|upsert|delete|deleteMany|count|aggregate|groupBy)\s*\("
    )

    # Sequelize Model: User.findAll(...) or Order.create(...)
    SEQUELIZE_PATTERN = re.compile(
        r"\b([A-Z][a-zA-Z0-9_]+)\.(?:findAll|findOne|findByPk|findOrCreate|create|bulkCreate|update|destroy|count)\s*\("
    )

    # SQL in template strings or function calls: client.query(`SELECT ...`), db.raw("SELECT ...")
    RAW_SQL_CALL_PATTERN = re.compile(
        r"(?:\.query|\.raw|\.execute)\s*\(\s*[`'\"]([^`'\"]*(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE)[^`'\"]*)[`'\"]",
        re.IGNORECASE,
    )

    # Standalone SQL template literals: sql`SELECT ...` or `SELECT * FROM ...`
    TEMPLATE_SQL_PATTERN = re.compile(
        r"[`]([^`]*(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE)[^`]*)[`]",
        re.IGNORECASE,
    )

    # Dynamic query execution: client.query(queryVar) without string quotes
    DYNAMIC_QUERY_PATTERN = re.compile(
        r"(?:\.query|\.execute|\.raw)\s*\(\s*([a-zA-Z_$][a-zA-Z0-9_$]*)\s*[,)]"
    )

    def __init__(
        self,
        src_dir: str | Path,
        schema_file: Optional[str | Path] = None,
    ) -> None:
        self.src_dir = Path(src_dir).resolve()
        self.schema_file = Path(schema_file).resolve() if schema_file else None

        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self._analyzed = False

        # Known tables from schema file
        self.known_tables: set[str] = set()
        self._load_schema()

    def _load_schema(self) -> None:
        if self.schema_file and self.schema_file.exists():
            try:
                with open(self.schema_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if "tables" in data:
                    for tbl_key, tbl_info in data["tables"].items():
                        name = tbl_info.get("name", tbl_key.split(".")[-1])
                        self.known_tables.add(name.lower())
                elif "nodes" in data:
                    for n in data["nodes"]:
                        if n.get("type") in ("table", "view"):
                            self.known_tables.add(n.get("name", "").lower())
            except Exception:
                pass

    def _should_skip_dir(self, dir_name: str) -> bool:
        return dir_name in IGNORED_DIRS or dir_name.startswith(".")

    def analyze(self) -> None:
        """Analyze all JavaScript and TypeScript files in src_dir."""
        if self._analyzed:
            return

        self.nodes.clear()
        self.edges.clear()

        if self.src_dir.is_file():
            if self.src_dir.suffix.lower() in JS_EXTENSIONS:
                self._analyze_file(self.src_dir)
        else:
            for root, dirs, files in os.walk(self.src_dir):
                dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]
                for file_name in files:
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext in JS_EXTENSIONS:
                        file_path = Path(root) / file_name
                        self._analyze_file(file_path)

        self._analyzed = True

    def _analyze_file(self, file_path: Path) -> None:
        try:
            rel_path = file_path.relative_to(self.src_dir).as_posix()
        except ValueError:
            rel_path = file_path.as_posix()

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        lines = content.splitlines()

        # Add File Node
        file_node_id = f"file:{rel_path}"
        self.nodes.append(
            Node(
                id=file_node_id,
                type=NodeType.FILE,
                name=rel_path,
                source_system="javascript",
                metadata={"path": rel_path, "lines_count": len(lines)},
            )
        )

        # Parse functions and their line ranges
        functions = self._extract_functions(lines, rel_path)

        # If no functions found, treat whole file as a global module scope
        if not functions:
            functions.append({
                "name": "<module>",
                "id": f"func:{rel_path}:<module>",
                "start_line": 1,
                "end_line": len(lines),
            })

        for fn in functions:
            fn_id = fn["id"]
            fn_name = fn["name"]
            start = fn["start_line"]
            end = fn["end_line"]

            # Add Function Node (if not already added)
            if not any(n.id == fn_id for n in self.nodes):
                self.nodes.append(
                    Node(
                        id=fn_id,
                        type=NodeType.FUNCTION,
                        name=fn_name,
                        source_system="javascript",
                        metadata={
                            "file": rel_path,
                            "lineno": start,
                            "end_lineno": end,
                        },
                    )
                )

            # Add Structural Edge (function -> file)
            self.edges.append(
                Edge(
                    source=fn_id,
                    target=file_node_id,
                    type=EdgeType.STRUCTURAL_BELONGS_TO,
                    confidence=1.0,
                    evidence=f"{fn_name} in {rel_path}:{start}",
                    metadata={"file": rel_path, "lineno": start},
                )
            )

            # Analyze function body text
            fn_lines = lines[start - 1 : end]
            fn_body = "\n".join(fn_lines)
            self._analyze_function_body(fn_id, fn_name, fn_body, rel_path, start)

    def _extract_functions(self, lines: list[str], rel_path: str) -> list[dict[str, Any]]:
        """Identify function signatures and estimate their bounds."""
        funcs: list[dict[str, Any]] = []

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("//") or line_stripped.startswith("/*"):
                continue

            for pattern in self.FUNCTION_PATTERNS:
                m = pattern.match(line)
                if m:
                    func_name = m.group(1)
                    # Ignore common JS keywords that look like function calls
                    if func_name in ("if", "for", "while", "switch", "catch", "return"):
                        continue

                    func_id = f"func:{rel_path}:{func_name}"
                    # Simple heuristic for end line: until next function or EOF
                    funcs.append({
                        "name": func_name,
                        "id": func_id,
                        "start_line": i + 1,
                        "end_line": len(lines),
                    })
                    break

        # Adjust end lines so each function ends before the next starts
        for idx in range(len(funcs) - 1):
            funcs[idx]["end_line"] = funcs[idx + 1]["start_line"] - 1

        return funcs

    def _analyze_function_body(
        self,
        fn_id: str,
        fn_name: str,
        body: str,
        rel_path: str,
        base_line: int,
    ) -> None:
        seen_targets: set[str] = set()

        # 1. Knex query builder
        for m in self.KNEX_PATTERN.finditer(body):
            table = m.group(1).lower()
            target_id = f"table:{table}"
            if target_id not in seen_targets:
                seen_targets.add(target_id)
                self.edges.append(
                    Edge(
                        source=fn_id,
                        target=target_id,
                        type=EdgeType.ORM_CALL,
                        confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                        evidence=m.group(0),
                        metadata={"file": rel_path, "lineno": base_line, "framework": "knex"},
                    )
                )

        # 2. Prisma Client
        for m in self.PRISMA_PATTERN.finditer(body):
            model_name = m.group(1).lower()
            table = pluralize(model_name)
            target_id = f"table:{table}"
            if target_id not in seen_targets:
                seen_targets.add(target_id)
                self.edges.append(
                    Edge(
                        source=fn_id,
                        target=target_id,
                        type=EdgeType.ORM_CALL,
                        confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                        evidence=m.group(0),
                        metadata={"file": rel_path, "lineno": base_line, "framework": "prisma"},
                    )
                )

        # 3. Sequelize Models
        for m in self.SEQUELIZE_PATTERN.finditer(body):
            model_name = m.group(1)
            # Avoid matching standard builtins like Promise, Object, JSON
            if model_name in ("Promise", "Object", "Array", "JSON", "Math", "Date", "String", "Number"):
                continue
            table = pluralize(model_name.lower())
            target_id = f"table:{table}"
            if target_id not in seen_targets:
                seen_targets.add(target_id)
                self.edges.append(
                    Edge(
                        source=fn_id,
                        target=target_id,
                        type=EdgeType.ORM_CALL,
                        confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                        evidence=m.group(0),
                        metadata={"file": rel_path, "lineno": base_line, "framework": "sequelize"},
                    )
                )

        # 4. Raw SQL calls and Template literals
        for pattern in (self.RAW_SQL_CALL_PATTERN, self.TEMPLATE_SQL_PATTERN):
            for m in pattern.finditer(body):
                sql_text = m.group(1).strip()
                tables = extract_tables_from_sql(sql_text)
                for tbl in tables:
                    clean_tbl = tbl.split(".")[-1].lower()
                    target_id = f"table:{clean_tbl}"
                    if target_id not in seen_targets:
                        seen_targets.add(target_id)
                        self.edges.append(
                            Edge(
                                source=fn_id,
                                target=target_id,
                                type=EdgeType.STATIC_SQL_STRING,
                                confidence=BASE_WEIGHTS[EdgeType.STATIC_SQL_STRING],
                                evidence=sql_text[:100],
                                metadata={"file": rel_path, "lineno": base_line, "sql": sql_text[:150]},
                            )
                        )

        # 5. Dynamic unresolved queries
        for m in self.DYNAMIC_QUERY_PATTERN.finditer(body):
            var_name = m.group(1)
            # Ensure it is not a string literal
            if not var_name.startswith(("'", '"', "`")):
                unresolved_id = "table:unresolved"
                self.edges.append(
                    Edge(
                        source=fn_id,
                        target=unresolved_id,
                        type=EdgeType.DYNAMIC_UNRESOLVED,
                        confidence=BASE_WEIGHTS[EdgeType.DYNAMIC_UNRESOLVED],
                        evidence=m.group(0),
                        metadata={"file": rel_path, "lineno": base_line, "var": var_name},
                    )
                )

    def extract_nodes(self) -> list[Node]:
        self.analyze()
        return self.nodes

    def extract_edges(self) -> list[Edge]:
        self.analyze()
        return self.edges

    def extract_raw_catalog(self) -> dict[str, Any]:
        self.analyze()
        return {
            "source_type": "javascript",
            "nodes_count": len(self.nodes),
            "edges_count": len(self.edges),
            "files_count": len([n for n in self.nodes if n.type == NodeType.FILE]),
            "functions_count": len([n for n in self.nodes if n.type == NodeType.FUNCTION]),
        }
