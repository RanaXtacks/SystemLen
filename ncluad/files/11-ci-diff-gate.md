# Feature gate — CI-diff pause

## Problem
`ci.py` / `systemlens ci-diff` was built and is already producing PR comments, before clustering existed, before any validation ran, and before confidence numbers were calibrated. This repeats a mistake already flagged once in this project: adding distribution surfaces before the core logic they depend on has been proven correct. A wrong blast-radius number in a PR comment is actively worse than no comment — a reviewer trusts it and merges.

## Goal
Keep the feature in the codebase, but gate it so it can't be relied on (or advertised) until the core is proven.

## Where
`ci.py`. Add an explicit flag requirement and a loud label.

## Method
1. Require an explicit `--experimental` flag to run `systemlens ci-diff` at all. Without it, the command exits with a message pointing to this gate.
2. Any markdown/JSON report it produces gets a visible header: `⚠ Experimental — impact confidence not yet validated against real-world accuracy.`
3. Document in the repo README that this command is unvalidated and why (link to Phase A/B/C status).

## Unlock condition
Remove the `--experimental` requirement only when all of the following are true:
- Phase A (`07-validation-harness.md`) validation report shows acceptable precision/recall.
- Phase B (`08-weight-calibration.md`) calibration curve passes.
- Phase C (`09-catalog-clustering-engine.md`) ARI/Q thresholds pass.
- Phase D (`10-confidence-presentation-fix.md`) is shipped, so the PR comment itself isn't showing a misleading float.

## Non-goal
Don't rip the feature out — the engineering is reasonable and the use case (CI/PR impact check) is genuinely valuable once trustworthy. The fix is sequencing, not deletion.
