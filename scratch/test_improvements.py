import ast
import json
import os
import re
from pathlib import Path

# Load Saleor ground truth
with open("scratch/saleor_models_catalog.json", "r", encoding="utf-8") as f:
    gt_data = json.load(f)

gt_models = gt_data["models"]
gt_catalog = gt_data["catalog"]
model_to_table = {m: info["table"] for m, info in gt_models.items()}
all_tables = set(gt_catalog["tables"].keys())

print(f"Loaded ground truth: {len(gt_models)} models, {len(all_tables)} tables.")

# Test 1: Naming inference with app-prefix stripping
from systemlens.inference.naming import generate_candidate_table_names

table_lookup = {}
for full_name, info in gt_catalog["tables"].items():
    bare = info["name"].lower()
    table_lookup.setdefault(bare, []).append(full_name)
    if "_" in bare:
        suffix = bare.split("_", 1)[1]
        table_lookup.setdefault(suffix, []).append(full_name)

gt_col_fks = {}
for m_name, info in gt_models.items():
    src_tbl = info["table"]
    for fk in info["fks"]:
        tgt_m = fk["target_model"]
        if tgt_m in model_to_table:
            gt_col_fks[(src_tbl, fk["column"])] = model_to_table[tgt_m]

inferred_naming_edges = []
for src_tbl, info in gt_catalog["tables"].items():
    src_app = src_tbl.split("_", 1)[0]
    for col in info["columns"]:
        col_name = col["name"]
        if col_name.endswith("_id"):
            stem = col_name[:-3]
            for cand, mod in generate_candidate_table_names(stem):
                targets = table_lookup.get(cand, [])
                if targets:
                    same_app = [t for t in targets if t.startswith(src_app + "_")]
                    target = same_app[0] if same_app else targets[0]
                    if target != src_tbl:
                        inferred_naming_edges.append({
                            "source": src_tbl,
                            "column": col_name,
                            "target": target,
                            "is_correct": gt_col_fks.get((src_tbl, col_name)) == target,
                        })
                    break

print(f"Naming edges: {len(inferred_naming_edges)}")
tp_naming = sum(1 for e in inferred_naming_edges if e["is_correct"])
prec_naming = tp_naming / len(inferred_naming_edges)
print(f"Naming Precision: {prec_naming:.4f} ({tp_naming}/{len(inferred_naming_edges)})")

# Test 2: ORM calls in Saleor order module with known model mapping
# Let's inspect AST of saleor/order files
order_dir = Path("d:/PythonProjects/saleor/saleor/order")
orm_edges = []

for py_path in order_dir.rglob("*.py"):
    if ".venv" in str(py_path): continue
    try:
        content = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content)
    except Exception:
        continue
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check Model.objects.filter()
            curr = node.func
            model_name = None
            while isinstance(curr, ast.Attribute):
                if curr.attr == "objects" and isinstance(curr.value, ast.Name):
                    model_name = curr.value.id
                    break
                curr = curr.value
            
            if model_name and model_name[0].isupper() and model_name in gt_models:
                target_table = model_to_table[model_name]
                orm_edges.append({
                    "model": model_name,
                    "target_table": target_table,
                    "file": str(py_path.name),
                    "is_correct": True, # mapped directly via ground truth model registry!
                })

print(f"ORM edges extracted in saleor/order: {len(orm_edges)}")

# Test 3: Static SQL strings in Saleor
sql_files = [
    Path("d:/PythonProjects/saleor/saleor/discount/models.py"),
    Path("d:/PythonProjects/saleor/saleor/order/models.py"),
    Path("d:/PythonProjects/saleor/saleor/order/migrations/0139_fix_undiscounted_total_on_lines.py"),
    Path("d:/PythonProjects/saleor/saleor/account/migrations/0063_save_customerevent_order_token.py"),
]
sql_edges = []
for p in sql_files:
    if p.exists():
        content = p.read_text(encoding="utf-8", errors="ignore")
        # Find raw SQL literals
        for match in re.finditer(r'execute\s*\(\s*("""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^"]*"|\'[^\']*\')', content):
            raw_sql = match.group(1).strip("\"'")
            if any(kw in raw_sql.upper() for kw in ("SELECT", "UPDATE", "INSERT", "DELETE")):
                # Check tables mentioned in SQL
                for tbl in all_tables:
                    if re.search(rf"\b{re.escape(tbl)}\b", raw_sql, re.IGNORECASE):
                        sql_edges.append({
                            "sql": raw_sql[:60].strip(),
                            "table": tbl,
                            "is_correct": True,
                        })

print(f"Static SQL edges found in sample files: {len(sql_edges)}")
