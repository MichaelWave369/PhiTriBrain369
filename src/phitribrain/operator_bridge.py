"""Rung 4a: offline, read-only, explicit-ID export for Phi369 operator workspaces.

No MCP server, agents, execution, network listener, automatic synchronization,
token issue, or write to the source ledger. The *local OS user* controls file
access. A consumer name in a manifest is a label, NOT authentication.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .evidence import cited_claim
from .relation_review import relation_detail
from .store import BrainStore, canonical_json, sha, utcnow, validate_scope

CONSUMERS = ("PhiMadaPrime", "PhiBots", "PhiOS", "PhiRSI")
MAX_MANIFEST_BYTES = 16_384
MAX_OUTPUT_BYTES = 262_144
MAX_CLAIMS = 20
MAX_LINKS = 10
MAX_DECISIONS = 10
ID_PATTERNS = {
    "claims": re.compile(r"clm_[0-9a-f]{20}\Z"),
    "relations": re.compile(r"rel_[0-9a-f]{20}\Z"),
    "decisions": re.compile(r"dec_[0-9a-f]{20}\Z"),
}


def _ids(value: object, *, kind: str, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{kind} must be a list of at most {limit} IDs")
    result = []
    for identifier in value:
        if not isinstance(identifier, str) or not ID_PATTERNS[kind].fullmatch(identifier):
            raise ValueError(f"Invalid {kind} record ID")
        result.append(identifier)
    if len(result) != len(set(result)):
        raise ValueError(f"Duplicate {kind} IDs in manifest")
    return sorted(result)


def parse_bridge_manifest(path: str | Path) -> dict:
    """Require an explicit, small, versioned record allowlist with no wildcards."""
    filename = Path(path).expanduser()
    if filename.is_symlink() or not filename.is_file():
        raise ValueError("Bridge manifest must be an existing, non-symlink JSON file")
    if filename.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Bridge manifest exceeds 16 KB")
    try:
        raw = filename.read_bytes()
        if not raw or len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("Bridge manifest must be 1 to 16384 bytes")
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Bridge manifest must contain valid UTF-8 JSON") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "consumer", "scope", "claims", "relations", "decisions",
    }:
        raise ValueError("Bridge manifest requires exactly six specified fields")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("Bridge manifest schema_version must be 1")
    if document["consumer"] not in CONSUMERS:
        raise ValueError("Bridge consumer must be one of the named Phi369 applications")
    scope = document["scope"]
    if not isinstance(scope, str):
        raise ValueError("Bridge scope must be a string")
    validate_scope(scope)
    claims = _ids(document["claims"], kind="claims", limit=MAX_CLAIMS)
    relations = _ids(document["relations"], kind="relations", limit=MAX_LINKS)
    decisions = _ids(document["decisions"], kind="decisions", limit=MAX_DECISIONS)
    if not claims:
        raise ValueError("At least one explicit WITNESS claim ID is required")
    return {
        "schema_version": 1, "consumer": document["consumer"], "scope": scope,
        "claims": claims, "relations": relations, "decisions": decisions,
    }


def _short(value: str, *, name: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{name} exceeds safe export limit ({limit} characters)")
    return value


def _citation(cited: dict) -> dict:
    citation = cited["citation"]
    references = []
    for ref in citation["references"]:
        if ref["kind"] == "github_immutable_commit":
            references.append({
                "kind": "github_immutable_commit",
                "repository": _short(ref["repository"], name="repository", limit=160),
                "commit": ref["commit"], "path": _short(
                    ref["path"], name="source path", limit=256
                ),
                "url": _short(ref["url"], name="citation URL", limit=1024),
            })
        elif ref["kind"] == "vault_active_note":
            references.append({
                "kind": "vault_active_note", "vault_id": ref["vault_id"],
                "path": _short(ref["path"], name="vault path", limit=256),
            })
    return {
        "source_id": citation["source_id"],
        "source_sha256": citation["sha256"],
        "source_title": _short(citation["title"], name="source title", limit=200),
        "quote": _short(cited["quote"], name="exact source quote", limit=768),
        "quote_offset": citation["char_offset"],
        "line_start": citation["line_start"],
        "line_end": citation["line_end"],
        "references": references[:10],
    }


def _claim(cited: dict) -> dict:
    return {
        "id": cited["claim_id"],
        "statement": _short(cited["statement"], name="statement", limit=600),
        "recorded_state": cited["claim_state"],
        "source_observed_at": cited["source_observed_at"],
        "source_observation_age_days": cited["source_observation_age_days"],
        "valid_time": {
            "status": cited["valid_time"]["status"],
            "kind": cited["valid_time"]["kind"],
        },
        "warnings": [
            _short(w, name="citation warning", limit=300)
            for w in cited["warnings"]
        ],
        "citation": _citation(cited),
        "source_attribution_only": True,
    }


def create_bridge_snapshot(store: BrainStore, *, manifest: dict) -> dict:
    """Generate a minimized three-lane operator view from explicit record IDs."""
    scope = manifest["scope"]
    validate_scope(scope)
    claim_ids = set(manifest["claims"])
    as_of = utcnow()
    witness = [
        _claim(cited_claim(store, scope=scope, claim_id=cid, as_of=as_of))
        for cid in manifest["claims"]
    ]
    weaver = []
    for rid in manifest["relations"]:
        detail = relation_detail(store, scope=scope, relation_id=rid)
        members = [x["claim_id"] for x in detail["claim_evidence"]]
        if not set(members).issubset(claim_ids):
            raise ValueError("A relation references a claim not explicitly allowlisted")
        weaver.append({
            "id": rid, "left_claim": members[0], "right_claim": members[1],
            "relation_proposed": detail["proposed_relation"],
            "review_status": detail["review_status"],
            "method": detail["proposal_method"] or (
                "local_semantic_neighbor" if detail["semantic_model"] else "manual"
            ),
            "review_required": detail["review_status"] == "pending",
            "is_factual_truth": False,
        })
    steward = []
    for did in manifest["decisions"]:
        d = store.inspect(scope=scope, record_id=did)
        if not set(d["evidence"]).issubset(claim_ids) or not d["evidence"]:
            raise ValueError("A decision references evidence not explicitly allowlisted")
        attestation = d["review_attestation"]
        steward.append({
            "id": did,
            "title": _short(d["title"], name="decision title", limit=200),
            "rationale": _short(d["rationale"], name="decision rationale", limit=600),
            "status": d["status"],
            "evidence_claim_ids": sorted(d["evidence"]),
            "credential_checked": (
                bool(attestation["credential_checked"]) if attestation else False
            ),
            "review_attestation_digest": (
                attestation["evidence_sha256"] if attestation else None
            ),
            "execution_authorized": False,
            "factual_truth_verified": False,
        })
    lanes = {"WITNESS": witness, "WEAVER": weaver, "STEWARD": steward}
    content = {
        "schema_version": 1,
        "consumer_label_not_authentication": manifest["consumer"],
        "scope": scope,
        "as_of": as_of,
        "permissions": {
            "source_read": True, "database_write": False,
            "network_access": False, "tool_execution": False,
            "deployment": False, "autonomous_actions": False,
        },
        "lanes": lanes,
        "notice": (
            "Explicitly selected, quote-backed local records; statements are "
            "unverified. Decision approval is not tool-execution authorization. "
            "This snapshot is information, not an authenticated API capability."
        ),
    }
    content["content_sha256"] = sha(canonical_json(content))
    if len(canonical_json(content).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("Bridge snapshot exceeds 256 KB")
    return content


def export_bridge_snapshot(snapshot: dict, *, output: str | Path) -> dict:
    """Create one new JSON file, never overwrite; restrictive mode where supported."""
    target = Path(output).expanduser()
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ValueError("Bridge destination parent must exist and not be a symlink")
    if target.is_symlink() or target.exists():
        raise ValueError("Bridge export refuses to overwrite existing files or symlinks")
    payload = (json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ValueError("Bridge snapshot exceeds 256 KB")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(target, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        if created:
            target.unlink(missing_ok=True)
        raise
    return {
        "path": str(target.resolve()), "bytes": len(payload),
        "content_sha256": snapshot["content_sha256"], "mode": "exported",
        "notice": "Local artifact only. Nothing has been sent to any application.",
    }
