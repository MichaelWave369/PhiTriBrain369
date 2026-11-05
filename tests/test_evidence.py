import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from phitribrain.evidence import annotate_claim_time, cited_claim, find_evidence
from phitribrain.store import BrainStore, sha


class EvidenceRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = BrainStore(Path(self.folder.name) / "brain.sqlite3")
        self.addCleanup(self.store.close)
        self.text = "# Architecture\nThe ledger is local.\nSources need exact quotes.\n"
        self.source = self.store.ingest(
            scope="PhiOS", title="Architecture", body=self.text,
            origin="local:architecture", actor="human",
        )
        self.claim = self.store.add_claim(
            scope="PhiOS", source_id=self.source["id"],
            statement="Ledger uses local storage",
            quote="The ledger is local.",
        )

    def cite(self, **kwargs):
        return cited_claim(
            self.store, scope="PhiOS", claim_id=self.claim["id"], **kwargs,
        )

    def test_returns_exact_quote_offset_line_and_digest(self):
        evidence = self.cite()
        self.assertEqual(evidence["quote"], "The ledger is local.")
        self.assertEqual(evidence["citation"]["source_id"], self.source["id"])
        self.assertEqual(evidence["citation"]["sha256"], sha(self.text))
        self.assertEqual(evidence["citation"]["char_offset"], self.text.index("The ledger"))
        self.assertEqual(evidence["citation"]["line_start"], 2)
        self.assertEqual(evidence["citation"]["line_end"], 2)
        self.assertTrue(evidence["attribution_only"])

    def test_multiline_claim_has_precise_lines(self):
        second = self.store.add_claim(
            scope="PhiOS", source_id=self.source["id"],
            statement="Quotes matter", quote="The ledger is local.\nSources need exact quotes.",
        )
        data = cited_claim(self.store, scope="PhiOS", claim_id=second["id"])
        self.assertEqual((data["citation"]["line_start"], data["citation"]["line_end"]), (2, 3))

    def test_scope_isolation(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            cited_claim(self.store, scope="Other", claim_id=self.claim["id"])
        self.assertTrue(
            find_evidence(self.store, scope="Other", query="ledger")["abstained"]
        )

    def test_only_quote_backed_claims_are_returned(self):
        results = find_evidence(self.store, scope="PhiOS", query="ledger")
        self.assertEqual(results["count"], 1)
        self.assertEqual(results["matches"][0]["claim_id"], self.claim["id"])
        self.assertFalse(results["abstained"])
        self.store.ingest(
            scope="PhiOS", title="One source, no claim", body="Quantum zwitterions",
            origin="local:unclaimed",
        )
        missing = find_evidence(self.store, scope="PhiOS", query="zwitterions")
        self.assertEqual(missing["matches"], [])
        self.assertTrue(missing["abstained"])

    def test_empty_query_abstains(self):
        data = find_evidence(self.store, scope="PhiOS", query="*&^")
        self.assertTrue(data["abstained"])
        self.assertEqual(data["count"], 0)

    def test_raw_sql_fts_queries_are_not_executed(self):
        for query in ('"OR', "ledger; DROP TABLE claims", "ledger* OR status:approved"):
            self.assertIsInstance(
                find_evidence(self.store, scope="PhiOS", query=query)["matches"],
                list,
            )
        self.assertIsNotNone(self.cite())

    def test_integrity_source_tamper_is_rejected(self):
        self.store.db.execute(
            "UPDATE sources SET body='fabricated text' WHERE id=?", (self.source["id"],)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.cite()

    def test_integrity_quote_tamper_is_rejected(self):
        self.store.db.execute(
            "UPDATE claims SET quote_offset=0 WHERE id=?", (self.claim["id"],)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "quote offset"):
            self.cite()

    def test_pinned_github_line_link(self):
        commit = "b" * 40
        url = f"https://github.com/example/project/blob/{commit}/docs/file.md"
        self.store.record_github_import(
            scope="PhiOS", source_id=self.source["id"],
            repository="example/project", commit=commit, path="docs/file.md",
            blob_sha="a" * 40, origin=url,
            fetched_at="2025-01-01T00:00:00+00:00",
        )
        data = self.cite(as_of="2026-01-01T00:00:00+00:00")
        github = [x for x in data["citation"]["references"]
                  if x["kind"] == "github_immutable_commit"]
        self.assertEqual(len(github), 1)
        self.assertEqual(github[0]["url"], url + "#L2")
        self.assertEqual(github[0]["commit"], commit)
        self.assertEqual(github[0]["path"], "docs/file.md")

    def test_source_age_is_observation_age_not_verification(self):
        self.store.db.execute(
            "UPDATE sources SET created_at='2020-01-01T00:00:00+00:00' "
            "WHERE id=?", (self.source["id"],)
        )
        self.store.db.commit()
        data = self.cite(as_of="2026-01-01T00:00:00Z", stale_after_days=30)
        self.assertTrue(any("older" in w for w in data["warnings"]))
        self.assertGreater(data["source_observation_age_days"], 2000)
        self.assertTrue(data["attribution_only"])

    def test_as_of_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.cite(as_of="2026-01-01T00:00:00")
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.cite(as_of="not-a-date")
        self.assertIsNotNone(self.cite(as_of="2026-01-01T12:00:00-08:00"))

    def test_invalid_stale_threshold_and_limit(self):
        with self.assertRaises(ValueError):
            self.cite(stale_after_days=0)
        with self.assertRaises(ValueError):
            find_evidence(self.store, scope="PhiOS", query="ledger", limit=0)
        with self.assertRaises(ValueError):
            find_evidence(self.store, scope="PhiOS", query="ledger", limit=51)

    def test_annotation_interval_is_unverified_and_append_only(self):
        one = annotate_claim_time(
            self.store, scope="PhiOS", claim_id=self.claim["id"],
            valid_from="2026-01-01", valid_until="2026-02-01",
            basis="Human's documented design phase",
        )
        self.assertEqual(one["status"], "asserted_not_verified")
        inside = self.cite(as_of="2026-01-20T12:00:00Z")["valid_time"]
        self.assertEqual(inside["status"], "within_asserted_interval")
        before = self.cite(as_of="2025-12-31T12:00:00Z")["valid_time"]
        self.assertEqual(before["status"], "before_asserted_interval")
        after = self.cite(as_of="2026-02-02T12:00:00Z")["valid_time"]
        self.assertEqual(after["status"], "after_asserted_interval")
        annotate_claim_time(
            self.store, scope="PhiOS", claim_id=self.claim["id"],
            valid_from="2027-01-01", basis="Revised annotation", actor="test",
        )
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM claim_time_annotations WHERE claim_id=?",
            (self.claim["id"],),
        ).fetchone()[0], 2)
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_unannotated_temporal_claim(self):
        self.assertEqual(self.cite()["valid_time"]["kind"], "unspecified")

    def test_invalid_date_interval_refused(self):
        options = [
            {"valid_from": "2026-02-30"},
            {"valid_from": "2026-04-02", "valid_until": "2026-04-01"},
            {"valid_from": "2026-01-01T00:00:00Z"},
            {},
        ]
        for params in options:
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    annotate_claim_time(
                        self.store, scope="PhiOS", claim_id=self.claim["id"],
                        basis="Test", **params,
                    )

    def test_cross_scope_annotation_refused(self):
        with self.assertRaisesRegex(ValueError, "requested scope"):
            annotate_claim_time(
                self.store, scope="Other", claim_id=self.claim["id"],
                valid_from="2026-01-01", basis="Invalid scope",
            )

    def test_proposed_contradiction_warns_not_verifies(self):
        source = self.store.ingest(
            scope="PhiOS", title="Opposition", body="The ledger is remote.",
            origin="test:remote",
        )
        claim2 = self.store.add_claim(
            scope="PhiOS", source_id=source["id"],
            statement="Ledger uses remote storage", quote="ledger is remote",
        )
        self.store.add_relation(
            scope="PhiOS", left=self.claim["id"], right=claim2["id"],
            relation="contradicts", rationale="Apparently incompatible architecture notes",
        )
        self.assertTrue(any(
            "proposed contradictory" in warning for warning in self.cite()["warnings"]
        ))

    def test_superseded_claim_warns(self):
        self.store.db.execute(
            "UPDATE claims SET state='superseded' WHERE id=?", (self.claim["id"],)
        )
        self.store.db.commit()
        self.assertTrue(any(
            "superseded" in warning for warning in self.cite()["warnings"]
        ))

    def test_historical_vault_snapshot_warns(self):
        from phitribrain.vault_import import apply_vault, rollback_vault, scan_vault
        root = Path(self.folder.name) / "vault"
        root.mkdir()
        (root / "note.md").write_text(self.text, encoding="utf-8")
        plan = scan_vault(directory=root, scope="PhiOS", vault_id="Lab")
        batch = apply_vault(self.store, plan)
        rollback_vault(self.store, scope="PhiOS", vault_id="Lab",
                       batch_id=batch["batch_id"])
        result = self.cite()
        self.assertTrue(any(
            "historical vault snapshot" in w for w in result["warnings"]
        ))

    def test_evaluation_fixture_precision(self):
        other_source = self.store.ingest(
            scope="PhiOS", title="Unrelated", body="Orbit distance: ninety miles",
            origin="test:unrelated",
        )
        other_claim = self.store.add_claim(
            scope="PhiOS", source_id=other_source["id"],
            statement="Orbit distance estimate", quote="ninety miles",
        )
        expected = {
            "ledger": {self.claim["id"]},
            "orbit": {other_claim["id"]},
            "zwitterions": set(),
        }
        for query, ids in expected.items():
            found = find_evidence(self.store, scope="PhiOS", query=query)
            self.assertEqual(
                {x["claim_id"] for x in found["matches"]}, ids,
                "retrieval must match pinned evaluation results"
            )


if __name__ == "__main__":
    unittest.main()
