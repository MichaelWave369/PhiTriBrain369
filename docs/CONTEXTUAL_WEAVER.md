# Rung 3d: contextual WEAVER suggestions

Rung 3d uses **already cached, scope-local embedding vectors** to propose a small set of potential connections between WITNESS claims. It adds visible source-context cautions to each suggestion, rather than treating a numeric similarity score as a reason to declare an automatic contradiction or fact.

**No new Ollama requests are made by this feature.** You must first explicitly index selected non-sensitive claims with Rung 3c. The default preview opens SQLite in read-only mode.

## Preview, with context and citations

~~~bash
phitribrain weave-semantic --scope PhiOS --model embeddinggemma
phitribrain weave-semantic --scope PhiOS --model embeddinggemma --min-cosine 0.9 --limit 10
~~~

The preview returns proposed `related` claim pairs, exact WITNESS citations, the embedding model name, cosine similarity, and review notes. Those notes include:

- Non-overlapping **asserted** validity windows. These annotations are not independently verified.
- Different immutable commits of the same GitHub repository. This may indicate a real change over time, not contradictory truth.
- The same underlying source snapshot for both claims. That does not establish independent corroboration.
- Existing WITNESS warnings for potentially stale or otherwise disputed source observations.
- One or both claims having no asserted validity window.

Even high similarity never implies logical entailment, contradiction, evidence reliability, or calibrated confidence.

## Save review-only suggestions

~~~bash
phitribrain weave-semantic --scope PhiOS --model embeddinggemma --apply
~~~

This explicitly stores the selected `related` proposals as **proposed** relationships. Each gets an audit event plus a separate `semantic_weaver_proposals` row holding model, similarity, and the context cautions from proposal time. The source and claim records are untouched.

The command recomputes and validates candidates under a SQLite write transaction and commits all proposals together. Existing manually created or reviewed relationships between the same pair are never duplicated or overwritten. Re-running an unchanged apply creates nothing new.

## Inspect and review in the Rung 3b queue

~~~bash
phitribrain relation-queue --scope PhiOS --status pending
phitribrain relation-detail --scope PhiOS --relation rel_REPLACE_ME
~~~

The queue shows the semantic model and cosine score. Detail includes the original WITNESS citations and all stored semantic context notes. You can then submit a manual `relation-review`, but acceptance means only that you accept the proposed link. It does not verify either claim or authorize a PhiBot to act.

## Safety and limitations

- At most **250 recorded claims per scope**, up to **30 proposals per invocation**. Default cosine threshold: 0.82; minimum allowed: 0.5.
- Only matching, non-stale embeddings for the **exact supplied model** are used. Unindexed or changed claims are counted and skipped.
- Source SHA-256 hashes and exact quote offsets are rechecked. Missing or malformed vector data fails closed.
- There is **no Ollama call, model prediction, network action or background job** in either preview or apply. They operate on the cached numeric vectors.
- Preview is read-only. Apply requires an explicit flag, records audit events and remains review-only.
- The semantic similarity is produced by the user's locally selected embedding model and is **not independently calibrated or verified**.
- Claims from different scopes are never compared. Scopes are organizational labels, not authenticated permissions.
- This rung does not infer contradictions from semantic similarity, merge equivalent claims, resolve historical truth, or add any automated STEWARD decision.
- The SQLite ledger is plaintext and not tamper-proof. Only import, index and review non-sensitive information.

**GMED Rule #373: Correlation gets a question mark, not a crown.**
