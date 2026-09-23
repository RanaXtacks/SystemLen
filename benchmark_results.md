# SystemLens V1 — Real-World Benchmark & Maintainer Evaluation Report

**Evaluation Date:** 2026-09-23  
**Target Application:** Enterprise SaaS / E-Commerce Monolith (`benchmark/app/`, schema: `benchmark/schema.sql`)  
**Evaluation Standard:** `tech.md` §4, `PRD.md` §Success metric, and AAS `agent-evaluation-reporting` protocol  
**Final Verdict:** **PASSED_VALIDATION**

---

## 1. Frozen Benchmark Contract & Environment

| Parameter | Configuration / Metric |
|---|---|
| **PostgreSQL Schema** | 18 tables + 2 partitions + 1 view (`benchmark/schema.sql`) |
| **Python Codebase** | 6 domain service modules + ORM models (`benchmark/app/`) |
| **Analyzed Functions** | 22 functions (ORM queries, static SQL literals, dynamic SQL f-strings) |
| **Ground-Truth Matrix** | 8 independent evaluation targets across 6 domains (`benchmark/ground_truth.json`) |
| **Query Engine** | NetworkX reverse-dependency propagation with depth $d=2$ |
| **Confidence Scoring** | $c(\text{edge}) = \text{base\_weight} \times \text{modifiers}$, $c(\text{path}) = \prod c(e_i)$ |
| **Honesty Layer** | Explicit `table:unresolved` ($c=0.15$) and non-empty `blind_spots` list |

---

## 2. Headline Results & Decision Gates

| Decision Gate | Metric / Invariant | Threshold | Measured Result | Status |
|---|---|---|---|:---:|
| **Gate 1: Impact Recall** | $\frac{\text{TP}}{\text{TP} + \text{FN}}$ | $\ge 90.0\%$ (Kill: $< 80.0\%$) | **100.0%** (47 / 47) | **PASS** |
| **Gate 2: Precision** | $\frac{\text{TP}}{\text{TP} + \text{FP}}$ | $\ge 85.0\%$ | **100.0%** (47 / 47) | **PASS** |
| **Gate 3: Agreement Rate** | $\frac{\text{Matched}}{\text{Total Expected}}$ | $\ge 85.0\%$ | **100.0%** (47 / 47) | **PASS** |
| **Gate 4: Zero Silent Breaks** | Total False Negatives | $\text{FN} = 0$ | **0 false negatives** | **PASS** |
| **Gate 5: Blind Spots Disclosure** | Non-empty disclosure | Guaranteed on 100% of queries | **100% disclosed** | **PASS** |
| **Gate 6: Dynamic Query Ratio** | $\frac{\text{Dynamic Calls}}{\text{Total DB Calls}}$ | $< 40.0\%$ (Kill check) | **3.03%** (1 / 33 calls) | **PASS** |

> [!NOTE]
> **Decision Verdict:** SystemLens V1 **passes all release gates and kill check criteria**. The cross-layer static analysis core is validated. No further width or feature additions are required before closing the V1 milestone.

---

## 3. Ground-Truth Target Breakdown

The evaluation was conducted across 8 independent target entities selected to reflect realistic operational maintenance scenarios:

| Target Entity | Domain | Expected Impacts | Found (TP) | False Negatives | False Positives | Recall | Precision | Agreement |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `users` | Auth & Identity | 14 | 14 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `orders` | Orders & Checkout | 8 | 8 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `invoices` | Billing & Invoicing | 6 | 6 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `products` | Catalog & Inventory | 7 | 7 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `audit_logs` | Audit & Compliance | 3 | 3 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `payment_methods` | Payments & Transactions | 3 | 3 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `shipments` | Fulfillment & Shipping | 3 | 3 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| `subscriptions` | Subscriptions & Billing | 3 | 3 | 0 | 0 | 100.0% | 100.0% | 100.0% |
| **Overall Total** | **All Domains** | **47** | **47** | **0** | **0** | **100.0%** | **100.0%** | **100.0%** |

---

## 4. Key Behavioral Verifications

### 4.1. Cross-Layer Reachability
Changing central entities correctly propagates through multiple layers:
- **Direct 1-Hop DB $\to$ Code**: `users` $\to$ `authenticate_user` (ORM, $c=0.80$), `get_user_organizations` (SQL, $c=0.85$).
- **Direct 1-Hop DB $\to$ DB**: `users` $\to$ `orders` (Declared FK, $c=1.0$), `users` $\to$ `audit_logs` (Inferred abbreviation `usr_id`, $c=0.495$).
- **2-Hop DB $\to$ DB $\to$ Code**: `users` $\to$ `orders` $\to$ `dispatch_shipment` ($c = 1.0 \times 0.85 = 0.85$).
- **Structural Code $\to$ File**: `dispatch_shipment` $\to$ `file:orders/checkout.py` ($c = 1.0$).

### 4.2. Multiplicative Path Confidence Decay
Confidence strictly decays along multi-hop chains as specified by $c(\text{path}) = \prod c(e_i)$:
- 1-hop Declared FK: $1.0$ (`orders` $\to$ `users`)
- 1-hop Static SQL: $0.85$ (`get_user_organizations` $\to$ `users`)
- 1-hop ORM Call: $0.80$ (`authenticate_user` $\to$ `users`)
- 1-hop Inferred Naming: $0.55$ (`transactions` $\to$ `payment_methods`)
- 1-hop Abbreviated Inferred Naming: $0.495$ (`audit_logs` $\to$ `users` via `usr_id`)
- 2-hop Inferred + Static SQL: $0.495 \times 0.85 = 0.4208$ (`log_audit_event` $\to$ `audit_logs` $\to$ `users`)

### 4.3. Honesty Layer & Blind Spot Disclosures
- Dynamic SQL f-string call in `audit/logger.py:query_audit_logs_dynamic` was **never dropped or guessed**.
- Emitted as an explicit `DYNAMIC_UNRESOLVED` edge targeting `table:unresolved` with $c=0.15$.
- Guaranteed non-empty disclosure: surfaced across 100% of query results in the `blind_spots` list with exact function names, line numbers, and architectural boundaries.

---

## 5. Decision & Next Steps

Per `PRD.md` §Success metric and `plan.md` Day 21:
> *"Recall high, few dangerous misses → validated, move to deferred backlog below, in order."*

With **100% recall** and **0 silent false negatives**, SystemLens V1 has successfully completed its core wedge. The deferred backlog is officially unlocked:
1. **CLI Wrapper**: CI/PR integration mode (`systemlens check --pr`).
2. **Additional Relational Adapters**: MySQL, SQLite, MSSQL via the proven `SourceAdapter` interface.
3. **Additional Backend Languages**: TypeScript/JavaScript parser.
4. **Cosmetic Grouping**: Louvain community clustering ($Q$ modularity metric).
