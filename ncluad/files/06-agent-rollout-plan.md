# Agent rollout plan — fix before build

## Context
Review of the execution flow found: no validation anywhere, confidence weights that are guessed not measured, the core clustering/catalog feature never built, a confidence number that overclaims precision, a CI-diff feature shipped before the core was proven, and a silent switch from "VS Code extension" to "CLI-only" that was never decided on purpose. This plan fixes that, in order.

## Gate 0 — freeze
Before starting Phase A: stop adding new adapters (no more JS analysis, no more pipelines). Every hour spent widening scope right now is an hour not spent finding out if what's already built is correct.

## Sequence (do not skip or reorder)

| Phase | File | What it fixes | Must pass before next phase |
|---|---|---|---|
| A | `07-validation-harness.md` | Zero evidence anything is accurate | Precision/recall measured on real schema |
| B | `08-weight-calibration.md` | BASE_WEIGHTS are guesses | Calibration curve roughly diagonal |
| C | `09-catalog-clustering-engine.md` | Core "group tables into modules" feature missing | ARI vs known module split passes threshold |
| D | `10-confidence-presentation-fix.md` | Single % overclaims precision | User output shows tier + evidence, not naked float |
| — | `11-ci-diff-gate.md` | CI-diff shipped before core proven | Unlocked only when A–D all pass |
| — | `12-surface-decision.md` | CLI vs extension never decided | Written decision exists in repo |

Phase A through D are sequential — each depends on the data the previous one produces. The CI gate and surface decision can be done anytime but must be written down explicitly, not left implicit in whatever got coded.

## Definition of done for this whole plan
A fresh reviewer can open the repo, read one file (`validation_report.json` + the decision doc), and know: how accurate is this, on what evidence, and why does it currently work the way it works. Right now none of that exists.
