import ast
import pathlib
import json
import re

p = pathlib.Path("d:/PythonProjects/saleor")
sql_calls = []

with open("scratch/saleor_models_catalog.json", "r", encoding="utf-8") as f:
    gt_data = json.load(f)

all_tables = set(gt_data["catalog"]["tables"].keys())

for py_path in p.rglob("*.py"):
    if ".venv" in str(py_path):
        continue
    try:
        content = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content, filename=str(py_path))
    except Exception:
        continue

    rel = str(py_path.relative_to(p))

    # Track string constants in the module/function
    str_constants = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        str_constants[t.id] = node.value.value

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            is_sql_call = False
            sql_text = None
            
            # 1. RunSQL(sql, ...)
            if isinstance(node.func, ast.Name) and node.func.id == "RunSQL":
                is_sql_call = True
                if node.args:
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        sql_text = arg0.value
                    elif isinstance(arg0, ast.Name) and arg0.id in str_constants:
                        sql_text = str_constants[arg0.id]
                for kw in node.keywords:
                    if kw.arg == "sql":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            sql_text = kw.value.value
                        elif isinstance(kw.value, ast.Name) and kw.value.id in str_constants:
                            sql_text = str_constants[kw.value.id]

            # 2. cursor.execute(sql, ...)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany"):
                is_sql_call = True
                if node.args:
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        sql_text = arg0.value
                    elif isinstance(arg0, ast.Name) and arg0.id in str_constants:
                        sql_text = str_constants[arg0.id]

            # 3. Model.objects.raw(sql, ...)
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "raw":
                is_sql_call = True
                if node.args:
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        sql_text = arg0.value
                    elif isinstance(arg0, ast.Name) and arg0.id in str_constants:
                        sql_text = str_constants[arg0.id]

            if is_sql_call and sql_text:
                # Find which tables are referenced
                found_tables = []
                for tbl in all_tables:
                    if re.search(rf"\b{re.escape(tbl)}\b", sql_text, re.IGNORECASE):
                        found_tables.append(tbl)
                
                sql_calls.append({
                    "file": rel,
                    "lineno": node.lineno,
                    "sql_text": " ".join(sql_text.split())[:120],
                    "tables": found_tables,
                })

print(f"Total resolved static SQL queries with tables: {len(sql_calls)}")
for item in sql_calls[:15]:
    print(f"  [{item['file']}:{item['lineno']}] tables={item['tables']}: {item['sql_text'][:70]}")
