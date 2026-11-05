import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.store import BrainStore
from phitribrain.weaver import MAX_CLAIMS, apply_candidates, candidates


class WeaverTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "brain.sqlite3"
        self.store = BrainStore(self.path)
        self.addCleanup(self.store.close)

    def claim(self, statement, scope="PhiOS"):
        body = f"Document asserts: {statement}\n"
        source = self.store.ingest(
            scope=scope, title=statement, body=body,
            origin="fixture:" + statement,
        )
        return self.store.add_claim(
            scope=scope, source_id=source["id"],
            statement=statement, quote=statement,
        )

    def plan(self, **kwargs):
        return candidates(self.store, scope="PhiOS", **kwargs)

    def test_exact_duplicate_is_related_not_automatically_merged(self):
        a = self.claim("Memory must remain local")
        b = self.claim("Memory must remain local")
        result = self.plan()
        self.assertEqual(result["count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["pattern"], "exact_text")
        self.assertEqual(candidate["relation"], "related")
        self.assertEqual(candidate["lexical_score"], 1.0)
        self.assertEqual(
            set((candidate["left_claim"], candidate["right_claim"])),
            {a["id"], b["id"]},
        )
        self.assertEqual(
            {x["id"] for x in candidate["evidence"]}, {a["id"], b["id"]}
        )
        self.assertEqual(candidate["truth_status"], "unverified_proposal")
        self.assertTrue(candidate["review_required"])

    def test_not_reversal_is_only_a_proposed_conflict(self):
        self.claim("The build is green")
        self.claim("The build is not green")
        result = self.plan()
        self.assertEqual(result["count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["pattern"], "explicit_not_frame")
        self.assertEqual(candidate["relation"], "contradicts")
        self.assertEqual(candidate["truth_status"], "unverified_proposal")

    def test_unaligned_negation_not_mistaken_for_opposite(self):
        self.claim("The build is green but not validated")
        self.claim("The build is green but validated")
        results = self.plan()
        self.assertFalse(
            any(c["pattern"] == "explicit_not_frame" for c in results["candidates"])
        )

    def test_overlap_is_related_without_claiming_semantics(self):
        self.claim("Local memory index preserves original text and citations")
        self.claim("Local memory index stores original text and provenance")
        result = self.plan(threshold=0.5)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["candidates"][0]["pattern"], "lexical_overlap")
        self.assertEqual(result["candidates"][0]["relation"], "related")
        self.assertLess(result["candidates"][0]["lexical_score"], 1.0)

    def test_no_pair_for_unrelated_claims(self):
        self.claim("The sun rises in the east")
        self.claim("Ocean salinity varies by latitude")
        self.assertEqual(self.plan()["count"], 0)

    def test_preview_has_no_side_effects(self):
        self.claim("The build is green")
        self.claim("The build is not green")
        before = self.store.db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.plan()
        after = self.store.db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 0
        )

    def test_apply_proposes_and_is_idempotent(self):
        self.claim("The service is enabled")
        self.claim("The service is not enabled")
        first = apply_candidates(self.store, scope="PhiOS")
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["relations"][0]["state"], "proposed")
        row = self.store.db.execute("SELECT * FROM relations").fetchone()
        self.assertEqual(row["state"], "proposed")
        self.assertEqual(row["relation"], "contradicts")
        provenance = self.store.db.execute(
            "SELECT * FROM weaver_proposals WHERE relation_id=?", (row["id"],)
        ).fetchone()
        self.assertEqual(provenance["method"], "explicit_not_frame")
        self.assertTrue(self.store.verify_audit()["ok"])
        second = apply_candidates(self.store, scope="PhiOS")
        self.assertEqual(second["created"], 0)

    def test_does_not_recreate_existing_manual_link(self):
        a = self.claim("The service is enabled")
        b = self.claim("The service is not enabled")
        self.store.add_relation(
            scope="PhiOS", left=a["id"], right=b["id"],
            relation="related", rationale="Manually noted",
        )
        self.assertEqual(self.plan()["count"], 0)
        self.assertEqual(apply_candidates(self.store, scope="PhiOS")["created"], 0)

    def test_scope_isolation(self):
        self.claim("The build is green", scope="Other")
        self.claim("The build is not green", scope="PhiOS")
        self.assertEqual(self.plan()["count"], 0)
        self.assertEqual(candidates(self.store, scope="Other")["count"], 0)

    def test_superseded_claims_are_not_suggested(self):
        a = self.claim("The build is green")
        b = self.claim("The build is not green")
        self.store.db.execute("UPDATE claims SET state='superseded' WHERE id=?", (b["id"],))
        self.store.db.commit()
        self.assertEqual(self.plan()["count"], 0)
        self.assertIsNotNone(a["id"])

    def test_source_tampering_fails_closed(self):
        self.claim("The build is green")
        self.store.db.execute("UPDATE sources SET body='fake'")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest"):
            self.plan()

    def test_quote_anchor_tampering_fails_closed(self):
        self.claim("The build is green")
        self.store.db.execute("UPDATE claims SET quote_offset=0")
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "quote"):
            self.plan()

    def test_threshold_and_limit_validation(self):
        for threshold in (0.1, 1.01, float("nan"), float("inf")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    self.plan(threshold=threshold)
        for limit in (0, 101):
            with self.assertRaises(ValueError):
                self.plan(limit=limit)
        with self.assertRaises(ValueError):
            candidates(self.store, scope="../bad")

    def test_candidate_cap_refuses_unbounded_scans(self):
        for i in range(MAX_CLAIMS + 1):
            self.claim(f"Unique statement number {i} is recorded")
        with self.assertRaisesRegex(ValueError, "limited to 250"):
            self.plan()

    def test_limit_and_determinism(self):
        for i in range(4):
            self.claim("The data is preserved")
        a = self.plan(limit=2)
        b = self.plan(limit=2)
        self.assertEqual(a["candidates"], b["candidates"])
        self.assertTrue(a["truncated"])
        self.assertEqual(a["count"], 2)

    def test_atomic_apply_on_failure(self):
        for i in range(3):
            self.claim("The data is preserved")
        original = self.store._event
        calls = [0]

        def fail_midway(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise ValueError("simulated audit failure")
            return original(*args, **kwargs)

        with patch.object(self.store, "_event", side_effect=fail_midway):
            with self.assertRaisesRegex(ValueError, "simulated"):
                apply_candidates(self.store, scope="PhiOS")
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 0
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM weaver_proposals").fetchone()[0], 0
        )
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_cli_preview_then_apply(self):
        self.claim("The build is green")
        self.claim("The build is not green")

        def run(*args):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["--db", str(self.path), *args])
            self.assertEqual(code, 0)
            return json.loads(buffer.getvalue())

        preview = run("weave", "--scope", "PhiOS")
        self.assertEqual(preview["mode"], "dry-run")
        self.assertEqual(preview["count"], 1)
        applied = run("weave", "--scope", "PhiOS", "--apply")
        self.assertEqual(applied["created"], 1)
        self.assertEqual(run("weave", "--scope", "PhiOS", "--apply")["created"], 0)

    def test_cli_preview_requires_existing_database(self):
        untouched = Path(self.folder.name) / "missing.sqlite3"
        self.assertFalse(untouched.exists())
        self.assertEqual(
            main(["--db", str(untouched), "weave", "--scope", "PhiOS"]), 2
        )
        self.assertFalse(untouched.exists())

    def test_citations_still_work_for_weaver_candidates(self):
        a = self.claim("The build is green")
        self.claim("The build is not green")
        results = self.plan()
        self.assertTrue(all(
            item["source_sha256"] and item["quote_offset"] >= 0
            for item in results["candidates"][0]["evidence"]
        ))
        from phitribrain.evidence import cited_claim
        self.assertEqual(
            cited_claim(self.store, scope="PhiOS", claim_id=a["id"])["quote"],
            "The build is green"
        )


if __name__ == "__main__":
    unittest.main()
