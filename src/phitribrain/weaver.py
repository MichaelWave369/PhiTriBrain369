"""Rung 3a WEAVER: deterministic, review-only relationship candidates.

This is *lexical pattern matching*, not natural language inference, an LLM,
truth verification, or calibrated confidence. Every proposed relation is tied
to two exact quote-backed claims already recorded by WITNESS.
"""
from __future__ import annotations

import re
from itertools import combinations

from .store import BrainStore, canonical_json, new_id, sha, utcnow, validate_scope

MAX_CLAIMS = 250
STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "to", "of", "for", "on", "in", "at",
    "by", "as", "with", "from", "this", "that", "these", "those", "it",
    "its", "their", "we", "our",
})
AUXILIARIES = frozenset({
    "is", "are", "was", "were", "can", "could", "should", "would",
    "will", "does", "do", "did", "has", "have", "had",
})
TOKEN_RE = re.compile(r"[^\W_]+(?:_[^\W_]+)*", re.UNICODE)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(text.casefold()))


def _polarity(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], bool] | None:
    """Narrow heuristic: single 'AUX not' vs same exact phrase with 'AUX'."""
    negations = [
        i for i, token in enumerate(tokens)
        if token == "not" and i > 0 and tokens[i - 1] in AUXILIARIES
    ]
    if len(negations) > 1:
        return None
    if len(negations) == 1:
        index = negations[0]
        return tokens[:index] + tokens[index + 1:], True
    if "not" in tokens:
        return None
    return tokens, False


def _pattern(a: tuple[str, ...], b: tuple[str, ...], threshold: float):
    if not a or not b:
        return None
    if a == b:
        return "exact_text", "related", 1.0, "Exactly matching normalized claim statements"
    polar_a, polar_b = _polarity(a), _polarity(b)
    if (
        polar_a is not None and polar_b is not None
        and polar_a[0] == polar_b[0]
        and polar_a[1] != polar_b[1]
        and len(polar_a[0]) >= 3
    ):
        return (
            "explicit_not_frame", "contradicts", 1.0,
            "Opposite 'not' polarity in an otherwise identical auxiliary-verb phrase; "
            "candidate conflict only, context may reverse the interpretation",
        )
    meaningful_a = {word for word in a if word not in STOPWORDS and len(word) > 2}
    meaningful_b = {word for word in b if word not in STOPWORDS and len(word) > 2}
    overlap = meaningful_a & meaningful_b
    if len(overlap) < 3:
        return None
    union = meaningful_a | meaningful_b
    if not union:
        return None
    jaccard = len(overlap) / len(union)
    if jaccard < threshold:
        return None
    return (
        "lexical_overlap", "related", round(jaccard, 4),
        "Shared content words: " + ", ".join(sorted(overlap)[:12])
        + "; lexical overlap is not semantic agreement",
    )


def _validate_parameters(scope: str, threshold: float, limit: int) -> str:
    scope = validate_scope(scope)
    if not isinstance(threshold, (int, float)) or not 0.3 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0.3 and 1.0")
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    return scope


def candidates(store: BrainStore, *, scope: str, threshold: float = 0.72,
               limit: int = 30) -> dict:
    """Preview bounded proposals. Never writes or modifies a relation."""
    scope = _validate_parameters(scope, threshold, limit)
    rows = store.db.execute(
        "SELECT c.id,c.statement,c.quote,c.quote_offset,c.source_id,"
        "s.body,s.digest FROM claims c JOIN sources s ON c.source_id=s.id "
        "WHERE c.scope=? AND c.state='recorded' AND s.scope=? "
        "ORDER BY c.id LIMIT ?",
        (scope, scope, MAX_CLAIMS + 1),
    ).fetchall()
    if len(rows) > MAX_CLAIMS:
        raise ValueError(
            f"WEAVER preview is limited to {MAX_CLAIMS} recorded claims per scope; "
            "split the project or use smaller scopes"
        )
    normalized = []
    for row in rows:
        if sha(row["body"]) != row["digest"]:
            raise ValueError("Invalid source digest in claim " + row["id"])
        offset, excerpt = row["quote_offset"], row["quote"]
        if (
            not isinstance(offset, int) or offset < 0
            or row["body"][offset:offset + len(excerpt)] != excerpt
        ):
            raise ValueError("Broken quote anchor in claim " + row["id"])
        normalized.append({
            "id": row["id"], "statement": row["statement"],
            "source_id": row["source_id"], "source_sha256": row["digest"],
            "quote": excerpt, "quote_offset": offset,
            "tokens": _tokens(row["statement"]),
        })
    # Existing manual or generated relationships are never silently replaced.
    existing = {
        tuple(sorted((row["left_claim"], row["right_claim"])))
        for row in store.db.execute(
            "SELECT left_claim,right_claim FROM relations WHERE scope=?", (scope,)
        )
    }
    output = []
    for a, b in combinations(normalized, 2):
        pair = tuple(sorted((a["id"], b["id"])))
        if pair in existing:
            continue
        match = _pattern(a["tokens"], b["tokens"], threshold)
        if match is None:
            continue
        method, relation, score, rationale = match
        output.append({
            "left_claim": pair[0], "right_claim": pair[1],
            "relation": relation,
            "pattern": method, "lexical_score": score,
            "rationale": rationale,
            "evidence": [
                {k: item[k] for k in (
                    "id", "source_id", "source_sha256", "statement",
                    "quote", "quote_offset",
                )}
                for item in (a, b)
            ],
            "review_required": True,
            "truth_status": "unverified_proposal",
        })
    # Deterministic priority order: potential contradiction, exact duplicate, overlap.
    order = {"explicit_not_frame": 0, "exact_text": 1, "lexical_overlap": 2}
    output.sort(key=lambda c: (
        order[c["pattern"]], -c["lexical_score"],
        c["left_claim"], c["right_claim"],
    ))
    shown = output[:limit]
    return {
        "scope": scope, "mode": "dry-run", "threshold": threshold,
        "scanned_claims": len(rows), "total_candidates": len(output),
        "truncated": len(output) > limit, "count": len(shown), "candidates": shown,
        "warning": (
            "Heuristic lexical proposals only; no semantic truth, fact-checking, "
            "confidence calibration, or execution authorization."
        ),
    }


def apply_candidates(store: BrainStore, *, scope: str, threshold: float = 0.72,
                     limit: int = 30) -> dict:
    """Persist new proposed relationships atomically, with audit metadata."""
    scope = _validate_parameters(scope, threshold, limit)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        plan = candidates(store, scope=scope, threshold=threshold, limit=limit)
        saved = []
        for candidate in plan["candidates"]:
            relation_id = new_id("rel")
            store.db.execute(
                "INSERT INTO relations(id,scope,left_claim,right_claim,relation,"
                "rationale,created_at) VALUES(?,?,?,?,?,?,?)",
                (relation_id, scope, candidate["left_claim"],
                 candidate["right_claim"], candidate["relation"],
                 "WEAVER suggested [" + candidate["pattern"] + "]: "
                 + candidate["rationale"], utcnow()),
            )
            store.db.execute(
                "INSERT INTO weaver_proposals(relation_id,scope,method,"
                "lexical_score,created_at) VALUES(?,?,?,?,?)",
                (relation_id, scope, candidate["pattern"],
                 candidate["lexical_score"], utcnow()),
            )
            store._event(scope, "weaver.relation.propose", {
                "relation_id": relation_id, "left_claim": candidate["left_claim"],
                "right_claim": candidate["right_claim"],
                "relation": candidate["relation"],
                "pattern": candidate["pattern"],
                "lexical_score": candidate["lexical_score"],
            })
            saved.append({"id": relation_id, "relation": candidate["relation"],
                          "left_claim": candidate["left_claim"],
                          "right_claim": candidate["right_claim"],
                          "method": candidate["pattern"], "state": "proposed"})
    return {
        "scope": scope, "mode": "applied", "created": len(saved),
        "scanned_claims": plan["scanned_claims"],
        "candidate_total_before_apply": plan["total_candidates"],
        "truncated": plan["truncated"], "relations": saved,
        "warning": "Only proposed links were written. No claims or decisions were promoted.",
    }
