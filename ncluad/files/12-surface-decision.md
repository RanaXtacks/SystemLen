# Decision — primary surface: CLI vs VS Code extension

## Problem
Original plan said VS Code extension first, for distribution (devs already live in their IDE). What actually got built is CLI-only, with a CI pipeline on top. That's a real pivot, but it happened by drift — nobody decided it, it's just what got coded. An undocumented pivot means the next person (or the next agent session) doesn't know which surface is "the product."

## Decision criteria (from earlier reasoning in this project)
- **CLI** earns its place when there's a CI/PR use case, or a batch/non-interactive need. Both are now true — `ci-diff` exists and depends on CLI invocation.
- **VS Code extension** earns its place when there's an individual-developer exploration need: search, browse the catalog, click through relationships interactively. That need is real but nothing currently serves it, because Phase C (clustering) — the thing worth browsing — didn't exist until this plan.

## Recommendation
Keep CLI as the primary surface for now — it already matches the demonstrated real use case (CI integration), and ripping it out to start an extension would waste working infrastructure. Treat the VS Code extension as a deliberate Phase F, started only after Phase C (clustering) ships, because browsing a catalog is the extension's actual reason to exist — building the extension shell before there's a catalog to browse just reproduces the "UI before core" mistake from the CI-diff case.

## Action required
This is not optional busywork — write the decision down. Add `ARCHITECTURE_DECISIONS.md` to the repo with:
- The decision (CLI primary, extension deferred to post-Phase-C).
- The date and the reasoning above.
- The condition under which this gets revisited (e.g. "if a non-engineer or cross-repo user need emerges, reconsider web dashboard before extension").

## Non-goal
Don't build both surfaces in parallel "to be safe." That splits effort across two UIs for a core that's still being validated in Phases A–D.
