"""Rung 3b: explicit local relation-review ledger for WITNESS/WEAVER.

Review annotations are append-only human-labelled opinions about proposed
links. They DO NOT promote original source claims into verified truth, grant
execution authority, or authenticate the reviewer.
"""
from __future__ import annotations

import json

from .evidence import cited_claim
from .store import BrainStore, new_id, utcnow, validate_scope

OUTCOMES = ("accepted", "rejected", "needs_context")
QUEUE_STATES = ("pending", *OUTCOMES, "all")


def _relation(store: BrainStore, scope: str, relation_id: str):
    row = store.db.execute(
        "SELECT r.*, w.method AS proposal_method, w.lexical_score, "
        "sw.model AS semantic_model, sw.cosine AS semantic_cosine, "
        "sw.context_json AS semantic_context_json "
        "FROM relations r LEFT JOIN weaver_proposals w "
        "ON w.relation_id=r.id AND w.scope=r.scope "
        "LEFT JOIN semantic_weaver_proposals sw "
        "ON sw.relation_id=r.id AND sw.scope=r.scope "
        "WHERE r.scope=? AND r.id=?",
        (scope, relation_id),
    ).fetchone()
    if row is None:
        raise ValueError("Relation does not exist in the requested scope")
    return dict(row)


def _last_review(store: BrainStore, scope: str, relation_id: str):
    row = store.db.execute(
        "SELECT id,outcome,reviewer,reason,created_at,previous_review_id "
        "FROM relation_reviews WHERE scope=? AND relation_id=? "
        "ORDER BY seq DESC LIMIT 1",
        (scope, relation_id),
    ).fetchone()
    return dict(row) if row is not None else None


def relation_detail(store: BrainStore, *, scope: str, relation_id: str) -> dict:
    """Return source-verified evidence for a relation and its full review history."""
    scope = validate_scope(scope)
    relation = _relation(store, scope, relation_id)
    citations = [
        cited_claim(store, scope=scope, claim_id=claim_id)
        for claim_id in (relation["left_claim"], relation["right_claim"])
    ]
    reviews = [
        dict(row) for row in store.db.execute(
            "SELECT id,outcome,reviewer,reason,created_at,previous_review_id "
            "FROM relation_reviews WHERE scope=? AND relation_id=? ORDER BY seq ASC",
            (scope, relation_id),
        )
    ]
    current = reviews[-1] if reviews else None
    return {
        "scope": scope, "relation_id": relation_id,
        "proposed_relation": relation["relation"],
        "proposal_rationale": relation["rationale"],
        "proposal_method": relation["proposal_method"],
        "lexical_score_not_confidence": relation["lexical_score"],
        "semantic_model": relation["semantic_model"],
        "semantic_cosine_not_confidence": relation["semantic_cosine"],
        "semantic_context_notes": (
            json.loads(relation["semantic_context_json"])
            if relation["semantic_context_json"] is not None else []
        ),
        "relation_database_state": relation["state"],
        "review_status": current["outcome"] if current else "pending",
        "last_review_id": current["id"] if current else None,
        "reviews": reviews, "claim_evidence": citations,
        "notice": (
            "Review is a local human-labelled annotation about a proposed link, "
            "not verification of either claim or permission to execute an action."
        ),
    }


def relation_queue(store: BrainStore, *, scope: str, status: str = "pending",
                   limit: int = 20, offset: int = 0) -> dict:
    """Read-only, stable, paginated queue. Also includes manually proposed links."""
    scope = validate_scope(scope)
    if status not in QUEUE_STATES:
        raise ValueError("status must be pending, accepted, rejected, needs_context, or all")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    if type(offset) is not int or not 0 <= offset <= 100_000:
        raise ValueError("offset must be an integer from 0 to 100000")
    join = (
        "FROM relations r "
        "LEFT JOIN weaver_proposals w ON w.relation_id=r.id AND w.scope=r.scope "
        "LEFT JOIN semantic_weaver_proposals sw "
        "ON sw.relation_id=r.id AND sw.scope=r.scope "
        "LEFT JOIN relation_reviews rv ON rv.seq=("
        "SELECT MAX(t.seq) FROM relation_reviews t "
        "WHERE t.scope=r.scope AND t.relation_id=r.id) "
        "WHERE r.scope=? "
    )
    params = [scope]
    if status != "all":
        join += "AND COALESCE(rv.outcome,'pending')=? "
        params.append(status)
    total = store.db.execute("SELECT COUNT(*) " + join, params).fetchone()[0]
    rows = store.db.execute(
        "SELECT r.id,r.left_claim,r.right_claim,r.relation,"
        "r.rationale,r.created_at AS proposed_at,"
        "w.method AS proposal_method,w.lexical_score,"
        "sw.model AS semantic_model,sw.cosine AS semantic_cosine,"
        "COALESCE(rv.outcome,'pending') AS review_status,"
        "rv.id AS last_review_id,rv.reviewer AS last_reviewer "
        + join + "ORDER BY r.created_at,r.id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {
        "scope": scope, "filter": status,
        "total": total, "limit": limit, "offset": offset,
        "count": len(rows), "items": [dict(r) for r in rows],
        "warning": "Queue status is annotation metadata, not a statement of truth.",
    }


def annotate_relation(store: BrainStore, *, scope: str, relation_id: str,
                      outcome: str, reviewer: str, reason: str,
                      supersedes: str | None = None) -> dict:
    """Append one review atomically, using the latest review ID as an optimistic lock.

    A first review must have supersedes=None. Every later review must provide
    the currently latest review ID. No destructive updates or authority grants.
    """
    scope = validate_scope(scope)
    if outcome not in OUTCOMES:
        raise ValueError("Review outcome must be accepted, rejected, or needs_context")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120:
        raise ValueError("Reviewer label must contain 1-120 nonblank characters")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4000:
        raise ValueError("Review reason must contain 1-4000 nonblank characters")
    if supersedes is not None and (
        not isinstance(supersedes, str) or not supersedes.startswith("rrev_")
    ):
        raise ValueError("--supersedes must be an existing review ID")
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        relation = _relation(store, scope, relation_id)
        # Revalidate source quotes and hashes before recording any adjudication.
        for claim in (relation["left_claim"], relation["right_claim"]):
            cited_claim(store, scope=scope, claim_id=claim)
        last = _last_review(store, scope, relation_id)
        expected = last["id"] if last else None
        if expected != supersedes:
            raise ValueError(
                "Review conflict: supply --supersedes with the current last_review_id "
                "to revise a previous assessment"
            )
        if last and last["outcome"] == outcome:
            raise ValueError(
                "Review outcome is unchanged; use a different outcome when revisiting"
            )
        review_id = new_id("rrev")
        created_at = utcnow()
        store.db.execute(
            "INSERT INTO relation_reviews("
            "id,scope,relation_id,outcome,reviewer,reason,previous_review_id,created_at"
            ") VALUES(?,?,?,?,?,?,?,?)",
            (review_id, scope, relation_id, outcome, reviewer.strip(),
             reason.strip(), expected, created_at),
        )
        store._event(scope, "relation.review.annotate", {
            "review_id": review_id, "relation_id": relation_id,
            "outcome": outcome, "reviewer": reviewer.strip(),
            "reason": reason.strip(), "previous_review_id": expected,
        })
    return {
        "scope": scope, "relation_id": relation_id,
        "review_id": review_id, "previous_review_id": expected,
        "review_status": outcome, "created_at": created_at,
        "truth_status": "unverified_relation_review",
        "notice": "The original relation remains proposed. No execution authorization.",
    }
