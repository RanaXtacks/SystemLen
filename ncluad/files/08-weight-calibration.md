# Phase B — Weight calibration

## Problem
`BASE_WEIGHTS` in `models.py` (0.55 naming, 0.85 SQL, 0.80 ORM, 0.15 dynamic) are hand-picked numbers presented as if they were measured probabilities. The multiplication math (`path_confidence = Π edge.confidence`) is legitimate; the inputs feeding it are not.

## Goal
Replace guessed constants with numbers backed by Phase A's measurements, and verify the final output is actually calibrated — meaning "85% confidence" is correct about 85% of the time.

## Where
`models.py: BASE_WEIGHTS`. Depends on `validation_report.json` from Phase A.

## Method
1. **Replace constants directly**: set `BASE_WEIGHTS[edge_type] = measured_precision` from `validation_report.json`, not the current hand-picked values.
2. **If an edge type has multiple contributing signals** (e.g. naming match + row-value overlap check both support one inferred FK), don't hand-multiply two guessed numbers — fit a simple logistic regression on the labeled sample from Phase A:
```
P(correct) = 1 / (1 + e^-(β0 + β1·signal1 + β2·signal2))
```
Use this fitted probability as the edge's confidence instead of an arbitrary product.
3. **Check calibration, not just accuracy.** Bucket all final path-confidence scores from a validation run into deciles (0.0-0.1, 0.1-0.2, ... 0.9-1.0). For each bucket, compute the actual fraction of paths that were correct (against hand-labeled ground truth). Plot predicted-confidence vs observed-accuracy per bucket — this is a **calibration curve**. A well-calibrated system sits close to the diagonal (predicted ≈ observed).
4. Optionally report a single summary number, the **Brier score**:
```
Brier = (1/N) Σ (predicted_i - actual_i)²
```
Lower is better; 0 is perfect, 0.25 is "no better than guessing 50/50."

## Acceptance criteria (gate to Phase C)
- Calibration curve within roughly ±15% of the diagonal per bucket with adequate sample size.
- Re-run Phase A's validation script after recalibration — precision/recall should not have gotten worse.

## Non-goal
Don't chase a perfect calibration curve before moving on — "roughly diagonal" is the bar. Perfect calibration on a single test schema is itself overfitting; the point is to stop shipping numbers with zero empirical basis, not to produce a flawless model.
