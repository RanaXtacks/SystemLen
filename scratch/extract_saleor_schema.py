import ast
import json
import pathlib
import re

saleor_dir = pathlib.Path("d:/PythonProjects/saleor/saleor")

models = {}  # model_name -> {"app": ..., "table": ..., "fields": [], "fks": []}

for py_path in saleor_dir.rglob("models*.py"):
    if ".venv" in str(py_path):
        continue
    rel = py_path.relative_to(saleor_dir)
    app = rel.parts[0]
    
    try:
        content = py_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content, filename=str(py_path))
    except Exception:
        continue

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        
        # Check if inherits from Model
        is_model = False
        for base in node.bases:
            if isinstance(base, ast.Attribute) and base.attr in ("Model", "ModelWithMetadata"):
                is_model = True
            elif isinstance(base, ast.Name) and "Model" in base.id:
                is_model = True
        
        if not is_model:
            continue

        model_name = node.name
        table_name = f"{app}_{model_name.lower()}"
        
        # Check class Meta for db_table
        for item in node.body:
            if isinstance(item, ast.ClassDef) and item.name == "Meta":
                for m_item in item.body:
                    if isinstance(m_item, ast.Assign):
                        for t in m_item.targets:
                            if isinstance(t, ast.Name) and t.id == "db_table":
                                if isinstance(m_item.value, ast.Constant) and isinstance(m_item.value.value, str):
                                    table_name = m_item.value.value.lower()

        fields = []
        fks = []
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        field_name = target.id
                        # Check if ForeignKey
                        if isinstance(item.value, ast.Call):
                            func_str = ast.unparse(item.value.func)
                            if "ForeignKey" in func_str or "OneToOneField" in func_str:
                                target_model = None
                                if item.value.args:
                                    arg0 = item.value.args[0]
                                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                                        target_model = arg0.value.split(".")[-1]
                                    elif isinstance(arg0, ast.Name):
                                        target_model = arg0.id
                                    elif isinstance(arg0, ast.Attribute):
                                        target_model = arg0.attr
                                fks.append({
                                    "field": field_name,
                                    "column": f"{field_name}_id",
                                    "target_model": target_model,
                                })
                        fields.append(field_name)

        models[model_name] = {
            "app": app,
            "table": table_name,
            "fields": fields,
            "fks": fks,
        }

print(f"Extracted {len(models)} models from Saleor.")
total_fks = sum(len(m["fks"]) for m in models.values())
print(f"Extracted {total_fks} ForeignKeys from Saleor models.")

# Build catalog format for SystemLens naming inference
catalog = {"tables": {}}
for m_name, m_info in models.items():
    tbl = m_info["table"]
    cols = [{"name": "id"}]
    for fk in m_info["fks"]:
        cols.append({"name": fk["column"]})
    for f in m_info["fields"]:
        if f != "id" and not f.endswith("_id"):
            cols.append({"name": f})
    catalog["tables"][tbl] = {
        "name": tbl,
        "schema": "public",
        "columns": cols,
    }

with open("scratch/saleor_models_catalog.json", "w", encoding="utf-8") as f:
    json.dump({"models": models, "catalog": catalog}, f, indent=2)

print("Saved catalog to scratch/saleor_models_catalog.json")
