"""Φ Standard Definer Rung 1. Structure validation, not truth verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "phi369.standard-definition.v0.1"
STATUSES = {"draft", "model_supported", "hypothesis", "speculative", "unknown"}
STANCES = {"supports", "challenges", "context"}
RELATIONS = {"is_a", "part_of", "related_to", "contrasts_with"}
REQUIRED = {
    "schema", "concept_id", "revision", "term", "domain", "context",
    "definition", "epistemic_status", "temporal", "assumptions",
    "evidence", "alternatives", "relations", "open_questions", "review_state",
}


def draft(concept_id: str, term: str, domain: str, context: str) -> dict[str, Any]:
    """Return an explicitly incomplete, unreviewed candidate."""
    return {
        "schema": SCHEMA, "concept_id": concept_id, "revision": 1,
        "term": term, "domain": domain, "context": context, "definition": "",
        "epistemic_status": "draft",
        "temporal": {"was": "", "is": "", "might_become": ""},
        "assumptions": [], "evidence": [], "alternatives": [],
        "relations": [], "open_questions": [], "review_state": "unreviewed",
    }


def _keys(value: Any, path: str, required: set[str], allowed: set[str],
          errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return False
    missing, extra = required - value.keys(), value.keys() - allowed
    if missing:
        errors.append(f"{path} missing: {', '.join(sorted(missing))}")
    if extra:
        errors.append(f"{path} unexpected: {', '.join(sorted(extra))}")
    return True


def _text(value: Any, path: str, errors: list[str], optional: bool = False) -> None:
    if not isinstance(value, str) or (not optional and not value.strip()):
        errors.append(f"{path} must be {'optional ' if optional else 'nonempty '}text")
    elif len(value) > 2000 or any(ord(c) < 32 and c not in "\n\t" for c in value):
        errors.append(f"{path} exceeds text bounds or contains control chars")


def _list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list) or len(value) > 50:
        errors.append(f"{path} must be an array of at most 50 elements")
        return []
    return value


def validate_record(value: Any) -> dict[str, Any]:
    """Validate schema and review boundaries only, never factual truth."""
    errors: list[str] = []
    warnings: list[str] = []
    if not _keys(value, "record", REQUIRED, REQUIRED, errors):
        return {"valid": False, "errors": errors, "warnings": warnings}
    if value.get("schema") != SCHEMA:
        errors.append("unsupported schema version")
    concept = value.get("concept_id")
    if not isinstance(concept, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+", concept):
        errors.append("concept_id must be a dotted lowercase identifier")
    if type(value.get("revision")) is not int or not 1 <= value["revision"] <= 1000000:
        errors.append("revision must be an integer from 1 to 1000000")
    for field in ("term", "domain", "context", "definition"):
        _text(value.get(field), field, errors)
    status = value.get("epistemic_status")
    if not isinstance(status, str) or status not in STATUSES:
        errors.append("unrecognized epistemic_status")
    if value.get("review_state") != "unreviewed":
        errors.append("Rung 1 cannot certify or approve any definition")
    temporal = value.get("temporal")
    fields = {"was", "is", "might_become"}
    if _keys(temporal, "temporal", fields, fields, errors):
        for field in fields:
            _text(temporal.get(field), "temporal." + field, errors, optional=True)
    for field in ("assumptions", "open_questions"):
        for i, item in enumerate(_list(value.get(field), field, errors)):
            _text(item, f"{field}[{i}]", errors)
    support_count = 0
    for i, item in enumerate(_list(value.get("evidence"), "evidence", errors)):
        path = f"evidence[{i}]"
        fields = {"source_id", "claim_id", "quote", "stance"}
        if not _keys(item, path, fields, fields, errors):
            continue
        for field in ("source_id", "claim_id", "quote"):
            _text(item.get(field), path + "." + field, errors)
        if not isinstance(item.get("stance"), str) or item.get("stance") not in STANCES:
            errors.append(path + ".stance invalid")
        if item.get("stance") == "supports":
            support_count += 1
    if status == "model_supported" and not support_count:
        errors.append("model_supported requires a supporting source attribution")
    if value.get("evidence"):
        warnings.append("Source IDs and quotes are unverified attributions, not verified truth")
    else:
        warnings.append("No source evidence included")
    for i, item in enumerate(_list(value.get("alternatives"), "alternatives", errors)):
        path = f"alternatives[{i}]"
        fields = {"label", "definition", "status", "distinguishing_test"}
        if not _keys(item, path, fields, fields, errors):
            continue
        for field in ("label", "definition"):
            _text(item.get(field), path + "." + field, errors)
        _text(item.get("distinguishing_test"), path + ".distinguishing_test",
              errors, optional=True)
        if not isinstance(item.get("status"), str) or item.get("status") not in STATUSES:
            errors.append(path + ".status invalid")
    for i, item in enumerate(_list(value.get("relations"), "relations", errors)):
        path = f"relations[{i}]"
        fields = {"type", "target_id", "why"}
        if not _keys(item, path, fields, fields, errors):
            continue
        if not isinstance(item.get("type"), str) or item.get("type") not in RELATIONS:
            errors.append(path + ".type invalid")
        _text(item.get("target_id"), path + ".target_id", errors)
        _text(item.get("why"), path + ".why", errors)
        if item.get("target_id") == concept:
            errors.append(path + " must not link a concept to itself")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


def fingerprint(record: Any) -> str:
    """Content SHA-256. This is not a signature or authenticity proof."""
    serialized = json.dumps(record, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compare(left: Any, right: Any) -> dict[str, str]:
    if not validate_record(left)["valid"] or not validate_record(right)["valid"]:
        raise ValueError("both definitions must validate")
    if left["concept_id"] != right["concept_id"]:
        outcome = "different_concepts"
    elif left["context"].strip().casefold() != right["context"].strip().casefold():
        outcome = "different_contexts"
    elif left["definition"].strip().casefold() == right["definition"].strip().casefold():
        outcome = "same_wording"
    else:
        outcome = "competing_wording_requires_review"
    return {
        "outcome": outcome, "left_sha256": fingerprint(left),
        "right_sha256": fingerprint(right),
        "caution": "A wording difference alone does not prove contradiction or truth",
    }


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def read_record(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as handle:
        raw = handle.read(262145)
    if len(raw) > 262144:
        raise ValueError("record exceeds 256 KiB")
    def bad_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")
    result = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                        parse_constant=bad_constant)
    if not isinstance(result, dict):
        raise ValueError("definition JSON must be an object")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review-only Φ Standard Definer")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("draft", help="Print an incomplete candidate JSON")
    for field in ("concept-id", "term", "domain", "context"):
        new.add_argument("--" + field, required=True)
    check = commands.add_parser("validate")
    check.add_argument("path")
    comparison = commands.add_parser("compare")
    comparison.add_argument("left")
    comparison.add_argument("right")
    evidence = commands.add_parser("evidence", help="Audit exact WITNESS quotes in a local read-only database")
    evidence.add_argument("path", help="Candidate definition JSON")
    evidence.add_argument("--db", required=True, help="Existing PhiTriBrain SQLite database")
    evidence.add_argument("--scope", required=True, help="Exact project scope; no cross-scope lookup")
    evidence.add_argument("--as-of", help="ISO 8601 timestamp with timezone")
    evidence.add_argument("--stale-after-days", type=int, default=180)
    args = parser.parse_args(argv)
    try:
        if args.command == "draft":
            result = draft(args.concept_id, args.term, args.domain, args.context)
        elif args.command == "validate":
            record = read_record(args.path)
            result = validate_record(record)
            if result["valid"]:
                result["fingerprint_sha256"] = fingerprint(record)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["valid"] else 2
        elif args.command == "evidence":
            from .standard_evidence import audit_definition
            from .store import BrainStore
            record = read_record(args.path)
            with BrainStore(args.db, readonly=True) as store:
                result = audit_definition(
                    store, record, scope=args.scope,
                    as_of=args.as_of, stale_after_days=args.stale_after_days,
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["state"] == "LOCAL_QUOTE_ANCHORS_MATCHED" else 2
        else:
            result = compare(read_record(args.left), read_record(args.right))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
