import ast
import pathlib
import json
import re

p = pathlib.Path("d:/PythonProjects/saleor")
genuine_sqls = []

with open("scratch/saleor_models_catalog.json", "r", encoding="utf-8") as f:
    gt_data = json.load(f)

all_tables = set(gt_data["catalog"]["tables"].keys())

sql_keywords = ["SELECT", "UPDATE", "INSERT", "DELETE", "ALTER TABLE", "CREATE TABLE", "DROP TABLE"]

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
            sql_text = None
            
            # RunSQL
            if isinstance(node.func, ast.Name) and node.func.id == "RunSQL":
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

            # cursor.execute (not GraphQL client.execute)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in ("execute", "executemany"):
                # verify it's a db cursor or db connection
                func_obj = node.func.value
                obj_name = ""
                if isinstance(func_obj, ast.Name):
                    obj_name = func_obj.id
                elif isinstance(func_obj, ast.Attribute):
                    obj_name = func_obj.attr
                
                # Exclude graphql client, test client
                if obj_name not in ("client", "api_client", "app_api_client", "user_api_client"):
                    if node.args:
                        arg0 = node.args[0]
                        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                            sql_text = arg0.value
                        elif isinstance(arg0, ast.Name) and arg0.id in str_constants:
                            sql_text = str_constants[arg0.id]

            if sql_text:
                upper = sql_text.upper().strip()
                if any(upper.startswith(kw) or f" {kw} " in upper for kw in sql_keywords):
                    found_tables = []
                    for tbl in all_tables:
                        if re.search(rf"\b{re.escape(tbl)}\b", sql_text, re.IGNORECASE):
                            found_tables.append(tbl)
                    
                    genuine_sqls.append({
                        "file": rel,
                        "lineno": node.lineno,
                        "sql": " ".join(sql_text.split())[:100],
                        "tables": found_tables,
                    })

print(f"Total genuine SQL executions: {len(genuine_sqls)}")
for s in genuine_sqls[:25]:
    print(f"  [{s['file']}:{s['lineno']}] tables={s['tables']}: {s['sql'][:65]}")
