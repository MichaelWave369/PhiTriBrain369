# Rung 3a: WEAVER relationship proposals

WEAVER's first suggestion engine is **deterministic lexical pattern matching**. It does **not** understand meaning, measure truth, deduplicate historical claims, or run a language model.

It takes only WITNESS-recorded claims whose original source SHA-256 and quote offsets still verify. It proposes relations, preserving the complete original source and evidence.

## Preview (no relationship writes)

~~~bash
phitribrain weave --scope PhiOS
~~~

Optional controls:

~~~bash
phitribrain weave --scope PhiOS --threshold 0.65 --limit 20
~~~

- `--threshold` affects only keyword-overlap candidates. It accepts 0.3-1.0, default 0.72.
- `--limit` sets the maximum suggestions to return or create (1-100, default 30).
- A scope with more than **250 recorded claims** is rejected instead of silently considering just the first 250. Later rungs will add indexed candidate generation and pagination.
- The preview returns a proposed relation type, exact quote-anchored claim IDs, source IDs/digests, pattern name, explanation, and a lexical score.
- Preview of an uninitialized database fails without creating a new file.

## Explicitly save suggestions

~~~bash
phitribrain weave --scope PhiOS --apply
~~~

The action recomputes candidates under a SQLite write transaction, creates only `proposed` relations, records which deterministic heuristic generated each relation, and appends hash-chained audit events. It never alters, deletes, approves, or merges source claims.

Apply is idempotent against all existing links between a pair of claims, including manually proposed links, irrespective of relation direction or type. A failed batch rolls back its new relations and associated audit events.

## Three candidate patterns

| Pattern | Relationship stored | When it fires | Interpretation |
|---|---|---|---|
| `exact_text` | `related` | Normalized statement text is exactly equal | Possible duplicate statement, not proof that either source is trustworthy |
| `explicit_not_frame` | `contradicts` | The same auxiliary-verb phrase appears with and without a single `not` | Possible surface-level conflict that still requires human context review |
| `lexical_overlap` | `related` | At least three nontrivial content words overlap and Jaccard similarity meets the threshold | Shared terminology, not necessarily semantically related |

A lexical score is **not a calibrated confidence probability**. Even a score of 1.0 can describe two identical but incorrect claims or a false conflict caused by quotation, time, context, modality, or sarcasm.

For example, these two statements become a *candidate contradiction*:

- “The build is green”
- “The build is not green”

But the system cannot determine whether they refer to the same build, commit, timestamp, or test run. WITNESS source citations and time annotations still need to be inspected, and humans must resolve whether the relationship is meaningful.

## Evaluation

The new tests cover:

- Exact wording matches and explicit single-negation frames
- Deterministic ordering and bounded top-N previews
- Nonmatching and misleading lexical overlap
- Source SHA-256 and quote-anchor corruption refusal
- Cross-scope isolation and superseded-claim exclusion
- Existing relation idempotency and one-transaction rollback
- CLI preview versus apply and behavior on a missing database

## Non-goals for Rung 3a

- No embeddings, vector store, external APIs, network access, LLMs, or self-running agents.
- No authenticated agent identities or review approval flow.
- No mass duplicate consolidation or modification of WITNESS sources.
- No semantic entailment, automatic fact checking, or confidence calibration.
- No cross-project memory traversal until access controls and permission policy are designed.

**Next:** a review interface for accepting or rejecting relationship proposals, better retrieval benchmarks and optional offline-model suggestions constrained to quoted source evidence.

**Ledger Above Ego.**
