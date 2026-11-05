"""WITNESS quote-backed retrieval: no LLM, no truth inference, no network.

Only source-attributed claims appear as evidence matches. Search scores are
lexical, not confidence estimates. Temporal validity is a *human/agent
annotation*, not independent verification of the original assertion.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .store import BrainStore, SEARCH_WORDS, new_id, sha, utcnow, validate_scope


def _as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("--as-of requires an ISO 8601 datetime with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of requires an ISO 8601 datetime with timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("Validity dates must use YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Validity dates must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("Validity dates must use YYYY-MM-DD")
    return value


def annotate_claim_time(store: BrainStore, *, scope: str, claim_id: str,
                        valid_from: str | None = None,
                        valid_until: str | None = None,
                        basis: str, actor: str = "local") -> dict:
    """Append an explicitly asserted valid-time interval, never rewrite history."""
    scope = validate_scope(scope)
    valid_from = _date(valid_from)
    valid_until = _date(valid_until)
    if not (valid_from or valid_until):
        raise ValueError("At least one validity boundary is required")
    if valid_from and valid_until and valid_until < valid_from:
        raise ValueError("Validity end date precedes start date")
    if not basis.strip() or not actor.strip():
        raise ValueError("An annotation basis and actor label are required")
    claim = store.db.execute(
        "SELECT id FROM claims WHERE id=? AND scope=?", (claim_id, scope)
    ).fetchone()
    if claim is None:
        raise ValueError("Claim was not found in the requested scope")
    annotation_id = new_id("time")
    with store.db:
        store.db.execute(
            "INSERT INTO claim_time_annotations(id,scope,claim_id,valid_from,"
            "valid_until,basis,actor,recorded_at) VALUES(?,?,?,?,?,?,?,?)",
            (annotation_id, scope, claim_id, valid_from, valid_until, basis, actor,
             utcnow()),
        )
        store._event(scope, "claim.time.annotate", {
            "annotation_id": annotation_id, "claim_id": claim_id,
            "valid_from": valid_from, "valid_until": valid_until, "basis": basis,
            "actor": actor,
        })
    return {
        "annotation_id": annotation_id, "claim_id": claim_id,
        "valid_from": valid_from, "valid_until": valid_until,
        "status": "asserted_not_verified",
    }


def _temporal(store: BrainStore, scope: str, claim_id: str, as_of: datetime) -> dict:
    annotation = store.db.execute(
        "SELECT id,valid_from,valid_until,basis,actor,recorded_at "
        "FROM claim_time_annotations WHERE scope=? AND claim_id=? "
        "ORDER BY seq DESC LIMIT 1",
        (scope, claim_id),
    ).fetchone()
    if annotation is None:
        return {"kind": "unspecified", "valid_from": None,
                "valid_until": None, "status": "no_valid_time_assertion"}
    row = dict(annotation)
    today = as_of.date().isoformat()
    if row["valid_from"] and today < row["valid_from"]:
        status = "before_asserted_interval"
    elif row["valid_until"] and today > row["valid_until"]:
        status = "after_asserted_interval"
    else:
        status = "within_asserted_interval"
    return {"kind": "asserted_not_verified", "status": status, **row}


def _parse_utc(value: str) -> datetime:
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Stored source timestamp was invalid") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("Stored source timestamp requires timezone")
    return t.astimezone(timezone.utc)


def cited_claim(store: BrainStore, *, scope: str, claim_id: str,
                as_of: str | None = None, stale_after_days: int = 180) -> dict:
    """Return one exact, verifiable citation for a scope-local claim."""
    scope = validate_scope(scope)
    if not isinstance(stale_after_days, int) or not 1 <= stale_after_days <= 36500:
        raise ValueError("stale_after_days must be an integer from 1 to 36500")
    timepoint = _as_of(as_of)
    row = store.db.execute(
        "SELECT c.id,c.statement,c.quote,c.quote_offset,c.state,c.created_at,"
        "s.id AS source_id,s.title,s.body,s.digest,s.created_at AS source_recorded_at "
        "FROM claims c JOIN sources s ON c.source_id=s.id "
        "WHERE c.id=? AND c.scope=? AND s.scope=?",
        (claim_id, scope, scope),
    ).fetchone()
    if row is None:
        raise ValueError("Claim not found in requested scope")
    original = row["body"]
    exact_quote = row["quote"]
    offset = row["quote_offset"]
    if sha(original) != row["digest"]:
        raise ValueError("Source content digest mismatch: cannot provide citation")
    if not isinstance(offset, int) or offset < 0 or original[offset:offset + len(exact_quote)] != exact_quote:
        raise ValueError("Claim quote offset no longer matches original text")
    line_start = original.count("\n", 0, offset) + 1
    line_end = original.count("\n", 0, offset + len(exact_quote) - 1) + 1
    line_anchor = f"#L{line_start}" if line_start == line_end else f"#L{line_start}-L{line_end}"

    github = store.github_provenance(scope=scope, source_id=row["source_id"])
    vault = [dict(x) for x in store.db.execute(
        "SELECT vault_id,relative_path,updated_at FROM vault_notes "
        "WHERE scope=? AND source_id=? ORDER BY vault_id,relative_path",
        (scope, row["source_id"]),
    )]
    had_vault_revision = bool(store.db.execute(
        "SELECT 1 FROM vault_revisions "
        "WHERE scope=? AND (previous_source_id=? OR new_source_id=?) LIMIT 1",
        (scope, row["source_id"], row["source_id"]),
    ).fetchone())
    timestamps = [row["source_recorded_at"]]
    timestamps.extend(item["fetched_at"] for item in github)
    timestamps.extend(item["updated_at"] for item in vault)
    observed_at = max((_parse_utc(t) for t in timestamps))
    age_seconds = (timepoint - observed_at).total_seconds()
    observation_age_days = round(max(0, age_seconds) / 86400, 2)
    warnings = []
    if age_seconds < -60:
        warnings.append("Source observation timestamp is later than requested as-of time")
    if age_seconds >= stale_after_days * 86400:
        warnings.append("Source observation is older than the configured review threshold")
    if had_vault_revision and not vault:
        warnings.append("This source is a historical vault snapshot without an active note mapping")
    if row["state"] in ("disputed", "superseded"):
        warnings.append(f"Claim is marked {row['state']}")
    possible_conflicts = store.db.execute(
        "SELECT COUNT(*) FROM relations r "
        "WHERE r.scope=? AND r.relation='contradicts' "
        "AND (r.left_claim=? OR r.right_claim=?) "
        "AND COALESCE((SELECT rv.outcome FROM relation_reviews rv "
        "WHERE rv.scope=r.scope AND rv.relation_id=r.id "
        "ORDER BY rv.seq DESC LIMIT 1),'pending') <> 'rejected'",
        (scope, claim_id, claim_id),
    ).fetchone()[0]
    if possible_conflicts:
        warnings.append("There are proposed contradictory relationships to inspect")

    refs = []
    for item in github:
        refs.append({
            "kind": "github_immutable_commit",
            "repository": item["repository"], "commit": item["commit_sha"],
            "path": item["path"], "blob_sha": item["blob_sha"],
            "observed_at": item["fetched_at"],
            "url": item["origin"] + line_anchor,
        })
    for item in vault:
        refs.append({
            "kind": "vault_active_note",
            "vault_id": item["vault_id"], "path": item["relative_path"],
            "observed_at": item["updated_at"],
            "locator": f"vault:{item['vault_id']}/{item['relative_path']}{line_anchor}",
        })
    refs.append({
        "kind": "internal_source",
        "locator": f"{row['source_id']}@{offset}:{len(exact_quote)}",
    })
    return {
        "claim_id": claim_id, "scope": scope, "statement": row["statement"],
        "claim_state": row["state"], "claim_recorded_at": row["created_at"],
        "quote": exact_quote,
        "citation": {
            "source_id": row["source_id"], "title": row["title"],
            "sha256": row["digest"], "char_offset": offset,
            "char_length": len(exact_quote), "line_start": line_start,
            "line_end": line_end, "references": refs,
        },
        "source_observed_at": observed_at.isoformat(),
        "source_observation_age_days": observation_age_days,
        "valid_time": _temporal(store, scope, claim_id, timepoint),
        "warnings": warnings,
        "attribution_only": True,
    }


def find_evidence(store: BrainStore, *, scope: str, query: str,
                  limit: int = 10, as_of: str | None = None,
                  stale_after_days: int = 180) -> dict:
    """Only return claims with exact quote anchors. Abstain if none exist."""
    scope = validate_scope(scope)
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be from 1 to 50")
    timepoint = _as_of(as_of)
    if not isinstance(stale_after_days, int) or not 1 <= stale_after_days <= 36500:
        raise ValueError("stale_after_days must be an integer from 1 to 36500")
    tokens = SEARCH_WORDS.findall(query)[:16]
    if not tokens:
        return {"scope": scope, "query": query, "matches": [],
                "count": 0, "abstained": True,
                "reason": "Query has no searchable words"}
    match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
    rows = store.db.execute(
        "SELECT record_id FROM search_fts WHERE search_fts MATCH ? "
        "AND scope=? AND kind='claim' ORDER BY bm25(search_fts) LIMIT ?",
        (match, scope, limit),
    ).fetchall()
    matches = [
        cited_claim(store, scope=scope, claim_id=row["record_id"],
                    as_of=timepoint.isoformat(), stale_after_days=stale_after_days)
        for row in rows
    ]
    return {
        "scope": scope, "query": query, "as_of": timepoint.isoformat(),
        "count": len(matches), "matches": matches,
        "abstained": not bool(matches),
        "reason": None if matches else "No quote-anchored claims matched this query",
        "disclaimer": "These are attributed source claims, not verified facts or AI-generated answers.",
    }
