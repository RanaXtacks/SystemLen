# Phase D — Confidence presentation fix

## Problem
`impact.py` multiplies confidences across qualitatively different evidence types — schema certainty (FK), code-detection certainty (ORM/SQL parse), and structural certainty (file/function membership) — into one float, then displays it as "85.0%" in the CLI output. This reads as a calibrated probability even where the underlying evidence types were never designed to be commensurate. Phase B improves the inputs; this phase fixes how the output is shown so it stops overclaiming.

## Goal
Keep the internal scalar for ranking/sorting (it's useful for ordering results). Stop presenting it to the user as a bare, falsely precise percentage.

## Where
`impact.py` output formatting; CLI/report rendering functions.

## Method
1. **Internal score stays**: `path_confidence = Π edge.confidence` (now calibrated per Phase B) — keep using it to sort results, highest first.
2. **User-facing display changes to tiers**, with boundaries set from Phase B's calibration curve (not picked arbitrarily):
   - **High** — only deterministic edges in the path (FK, structural belongs-to).
   - **Medium** — includes at least one high-signal heuristic (ORM call, parsed SQL).
   - **Low** — includes naming-inference or dynamic-unresolved edges.
3. **Show the evidence chain, not just a number.** Instead of `[85.0%] get_user_organizations`, show `get_user_organizations — via FK → ORM call (Medium confidence)`. This tells the user *what kind* of evidence they're trusting, which a blended float hides.
4. Keep raw numeric score available behind a `--verbose` or `--json` flag for anyone who wants it — don't delete the data, just stop making it the headline in the default human-readable output.

## Acceptance criteria
- Default CLI output shows tier + evidence chain, not a naked percentage.
- Tier boundaries are documented as derived from the Phase B calibration curve, with the specific cutoff values stated (e.g. "High = calibration bucket where observed accuracy ≥ 0.85").
- Raw score still accessible via an explicit flag for programmatic use (e.g. the CI pipeline in Phase E can still consume the float).

## Non-goal
Don't invent new intermediate tiers beyond three — more granularity just reintroduces the same false-precision problem at a smaller scale.
