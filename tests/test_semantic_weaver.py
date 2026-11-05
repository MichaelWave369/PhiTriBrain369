import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.evidence import annotate_claim_time
from phitribrain.hybrid import _content_hash
from phitribrain.relation_review import relation_detail, relation_queue
from phitribrain.semantic_weaver import (
    apply_semantic_candidates, semantic_candidates,
)
from phitribrain.store import BrainStore, canonical_json


MODEL = "embeddinggemma"


class SemanticWeaverTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "brain.sqlite3"
        self.store = BrainStore(self.path)
        self.addCleanup(self.store.close)
        self.a = self.claim("The pipeline finished successfully")
        self.b = self.claim("The compilation workflow completed")
        self.c = self.claim("Orbital navigation is complicated")
        self.embed(self.a, [1.0, 0.0, 0.0])
        self.embed(self.b, [0.95, 0.3122499, 0.0])
        self.embed(self.c, [0.0, 0.0, 1.0])

    def claim(self, statement, scope="PhiOS", source_id=None):
        if source_id is None:
            s = self.store.ingest(
                scope=scope, title="Test note",
                body="Source says: " + statement,
                origin="fixture:" + statement,
            )
            source_id = s["id"]
        return self.store.add_claim(
            scope=scope, source_id=source_id,
            statement=statement, quote=statement,
        )

    def embed(self, claim, vector, model=MODEL):
        row = self.store.db.execute(
            "SELECT c.id,c.statement,c.quote,c.source_id,s.digest "
            "FROM claims c JOIN sources s ON c.source_id=s.id "
            "WHERE c.id=?", (claim["id"],),
        ).fetchone()
        self.store.db.execute(
            "INSERT INTO claim_embeddings(scope,claim_id,model,content_sha256,"
            "dimension,vector_json,indexed_at) VALUES(?,?,?,?,?,?,?)",
            ("PhiOS", claim["id"], model, _content_hash(dict(row)),
             len(vector), canonical_json(vector), "2026-11-05T00:00:00+00:00"),
        )
        self.store.db.commit()

    def preview(self, **kwargs):
        return semantic_candidates(
            self.store, scope="PhiOS", model=MODEL, **kwargs,
        )

    def test_only_related_neighborhood_is_proposed_with_exact_citations(self):
        plan = self.preview()
        self.assertEqual(plan["count"], 1)
        item = plan["candidates"][0]
        self.assertEqual(item["relation"], "related")
        self.assertEqual(item["method"], "local_semantic_neighbor")
        self.assertEqual(item["truth_status"], "unverified_proposal")
        self.assertEqual(set((item["left_claim"], item["right_claim"])),
                         {self.a["id"], self.b["id"]})
        self.assertTrue(0.9 < item["cosine_not_confidence"] <= 1)
        self.assertTrue(all(c["attribution_only"] for c in item["citations"]))
        self.assertIn("One or both claims lack asserted validity windows",
                      item["review_notes"])

    def test_preview_does_not_call_ollama_or_write_database(self):
        before = self.store.db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]
        with patch("phitribrain.hybrid.local_ollama_embed",
                   side_effect=AssertionError("no model calls")):
            plan = self.preview()
        self.assertEqual(plan["mode"], "dry-run")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relations"
        ).fetchone()[0], 0)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0], before)

    def test_disjoint_validity_windows_are_review_cautions(self):
        annotate_claim_time(
            self.store, scope="PhiOS", claim_id=self.a["id"],
            valid_from="2024-01-01", valid_until="2024-12-31",
            basis="Earlier stage",
        )
        annotate_claim_time(
            self.store, scope="PhiOS", claim_id=self.b["id"],
            valid_from="2026-01-01", valid_until="2026-12-31",
            basis="Later stage",
        )
        note = self.preview()["candidates"][0]
        self.assertTrue(any("do not overlap" in x for x in note["review_notes"]))
        self.assertEqual(note["relation"], "related")

    def test_different_github_commits_are_flagged_not_contradictions(self):
        for claim, commit in ((self.a, "a" * 40), (self.b, "b" * 40)):
            source_id = self.store.db.execute(
                "SELECT source_id FROM claims WHERE id=?", (claim["id"],)
            ).fetchone()["source_id"]
            self.store.record_github_import(
                scope="PhiOS", source_id=source_id, repository="example/project",
                commit=commit, path="README.md", blob_sha="c" * 40,
                origin=f"https://github.com/example/project/blob/{commit}/README.md",
                fetched_at="2026-11-05T00:00:00+00:00",
            )
        candidate = self.preview()["candidates"][0]
        self.assertTrue(any("different commits" in note for note in candidate["review_notes"]))
        self.assertEqual(candidate["relation"], "related")

    def test_same_source_is_not_independent_corroboration(self):
        source = self.store.ingest(
            scope="OtherScope", title="Both", body="First proof. Second proof.",
            origin="test:both",
        )
        first = self.claim("First proof", scope="OtherScope", source_id=source["id"])
        second = self.claim("Second proof", scope="OtherScope", source_id=source["id"])
        for cid in (first["id"], second["id"]):
            row = self.store.db.execute(
                "SELECT c.id,c.statement,c.quote,c.source_id,s.digest "
                "FROM claims c JOIN sources s ON c.source_id=s.id WHERE c.id=?",
                (cid,),
            ).fetchone()
            self.store.db.execute(
                "INSERT INTO claim_embeddings(scope,claim_id,model,"
                "content_sha256,dimension,vector_json,indexed_at)"
                "VALUES(?,?,?,?,?,?,?)",
                ("OtherScope", cid, MODEL, _content_hash(dict(row)), 3,
                 "[1,0,0]", "2026-11-05T00:00:00+00:00"),
            )
        self.store.db.commit()
        result = semantic_candidates(self.store, scope="OtherScope", model=MODEL)
        self.assertEqual(result["count"], 1)
        self.assertTrue(any("not independent corroboration" in n
                            for n in result["candidates"][0]["review_notes"]))

    def test_missing_and_stale_embeddings_are_skipped(self):
        self.store.db.execute(
            "UPDATE claim_embeddings SET content_sha256='tampered' WHERE claim_id=?",
            (self.b["id"],),
        )
        self.store.db.commit()
        self.assertEqual(self.preview()["count"], 0)
        self.assertEqual(self.preview()["unindexed_or_stale_claims"], 1)

    def test_bad_source_or_quote_rejected(self):
        sid = self.store.db.execute(
            "SELECT source_id FROM claims WHERE id=?", (self.a["id"],)
        ).fetchone()["source_id"]
        self.store.db.execute("UPDATE sources SET body='tampered' WHERE id=?", (sid,))
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.preview()

    def test_bad_cached_vector_or_dimensions_fails_closed(self):
        self.store.db.execute(
            "UPDATE claim_embeddings SET vector_json='[true,1,0]' WHERE claim_id=?",
            (self.a["id"],),
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "Invalid stored embedding"):
            self.preview()
        self.store.db.execute(
            "UPDATE claim_embeddings SET vector_json='[1,0]',dimension=2 WHERE claim_id=?",
            (self.a["id"],),
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "Inconsistent dimensions"):
            self.preview()

    def test_cross_scope_isolation(self):
        other = self.claim("A different project's build succeeded", scope="OtherScope")
        self.assertNotIn(other["id"],
                         [x["left_claim"] for x in self.preview()["candidates"]])
        self.assertEqual(
            semantic_candidates(self.store, scope="OtherScope", model=MODEL)["count"], 0
        )

    def test_apply_saves_only_proposed_related_with_review_context(self):
        result = apply_semantic_candidates(self.store, scope="PhiOS", model=MODEL)
        self.assertEqual(result["created"], 1)
        relation_id = result["relations"][0]["id"]
        self.assertEqual(result["relations"][0]["state"], "proposed")
        detail = relation_detail(
            self.store, scope="PhiOS", relation_id=relation_id,
        )
        self.assertEqual(detail["review_status"], "pending")
        self.assertEqual(detail["proposed_relation"], "related")
        self.assertEqual(detail["semantic_model"], MODEL)
        self.assertIsNotNone(detail["semantic_cosine_not_confidence"])
        self.assertTrue(detail["semantic_context_notes"])
        queued = relation_queue(self.store, scope="PhiOS")
        self.assertEqual(queued["items"][0]["semantic_model"], MODEL)
        self.assertTrue(self.store.verify_audit()["ok"])
        self.assertEqual(
            apply_semantic_candidates(self.store, scope="PhiOS", model=MODEL)["created"], 0
        )

    def test_existing_manual_relationship_is_respected(self):
        self.store.add_relation(
            scope="PhiOS", left=self.a["id"], right=self.b["id"],
            relation="contradicts", rationale="Human suggestion",
        )
        self.assertEqual(self.preview()["count"], 0)

    def test_failure_rolls_back_relation_and_audit(self):
        original = self.store._event

        def broken(*args, **kwargs):
            raise ValueError("audit failure")

        with patch.object(self.store, "_event", side_effect=broken):
            with self.assertRaisesRegex(ValueError, "audit failure"):
                apply_semantic_candidates(self.store, scope="PhiOS", model=MODEL)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 0
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM semantic_weaver_proposals"
            ).fetchone()[0], 0
        )
        self.assertTrue(self.store.verify_audit()["ok"])
        self.assertIsNotNone(original)

    def test_input_validation(self):
        for value in (float("nan"), float("inf"), 0.3, 1.1, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.preview(min_cosine=value)
        for value in (0, -1, 31, True):
            with self.assertRaises(ValueError):
                self.preview(limit=value)
        with self.assertRaises(ValueError):
            semantic_candidates(self.store, scope="PhiOS", model="model:cloud")

    def test_preview_cli_opens_database_read_only(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main([
                "--db", str(self.path), "weave-semantic",
                "--scope", "PhiOS", "--model", MODEL,
            ])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 0
        )

    def test_apply_cli_and_uninitialized_database(self):
        missing = Path(self.folder.name) / "not-yet.sqlite3"
        self.assertEqual(main([
            "--db", str(missing), "weave-semantic",
            "--scope", "PhiOS", "--model", MODEL,
        ]), 2)
        self.assertFalse(missing.exists())
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "--db", str(self.path), "weave-semantic",
                "--scope", "PhiOS", "--model", MODEL, "--apply",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["created"], 1)


if __name__ == "__main__":
    unittest.main()
