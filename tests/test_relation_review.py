import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.relation_review import (
    annotate_relation, relation_detail, relation_queue,
)
from phitribrain.store import BrainStore
from phitribrain.weaver import apply_candidates


class RelationReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "brain.sqlite3"
        self.store = BrainStore(self.path)
        self.addCleanup(self.store.close)
        self.a = self.claim("The build is green")
        self.b = self.claim("The build is not green")
        result = apply_candidates(self.store, scope="PhiOS")
        self.rel = result["relations"][0]["id"]

    def claim(self, words, scope="PhiOS"):
        source = self.store.ingest(
            scope=scope, title="Build note",
            body="One observed statement: " + words,
            origin="fixture:" + words,
        )
        return self.store.add_claim(
            scope=scope, source_id=source["id"],
            statement=words, quote=words,
        )

    def review(self, outcome="accepted", supersedes=None, **kwargs):
        return annotate_relation(
            self.store, scope="PhiOS", relation_id=self.rel,
            outcome=outcome, reviewer="Human Tester",
            reason="Reviewed source context; this is an annotation only",
            supersedes=supersedes, **kwargs,
        )

    def test_pending_queue_is_read_only(self):
        before = self.store.db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]
        items = relation_queue(self.store, scope="PhiOS")
        self.assertEqual(items["total"], 1)
        self.assertEqual(items["items"][0]["review_status"], "pending")
        self.assertEqual(items["items"][0]["proposal_method"], "explicit_not_frame")
        self.assertIsNone(items["items"][0]["last_review_id"])
        after = self.store.db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]
        self.assertEqual(before, after)

    def test_manual_relation_appears_in_queue(self):
        a = self.claim("Evidence and explanations matter")
        b = self.claim("Reasoning and citations matter")
        relation = self.store.add_relation(
            scope="PhiOS", left=a["id"], right=b["id"],
            relation="related", rationale="Human noticed a relationship",
        )
        items = relation_queue(self.store, scope="PhiOS")
        found = next(x for x in items["items"] if x["id"] == relation["id"])
        self.assertIsNone(found["proposal_method"])

    def test_acceptance_is_review_only(self):
        result = self.review()
        self.assertEqual(result["review_status"], "accepted")
        self.assertEqual(result["truth_status"], "unverified_relation_review")
        detail = relation_detail(self.store, scope="PhiOS", relation_id=self.rel)
        self.assertEqual(detail["review_status"], "accepted")
        self.assertEqual(detail["relation_database_state"], "proposed")
        self.assertEqual(len(detail["reviews"]), 1)
        self.assertTrue(all(c["attribution_only"] for c in detail["claim_evidence"]))
        self.assertEqual(self.store.db.execute(
            "SELECT state FROM relations WHERE id=?", (self.rel,)
        ).fetchone()["state"], "proposed")
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_rejection_does_not_erase_link_or_source(self):
        self.review(outcome="rejected")
        reviewed = relation_queue(self.store, scope="PhiOS", status="rejected")
        self.assertEqual(reviewed["total"], 1)
        self.assertEqual(relation_queue(
            self.store, scope="PhiOS", status="pending"
        )["total"], 0)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relations"
        ).fetchone()[0], 1)
        self.assertEqual(self.store.summary(scope="PhiOS")["claims"], 2)

    def test_review_can_be_revisited_without_rewriting_history(self):
        first = self.review(outcome="rejected")
        second = self.review(outcome="needs_context", supersedes=first["review_id"])
        third = self.review(outcome="accepted", supersedes=second["review_id"])
        detail = relation_detail(self.store, scope="PhiOS", relation_id=self.rel)
        self.assertEqual(detail["review_status"], "accepted")
        self.assertEqual([r["outcome"] for r in detail["reviews"]],
                         ["rejected", "needs_context", "accepted"])
        self.assertEqual(detail["reviews"][1]["previous_review_id"], first["review_id"])
        self.assertEqual(detail["reviews"][2]["previous_review_id"], second["review_id"])
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_review_requires_latest_optimistic_lock(self):
        first = self.review(outcome="accepted")
        with self.assertRaisesRegex(ValueError, "Review conflict"):
            self.review(outcome="rejected")
        with self.assertRaisesRegex(ValueError, "Review conflict"):
            self.review(outcome="rejected", supersedes="rrev_stale")
        self.assertEqual(
            relation_detail(self.store, scope="PhiOS", relation_id=self.rel)["last_review_id"],
            first["review_id"],
        )

    def test_cannot_duplicate_same_outcome(self):
        first = self.review()
        with self.assertRaisesRegex(ValueError, "unchanged"):
            self.review(supersedes=first["review_id"])
        self.assertEqual(len(relation_detail(
            self.store, scope="PhiOS", relation_id=self.rel
        )["reviews"]), 1)

    def test_rejected_conflict_no_longer_triggers_active_warning(self):
        from phitribrain.evidence import cited_claim

        before = cited_claim(
            self.store, scope="PhiOS", claim_id=self.a["id"]
        )
        self.assertTrue(any("proposed contradictory" in w for w in before["warnings"]))
        first = self.review(outcome="rejected")
        after = cited_claim(
            self.store, scope="PhiOS", claim_id=self.a["id"]
        )
        self.assertFalse(any("proposed contradictory" in w for w in after["warnings"]))
        self.review(outcome="needs_context", supersedes=first["review_id"])
        again = cited_claim(
            self.store, scope="PhiOS", claim_id=self.a["id"]
        )
        self.assertTrue(any("proposed contradictory" in w for w in again["warnings"]))

    def test_scope_isolation(self):
        with self.assertRaisesRegex(ValueError, "requested scope"):
            relation_detail(self.store, scope="Other", relation_id=self.rel)
        with self.assertRaisesRegex(ValueError, "requested scope"):
            annotate_relation(
                self.store, scope="Other", relation_id=self.rel,
                outcome="accepted", reviewer="User", reason="Because",
            )
        self.assertEqual(relation_queue(self.store, scope="Other")["total"], 0)

    def test_invalid_inputs_and_states(self):
        for outcome in ("approved", "confirmed", "truth", ""):
            with self.assertRaises(ValueError):
                self.review(outcome=outcome)
        with self.assertRaises(ValueError):
            annotate_relation(
                self.store, scope="PhiOS", relation_id=self.rel,
                outcome="accepted", reviewer=" ", reason="Reason",
            )
        with self.assertRaises(ValueError):
            annotate_relation(
                self.store, scope="PhiOS", relation_id=self.rel,
                outcome="accepted", reviewer="Human", reason=" ",
            )
        with self.assertRaises(ValueError):
            relation_queue(self.store, scope="PhiOS", status="invalid")
        with self.assertRaises(ValueError):
            relation_queue(self.store, scope="PhiOS", limit=0)
        with self.assertRaises(ValueError):
            relation_queue(self.store, scope="PhiOS", offset=-1)

    def test_missing_relation_has_no_review(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            annotate_relation(
                self.store, scope="PhiOS", relation_id="rel_does_not_exist",
                outcome="accepted", reviewer="Human", reason="Reason",
            )

    def test_quote_tampering_refuses_review(self):
        self.store.db.execute("UPDATE claims SET quote_offset=-1 WHERE id=?", (self.a["id"],))
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "quote offset"):
            self.review()
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)

    def test_digest_tampering_refuses_review_and_detail(self):
        source_id = self.store.db.execute(
            "SELECT source_id FROM claims WHERE id=?", (self.a["id"],)
        ).fetchone()["source_id"]
        self.store.db.execute(
            "UPDATE sources SET body='Fabricated' WHERE id=?", (source_id,)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            relation_detail(self.store, scope="PhiOS", relation_id=self.rel)
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.review()

    def test_atomic_review_rollback_on_audit_failure(self):
        with patch.object(self.store, "_event", side_effect=ValueError("audit failed")):
            with self.assertRaisesRegex(ValueError, "audit failed"):
                self.review()
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_queue_stable_pagination(self):
        relations = []
        for i in range(4):
            a = self.claim(f"Memory system iteration {i}")
            b = self.claim(f"Memory system revision {i}")
            relations.append(self.store.add_relation(
                scope="PhiOS", left=a["id"], right=b["id"],
                relation="related", rationale="Manually proposed",
            )["id"])
        one = relation_queue(self.store, scope="PhiOS", status="all", limit=2)
        two = relation_queue(self.store, scope="PhiOS", status="all", limit=2, offset=2)
        again = relation_queue(self.store, scope="PhiOS", status="all", limit=2)
        self.assertEqual(one, again)
        self.assertEqual(one["total"], 5)
        self.assertEqual(one["count"], 2)
        self.assertEqual(two["count"], 2)
        self.assertFalse(set(item["id"] for item in one["items"]) &
                         set(item["id"] for item in two["items"]))

    def test_cli_queue_and_detail(self):
        def run(*args):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["--db", str(self.path), *args])
            self.assertEqual(code, 0)
            return json.loads(buf.getvalue())
        queued = run("relation-queue", "--scope", "PhiOS")
        self.assertEqual(queued["total"], 1)
        detail = run("relation-detail", "--scope", "PhiOS", "--relation", self.rel)
        self.assertEqual(detail["review_status"], "pending")
        self.assertEqual(len(detail["claim_evidence"]), 2)

    def test_cli_review_requires_terminal(self):
        with patch("sys.stdin") as fake:
            fake.isatty.return_value = False
            code = main([
                "--db", str(self.path), "relation-review", "--scope", "PhiOS",
                "--relation", self.rel, "--outcome", "accepted",
                "--reviewer", "Human", "--reason", "Reviewed manually",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)

    def test_cli_confirmation_and_revision(self):
        def cli_review(outcome, supersedes=None, confirmation=None):
            args = [
                "--db", str(self.path), "relation-review", "--scope", "PhiOS",
                "--relation", self.rel, "--outcome", outcome,
                "--reviewer", "Human", "--reason", "Reviewed original sources",
            ]
            if supersedes:
                args.extend(["--supersedes", supersedes])
            output = io.StringIO()
            with (patch("sys.stdin") as stdin,
                  patch("builtins.input", return_value=confirmation),
                  redirect_stdout(output)):
                stdin.isatty.return_value = True
                status = main(args)
            return status, json.loads(output.getvalue()) if output.getvalue() else None

        no, _ = cli_review("accepted", confirmation="incorrect")
        self.assertEqual(no, 2)
        code, first = cli_review(
            "accepted", confirmation=f"REVIEW {self.rel} ACCEPTED"
        )
        self.assertEqual(code, 0)
        self.assertEqual(first["review_status"], "accepted")
        code, second = cli_review(
            "rejected", supersedes=first["review_id"],
            confirmation=f"REVIEW {self.rel} REJECTED",
        )
        self.assertEqual(code, 0)
        self.assertEqual(second["review_status"], "rejected")
        self.assertEqual(len(relation_detail(
            self.store, scope="PhiOS", relation_id=self.rel
        )["reviews"]), 2)

    def test_no_database_created_by_queue(self):
        missing = Path(self.folder.name) / "absent.sqlite3"
        self.assertEqual(main([
            "--db", str(missing), "relation-queue", "--scope", "PhiOS",
        ]), 2)
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
