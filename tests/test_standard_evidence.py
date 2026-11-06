"""Offline, read-only, single-scope Standard Definer Rung 2 tests."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from phitribrain.standard_definer import draft, main
from phitribrain.standard_evidence import audit_definition
from phitribrain.store import BrainStore, sha


class WitnessDefinitionAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "brain.sqlite3"
        with BrainStore(self.path) as store:
            self.body = "# Local note\nA dimension is defined by a model.\n"
            self.source = store.ingest(
                scope="Physics", body=self.body, title="Dimension note",
                origin="local:note",
            )["id"]
            self.claim = store.add_claim(
                scope="Physics", source_id=self.source, statement="Model-relative dimension",
                quote="A dimension is defined by a model.",
            )["id"]
            self.second = store.add_claim(
                scope="Physics", source_id=self.source, statement="Definitions need context",
                quote="dimension is defined by a model",
            )["id"]
        self.item = draft("physics.dimension", "Dimension", "physics", "spacetime models")
        self.item["definition"] = "A model-relative independent coordinate."
        self.item["epistemic_status"] = "hypothesis"
        self.item["evidence"] = [{
            "source_id": self.source,
            "claim_id": self.claim,
            "quote": "A dimension is defined by a model.",
            "stance": "supports",
        }]

    def audit(self, scope="Physics"):
        with BrainStore(self.path, readonly=True) as store:
            return audit_definition(store, self.item, scope=scope)

    def test_exact_source_quote_and_hash_match_not_truth(self):
        r = self.audit()
        self.assertEqual(r["state"], "LOCAL_QUOTE_ANCHORS_MATCHED")
        self.assertTrue(r["attributions_matched"])
        self.assertFalse(r["truth_verified"])
        self.assertFalse(r["source_authenticated"])
        self.assertFalse(r["standard_approved"])
        self.assertFalse(r["execution_authorized"])
        self.assertTrue(r["review_required"])
        self.assertEqual(r["checks"][0]["source_sha256"], sha(self.body))
        self.assertEqual(r["checks"][0]["line_start"], 2)
        self.assertTrue(r["checks"][0]["source_attribution_only"])

    def test_no_evidence_abstains(self):
        self.item["evidence"] = []
        r = self.audit()
        self.assertEqual(r["state"], "NO_EVIDENCE_TO_CHECK")
        self.assertFalse(r["attributions_matched"])

    def test_wrong_project_scope_fails_closed(self):
        r = self.audit("Other")
        self.assertEqual(r["state"], "ATTRIBUTION_CHECK_FAILED")
        self.assertEqual(r["checks"], [])

    def test_wrong_source_binding_fails_closed(self):
        self.item["evidence"][0]["source_id"] = "src_" + "a" * 24
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")

    def test_mismatched_verbatim_quote_fails_closed(self):
        self.item["evidence"][0]["quote"] = "a dimension is defined by a model."
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")

    def test_missing_or_fake_claim_fails_closed(self):
        self.item["evidence"][0]["claim_id"] = "clm_" + "b" * 20
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")

    def test_duplicate_evidence_cannot_inflate_support(self):
        self.item["evidence"].append(dict(self.item["evidence"][0]))
        r = self.audit()
        self.assertEqual(r["state"], "ATTRIBUTION_CHECK_FAILED")
        self.assertIn("duplicate", " ".join(r["issues"]))

    def test_invalid_identifiers_fail_before_read(self):
        self.item["evidence"][0]["claim_id"] = "clm_1"
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")

    def test_tampered_source_or_offset_refused(self):
        with BrainStore(self.path) as store:
            store.db.execute("UPDATE sources SET body='fabricated' WHERE id=?", (self.source,))
            store.db.commit()
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")
        with BrainStore(self.path) as store:
            store.db.execute("UPDATE sources SET body=? WHERE id=?", (self.body, self.source))
            store.db.execute("UPDATE claims SET quote_offset=0 WHERE id=?", (self.claim,))
            store.db.commit()
        self.assertEqual(self.audit()["state"], "ATTRIBUTION_CHECK_FAILED")

    def test_disputed_claim_stays_attached_but_warns(self):
        with BrainStore(self.path) as store:
            store.db.execute("UPDATE claims SET state='disputed' WHERE id=?", (self.claim,))
            store.db.commit()
        r = self.audit()
        self.assertTrue(r["attributions_matched"])
        self.assertIn("disputed", " ".join(r["warnings"]))

    def test_old_observation_never_becomes_fresh(self):
        with BrainStore(self.path) as store:
            store.db.execute(
                "UPDATE sources SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?",
                (self.source,),
            )
            store.db.commit()
        with BrainStore(self.path, readonly=True) as store:
            r = audit_definition(
                store, self.item, scope="Physics",
                as_of="2026-01-01T00:00:00+00:00", stale_after_days=30,
            )
        self.assertIn("older", " ".join(r["warnings"]))
        self.assertFalse(r["truth_verified"])

    def test_existing_weaver_proposals_read_only(self):
        self.item["evidence"].append({
            "source_id": self.source,
            "claim_id": self.second,
            "quote": "dimension is defined by a model",
            "stance": "context",
        })
        with BrainStore(self.path) as store:
            store.add_relation(
                scope="Physics", left=self.claim, right=self.second,
                relation="related", rationale="Shared source vocabulary",
            )
            before = store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        r = self.audit()
        self.assertEqual(r["state"], "LOCAL_QUOTE_ANCHORS_MATCHED")
        self.assertEqual(r["existing_weaver_proposals"][0]["relation_proposed_not_fact"], "related")
        with BrainStore(self.path, readonly=True) as store:
            after = store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        self.assertEqual(before, after)

    def test_invalid_definition_shape_does_not_query(self):
        self.item["review_state"] = "approved"
        r = self.audit()
        self.assertEqual(r["state"], "INVALID_DEFINITION")
        self.assertFalse(r["attributions_matched"])

    def test_model_supported_is_still_not_factual(self):
        self.item["epistemic_status"] = "model_supported"
        r = self.audit()
        self.assertEqual(r["state"], "LOCAL_QUOTE_ANCHORS_MATCHED")
        self.assertFalse(r["truth_verified"])

    def test_cli_preview_uses_readonly_db_and_returns_json(self):
        path = Path(self.tmp.name) / "candidate.json"
        path.write_text(json.dumps(self.item), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            result = main(["evidence", str(path), "--db", str(self.path), "--scope", "Physics"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(out.getvalue())["state"], "LOCAL_QUOTE_ANCHORS_MATCHED")
        self.assertFalse((Path(self.tmp.name) / "missing.sqlite3").exists())

    def test_cli_missing_db_does_not_create_it(self):
        path = Path(self.tmp.name) / "candidate.json"
        path.write_text(json.dumps(self.item), encoding="utf-8")
        missing = Path(self.tmp.name) / "missing.sqlite3"
        with redirect_stdout(io.StringIO()):
            result = main(["evidence", str(path), "--db", str(missing), "--scope", "Physics"])
        self.assertEqual(result, 2)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
