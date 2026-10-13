import json
import math
import random
from collections import Counter
from pathlib import Path

# Load extracted Saleor ground truth models & catalog
with open("scratch/saleor_models_catalog.json", "r", encoding="utf-8") as f:
    gt_data = json.load(f)

gt_models = gt_data["models"]      # ModelName -> {app, table, fields, fks}
gt_catalog = gt_data["catalog"]    # tables -> {name, schema, columns}

print(f"Loaded ground truth: {len(gt_models)} models, {len(gt_catalog['tables'])} tables.")

# Ground truth model-to-table lookup
model_to_table = {m: info["table"] for m, info in gt_models.items()}
all_tables = set(gt_catalog["tables"].keys())

# Ground truth ForeignKeys: (source_table, column) -> target_table
gt_col_fks = {}
for m_name, info in gt_models.items():
    src_tbl = info["table"]
    for fk in info["fks"]:
        tgt_m = fk["target_model"]
        if tgt_m in model_to_table:
            gt_col_fks[(src_tbl, fk["column"])] = model_to_table[tgt_m]

print(f"Loaded ground truth FK relationships: {len(gt_col_fks)}")

# Wilson interval function
def wilson_interval(p_hat: float, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    denom = 1.0 + (z**2) / n
    center = (p_hat + (z**2) / (2 * n)) / denom
    margin = (z * math.sqrt((p_hat * (1 - p_hat)) / n + (z**2) / (4 * n**2))) / denom
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (center, lower, upper)

print("Wilson function defined.")
