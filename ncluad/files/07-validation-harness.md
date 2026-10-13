# Phase A — Validation harness

## Problem
Every confidence number in the system (0.55, 0.85, 0.80, 0.15) was assigned by hand. Nobody has checked whether naming-inferred edges, ORM-detected edges, or SQL-parsed edges are actually correct at the rates implied. Ship nothing further until this exists.

## Goal
A repeatable script that runs the full pipeline against one real schema with known structure, and reports measured accuracy per edge type.

## Where
New directory `tests/validation/`. New script `validate.py`.

## Method
1. **Pick target**: one real open-source project with a non-trivial schema and available module documentation (e.g. Gitea, Discourse — something with 50+ tables and either docs or a maintainer-recognizable module split).
2. Run the existing pipeline end to end: ingest → naming inference → code analysis → `graph.json`.
3. **Hand-label a sample** of each edge type (not all — a sample is enough):
   - 50 naming-inferred edges: mark each true/false by checking the actual schema intent.
   - 50 ORM_CALL edges: check against actual model→table mapping.
   - 50 STATIC_SQL_STRING edges: check against actual query.
4. Compute per edge type:
```
precision = true_positives / (true_positives + false_positives)
recall    = true_positives / (true_positives + false_negatives)
```
5. Because sample size is small (~50), report a **95% Wilson score interval** around precision, not just the point estimate — a point value from 50 samples is easy to over-trust.
```
Wilson interval for p̂ with n samples, z=1.96:
center = (p̂ + z²/2n) / (1 + z²/n)
margin = z * sqrt(p̂(1-p̂)/n + z²/4n²) / (1 + z²/n)
```
6. Write results to `validation_report.json`: `{ edge_type, precision, interval, recall, sample_size, date, schema_used }`.

## Acceptance criteria (gate to Phase B)
- Naming inference precision ≥ 0.7 (lower bound of interval)
- ORM_CALL and STATIC_SQL_STRING precision ≥ 0.8 (these are labeled "high signal" — prove it)
- If any edge type fails, do not proceed to calibration with confidence — first improve the detection logic itself, then re-measure.

## Non-goal
Don't try to validate every edge — sampling is the point. Don't skip the Wilson interval and report only the raw percentage; a naked "92% precision" from 50 samples hides how uncertain that number really is.
