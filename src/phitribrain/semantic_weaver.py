"""Rung 3d: offline, evidence-cited semantic relation candidates.

Reads only existing, explicitly indexed local embeddings. Preview does not call
Ollama or write SQLite. A high cosine score proposes RELATED, never support,
contradiction, duplicate-equivalence, confidence or factual truth.
"""
from __future__ import annotations

import json
import math
from itertools import combinations

from .evidence import cited_claim
from .hybrid import _claim_rows, _content_hash, _unit_vector, _validate_model
from .store import BrainStore, canonical_json, new_id, utcnow, validate_scope

MAX_RESULTS = 30
MAX_CLAIMS = 250


def _arguments(scope: str, model: str, min_cosine: float, limit: int):
    scope = validate_scope(scope)
    model = _validate_model(model)
    if type(min_cosine) not in (int, float) or not math.isfinite(min_cosine) or not 0.5 <= min_cosine <= 1:
        raise ValueError("min_cosine must be finite and within [0.5, 1]")
    if type(limit) is not int or not 1 <= limit <= MAX_RESULTS:
        raise ValueError("limit must be an integer from 1 to 30")
    return scope, model


def _context(left: dict, right: dict) -> list[str]:
    """Return review cautions, not computed truth values."""
    alerts = []
    lt, rt = left["valid_time"], right["valid_time"]
    if lt["kind"] != "asserted_not_verified" or rt["kind"] != "asserted_not_verified":
        alerts.append("One or both claims lack asserted validity windows")
    else:
        if ((lt["valid_until"] and rt["valid_from"] and lt["valid_until"] < rt["valid_from"])
                or (rt["valid_until"] and lt["valid_from"] and rt["valid_until"] < lt["valid_from"])):
            alerts.append("Asserted validity windows do not overlap; compare historical context")
    if left["citation"]["source_id"] == right["citation"]["source_id"]:
        alerts.append("Both statements came from the same source snapshot, not independent corroboration")
    left_git = {
        (item["repository"], item["commit"])
        for item in left["citation"]["references"]
        if item["kind"] == "github_immutable_commit"
    }
    right_git = {
        (item["repository"], item["commit"])
        for item in right["citation"]["references"]
        if item["kind"] == "github_immutable_commit"
    }
    if any(a == b and x != y for a, x in left_git for b, y in right_git):
        alerts.append("Sources are from different commits of the same repository")
    if left["warnings"] or right["warnings"]:
        alerts.append("At least one citation has freshness, history, or disagreement warnings")
    return alerts


def semantic_candidates(store: BrainStore, *, scope: str, model: str,
                        min_cosine: float = 0.82, limit: int = 20) -> dict:
    """Read-only bounded, deterministic candidate generation from cached vectors."""
    scope, model = _arguments(scope, model, min_cosine, limit)
    claims = _claim_rows(store, scope)
    if len(claims) > MAX_CLAIMS:
        raise ValueError("Semantic WEAVER scope exceeds 250 claims")
    records = []
    skipped = 0
    required_dim = None
    for row in claims:
        cached = store.db.execute(
            "SELECT content_sha256,dimension,vector_json "
            "FROM claim_embeddings WHERE scope=? AND model=? AND claim_id=?",
            (scope, model, row["id"]),
        ).fetchone()
        if cached is None:
            skipped += 1
            continue
        if cached["content_sha256"] != _content_hash(row):
            skipped += 1
            continue
        # Validate the source/quote even when no candidate eventually emerges.
        receipt = cited_claim(store, scope=scope, claim_id=row["id"])
        try:
            vector = _unit_vector(json.loads(cached["vector_json"]))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid stored embedding for claim " + row["id"]) from exc
        if len(vector) != cached["dimension"]:
            raise ValueError("Stored embedding dimension mismatch")
        if required_dim is not None and required_dim != len(vector):
            raise ValueError("Inconsistent dimensions for the selected model")
        required_dim = len(vector)
        records.append((row, receipt, vector))
    known_pairs = {
        tuple(sorted((r["left_claim"], r["right_claim"])))
        for r in store.db.execute(
            "SELECT left_claim,right_claim FROM relations WHERE scope=?", (scope,)
        )
    }
    found = []
    for a, b in combinations(records, 2):
        left, left_cite, left_vec = a
        right, right_cite, right_vec = b
        pair = tuple(sorted((left["id"], right["id"])))
        if pair in known_pairs:
            continue
        cosine = sum(x * y for x, y in zip(left_vec, right_vec))
        if cosine < min_cosine:
            continue
        notes = _context(left_cite, right_cite)
        found.append({
            "left_claim": pair[0], "right_claim": pair[1],
            "relation": "related", "method": "local_semantic_neighbor",
            "model": model, "cosine_not_confidence": round(cosine, 6),
            "review_notes": notes,
            "citations": [left_cite, right_cite],
            "truth_status": "unverified_proposal",
            "review_required": True,
        })
    found.sort(key=lambda candidate: (
        -candidate["cosine_not_confidence"],
        candidate["left_claim"], candidate["right_claim"],
    ))
    return {
        "scope": scope, "model": model, "mode": "dry-run",
        "min_cosine": min_cosine, "indexed_claims": len(records),
        "unindexed_or_stale_claims": skipped, "total_candidates": len(found),
        "count": len(found[:limit]), "truncated": len(found) > limit,
        "candidates": found[:limit],
        "warning": (
            "Numeric semantic proximity is not entailment or contradiction. "
            "All suggestions are RELATED only; compare citations and context manually. "
            "No Ollama calls or SQLite writes in preview."
        ),
    }


def apply_semantic_candidates(store: BrainStore, *, scope: str, model: str,
                              min_cosine: float = 0.82, limit: int = 20) -> dict:
    """Atomically add review-only RELATED links, with method and context audit."""
    scope, model = _arguments(scope, model, min_cosine, limit)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        plan = semantic_candidates(
            store, scope=scope, model=model, min_cosine=min_cosine, limit=limit
        )
        created = []
        for item in plan["candidates"]:
            relation_id = new_id("rel")
            context_json = canonical_json(item["review_notes"])
            store.db.execute(
                "INSERT INTO relations(id,scope,left_claim,right_claim,relation,"
                "rationale,created_at) VALUES(?,?,?,?,?,?,?)",
                (relation_id, scope, item["left_claim"], item["right_claim"], "related",
                 "WEAVER local embedding neighbor only; review claims and context", utcnow()),
            )
            store.db.execute(
                "INSERT INTO semantic_weaver_proposals(relation_id,scope,model,"
                "cosine,context_json,created_at) VALUES(?,?,?,?,?,?)",
                (relation_id, scope, model, item["cosine_not_confidence"],
                 context_json, utcnow()),
            )
            store._event(scope, "weaver.semantic.propose", {
                "relation_id": relation_id, "left_claim": item["left_claim"],
                "right_claim": item["right_claim"], "model": model,
                "cosine_not_confidence": item["cosine_not_confidence"],
                "review_notes": item["review_notes"],
            })
            created.append({
                "id": relation_id, "left_claim": item["left_claim"],
                "right_claim": item["right_claim"], "state": "proposed",
                "relation": "related",
            })
    return {
        "scope": scope, "model": model, "mode": "applied",
        "created": len(created), "relations": created,
        "total_candidates_before_apply": plan["total_candidates"],
        "warning": "Only reviewable RELATED proposals were written. No claims or actions changed.",
    }
