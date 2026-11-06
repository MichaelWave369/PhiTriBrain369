"""Φ Standard Definer Rung 2: explicitly selected WITNESS attribution audit.

This is a read-only local quote/digest check. A matching source quote establishes
what one stored source says, NOT the scientific truth or approval of a definition.
Never infers evidence, promotes a claim, or writes WEAVER/STEWARD records.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from .evidence import cited_claim
from .standard_definer import fingerprint, validate_record
from .store import BrainStore, validate_scope

_SOURCE = re.compile(r"src_[0-9a-f]{24}\Z")
_CLAIM = re.compile(r"clm_[0-9a-f]{20}\Z")
_NOTICE = (
    "Local source digest and exact quote anchor are checked against the "
    "existing WITNESS database. Source authenticity, external-world truth, "
    "scientific consensus and review authorization are NOT established."
)


def audit_definition(
    store: BrainStore, record: Any, *, scope: str,
    as_of: str | None = None, stale_after_days: int = 180,
) -> dict[str, Any]:
    """Check only explicit evidence records, in one scope; produce no mutations."""
    scope = validate_scope(scope)
    if type(stale_after_days) is not int or not 1 <= stale_after_days <= 36500:
        raise ValueError("stale_after_days must be an integer from 1 to 36500")
    structure = validate_record(record)
    report: dict[str, Any] = {
        "schema": "phi369.standard-evidence-audit.v0.1",
        "scope": scope,
        "state": "INVALID_DEFINITION",
        "valid_definition_shape": structure["valid"],
        "attributions_matched": False,
        "truth_verified": False,
        "source_authenticated": False,
        "standard_approved": False,
        "execution_authorized": False,
        "review_required": True,
        "notice": _NOTICE,
        "warnings": [],
        "issues": list(structure["errors"]),
        "checks": [],
        "existing_weaver_proposals": [],
    }
    if not structure["valid"]:
        return report

    report["definition_sha256"] = fingerprint(record)
    citations = record["evidence"]
    if not citations:
        report["state"] = "NO_EVIDENCE_TO_CHECK"
        report["issues"].append("No explicit WITNESS claims were provided")
        return report
    if len(citations) > 20:
        report["state"] = "ATTRIBUTION_CHECK_FAILED"
        report["issues"].append("Rung 2 permits at most 20 selected evidence entries")
        return report

    seen: set[tuple[str, str]] = set()
    valid_ids: set[str] = set()
    for index, entry in enumerate(citations):
        prefix = f"evidence[{index}]"
        source_id, claim_id = entry["source_id"], entry["claim_id"]
        if not _SOURCE.fullmatch(source_id) or not _CLAIM.fullmatch(claim_id):
            report["issues"].append(prefix + ": invalid local source or claim ID format")
            continue
        key = (source_id, claim_id)
        if key in seen:
            report["issues"].append(prefix + ": duplicate selected citation")
            continue
        seen.add(key)
        try:
            cited = cited_claim(
                store, scope=scope, claim_id=claim_id,
                as_of=as_of, stale_after_days=stale_after_days,
            )
        except (ValueError, sqlite3.DatabaseError):
            report["issues"].append(prefix + ": claim missing, wrong scope, invalid ledger, or source integrity check failed")
            continue
        if cited["citation"]["source_id"] != source_id:
            report["issues"].append(prefix + ": source ID does not match WITNESS claim")
            continue
        if cited["quote"] != entry["quote"]:
            report["issues"].append(prefix + ": quote does not exactly match WITNESS")
            continue
        if cited["attribution_only"] is not True:
            report["issues"].append(prefix + ": source attribution boundary is missing")
            continue
        citation = cited["citation"]
        valid_ids.add(claim_id)
        notes = list(cited["warnings"])
        report["checks"].append({
            "evidence_index": index,
            "source_id": source_id,
            "claim_id": claim_id,
            "stance_as_supplied": entry["stance"],
            "source_sha256": citation["sha256"],
            "claim_state": cited["claim_state"],
            "quote_offset": citation["char_offset"],
            "line_start": citation["line_start"],
            "line_end": citation["line_end"],
            "source_observed_at": cited["source_observed_at"],
            "source_age_days": cited["source_observation_age_days"],
            "valid_time_status": cited["valid_time"]["status"],
            "review_warnings": notes,
            "quote_anchor_matches_local_source": True,
            "source_digest_matches_local_snapshot": True,
            "source_attribution_only": True,
        })
        for message in notes:
            report["warnings"].append(prefix + ": " + message)
        if cited["claim_state"] != "recorded":
            report["warnings"].append(prefix + ": claim is disputed or superseded")

    if report["issues"] or len(report["checks"]) != len(citations):
        report["state"] = "ATTRIBUTION_CHECK_FAILED"
        return report

    # Discover pre-existing relationship proposals between only cited claims.
    # This is a read-only preview; WEAVER relations never become facts here.
    if len(valid_ids) >= 2:
        identifiers = sorted(valid_ids)
        markers = ",".join("?" for _ in identifiers)
        try:
            rows = store.db.execute(
                "SELECT id,left_claim,right_claim,relation FROM relations "
                "WHERE scope=? AND state='proposed' "
                "AND left_claim IN (" + markers + ") "
                "AND right_claim IN (" + markers + ") "
                "ORDER BY id LIMIT 21",
                (scope, *identifiers, *identifiers),
            ).fetchall()
        except sqlite3.DatabaseError:
            report["issues"].append("Local WEAVER relation table could not be read")
            report["state"] = "ATTRIBUTION_CHECK_FAILED"
            return report
        for row in rows[:20]:
            report["existing_weaver_proposals"].append({
                "relation_id": row["id"],
                "left_claim": row["left_claim"],
                "right_claim": row["right_claim"],
                "relation_proposed_not_fact": row["relation"],
            })
        if len(rows) > 20:
            report["warnings"].append("Only first 20 existing WEAVER proposals are displayed")

    report["state"] = "LOCAL_QUOTE_ANCHORS_MATCHED"
    report["attributions_matched"] = True
    return report
