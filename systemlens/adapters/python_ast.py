"""Python AST Static Analysis Adapter for SystemLens.

Performs static analysis of Python source trees to extract:
1. Function and file nodes (`Node(type=NodeType.FUNCTION)` and `Node(type=NodeType.FILE)`).
2. Structural ownership edges (`function -> file`, confidence=1.0).
3. Raw SQL literal detections via `sqlparse` (`function -> table`, confidence=0.85).
4. ORM call detections for SQLAlchemy and Django (`function -> table`, confidence=0.80).
5. Dynamic/unresolved database calls (`function -> table:unresolved`, confidence=0.15).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Iterable

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis
from sqlparse.tokens import DML, Keyword

from systemlens.inference.naming import pluralize
from systemlens.models import BASE_WEIGHTS, Edge, EdgeType, Node, NodeType

# Folders to ignore when recursively walking source directories
IGNORED_DIRS = {
    ".venv",
    "venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "node_modules",
    ".agents",
    ".gemini",
    "site-packages",
}

# SQL keywords that introduce table references
TABLE_INTRODUCING_KEYWORDS = {
    "FROM",
    "JOIN",
    "INNER JOIN",
    "LEFT JOIN",
    "RIGHT JOIN",
    "FULL JOIN",
    "CROSS JOIN",
    "INTO",
    "UPDATE",
    "TABLE",
}

NON_TABLE_WORDS = {
    "SELECT",
    "SET",
    "WHERE",
    "VALUES",
    "ORDER",
    "GROUP",
    "HAVING",
    "LIMIT",
    "OFFSET",
    "(",
    ")",
}


def extract_tables_from_sql(sql: str) -> list[str]:
    """
    Extract referenced table names from a raw SQL string using sqlparse.

    Handles SELECT, JOIN, INSERT INTO, UPDATE, DELETE FROM, subqueries,
    and schema-qualified table names (e.g. 'public.users' or 'users').
    """
    parsed = sqlparse.parse(sql)
    tables: list[str] = []

    def _is_subquery_identifier(token: Any) -> Parenthesis | None:
        if hasattr(token, "tokens"):
            for sub in token.tokens:
                if isinstance(sub, Parenthesis):
                    return sub
        return None

    def _traverse_tokens(tokens: Iterable[Any]) -> None:
        from_seen = False
        for token in tokens:
            if token.is_whitespace:
                continue

            # If token is a parenthesized subquery, recurse inside it
            if isinstance(token, Parenthesis):
                _traverse_tokens(token.tokens)
                continue

            val_upper = token.value.upper().strip()

            # Check if this token introduces a table
            if any(val_upper == kw or val_upper.endswith(" " + kw) for kw in TABLE_INTRODUCING_KEYWORDS):
                from_seen = True
                continue

            if from_seen:
                if isinstance(token, IdentifierList):
                    for id_token in token.get_identifiers():
                        sub_paren = _is_subquery_identifier(id_token)
                        if sub_paren:
                            _traverse_tokens(sub_paren.tokens)
                        else:
                            t_name = id_token.get_real_name() or id_token.get_name() or str(id_token).split()[0]
                            parent = id_token.get_parent_name()
                            full = f"{parent}.{t_name}" if parent else t_name
                            if full and full.upper() not in NON_TABLE_WORDS:
                                tables.append(full)
                    from_seen = False
                elif isinstance(token, Identifier):
                    sub_paren = _is_subquery_identifier(token)
                    if sub_paren:
                        _traverse_tokens(sub_paren.tokens)
                    else:
                        t_name = token.get_real_name() or token.get_name() or str(token).split()[0]
                        parent = token.get_parent_name()
                        full = f"{parent}.{t_name}" if parent else t_name
                        if full and full.upper() not in NON_TABLE_WORDS:
                            tables.append(full)
                    from_seen = False
                elif token.ttype is Keyword or token.ttype in DML:
                    from_seen = False
                else:
                    raw = token.value.strip().strip("`\"'")
                    if raw and raw.upper() not in NON_TABLE_WORDS:
                        first_word = raw.split()[0].rstrip(",;")
                        if first_word and first_word.upper() not in NON_TABLE_WORDS:
                            tables.append(first_word)
                    from_seen = False

    for stmt in parsed:
        _traverse_tokens(stmt.tokens)

    # Clean and deduplicate table names while preserving original order
    cleaned: list[str] = []
    for t in tables:
        t_clean = t.strip("`\"'() ;,")
        if t_clean and t_clean.lower() not in cleaned:
            cleaned.append(t_clean.lower())
    return cleaned


def _extract_django_model_name(node: ast.AST) -> str | None:
    """
    Detect if an AST call expression originates from a Django ORM query,
    e.g. `User.objects.filter(...)`, `Order.objects.all().order_by(...)`.
    Returns the root model class name (e.g. 'User') or None.
    """
    curr = node
    while isinstance(curr, ast.Attribute):
        if curr.attr == "objects" and isinstance(curr.value, ast.Name):
            return curr.value.id
        curr = curr.value
    return None


class PythonASTAdapter:
    """
    Static analyzer for Python codebases to map functions to database entities.
    """

    def __init__(
        self,
        root_dir: str | Path,
        known_tables: set[str] | list[str] | None = None,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.known_tables = set(known_tables or [])

        # Build table lookup map: bare table name -> schema qualified name
        # e.g. "users" -> "public.users"
        self.table_lookup: dict[str, str] = {}
        for full_tbl in self.known_tables:
            bare = full_tbl.split(".")[-1].lower()
            self.table_lookup.setdefault(bare, full_tbl)
            self.table_lookup[full_tbl.lower()] = full_tbl

        # Pre-scanned model registry: class_name -> db_table_name
        self.model_registry: dict[str, str] = {}
        self._pre_scan_models()

    def _should_skip_dir(self, dir_name: str) -> bool:
        return dir_name in IGNORED_DIRS or dir_name.startswith(".")

    def _iter_python_files(self) -> list[Path]:
        """Collect all relevant Python files in the source tree."""
        py_files: list[Path] = []
        if self.root_dir.is_file():
            if self.root_dir.suffix == ".py":
                return [self.root_dir]
            return []

        for root, dirs, files in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if not self._should_skip_dir(d)]
            for file in files:
                if file.endswith(".py") and not file.startswith(".#"):
                    py_files.append(Path(root) / file)
        return sorted(py_files)

    def _pre_scan_models(self) -> None:
        """
        Scan all Python files to build a registry of ORM classes to table names:
        - SQLAlchemy: `__tablename__ = 'users'`
        - Django: `class Meta: db_table = 'users'`
        """
        for py_file in self._iter_python_files():
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(py_file))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    for item in node.body:
                        # SQLAlchemy __tablename__ = "..."
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == "__tablename__":
                                    if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                                        self.model_registry[class_name] = item.value.value.lower()
                        # Django class Meta: db_table = "..."
                        elif isinstance(item, ast.ClassDef) and item.name == "Meta":
                            for meta_item in item.body:
                                if isinstance(meta_item, ast.Assign):
                                    for target in meta_item.targets:
                                        if isinstance(target, ast.Name) and target.id == "db_table":
                                            if isinstance(meta_item.value, ast.Constant) and isinstance(meta_item.value.value, str):
                                                self.model_registry[class_name] = meta_item.value.value.lower()

    def resolve_model_to_table(self, model_name: str) -> str:
        """
        Resolve an ORM model name (e.g. 'User', 'OrderItem') to a table name.
        Uses registry if known, otherwise converts PascalCase to snake_case plural.
        """
        if model_name in self.model_registry:
            return self.model_registry[model_name]

        # Convert PascalCase to snake_case: OrderItem -> order_item
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", model_name)
        snake = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

        # Pluralize: order_item -> order_items
        plural = pluralize(snake)
        return plural

    def resolve_table_node_id(self, raw_table: str) -> str:
        """
        Map a raw table name (e.g. 'users' or 'public.users') to its target node ID.
        If table exists in database lookup, returns schema-qualified ID.
        """
        lower = raw_table.lower()
        if lower in self.table_lookup:
            return f"table:{self.table_lookup[lower]}"
        return f"table:{raw_table}"

    def extract_nodes(self) -> list[Node]:
        """
        Extract all File and Function nodes across the Python codebase.
        """
        nodes: list[Node] = []

        for py_file in self._iter_python_files():
            rel_path = str(py_file.relative_to(self.root_dir)).replace("\\", "/")
            file_node_id = f"file:{rel_path}"

            nodes.append(
                Node(
                    id=file_node_id,
                    type=NodeType.FILE,
                    name=py_file.name,
                    source_system="python",
                    metadata={"path": rel_path, "size_bytes": py_file.stat().st_size},
                )
            )

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(py_file))
            except Exception as e:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    func_node_id = f"func:{rel_path}:{func_name}"
                    nodes.append(
                        Node(
                            id=func_node_id,
                            type=NodeType.FUNCTION,
                            name=func_name,
                            source_system="python",
                            metadata={
                                "file": rel_path,
                                "lineno": node.lineno,
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "docstring": ast.get_docstring(node),
                            },
                        )
                    )

        return nodes

    def extract_edges(self) -> list[Edge]:
        """
        Extract code-layer edges:
        - Structural edges: Function -> File
        - Static SQL edges: Function -> Table (0.85)
        - ORM call edges: Function -> Table (0.80)
        - Dynamic unresolved edges: Function -> table:unresolved (0.15)
        """
        edges: list[Edge] = []

        for py_file in self._iter_python_files():
            rel_path = str(py_file.relative_to(self.root_dir)).replace("\\", "/")
            file_node_id = f"file:{rel_path}"

            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(py_file))
            except Exception:
                continue

            # Traverse the AST tracking the enclosing function
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    func_node_id = f"func:{rel_path}:{func_name}"

                    # 1. Structural ownership edge: Function -> File
                    edges.append(
                        Edge(
                            source=func_node_id,
                            target=file_node_id,
                            type=EdgeType.STRUCTURAL_BELONGS_TO,
                            confidence=BASE_WEIGHTS[EdgeType.STRUCTURAL_BELONGS_TO],
                            evidence=f"Defined in {rel_path}:{node.lineno}",
                            metadata={"lineno": node.lineno, "file": rel_path},
                        )
                    )

                    # 2. Inspect calls inside this function
                    seen_calls: set[tuple[str, str, int]] = set()

                    # Track local variables assigned string constants within this function
                    local_str_vars: dict[str, str] = {}
                    for stmt in ast.walk(node):
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if (
                                    isinstance(target, ast.Name)
                                    and isinstance(stmt.value, ast.Constant)
                                    and isinstance(stmt.value.value, str)
                                ):
                                    local_str_vars[target.id] = stmt.value.value

                    for sub_node in ast.walk(node):
                        if not isinstance(sub_node, ast.Call):
                            continue

                        # A) .execute(...) calls
                        if (
                            isinstance(sub_node.func, ast.Attribute)
                            and sub_node.func.attr in ("execute", "executemany")
                        ):
                            if not sub_node.args:
                                continue
                            first_arg = sub_node.args[0]

                            # Check for static SQL string: direct constant or local constant variable
                            sql_str = None
                            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                sql_str = first_arg.value
                            elif isinstance(first_arg, ast.Name) and first_arg.id in local_str_vars:
                                sql_str = local_str_vars[first_arg.id]

                            if sql_str is not None:
                                tables = extract_tables_from_sql(sql_str)
                                for tbl in tables:
                                    target_node_id = self.resolve_table_node_id(tbl)
                                    call_key = (func_node_id, target_node_id, sub_node.lineno)
                                    if call_key in seen_calls:
                                        continue
                                    seen_calls.add(call_key)

                                    edges.append(
                                        Edge(
                                            source=func_node_id,
                                            target=target_node_id,
                                            type=EdgeType.STATIC_SQL_STRING,
                                            confidence=BASE_WEIGHTS[EdgeType.STATIC_SQL_STRING],
                                            evidence=(
                                                f"SQL literal execution in {rel_path}:{sub_node.lineno} -> {tbl}: "
                                                f"{sql_str.strip()[:80]}"
                                            ),
                                            metadata={
                                                "lineno": sub_node.lineno,
                                                "file": rel_path,
                                                "raw_sql": sql_str.strip(),
                                                "table": tbl,
                                            },
                                        )
                                    )
                            # Dynamic unresolved query (f-string, variable, concat, format)
                            else:
                                call_key = (func_node_id, "table:unresolved", sub_node.lineno)
                                if call_key not in seen_calls:
                                    seen_calls.add(call_key)
                                    arg_type = type(first_arg).__name__
                                    edges.append(
                                        Edge(
                                            source=func_node_id,
                                            target="table:unresolved",
                                            type=EdgeType.DYNAMIC_UNRESOLVED,
                                            confidence=BASE_WEIGHTS[EdgeType.DYNAMIC_UNRESOLVED],
                                            evidence=(
                                                f"Dynamic unresolved query call ({arg_type}) "
                                                f"in {rel_path}:{sub_node.lineno}"
                                            ),
                                            metadata={
                                                "lineno": sub_node.lineno,
                                                "file": rel_path,
                                                "arg_type": arg_type,
                                                "unresolved": True,
                                            },
                                        )
                                    )

                        # B) SQLAlchemy .query(Model)
                        elif isinstance(sub_node.func, ast.Attribute) and sub_node.func.attr == "query":
                            for arg in sub_node.args:
                                model_name = None
                                if isinstance(arg, ast.Name):
                                    model_name = arg.id
                                elif isinstance(arg, ast.Attribute):
                                    model_name = arg.attr

                                if model_name and model_name[0].isupper():
                                    tbl = self.resolve_model_to_table(model_name)
                                    target_node_id = self.resolve_table_node_id(tbl)
                                    call_key = (func_node_id, target_node_id, sub_node.lineno)
                                    if call_key in seen_calls:
                                        continue
                                    seen_calls.add(call_key)

                                    edges.append(
                                        Edge(
                                            source=func_node_id,
                                            target=target_node_id,
                                            type=EdgeType.ORM_CALL,
                                            confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                                            evidence=(
                                                f"SQLAlchemy query({model_name}) call in "
                                                f"{rel_path}:{sub_node.lineno} -> {tbl}"
                                            ),
                                            metadata={
                                                "lineno": sub_node.lineno,
                                                "file": rel_path,
                                                "model": model_name,
                                                "table": tbl,
                                                "orm": "sqlalchemy",
                                            },
                                        )
                                    )

                        # C) SQLAlchemy select(Model)
                        elif isinstance(sub_node.func, ast.Name) and sub_node.func.id == "select":
                            for arg in sub_node.args:
                                model_name = None
                                if isinstance(arg, ast.Name):
                                    model_name = arg.id
                                elif isinstance(arg, ast.Attribute):
                                    model_name = arg.attr

                                if model_name and model_name[0].isupper():
                                    tbl = self.resolve_model_to_table(model_name)
                                    target_node_id = self.resolve_table_node_id(tbl)
                                    call_key = (func_node_id, target_node_id, sub_node.lineno)
                                    if call_key in seen_calls:
                                        continue
                                    seen_calls.add(call_key)

                                    edges.append(
                                        Edge(
                                            source=func_node_id,
                                            target=target_node_id,
                                            type=EdgeType.ORM_CALL,
                                            confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                                            evidence=(
                                                f"SQLAlchemy select({model_name}) call in "
                                                f"{rel_path}:{sub_node.lineno} -> {tbl}"
                                            ),
                                            metadata={
                                                "lineno": sub_node.lineno,
                                                "file": rel_path,
                                                "model": model_name,
                                                "table": tbl,
                                                "orm": "sqlalchemy",
                                            },
                                        )
                                    )

                        # D) Django Model.objects.filter()
                        else:
                            django_model = _extract_django_model_name(sub_node.func)
                            if django_model:
                                tbl = self.resolve_model_to_table(django_model)
                                target_node_id = self.resolve_table_node_id(tbl)
                                call_key = (func_node_id, target_node_id, sub_node.lineno)
                                if call_key in seen_calls:
                                    continue
                                seen_calls.add(call_key)

                                edges.append(
                                    Edge(
                                        source=func_node_id,
                                        target=target_node_id,
                                        type=EdgeType.ORM_CALL,
                                        confidence=BASE_WEIGHTS[EdgeType.ORM_CALL],
                                        evidence=(
                                            f"Django {django_model}.objects call in "
                                            f"{rel_path}:{sub_node.lineno} -> {tbl}"
                                        ),
                                        metadata={
                                            "lineno": sub_node.lineno,
                                            "file": rel_path,
                                            "model": django_model,
                                            "table": tbl,
                                            "orm": "django",
                                        },
                                    )
                                )

        return edges
