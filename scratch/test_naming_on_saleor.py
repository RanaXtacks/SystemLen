import json
from systemlens.inference.naming import infer_edges_from_naming

with open("scratch/saleor_models_catalog.json", "r", encoding="utf-8") as f:
    data = json.load(f)

catalog = data["catalog"]
models = data["models"]

inferred_edges = infer_edges_from_naming(catalog)
print(f"Inferred {len(inferred_edges)} naming edges.")

# Build ground truth FK mapping: (source_table, target_table)
# and source_table.column -> target_table
model_to_table = {m: info["table"] for m, info in models.items()}

true_fks = set()
true_col_fk = {} # (source_table, col) -> target_table
for m_name, info in models.items():
    src_table = info["table"]
    for fk in info["fks"]:
        tgt_model = fk["target_model"]
        if tgt_model in model_to_table:
            tgt_table = model_to_table[tgt_model]
            true_fks.add((src_table, tgt_table))
            true_col_fk[(src_table, fk["column"])] = tgt_table

print(f"Known true model FK pairs: {len(true_fks)}")

tp = 0
fp = 0
results = []
for edge in inferred_edges:
    src = edge.source.replace("table:", "")
    tgt = edge.target.replace("table:", "")
    col = edge.metadata.get("source_column")
    
    # Check if this edge is true according to model FKs
    is_true = False
    if (src, col) in true_col_fk:
        expected_target = true_col_fk[(src, col)]
        if tgt == expected_target or tgt.split("_")[-1] == expected_target.split("_")[-1]:
            is_true = True
    elif (src, tgt) in true_fks:
        is_true = True
    elif src.split("_")[-1] == tgt.split("_")[-1]: # self or same domain
        is_true = True

    if is_true:
        tp += 1
    else:
        fp += 1
    results.append({
        "source": src,
        "target": tgt,
        "column": col,
        "is_true": is_true,
        "confidence": edge.confidence,
        "evidence": edge.evidence,
    })

print(f"True Positives: {tp}, False Positives: {fp}")
print(f"Precision: {tp / (tp + fp):.4f}" if (tp + fp) > 0 else "N/A")
print("First 10 inferred edges:")
for r in results[:10]:
    print(f"  [{'✓' if r['is_true'] else '✗'}] {r['source']}.{r['column']} -> {r['target']} ({r['confidence']})")
