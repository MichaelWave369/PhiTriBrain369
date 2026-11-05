"""PhiTriBrain369 CLI: no daemon, external model, or automatic actions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .store import BrainStore
from .vault_import import apply_vault, preview_vault, rollback_vault, scan_vault
from .github_ingest import (
    apply as apply_github, parse_manifest, prepare as prepare_github,
    preview as preview_github,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="phitribrain", description="Three brains, one accountable ledger.")
    p.add_argument("--db", default=os.getenv("PHITRIBRAIN_DB", ".phitribrain/brain.sqlite3"), help="SQLite database path")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create local schema")
    ingest = sub.add_parser("ingest", help="WITNESS: ingest a UTF-8 text file")
    ingest.add_argument("--scope", required=True)
    ingest.add_argument("--file", required=True)
    ingest.add_argument("--title")
    ingest.add_argument("--origin")
    ingest.add_argument("--actor", default="local")
    claim = sub.add_parser("claim", help="WITNESS: add a quote-anchored claim")
    claim.add_argument("--scope", required=True)
    claim.add_argument("--source", required=True)
    claim.add_argument("--statement", required=True)
    claim.add_argument("--quote", required=True)
    claim.add_argument("--actor", default="local")
    link = sub.add_parser("link", help="WEAVER: propose a relationship between claims")
    link.add_argument("--scope", required=True)
    link.add_argument("--left", required=True)
    link.add_argument("--right", required=True)
    link.add_argument("--type", choices=("supports", "contradicts", "related"), required=True)
    link.add_argument("--why", required=True)
    decision = sub.add_parser("propose", help="STEWARD: propose a decision backed by claims")
    decision.add_argument("--scope", required=True)
    decision.add_argument("--title", required=True)
    decision.add_argument("--why", required=True)
    decision.add_argument("--evidence", nargs="+", required=True)
    decision.add_argument("--actor", default="local")
    review = sub.add_parser("review", help="STEWARD: manual decision annotation (interactive only)")
    review.add_argument("--scope", required=True)
    review.add_argument("--decision", required=True)
    review.add_argument("--outcome", choices=("approved", "rejected"), required=True)
    review.add_argument("--reviewer", required=True)
    search = sub.add_parser("search", help="Search one project scope")
    search.add_argument("--scope", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    show = sub.add_parser("show", help="Inspect one record")
    show.add_argument("--scope", required=True)
    show.add_argument("--id", required=True)
    stats = sub.add_parser("stats", help="Record counts for one scope")
    stats.add_argument("--scope", required=True)
    sub.add_parser("audit", help="Verify the audit-event hash chain")
    export = sub.add_parser("export", help="Export a scope to an empty Markdown folder")
    export.add_argument("--scope", required=True)
    export.add_argument("--directory", required=True)
    github = sub.add_parser("github", help="WITNESS: preview commit-pinned public GitHub imports")
    github.add_argument("--manifest", required=True, help="Explicit JSON allowlist (repository, commit, paths)")
    github.add_argument("--apply", action="store_true", help="Write verified sources to local SQLite")
    vault = sub.add_parser("vault", help="WITNESS: preview/apply/roll back local Markdown vault notes")
    vault.add_argument("--scope", required=True)
    vault.add_argument("--vault-id", required=True, help="Stable, nonsecret identifier for a vault")
    vault.add_argument("--directory", help="Existing directory of Markdown notes")
    vault.add_argument("--apply", action="store_true", help="Ingest selected notes into local SQLite")
    vault.add_argument("--accept-updates", action="store_true", help="Allow newer note contents to replace active path mappings")
    vault.add_argument("--rollback", metavar="BATCH_ID", help="Undo a prior import's active mappings")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "vault" and not args.rollback:
            if not args.directory:
                raise ValueError("--directory is required for vault preview/import")
            if args.accept_updates and not args.apply:
                raise ValueError("--accept-updates requires --apply")
            plans = scan_vault(
                directory=args.directory, scope=args.scope, vault_id=args.vault_id
            )
            if not args.apply:
                print(json.dumps(preview_vault(plans), ensure_ascii=False, indent=2))
                return 0
        if args.command == "vault" and args.rollback:
            if args.apply or args.accept_updates or args.directory:
                raise ValueError("--rollback cannot be combined with --apply, --accept-updates or --directory")
        if args.command == "github" and not args.apply:
            result = preview_github(prepare_github(parse_manifest(args.manifest)))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        with BrainStore(args.db) as store:
            if args.command == "init":
                result = {"database": str(Path(args.db).resolve()), "created": True}
            elif args.command == "github":
                result = apply_github(store, prepare_github(parse_manifest(args.manifest)))
            elif args.command == "vault":
                if args.rollback:
                    result = rollback_vault(
                        store, scope=args.scope, vault_id=args.vault_id,
                        batch_id=args.rollback
                    )
                else:
                    result = apply_vault(store, plans, accept_updates=args.accept_updates)
            elif args.command == "ingest":
                file_path = Path(args.file)
                if file_path.stat().st_size > 5_000_000:
                    raise ValueError("Rung 1 source size limit is 5 MB")
                result = store.ingest(
                    scope=args.scope, title=args.title or file_path.name,
                    body=file_path.read_text(encoding="utf-8"),
                    origin=args.origin or file_path.name, actor=args.actor,
                )
            elif args.command == "claim":
                result = store.add_claim(
                    scope=args.scope, source_id=args.source,
                    statement=args.statement, quote=args.quote, actor=args.actor,
                )
            elif args.command == "link":
                result = store.add_relation(
                    scope=args.scope, left=args.left, right=args.right,
                    relation=args.type, rationale=args.why,
                )
            elif args.command == "propose":
                result = store.propose_decision(
                    scope=args.scope, title=args.title, rationale=args.why,
                    claim_ids=args.evidence, actor=args.actor,
                )
            elif args.command == "review":
                if not sys.stdin.isatty():
                    raise ValueError("Review requires an interactive terminal. Automated review is disabled.")
                command = ("APPROVE" if args.outcome == "approved" else "REJECT") + " " + args.decision
                print(
                    "Manual annotation only. Does not authorize external actions."
                    f"\nType exactly: {command}", file=sys.stderr,
                )
                if input("Confirmation: ").strip() != command:
                    raise ValueError("review confirmation did not match")
                result = store.review_decision(
                    scope=args.scope, decision_id=args.decision,
                    outcome=args.outcome, reviewer=args.reviewer,
                )
            elif args.command == "search":
                result = store.search(scope=args.scope, query=args.query, limit=args.limit)
            elif args.command == "show":
                result = store.inspect(scope=args.scope, record_id=args.id)
            elif args.command == "stats":
                result = store.summary(scope=args.scope)
            elif args.command == "audit":
                result = store.verify_audit()
            elif args.command == "export":
                result = store.export_scope(args.scope, args.directory)
            else:
                raise AssertionError("unknown command")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
