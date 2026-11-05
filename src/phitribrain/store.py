"""Φ TriBrain 369 local-first evidence ledger.

WITNESS preserves sources and source-attributed claims.
WEAVER proposes relationships between sourced claims.
STEWARD proposes decisions but never executes actions.
No networking, model calls, background services, or external dependencies.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import nullcontext
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SEARCH_WORDS = re.compile(r"\w+", re.UNICODE)
RELATIONS = ("supports", "contradicts", "related")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_scope(scope: str) -> str:
    if not SCOPE_PATTERN.fullmatch(scope):
        raise ValueError("scope must be 1-64 characters: letters, digits, periods, underscores, hyphens")
    return scope


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 title TEXT NOT NULL,
 body TEXT NOT NULL,
 digest TEXT NOT NULL,
 created_at TEXT NOT NULL,
 recorded_by TEXT NOT NULL,
 UNIQUE(scope, digest)
);
CREATE TABLE IF NOT EXISTS source_origins (
 source_id TEXT NOT NULL REFERENCES sources(id),
 origin TEXT NOT NULL,
 first_seen TEXT NOT NULL,
 PRIMARY KEY(source_id, origin)
);
CREATE TABLE IF NOT EXISTS claims (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources(id),
 statement TEXT NOT NULL,
 quote TEXT NOT NULL,
 quote_offset INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'recorded' CHECK(state IN ('recorded','disputed','superseded')),
 created_at TEXT NOT NULL,
 recorded_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relations (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 left_claim TEXT NOT NULL REFERENCES claims(id),
 right_claim TEXT NOT NULL REFERENCES claims(id),
 relation TEXT NOT NULL CHECK(relation IN ('supports','contradicts','related')),
 rationale TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'proposed' CHECK(state IN ('proposed')),
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 title TEXT NOT NULL,
 rationale TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('proposed','approved','rejected')),
 created_at TEXT NOT NULL,
 proposed_by TEXT NOT NULL,
 reviewed_at TEXT,
 reviewed_by TEXT
);
CREATE TABLE IF NOT EXISTS decision_evidence (
 decision_id TEXT NOT NULL REFERENCES decisions(id),
 claim_id TEXT NOT NULL REFERENCES claims(id),
 PRIMARY KEY(decision_id, claim_id)
);
CREATE TABLE IF NOT EXISTS audit_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL,
 scope TEXT NOT NULL,
 operation TEXT NOT NULL,
 details_json TEXT NOT NULL,
 prev_hash TEXT NOT NULL,
 event_hash TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
 scope UNINDEXED, kind UNINDEXED, record_id UNINDEXED,
 title, body, tokenize='unicode61'
);
CREATE INDEX IF NOT EXISTS idx_claims_scope ON claims(scope);
CREATE INDEX IF NOT EXISTS idx_decisions_scope ON decisions(scope);
CREATE TABLE IF NOT EXISTS github_imports (
 import_id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources(id),
 repository TEXT NOT NULL,
 commit_sha TEXT NOT NULL,
 path TEXT NOT NULL,
 blob_sha TEXT NOT NULL,
 origin TEXT NOT NULL,
 fetched_at TEXT NOT NULL,
 UNIQUE(scope, repository, commit_sha, path)
);
CREATE INDEX IF NOT EXISTS idx_github_imports_source ON github_imports(source_id);
CREATE TABLE IF NOT EXISTS vault_batches (
 id TEXT PRIMARY KEY,
 scope TEXT NOT NULL,
 vault_id TEXT NOT NULL,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','rolled_back')),
 rolled_back_at TEXT
);
CREATE TABLE IF NOT EXISTS vault_notes (
 scope TEXT NOT NULL,
 vault_id TEXT NOT NULL,
 relative_path TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources(id),
 digest TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(scope,vault_id,relative_path)
);
CREATE TABLE IF NOT EXISTS vault_revisions (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 batch_id TEXT NOT NULL REFERENCES vault_batches(id),
 scope TEXT NOT NULL,
 vault_id TEXT NOT NULL,
 relative_path TEXT NOT NULL,
 previous_source_id TEXT REFERENCES sources(id),
 previous_digest TEXT,
 new_source_id TEXT NOT NULL REFERENCES sources(id),
 new_digest TEXT NOT NULL,
 UNIQUE(batch_id,relative_path)
);
CREATE INDEX IF NOT EXISTS idx_vault_rev_batch ON vault_revisions(batch_id);
CREATE TABLE IF NOT EXISTS claim_time_annotations (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 id TEXT NOT NULL UNIQUE,
 scope TEXT NOT NULL,
 claim_id TEXT NOT NULL REFERENCES claims(id),
 valid_from TEXT,
 valid_until TEXT,
 basis TEXT NOT NULL,
 actor TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_time_lookup ON claim_time_annotations(scope,claim_id,seq);
CREATE TABLE IF NOT EXISTS weaver_proposals (
 relation_id TEXT PRIMARY KEY REFERENCES relations(id),
 scope TEXT NOT NULL,
 method TEXT NOT NULL CHECK(method IN ('exact_text','explicit_not_frame','lexical_overlap')),
 lexical_score REAL NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_scope ON audit_events(scope);
"""


class BrainStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _event(self, scope: str, operation: str, details: dict):
        """Call inside the transaction corresponding to a write."""
        row = self.db.execute("SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row["event_hash"] if row else "0" * 64
        event_id = new_id("evt")
        fields = [event_id, utcnow(), scope, operation, canonical_json(details), previous]
        event_hash = sha(canonical_json(fields))
        self.db.execute(
            "INSERT INTO audit_events(event_id,created_at,scope,operation,details_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?)",
            (*fields, event_hash),
        )

    def ingest(self, *, scope: str, title: str, body: str, origin: str, actor: str = "local", defer_commit: bool = False) -> dict:
        """WITNESS: store exact UTF-8 text and a recorded origin."""
        scope = validate_scope(scope)
        if not title.strip() or not origin.strip() or not body.strip():
            raise ValueError("title, origin, and body must be nonempty")
        if len(body.encode("utf-8")) > 5_000_000:
            raise ValueError("Rung 1 text source limit is 5 MB")
        if defer_commit and not self.db.in_transaction:
            raise ValueError("defer_commit requires an active caller transaction")
        digest = sha(body)
        source_id = "src_" + sha(scope + "\x00" + digest)[:24]
        with (nullcontext() if defer_commit else self.db):
            existing = self.db.execute(
                "SELECT id FROM sources WHERE scope=? AND digest=?", (scope, digest)
            ).fetchone()
            inserted = not bool(existing)
            if inserted:
                self.db.execute(
                    "INSERT INTO sources(id,scope,title,body,digest,created_at,recorded_by) VALUES(?,?,?,?,?,?,?)",
                    (source_id, scope, title, body, digest, utcnow(), actor),
                )
                self.db.execute(
                    "INSERT INTO search_fts(scope,kind,record_id,title,body) VALUES(?,?,?,?,?)",
                    (scope, "source", source_id, title, body),
                )
                self._event(scope, "source.ingest", {"id": source_id, "digest": digest, "actor": actor})
            else:
                source_id = existing["id"]
            cur = self.db.execute(
                "INSERT OR IGNORE INTO source_origins(source_id,origin,first_seen) VALUES(?,?,?)",
                (source_id, origin, utcnow()),
            )
            if cur.rowcount:
                self._event(scope, "source.origin", {"id": source_id, "origin": origin})
        return {"id": source_id, "digest": digest, "new_content": inserted, "scope": scope}

    def add_claim(self, *, scope: str, source_id: str, statement: str, quote: str, actor: str = "local") -> dict:
        """WITNESS: an attributed claim, not a guaranteed fact."""
        scope = validate_scope(scope)
        source = self.db.execute(
            "SELECT * FROM sources WHERE id=? AND scope=?", (source_id, scope)
        ).fetchone()
        if not source:
            raise ValueError("source does not exist in the requested scope")
        if not statement.strip() or not quote.strip():
            raise ValueError("statement and quote must be nonempty")
        offset = source["body"].find(quote)
        if offset < 0:
            raise ValueError("quote must appear verbatim in the source text")
        claim_id = new_id("clm")
        with self.db:
            self.db.execute(
                "INSERT INTO claims(id,scope,source_id,statement,quote,quote_offset,created_at,recorded_by) VALUES(?,?,?,?,?,?,?,?)",
                (claim_id, scope, source_id, statement, quote, offset, utcnow(), actor),
            )
            self.db.execute(
                "INSERT INTO search_fts(scope,kind,record_id,title,body) VALUES(?,?,?,?,?)",
                (scope, "claim", claim_id, statement, quote),
            )
            self._event(scope, "claim.record", {"id": claim_id, "source_id": source_id, "actor": actor})
        return {"id": claim_id, "source_id": source_id, "quote_offset": offset, "state": "recorded"}

    def add_relation(self, *, scope: str, left: str, right: str, relation: str, rationale: str) -> dict:
        """WEAVER: propose relationships, never silently assert them as facts."""
        scope = validate_scope(scope)
        if relation not in RELATIONS:
            raise ValueError("relation must be supports, contradicts, or related")
        if left == right or not rationale.strip():
            raise ValueError("different claims and a rationale are required")
        found = self.db.execute(
            "SELECT id FROM claims WHERE scope=? AND id IN (?,?)", (scope, left, right)
        ).fetchall()
        if len(found) != 2:
            raise ValueError("both claims must exist in the same scope")
        relation_id = new_id("rel")
        with self.db:
            self.db.execute(
                "INSERT INTO relations(id,scope,left_claim,right_claim,relation,rationale,created_at) VALUES(?,?,?,?,?,?,?)",
                (relation_id, scope, left, right, relation, rationale, utcnow()),
            )
            self._event(scope, "relation.propose", {"id": relation_id, "left": left, "right": right, "type": relation})
        return {"id": relation_id, "state": "proposed", "relation": relation}

    def propose_decision(self, *, scope: str, title: str, rationale: str, claim_ids: list[str], actor: str = "local") -> dict:
        """STEWARD: only propose evidence-linked decisions, never execute them."""
        scope = validate_scope(scope)
        claim_ids = list(dict.fromkeys(claim_ids))
        if not title.strip() or not rationale.strip() or not claim_ids:
            raise ValueError("title, rationale, and at least one evidence claim are required")
        matches = self.db.execute(
            "SELECT id FROM claims WHERE scope=? AND id IN (" + ",".join("?" for _ in claim_ids) + ")",
            [scope, *claim_ids],
        ).fetchall()
        if len(matches) != len(claim_ids):
            raise ValueError("every evidence claim must exist in the same scope")
        decision_id = new_id("dec")
        with self.db:
            self.db.execute(
                "INSERT INTO decisions(id,scope,title,rationale,status,created_at,proposed_by) VALUES(?,?,?,?,'proposed',?,?)",
                (decision_id, scope, title, rationale, utcnow(), actor),
            )
            for claim in claim_ids:
                self.db.execute(
                    "INSERT INTO decision_evidence(decision_id,claim_id) VALUES(?,?)",
                    (decision_id, claim),
                )
            self.db.execute(
                "INSERT INTO search_fts(scope,kind,record_id,title,body) VALUES(?,?,?,?,?)",
                (scope, "decision", decision_id, title, rationale),
            )
            self._event(scope, "decision.propose", {"id": decision_id, "claim_ids": claim_ids, "actor": actor})
        return {"id": decision_id, "status": "proposed", "evidence": claim_ids}

    def review_decision(self, *, scope: str, decision_id: str, outcome: str, reviewer: str) -> dict:
        """A local approval annotation, not validated authentication or action permission."""
        scope = validate_scope(scope)
        if outcome not in ("approved", "rejected") or not reviewer.strip():
            raise ValueError("outcome must be approved/rejected and reviewer must be nonempty")
        with self.db:
            existing = self.db.execute(
                "SELECT status FROM decisions WHERE id=? AND scope=?", (decision_id, scope)
            ).fetchone()
            if not existing or existing["status"] != "proposed":
                raise ValueError("decision not found, or it has already been reviewed")
            self.db.execute(
                "UPDATE decisions SET status=?,reviewed_at=?,reviewed_by=? WHERE id=?",
                (outcome, utcnow(), reviewer, decision_id),
            )
            self._event(scope, "decision.review", {"id": decision_id, "outcome": outcome, "reviewer": reviewer})
        return {"id": decision_id, "status": outcome, "reviewed_by": reviewer}


    def record_github_import(self, *, scope: str, source_id: str, repository: str,
                             commit: str, path: str, blob_sha: str, origin: str,
                             fetched_at: str) -> dict:
        """Add a structured, idempotent GitHub provenance record.

        This links an existing source to an immutable commit and Git blob ID.
        Does not prove that the underlying source statement is factual.
        """
        scope = validate_scope(scope)
        source = self.db.execute(
            "SELECT id FROM sources WHERE id=? AND scope=?", (source_id, scope)
        ).fetchone()
        if not source:
            raise ValueError("GitHub import source must exist in the same scope")
        import_id = "ghi_" + sha(canonical_json(
            [scope, repository, commit, path]
        ))[:24]
        existing = self.db.execute(
            "SELECT source_id,blob_sha,origin FROM github_imports "
            "WHERE scope=? AND repository=? AND commit_sha=? AND path=?",
            (scope, repository, commit, path),
        ).fetchone()
        if existing:
            if (existing["source_id"], existing["blob_sha"], existing["origin"]) != (
                source_id, blob_sha, origin
            ):
                raise ValueError("Conflicting contents for an already pinned GitHub import")
            return {"id": import_id, "new_import": False}
        with self.db:
            self.db.execute(
                "INSERT INTO github_imports(import_id,scope,source_id,repository,"
                "commit_sha,path,blob_sha,origin,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (import_id, scope, source_id, repository, commit, path,
                 blob_sha, origin, fetched_at),
            )
            self._event(scope, "github.import", {
                "id": import_id, "source_id": source_id, "repository": repository,
                "commit": commit, "path": path, "blob_sha": blob_sha,
                "origin": origin, "fetched_at": fetched_at,
            })
        return {"id": import_id, "new_import": True}

    def github_provenance(self, *, scope: str, source_id: str) -> list[dict]:
        """Return structured provenance for an already recorded source."""
        scope = validate_scope(scope)
        return [dict(row) for row in self.db.execute(
            "SELECT repository,commit_sha,path,blob_sha,origin,fetched_at "
            "FROM github_imports WHERE scope=? AND source_id=? "
            "ORDER BY fetched_at,repository,path",
            (scope, source_id),
        )]

    def search(self, *, scope: str, query: str, limit: int = 10) -> list[dict]:
        """Scoped FTS5 lexical search. Does not execute arbitrary query syntax."""
        scope = validate_scope(scope)
        tokens = SEARCH_WORDS.findall(query)[:16]
        if not tokens:
            return []
        match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        rows = self.db.execute(
            "SELECT kind,record_id,title,snippet(search_fts,4,'[',']','...',16) AS excerpt,"
            "bm25(search_fts) AS score FROM search_fts "
            "WHERE search_fts MATCH ? AND scope=? ORDER BY score LIMIT ?",
            (match, scope, min(max(int(limit), 1), 100)),
        ).fetchall()
        return [dict(row) for row in rows]

    def inspect(self, *, scope: str, record_id: str) -> dict:
        scope = validate_scope(scope)
        tables = {"src": "sources", "clm": "claims", "rel": "relations", "dec": "decisions"}
        table = tables.get(record_id.split("_", 1)[0])
        if not table:
            raise ValueError("unrecognized record ID")
        row = self.db.execute(
            f"SELECT * FROM {table} WHERE id=? AND scope=?", (record_id, scope)
        ).fetchone()
        if not row:
            raise ValueError("record not found in that scope")
        data = dict(row)
        if table == "sources":
            data["origins"] = [
                r["origin"] for r in self.db.execute(
                    "SELECT origin FROM source_origins WHERE source_id=?", (record_id,)
                )
            ]
            data["github_provenance"] = self.github_provenance(
                scope=scope, source_id=record_id
            )
            data["vault_paths"] = [
                {"vault_id": r["vault_id"], "relative_path": r["relative_path"]}
                for r in self.db.execute(
                    "SELECT vault_id,relative_path FROM vault_notes WHERE scope=? AND source_id=? "
                    "ORDER BY vault_id,relative_path", (scope, record_id)
                )
            ]
        if table == "decisions":
            data["evidence"] = [
                r["claim_id"] for r in self.db.execute(
                    "SELECT claim_id FROM decision_evidence WHERE decision_id=?", (record_id,)
                )
            ]
        return data

    def summary(self, *, scope: str) -> dict:
        scope = validate_scope(scope)
        totals = {}
        for table in ("sources", "claims", "relations", "decisions"):
            totals[table] = self.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE scope=?", (scope,)
            ).fetchone()[0]
        totals["proposed_decisions"] = self.db.execute(
            "SELECT COUNT(*) FROM decisions WHERE scope=? AND status='proposed'", (scope,)
        ).fetchone()[0]
        totals["audit_events"] = self.db.execute(
            "SELECT COUNT(*) FROM audit_events WHERE scope=?", (scope,)
        ).fetchone()[0]
        return {"scope": scope, **totals}

    def verify_audit(self) -> dict:
        """Detect broken links in event chain. This is not tamper-proof against a DB owner."""
        previous = "0" * 64
        count = 0
        for row in self.db.execute("SELECT * FROM audit_events ORDER BY seq"):
            fields = [
                row[k] for k in (
                    "event_id", "created_at", "scope", "operation", "details_json", "prev_hash"
                )
            ]
            if row["prev_hash"] != previous or row["event_hash"] != sha(canonical_json(fields)):
                return {"ok": False, "checked": count, "failed_seq": row["seq"]}
            previous = row["event_hash"]
            count += 1
        return {"ok": True, "checked": count, "head_hash": previous}

    def export_scope(self, scope: str, directory: str | Path) -> dict:
        """Read-only Obsidian-compatible snapshot export. Will not overwrite existing files."""
        scope = validate_scope(scope)
        target = Path(directory).expanduser()
        if target.exists() and any(target.iterdir()):
            raise ValueError("export directory must be empty; refusing to overwrite files")
        target.mkdir(parents=True, exist_ok=True)
        counts = {}
        for table in ("sources", "claims", "relations", "decisions"):
            rows = [
                dict(r) for r in self.db.execute(
                    f"SELECT * FROM {table} WHERE scope=? ORDER BY created_at", (scope,)
                )
            ]
            destination = target / table
            destination.mkdir(exist_ok=True)
            for row in rows:
                rid = row["id"]
                if table == "sources":
                    row["origins"] = [
                        r["origin"] for r in self.db.execute(
                            "SELECT origin FROM source_origins WHERE source_id=?", (rid,)
                        )
                    ]
                    note = f"# {row['title']}\n\nSource ID: \x60{rid}\x60\n\nScope: \x60{scope}\x60\n\n## Original text\n\n{row['body']}\n"
                elif table == "claims":
                    note = (
                        f"# Claim {rid}\n\nStatus: **{row['state']}** "
                        "(source-attributed, not independently verified)\n\n"
                        f"{row['statement']}\n\nSource: [[{row['source_id']}]]\n\n"
                        f"> {row['quote'].replace(chr(10), chr(10) + '> ')}\n"
                    )
                elif table == "relations":
                    note = (
                        f"# Proposed {row['relation']} relation\n\n"
                        f"[[{row['left_claim']}]] → [[{row['right_claim']}]]\n\n"
                        f"Status: **proposed**\n\n{row['rationale']}\n"
                    )
                else:
                    row["evidence"] = [
                        r["claim_id"] for r in self.db.execute(
                            "SELECT claim_id FROM decision_evidence WHERE decision_id=?", (rid,)
                        )
                    ]
                    note = (
                        f"# {row['title']}\n\nStatus: **{row['status']}**\n\n"
                        f"{row['rationale']}\n\nEvidence: "
                        + ", ".join(f"[[{c}]]" for c in row["evidence"]) + "\n"
                    )
                (destination / f"{rid}.md").write_text(note, encoding="utf-8")
            counts[table] = len(rows)
        (target / "manifest.json").write_text(
            json.dumps(
                {"scope": scope, "counts": counts, "exported_at": utcnow()},
                indent=2,
            ),
            encoding="utf-8",
        )
        (target / "README.md").write_text(
            f"# PhiTriBrain snapshot: {scope}\n\n"
            "Read-only export. Original records and database audit chain remain in "
            "the local database.\n\nLinks use Obsidian wikilink syntax.\n",
            encoding="utf-8",
        )
        return {"directory": str(target), "counts": counts}
