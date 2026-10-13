# SystemLens Architecture Decision Records (ADRs)

This document records the foundational architectural decisions governing SystemLens design, distribution surfaces, and quality gates.

---

## ADR-001: Primary Surface Strategy — CLI as Primary Surface; Extension Deferred to Post-Phase-C

- **Status:** Accepted / Active
- **Date:** October 13, 2026
- **Context:** [ncluad/files/12-surface-decision.md](ncluad/files/12-surface-decision.md)
- **Deciders:** SystemLens Core Team

### Context & Problem Statement
The original roadmap envisioned the VS Code extension as the initial primary distribution mechanism, operating under the assumption that developers work inside their IDEs. However, the implementation that evolved in practice focused on the CLI, with automated CI/PR analysis (`systemlens ci-diff`) built on top.

This pivot occurred organically through development drift without formal documentation. An undocumented surface pivot leaves subsequent contributors and agent sessions uncertain about which surface represents "the product," risking fragmented development across two distinct frontends before the underlying core analysis engine has been validated.

### Decision Criteria
1. **CLI Surface:** Earns its place when there is a CI/PR use case or a batch/non-interactive automation need. Both conditions are met: `systemlens ci-diff`, `systemlens impact`, and headless AST/SQL ingestion rely entirely on CLI invocation.
2. **VS Code Extension Surface:** Earns its place when there is an interactive exploration need: browsing a clustered catalog, navigating hierarchical domains, and clicking through relationships. That interactive catalog browsing requires Phase C (clustering engine) to provide semantic domain organization. Building or expanding extension UI before the clustering engine exists reproduces the "UI before core" failure mode.

### Decision
1. **CLI is the single primary surface** for SystemLens. All core features, query APIs, and automation workflows target the CLI first.
2. **The VS Code extension is formally frozen** and its expansion deferred to post-Phase-C. Existing v0.2.0 artifacts remain preserved as a proof-of-concept, but no engineering bandwidth will be allocated to extension development until Phase C ships.
3. **Do not develop both surfaces in parallel.** Developing two frontends simultaneously splits effort and distracts from core validation (Phases A–D).

### Conditions for Revisit
This decision will be formally revisited when:
1. **Phase C (Catalog Clustering Engine)** ships and satisfies modularity ($Q \ge 0.40$) and Adjusted Rand Index ($ARI \ge 0.70$) thresholds. At that point, a clustered catalog exists for an IDE extension to meaningfully browse.
2. **A non-engineer or cross-repository user need emerges**, at which point a lightweight web dashboard should be evaluated against an IDE extension before resuming extension work.

---

## ADR-002: Feature Gate on CI Impact Analysis (`systemlens ci-diff`)

- **Status:** Accepted / Active
- **Date:** October 13, 2026
- **Context:** [ncluad/files/11-ci-diff-gate.md](ncluad/files/11-ci-diff-gate.md)
- **Deciders:** SystemLens Core Team

### Context & Problem Statement
`systemlens ci-diff` generates automated PR comments assessing the blast radius of code changes. However, this feature was implemented before:
1. Edge extraction was validated on open-source ground truth (Phase A).
2. Edge type weights were empirically calibrated against precision (Phase B).
3. The catalog clustering engine was implemented (Phase C).
4. Confidence scores were categorized into discrete presentation tiers (Phase D).

A false negative or misleading float confidence in a PR comment can give code reviewers unwarranted confidence, leading to breaking database migrations or service outages.

### Decision
1. **Mandatory `--experimental` Flag:** `systemlens ci-diff` requires an explicit `--experimental` flag to run. Invocations without this flag immediately exit with code 1 and point to the gate documentation.
2. **Visible Report Header:** Every markdown and JSON report emitted by `ci-diff` includes the mandatory warning header:
   `⚠ Experimental — impact confidence not yet validated against real-world accuracy.`
3. **Non-Deletion:** The feature remains in the codebase with all existing tests intact. It is gated to prevent reliance on unvalidated data, not removed.

### Unlock Conditions
The `--experimental` requirement will be removed only when all of the following gates pass:
- **Phase A (`07-validation-harness.md`):** Real-world validation report shows empirical precision lower bounds meeting targets ($\ge 0.70$ for naming inference, $\ge 0.80$ for static SQL and ORM).
- **Phase B (`08-weight-calibration.md`):** BASE_WEIGHTS replaced by measured precision and calibration curve passes.
- **Phase C (`09-catalog-clustering-engine.md`):** Louvain clustering passes modularity $Q \ge 0.40$ and $ARI \ge 0.70$.
- **Phase D (`10-confidence-presentation-fix.md`):** Three-tier presentation (High/Medium/Low) replaces raw percentage floats in all PR comments.
