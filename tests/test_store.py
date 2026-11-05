import tempfile
import unittest
from pathlib import Path

from phitribrain.store import BrainStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dbpath = Path(self.tmp.name) / "memory.sqlite3"
        self.store = BrainStore(self.dbpath)
        self.addCleanup(self.store.close)

    def source(self, scope="PhiOS", content="The design calls for local memory."):
        return self.store.ingest(
            scope=scope, title="Design", body=content, origin="README.md"
        )

    def claim(self, scope="PhiOS", content="The design calls for local memory."):
        source = self.source(scope, content)
        claim = self.store.add_claim(
            scope=scope, source_id=source["id"],
            statement="Local memory is proposed", quote="local memory",
        )
        return source, claim

    def test_deduplicates_content_but_keeps_origins(self):
        original = self.source()
        again = self.store.ingest(
            scope="PhiOS", title="Second copy",
            body="The design calls for local memory.", origin="duplicate.txt",
        )
        self.assertEqual(original["id"], again["id"])
        self.assertFalse(again["new_content"])
        origins = self.store.inspect(scope="PhiOS", record_id=original["id"])["origins"]
        self.assertEqual(set(origins), {"README.md", "duplicate.txt"})

    def test_scope_isolation(self):
        source, claim = self.claim()
        self.assertIn(
            "source", [r["kind"] for r in self.store.search(scope="PhiOS", query="memory")]
        )
        self.assertEqual(self.store.search(scope="PhiBots", query="memory"), [])
        with self.assertRaises(ValueError):
            self.store.add_claim(
                scope="PhiBots", source_id=source["id"],
                statement="wrong", quote="memory",
            )
        with self.assertRaises(ValueError):
            self.store.inspect(scope="PhiBots", record_id=claim["id"])

    def test_quote_must_match_source_verbatim(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "verbatim"):
            self.store.add_claim(
                scope="PhiOS", source_id=source["id"],
                statement="Invented", quote="not found",
            )

    def test_relation_is_proposed_and_same_scope(self):
        _, a = self.claim()
        source2 = self.source(content="Shared memory can use SQLite.")
        b = self.store.add_claim(
            scope="PhiOS", source_id=source2["id"],
            statement="SQLite is proposed", quote="SQLite",
        )
        relation = self.store.add_relation(
            scope="PhiOS", left=a["id"], right=b["id"],
            relation="related", rationale="both discuss persistence",
        )
        self.assertEqual(relation["state"], "proposed")
        self.assertEqual(
            self.store.inspect(scope="PhiOS", record_id=relation["id"])["relation"],
            "related",
        )
        with self.assertRaises(ValueError):
            self.store.add_relation(
                scope="PhiBots", left=a["id"], right=b["id"],
                relation="related", rationale="cross project forbidden",
            )

    def test_decisions_need_valid_evidence(self):
        with self.assertRaisesRegex(ValueError, "evidence"):
            self.store.propose_decision(
                scope="PhiOS", title="Plan", rationale="Test", claim_ids=[],
            )
        with self.assertRaisesRegex(ValueError, "same scope"):
            self.store.propose_decision(
                scope="PhiOS", title="Plan", rationale="Test", claim_ids=["clm_invalid"],
            )
        _, claim = self.claim()
        decision = self.store.propose_decision(
            scope="PhiOS", title="Add local search",
            rationale="Makes evidence retrievable", claim_ids=[claim["id"]],
        )
        self.assertEqual(decision["status"], "proposed")
        self.assertEqual(
            self.store.inspect(scope="PhiOS", record_id=decision["id"])["evidence"],
            [claim["id"]],
        )
        reviewed = self.store.review_decision(
            scope="PhiOS", decision_id=decision["id"],
            outcome="approved", reviewer="human-test",
        )
        self.assertEqual(reviewed["status"], "approved")
        with self.assertRaises(ValueError):
            self.store.review_decision(
                scope="PhiOS", decision_id=decision["id"],
                outcome="approved", reviewer="human-test",
            )

    def test_audit_detects_modified_event(self):
        self.source()
        verified = self.store.verify_audit()
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["checked"], 2)
        self.store.db.execute(
            "UPDATE audit_events SET operation='changed' WHERE seq=1"
        )
        self.store.db.commit()
        self.assertFalse(self.store.verify_audit()["ok"])

    def test_export_and_no_overwrite(self):
        source, claim = self.claim()
        export = Path(self.tmp.name) / "vault"
        result = self.store.export_scope("PhiOS", export)
        self.assertEqual(result["counts"]["claims"], 1)
        self.assertTrue(
            (export / "sources" / f"{source['id']}.md").exists()
        )
        self.assertTrue(
            (export / "claims" / f"{claim['id']}.md").exists()
        )
        with self.assertRaisesRegex(ValueError, "empty"):
            self.store.export_scope("PhiOS", export)

    def test_search_does_not_accept_raw_fts_syntax(self):
        self.source()
        for malformed in ('"OR', 'memory:foo OR*', "!!!", "memory; DROP TABLE sources"):
            result = self.store.search(scope="PhiOS", query=malformed)
            self.assertIsInstance(result, list)
        self.assertEqual(self.store.summary(scope="PhiOS")["sources"], 1)

    def test_same_content_independent_scopes(self):
        a = self.source("PhiOS")
        b = self.source("PhiBots")
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(self.store.summary(scope="PhiOS")["sources"], 1)
        self.assertEqual(self.store.summary(scope="PhiBots")["sources"], 1)

    def test_invalid_scope_rejected(self):
        with self.assertRaises(ValueError):
            self.source("../evil")

    def test_same_claim_cannot_be_linked_to_itself(self):
        _, claim = self.claim()
        with self.assertRaisesRegex(ValueError, "different"):
            self.store.add_relation(
                scope="PhiOS", left=claim["id"], right=claim["id"],
                relation="related", rationale="self-link",
            )

    def test_claim_is_not_truth_assertion(self):
        source = self.source(content="Someone predicted the moon is cheese.")
        claim = self.store.add_claim(
            scope="PhiOS", source_id=source["id"],
            statement="The document predicts a cheese moon",
            quote="moon is cheese",
        )
        entry = self.store.inspect(scope="PhiOS", record_id=claim["id"])
        self.assertEqual(entry["state"], "recorded")
        self.assertEqual(entry["source_id"], source["id"])


if __name__ == "__main__":
    unittest.main()
