import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.review_auth import enroll_reviewer, change_reviewer_status
from phitribrain.store import BrainStore

OWNER_PASSWORD = "Local owner test passphrase 369!"
REVIEWER_PASSWORD = "Local reviewer test passphrase 369!"
OBSERVER_PASSWORD = "Local observer test passphrase 369!"


class StewardReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "brain.sqlite3"
        self.store = BrainStore(self.path)
        self.addCleanup(self.store.close)
        self.source = self.store.ingest(
            scope="PhiOS", title="Architecture",
            body="A local evidence ledger keeps original source text.",
            origin="fixture:architecture",
        )
        self.claim = self.store.add_claim(
            scope="PhiOS", source_id=self.source["id"],
            statement="Local ledger retains originals",
            quote="keeps original source text",
        )
        self.decision = self.store.propose_decision(
            scope="PhiOS", title="Use local ledger",
            rationale="Quote-backed record required",
            claim_ids=[self.claim["id"]],
        )

    def owner(self):
        return enroll_reviewer(
            self.store, scope="PhiOS", username="localowner",
            role="owner", password=OWNER_PASSWORD,
        )

    def member(self, username="curator", role="reviewer", password=REVIEWER_PASSWORD):
        return enroll_reviewer(
            self.store, scope="PhiOS", username=username,
            role=role, password=password,
            owner_username="localowner", owner_password=OWNER_PASSWORD,
        )

    def judge(self, reviewer="localowner", password=None,
              outcome="approved", decision_id=None, scope="PhiOS"):
        return self.store.review_decision(
            scope=scope, decision_id=decision_id or self.decision["id"],
            outcome=outcome, reviewer=reviewer, auth_password=password,
        )

    def attestation_count(self):
        return self.store.db.execute(
            "SELECT COUNT(*) FROM decision_review_attestations"
        ).fetchone()[0]

    def test_unenrolled_scope_retains_old_review_behavior(self):
        result = self.judge(reviewer="legacy human", outcome="rejected")
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(result["credential_checked"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["truth_status"], "source_attributed_review_only")
        detail = self.store.inspect(
            scope="PhiOS", record_id=self.decision["id"]
        )["review_attestation"]
        self.assertEqual(detail["reviewer_role"], "legacy_unverified")
        self.assertFalse(detail["credential_checked"])
        self.assertEqual(self.attestation_count(), 1)
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_owner_with_password_can_review(self):
        self.owner()
        result = self.judge(password=OWNER_PASSWORD)
        self.assertEqual(result["status"], "approved")
        self.assertTrue(result["credential_checked"])
        self.assertFalse(result["execution_authorized"])
        detail = self.store.inspect(
            scope="PhiOS", record_id=self.decision["id"]
        )
        att = detail["review_attestation"]
        self.assertEqual(att["reviewer"], "localowner")
        self.assertEqual(att["reviewer_role"], "owner")
        self.assertTrue(att["credential_checked"])
        self.assertEqual(att["evidence_sha256"], result["evidence_sha256"])
        self.assertEqual(att["evidence"][0]["claim_id"], self.claim["id"])
        self.assertEqual(att["evidence"][0]["source_sha256"],
                         self.store.db.execute(
                             "SELECT digest FROM sources WHERE id=?",
                             (self.source["id"],)
                         ).fetchone()["digest"])
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_reviewer_can_reject_with_own_password(self):
        self.owner()
        self.member()
        output = self.judge(
            reviewer="curator", password=REVIEWER_PASSWORD, outcome="rejected",
        )
        self.assertTrue(output["credential_checked"])
        self.assertEqual(output["reviewed_by"], "curator")
        self.assertEqual(
            self.store.inspect(
                scope="PhiOS", record_id=self.decision["id"]
            )["review_attestation"]["reviewer_role"], "reviewer"
        )

    def test_unenrolled_or_wrong_password_denied_direct_api(self):
        self.owner()
        self.member()
        for reviewer, password in (
            ("localowner", None),
            ("localowner", "bad"),
            ("curator", OWNER_PASSWORD),
            ("localowner", REVIEWER_PASSWORD),
            ("unknown", OWNER_PASSWORD),
        ):
            with self.subTest(reviewer=reviewer):
                with self.assertRaises(ValueError):
                    self.judge(reviewer=reviewer, password=password)
        self.assertEqual(self.attestation_count(), 0)
        self.assertEqual(self.store.inspect(
            scope="PhiOS", record_id=self.decision["id"]
        )["status"], "proposed")

    def test_observer_cannot_approve_even_with_password(self):
        self.owner()
        self.member(username="observer", role="observer", password=OBSERVER_PASSWORD)
        with self.assertRaisesRegex(ValueError, "required role"):
            self.judge(reviewer="observer", password=OBSERVER_PASSWORD)
        self.assertEqual(self.attestation_count(), 0)

    def test_disabled_reviewer_cannot_approve(self):
        self.owner()
        self.member()
        change_reviewer_status(
            self.store, scope="PhiOS", username="curator",
            enabled=False, owner_username="localowner",
            owner_password=OWNER_PASSWORD,
        )
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.judge(reviewer="curator", password=REVIEWER_PASSWORD)
        self.assertEqual(self.attestation_count(), 0)

    def test_scope_passwords_do_not_transfer(self):
        self.owner()
        enroll_reviewer(
            self.store, scope="Other", username="another",
            role="owner", password=REVIEWER_PASSWORD,
        )
        source = self.store.ingest(
            scope="Other", title="Another scope",
            body="Other project recorded a design.", origin="example:other"
        )
        claim = self.store.add_claim(
            scope="Other", source_id=source["id"],
            statement="Other claim", quote="recorded a design",
        )
        other = self.store.propose_decision(
            scope="Other", title="Other decision", rationale="Other reason",
            claim_ids=[claim["id"]],
        )
        with self.assertRaises(ValueError):
            self.judge(
                reviewer="localowner", password=OWNER_PASSWORD,
                scope="Other", decision_id=other["id"],
            )
        self.assertEqual(self.store.inspect(
            scope="Other", record_id=other["id"]
        )["status"], "proposed")

    def test_source_digest_tamper_blocks_approval(self):
        self.owner()
        self.store.db.execute(
            "UPDATE sources SET body='Tampered' WHERE id=?",
            (self.source["id"],)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.judge(password=OWNER_PASSWORD)
        self.assertEqual(self.attestation_count(), 0)
        self.assertEqual(self.store.inspect(
            scope="PhiOS", record_id=self.decision["id"]
        )["status"], "proposed")

    def test_quote_offset_tamper_blocks_rejection(self):
        self.owner()
        self.store.db.execute(
            "UPDATE claims SET quote_offset=0 WHERE id=?",
            (self.claim["id"],),
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "quote offset"):
            self.judge(password=OWNER_PASSWORD, outcome="rejected")
        self.assertEqual(self.attestation_count(), 0)

    def test_no_scoped_evidence_is_rejected(self):
        self.owner()
        self.store.db.execute(
            "DELETE FROM decision_evidence WHERE decision_id=?",
            (self.decision["id"],)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "no scoped"):
            self.judge(password=OWNER_PASSWORD)

    def test_second_decision_review_is_rejected(self):
        self.owner()
        self.judge(password=OWNER_PASSWORD)
        with self.assertRaisesRegex(ValueError, "already been reviewed"):
            self.judge(password=OWNER_PASSWORD, outcome="rejected")
        self.assertEqual(self.attestation_count(), 1)

    def test_invalid_outcome_does_not_change_decision(self):
        self.owner()
        with self.assertRaises(ValueError):
            self.judge(password=OWNER_PASSWORD, outcome="execute")
        self.assertEqual(self.attestation_count(), 0)

    def test_audit_write_failure_rolls_back_approval_and_attestation(self):
        self.owner()
        with patch.object(
            self.store, "_event", side_effect=ValueError("simulated audit failure")
        ):
            with self.assertRaisesRegex(ValueError, "simulated audit"):
                self.judge(password=OWNER_PASSWORD)
        self.assertEqual(self.attestation_count(), 0)
        self.assertEqual(self.store.inspect(
            scope="PhiOS", record_id=self.decision["id"]
        )["status"], "proposed")
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_unreviewed_decision_has_no_attestation(self):
        self.assertIsNone(
            self.store.inspect(
                scope="PhiOS", record_id=self.decision["id"]
            )["review_attestation"]
        )

    def test_cli_password_prompt_only_for_enrolled_scope(self):
        self.owner()
        output = io.StringIO()
        with (
            patch("sys.stdin") as stdin,
            patch("builtins.input",
                  return_value="APPROVE " + self.decision["id"]),
            patch("getpass.getpass", return_value=OWNER_PASSWORD) as prompt,
            redirect_stdout(output),
        ):
            stdin.isatty.return_value = True
            code = main([
                "--db", str(self.path), "review",
                "--scope", "PhiOS", "--decision", self.decision["id"],
                "--outcome", "approved", "--reviewer", "localowner",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(prompt.call_count, 1)
        self.assertTrue(json.loads(output.getvalue())["credential_checked"])

    def test_cli_denies_wrong_password(self):
        self.owner()
        with (
            patch("sys.stdin") as stdin,
            patch("builtins.input",
                  return_value="APPROVE " + self.decision["id"]),
            patch("getpass.getpass", return_value="wrong"),
        ):
            stdin.isatty.return_value = True
            code = main([
                "--db", str(self.path), "review",
                "--scope", "PhiOS", "--decision", self.decision["id"],
                "--outcome", "approved", "--reviewer", "localowner",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(self.attestation_count(), 0)

    def test_cli_noninteractive_review_is_refused(self):
        self.owner()
        with patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            code = main([
                "--db", str(self.path), "review",
                "--scope", "PhiOS", "--decision", self.decision["id"],
                "--outcome", "approved", "--reviewer", "localowner",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(self.attestation_count(), 0)


if __name__ == "__main__":
    unittest.main()
