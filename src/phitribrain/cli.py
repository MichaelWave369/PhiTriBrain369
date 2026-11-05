"""PhiTriBrain369 CLI: no daemon, external model, or automatic actions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .store import BrainStore
from .hybrid import build_index, evaluate_hybrid, hybrid_search, index_plan
from .relation_review import annotate_relation, relation_detail, relation_queue
from .weaver import candidates as weaver_candidates, apply_candidates as apply_weaver
from .evidence import annotate_claim_time, cited_claim, find_evidence
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
    evidence = sub.add_parser("evidence", help="Find quote-backed claims with source citations")
    evidence.add_argument("--scope", required=True)
    evidence.add_argument("--query", required=True)
    evidence.add_argument("--limit", type=int, default=10)
    evidence.add_argument("--as-of", help="ISO 8601 datetime with timezone")
    evidence.add_argument("--stale-after-days", type=int, default=180)
    cite = sub.add_parser("cite", help="Show an exact quote citation for a claim")
    cite.add_argument("--scope", required=True)
    cite.add_argument("--claim", required=True)
    cite.add_argument("--as-of", help="ISO 8601 datetime with timezone")
    cite.add_argument("--stale-after-days", type=int, default=180)
    claim_time = sub.add_parser("claim-time", help="Append a claimed validity interval, never verify it")
    claim_time.add_argument("--scope", required=True)
    claim_time.add_argument("--claim", required=True)
    claim_time.add_argument("--from", dest="valid_from", help="Asserted earliest validity date (YYYY-MM-DD)")
    claim_time.add_argument("--until", dest="valid_until", help="Asserted latest validity date (YYYY-MM-DD)")
    claim_time.add_argument("--basis", required=True, help="Explain why this interval is asserted")
    claim_time.add_argument("--actor", default="local", help="Unauthenticated actor label")
    weave = sub.add_parser("weave", help="WEAVER: preview bounded lexical relation suggestions")
    weave.add_argument("--scope", required=True)
    weave.add_argument("--threshold", type=float, default=0.72, help="Jaccard overlap threshold (0.3-1.0)")
    weave.add_argument("--limit", type=int, default=30, help="Maximum suggestions per run (1-100)")
    weave.add_argument("--apply", action="store_true", help="Save review-only proposed links")
    queue = sub.add_parser("relation-queue", help="View pending and reviewed relation proposals")
    queue.add_argument("--scope", required=True)
    queue.add_argument("--status", default="pending",
                       choices=("pending", "accepted", "rejected", "needs_context", "all"))
    queue.add_argument("--limit", type=int, default=20)
    queue.add_argument("--offset", type=int, default=0)
    detail = sub.add_parser("relation-detail", help="Show source citations and full review history")
    detail.add_argument("--scope", required=True)
    detail.add_argument("--relation", required=True)
    review_relation = sub.add_parser("relation-review", help="Append manual review of one proposed link")
    review_relation.add_argument("--scope", required=True)
    review_relation.add_argument("--relation", required=True)
    review_relation.add_argument("--outcome", required=True,
                                 choices=("accepted", "rejected", "needs_context"))
    review_relation.add_argument("--reviewer", required=True, help="Local, unauthenticated label")
    review_relation.add_argument("--reason", required=True, help="Explain the assessment with context")
    review_relation.add_argument("--supersedes", help="Required previous review ID when revising")
    embed = sub.add_parser("embed-index", help="Preview or explicitly build a local Ollama claim vector index")
    embed.add_argument("--scope", required=True)
    embed.add_argument("--model", required=True, help="Installed LOCAL Ollama embedding model name")
    embed.add_argument("--limit", type=int, default=20, help="Max newly indexed claims per call (1-100)")
    embed.add_argument("--apply", action="store_true", help="Explicitly send selected claims to loopback Ollama")
    hybrid = sub.add_parser("hybrid", help="Quote-backed lexical + local embedding RRF retrieval")
    hybrid.add_argument("--scope", required=True)
    hybrid.add_argument("--query", required=True)
    hybrid.add_argument("--model", required=True)
    hybrid.add_argument("--limit", type=int, default=10)
    hybrid.add_argument("--min-cosine", type=float, default=0.15)
    metric = sub.add_parser("hybrid-eval", help="Evaluate hybrid versus lexical on a human-judged corpus")
    metric.add_argument("--scope", required=True)
    metric.add_argument("--model", required=True)
    metric.add_argument("--corpus", required=True, help="Local JSON with scoped query and relevant claim IDs")
    metric.add_argument("--k", type=int, default=5)
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
        if args.command in (
            "weave", "relation-queue", "relation-detail", "relation-review",
            "embed-index", "hybrid", "hybrid-eval"
        ) and not Path(args.db).expanduser().is_file():
            raise ValueError("Knowledge retrieval requires an existing initialized database")
        if args.command == "relation-review":
            if not sys.stdin.isatty():
                raise ValueError("Relation reviews require an interactive terminal; automated approval disabled")
            confirmation = f"REVIEW {args.relation} {args.outcome.upper()}"
            print("Review is an annotation, not truth verification or action permission.",
                  file=sys.stderr)
            print(f"Type exactly: {confirmation}", file=sys.stderr)
            if input("Confirmation: ").strip() != confirmation:
                raise ValueError("Review confirmation did not match")
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
            elif args.command == "weave":
                if args.apply:
                    result = apply_weaver(
                        store, scope=args.scope, threshold=args.threshold,
                        limit=args.limit,
                    )
                else:
                    result = weaver_candidates(
                        store, scope=args.scope, threshold=args.threshold,
                        limit=args.limit,
                    )
            elif args.command == "relation-queue":
                result = relation_queue(store, scope=args.scope,
                                        status=args.status, limit=args.limit,
                                        offset=args.offset)
            elif args.command == "relation-detail":
                result = relation_detail(store, scope=args.scope,
                                         relation_id=args.relation)
            elif args.command == "relation-review":
                result = annotate_relation(
                    store, scope=args.scope, relation_id=args.relation,
                    outcome=args.outcome, reviewer=args.reviewer,
                    reason=args.reason, supersedes=args.supersedes,
                )
            elif args.command == "evidence":
                result = find_evidence(
                    store, scope=args.scope, query=args.query, limit=args.limit,
                    as_of=args.as_of, stale_after_days=args.stale_after_days,
                )
            elif args.command == "embed-index":
                if args.apply:
                    result = build_index(
                        store, scope=args.scope, model=args.model, limit=args.limit,
                    )
                else:
                    plan = index_plan(
                        store, scope=args.scope, model=args.model, limit=args.limit,
                    )
                    result = {k: v for k, v in plan.items() if k != "selected"}
                    result["selected_claim_ids"] = [
                        row["id"] for row in plan["selected"]
                    ]
            elif args.command == "hybrid":
                result = hybrid_search(
                    store, scope=args.scope, model=args.model,
                    query=args.query, limit=args.limit,
                    min_cosine=args.min_cosine,
                )
            elif args.command == "hybrid-eval":
                result = evaluate_hybrid(
                    store, scope=args.scope, model=args.model,
                    corpus=args.corpus, k=args.k,
                )
            elif args.command == "cite":
                result = cited_claim(
                    store, scope=args.scope, claim_id=args.claim,
                    as_of=args.as_of, stale_after_days=args.stale_after_days,
                )
            elif args.command == "claim-time":
                result = annotate_claim_time(
                    store, scope=args.scope, claim_id=args.claim,
                    valid_from=args.valid_from, valid_until=args.valid_until,
                    basis=args.basis, actor=args.actor,
                )
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
