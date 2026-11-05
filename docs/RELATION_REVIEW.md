# Rung 3b: WEAVER relation review ledger

WEAVER now has an append-only **review annotation** workflow for potential relationships. This is not a fact-checker, identity system, consensus mechanism or execution authorization gateway.

A relationship in the original `relations` table remains `proposed` forever in this rung. Review outcomes are **separate, versioned records**. Sources, claims and quote anchors never get rewritten just because a review was accepted.

## View the review queue

~~~bash
phitribrain relation-queue --scope PhiOS
phitribrain relation-queue --scope PhiOS --status all --limit 20 --offset 0
phitribrain relation-queue --scope PhiOS --status rejected
~~~

The default filter is `pending`. Other filters: `accepted`, `rejected`, `needs_context` and `all`. Each row shows the proposed relationship, claim IDs, lexical method/score (if machine-proposed), current review status, and last review ID.

The queue is read-only. It includes WEAVER suggestions and manually proposed relationships. It does not validate each source citation until a specific relation is inspected or reviewed.

## Inspect both sides before review

~~~bash
phitribrain relation-detail --scope PhiOS --relation rel_REPLACE_ME
~~~

The response includes both WITNESS quote-backed citations, intact source hashes, proposed relation and rationale, WEAVER heuristic, and **full review history**. It fails closed if original source hashes or quote offsets no longer match.

## Review interactively

~~~bash
phitribrain relation-review --scope PhiOS --relation rel_REPLACE_ME --outcome needs_context --reviewer "Local human" --reason "Build SHA and timestamps need comparison"
~~~

The CLI requires an interactive terminal and the exact confirmation:

~~~text
REVIEW rel_REPLACE_ME NEEDS_CONTEXT
~~~

Outcomes are `accepted`, `rejected` or `needs_context`. They refer to whether you *accept the proposed relationship*, **not** whether either original claim is true. The reviewer label is arbitrary text and **not authenticated**. All reviews are recorded with an audit event.

## Revisit an earlier assessment

First inspect the relation and copy its current `last_review_id`. A second review must name that exact review ID:

~~~bash
phitribrain relation-review --scope PhiOS --relation rel_REPLACE_ME --outcome rejected --reviewer "Local human" --reason "Compared different commits, no actual contradiction" --supersedes rrev_REPLACE_ME
~~~

The original review remains in the history. If another review has happened since you inspected the relation, the update is rejected. This prevents accidental overwrites by out-of-date reviewers.

A repeated identical outcome is refused to reduce accidental duplicate review entries. Changing a decision is represented by a new outcome with an explicit reason.

## WITNESS contradiction warnings

If a contradiction proposal has been explicitly reviewed and **rejected**, WITNESS no longer treats it as an active contradiction-warning candidate. The relation itself and all reviews remain available for inspection, including rejected links. Switching it to `needs_context` or `accepted` brings the warning back. None of these outcomes proves any claim true.

## Integrity and limitations

- Writes are SQLite transactions containing both the new review annotation and a hash-chained audit event.
- Both quote anchors and source SHA-256 digests are checked before accepting the annotation.
- Scopes are organizational labels, not access-control boundaries.
- The CLI refuses noninteractive review, but this is **not cryptographic proof of human identity**. The Python API can also annotate directly; protect the local database and process access.
- No claim gets promoted to fact; no decision/action authority is conveyed. The `relations.state` column remains `proposed`.
- Database administrators can rewrite the entire ledger and audit trail. This is not a tamper-proof security system.
- Never expose the local review CLI or SQLite to untrusted users as a network service.
- WITNESS citations and review details contain quotes and source paths. Do not import secret or confidential notes without separate controls.
- There is no semantic contradiction verification, contextual truth resolution, automatic merging of duplicates, model inference, or user authentication in this rung.

## Future rung

An authenticated, evidence-focused reviewer interface, with permission scopes and evaluated retrieval models, should precede shared PhiBots and PhiMadaPrime workflows.
