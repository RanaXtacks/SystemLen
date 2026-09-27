# Rule: Relational Edge Inference and Multi-Source Merging

## Context
Inferring relationships from database column naming conventions (e.g., `user_id` -> `users`, `usr_id` -> `users`, `shipping_address_id` -> `addresses`) requires probabilistic scoring and careful disambiguation to prevent false-positive graph pollution.

## Rules
1. **Confidence Scoring Formula**:
   - Follow `tech.md`: `c(edge) = base_weight × modifiers`.
   - Base weight for `inferred_naming` is `0.55`.
   - Modifiers must be applied selectively: `1.0` for exact/pluralized matches, `0.9` for fuzzy/abbreviation/role-prefixed matches (`c = 0.495`).
   - Round confidence scores to 4 decimal places (`round(confidence, 4)`) to avoid floating-point drift.
2. **Schema-Aware Target Disambiguation**:
   - In multi-schema databases, if candidate target tables exist in both the source schema and foreign schemas, always prioritize the table in the same schema (`target_schema == source_schema`).
3. **Self-Reference Handling**:
   - Suppress trivial self-loops (e.g. `users.user_id` inside `users`).
   - Preserve valid hierarchical self-references (e.g. `categories.parent_category_id` in `categories`).
4. **Agreement Detection & Merging**:
   - When `declared_fk` and `inferred_naming` both identify the same `(source, target)` pair, record cross-evidence agreement (`naming_agreement = True`, `declared_agreement = True`, `agreement_bonus = 1.0`).
   - Support a unified edge list preserving distinguishable edge classes by default, with optional deduplication.
5. **Precision Kill Check Protocol**:
   - Before proceeding across layers, test inferred edges against a hand-checked multi-table fixture with negative controls.
   - The false positive rate must remain strictly below 30% (ideally 0%).
