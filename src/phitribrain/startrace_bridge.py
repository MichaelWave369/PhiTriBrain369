"""STARTRACE-5 research-receipt to WITNESS-preview bridge.

Strictly import-adjacent: generates a source note but never touches SQLite,
creates a claim, verifies the paper, or endorses an astronomical hypothesis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

SCHEMA = "gmed-startrace-5:research-receipt:v1"
VERDICT = "ILLUSTRATIVE_PHYSICS_ONLY"
MAX_BYTES = 1_048_576
ALLOWED_STATUSES = frozenset({
    "reported-observation",
    "published-hypothesis",
    "recorded-text",
    "unverified-attribution",
    "unconfirmed",
})


def _plain(value: Any, field: str, limit: int = 2400) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters")
    if any(ord(c) < 32 and c not in "\t\n" for c in value):
        raise ValueError(f"{field} contains control characters")
    return " ".join(value.split())


def parse_receipt(content: bytes) -> dict[str, Any]:
    """Validate a GMED analytic receipt; NOT signature authentication."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ValueError("receipt must be between 1 byte and 1 MiB")
    try:
        record = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt must contain valid UTF-8 JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("receipt root must be an object")
    if record.get("schema") != SCHEMA or record.get("verdict") != VERDICT:
        raise ValueError("not a STARTRACE-5 illustrative research receipt")
    for key in ("historicalIdentificationConfirmed", "skyPathReproduced", "independentVerification"):
        if record.get(key) is not False:
            raise ValueError(f"unsafe or missing research boundary: {key} must be false")
    _plain(record.get("generatedAt"), "generatedAt", 100)
    _plain(record.get("model"), "model", 300)
    entries = record.get("evidence")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 40:
        raise ValueError("evidence must be an array of 1 to 40 source annotations")
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"evidence[{i}] must be an object")
        eid = _plain(entry.get("id"), f"evidence[{i}].id", 100)
        if eid in seen:
            raise ValueError("duplicate evidence ID")
        seen.add(eid)
        if entry.get("status") not in ALLOWED_STATUSES:
            raise ValueError(f"invalid attribution status for {eid}")
        for name in ("category", "statement", "limitation", "source", "url"):
            _plain(entry.get(name), f"evidence[{i}].{name}")
        url = entry["url"]
        if not url.startswith("https://") or any(ch.isspace() for ch in url):
            raise ValueError(f"source URL must be HTTPS for {eid}")
    if not isinstance(record.get("inputs"), dict) or not isinstance(record.get("calculated"), dict):
        raise ValueError("receipt must contain input and calculation objects")
    return record


def render_witness_note(receipt: dict[str, Any], original_bytes: bytes) -> str:
    """Render a faithful attributed source note for optional manual WITNESS ingest."""
    parse_receipt(original_bytes)
    lines = [
        "# STARTRACE-5 | attributed research-receipt preview",
        "",
        "**This is untrusted research output, not a fact-check or proof.**",
        "",
        f"- Source JSON SHA-256: \`{hashlib.sha256(original_bytes).hexdigest()}\`",
        f"- Receipt schema: \`{SCHEMA}\`",
        f"- Receipt verdict: \`{VERDICT}\`",
        f"- Generated at (source-reported, not verified): {_plain(receipt['generatedAt'], 'generatedAt')}",
        f"- Model (source-reported): {_plain(receipt['model'], 'model')}",
        "",
        "## Source statements (attributions, not certified truths)",
        "",
    ]
    for entry in receipt["evidence"]:
        eid = _plain(entry["id"], "evidence id", 100)
        category = _plain(entry["category"], "category")
        status = _plain(entry["status"], "status")
        statement = _plain(entry["statement"], "statement")
        limitation = _plain(entry["limitation"], "limitation")
        source = _plain(entry["source"], "source")
        url = _plain(entry["url"], "url")
        lines.extend([
            f"### {eid}",
            "",
            f"- Kind: {category}",
            f"- Attribution status: {status}",
            f"- Attributed source: {source}",
            f"- Source URL (unverified link): {url}",
            "",
            f"> {statement}",
            "",
            f"Limitation: {limitation}",
            "",
        ])
    lines.extend([
        "## Calculation boundaries",
        "",
        "Input and calculated values remain in the original JSON. They are not independently checked by this bridge.",
        "No sky ephemeris, ancient-orbit reconstruction, independent source verification, or historical identification is implied.",
        "Importing this note into WITNESS preserves attribution only; create any quote-anchored claims explicitly.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Preview an untrusted STARTRACE-5 receipt as a WITNESS source note")
    parser.add_argument("receipt", type=Path, help="STARTRACE-5 JSON receipt generated by GMED")
    parser.add_argument("--output", type=Path, help="Write UTF-8 Markdown to a NEW file; never overwrite")
    args = parser.parse_args(argv)
    try:
        if args.receipt.stat().st_size > MAX_BYTES:
            raise ValueError("receipt exceeds 1 MiB")
        raw = args.receipt.read_bytes()
        record = parse_receipt(raw)
        note = render_witness_note(record, raw)
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as file:
                file.write(note)
            print(f"PREVIEW_CREATED: {args.output}")
        else:
            print(note)
    except (OSError, ValueError) as exc:
        print(f"STARTRACE_PREVIEW_REFUSED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
