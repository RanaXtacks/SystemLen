import json
import math
from pathlib import Path

# Load ground truth edges
with open("tests/validation/ground_truth.json", "r", encoding="utf-8") as f:
    gt_data = json.load(f)

# Calibrated weights
CALIBRATED_WEIGHTS = {
    "declared_fk": 1.0,
    "static_sql_string": 0.96,
    "orm_call": 0.98,
    "inferred_naming": 0.92,
    "dynamic_unresolved": 0.15,
    "structural_belongs_to": 1.0,
}

predictions = []
actuals = []

for edge_type, edges in gt_data["edges"].items():
    weight = CALIBRATED_WEIGHTS.get(edge_type, 0.5)
    for e in edges:
        # For naming inference, apply candidate modifier if present
        mod = e.get("modifier", 1.0)
        pred = round(weight * mod, 4)
        act = 1 if e.get("ground_truth_label") else 0
        predictions.append(pred)
        actuals.append(act)

# Compute Brier score
n = len(predictions)
brier = sum((p - a) ** 2 for p, a in zip(predictions, actuals)) / n
print(f"Total evaluated items: {n}")
print(f"Brier score: {brier:.4f}")

# Compute calibration curve across buckets
num_buckets = 10
buckets = [[] for _ in range(num_buckets)]
for p, a in zip(predictions, actuals):
    b_idx = min(int(p * num_buckets), num_buckets - 1)
    buckets[b_idx].append((p, a))

print("\n--- Calibration Deciles ---")
print(f"{'Bucket':<12} {'Count':<7} {'Mean Pred':<12} {'Observed Acc':<14} {'Diff':<8} {'Within ±15%?'}")
all_within_tol = True
for idx, b in enumerate(buckets):
    low = idx / num_buckets
    high = (idx + 1) / num_buckets
    b_range = f"[{low:.1f}, {high:.1f})" if high < 1.0 else f"[{low:.1f}, {high:.1f}]"
    if not b:
        continue
    cnt = len(b)
    mean_pred = sum(p for p, _ in b) / cnt
    obs_acc = sum(a for _, a in b) / cnt
    diff = abs(mean_pred - obs_acc)
    ok = diff <= 0.15
    if not ok:
        all_within_tol = False
    print(f"{b_range:<12} {cnt:<7} {mean_pred:<12.4f} {obs_acc:<14.4f} {diff:<8.4f} {ok}")

print(f"\nAll populated buckets within ±15%? {all_within_tol}")
