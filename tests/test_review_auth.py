import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.relation_review import annotate_relation, relation_detail
from phitribrain.review_auth import (
    authorize_review, change_reviewer_status, enroll_reviewer,
    list_reviewers, review_gate_enabled,
)
from phitribrain.store import BrainStore
from phitribrain.weaver import apply_candidates


OWNER_PW = "Owner strong local password 369!"
REVIEW_PW = "Reviewer strong local password!"
OBS_PW = "Observer strong local password!"


class ReviewAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "brain.sqlite3"
        self.store = BrainStore(self.path)
        self.addCleanup(self.store.close)
        self.a = self._claim("The build is green")
        self.b = self._claim("The build is not green")
        self.relation = apply_candidates(
            self.store, scope="PhiOS"
        )["relations"][0]["id"]

    def _claim(self, statement):
        source = self.store.ingest(
            scope="PhiOS", title="Testing",
            body="Observed: " + statement,
            origin="example:" + statement,
        )
        return self.store.add_claim(
            scope="PhiOS", source_id=source["id"],
            statement=statement, quote=statement,
        )

    def owner(self):
        return enroll_reviewer(
            self.store, scope="PhiOS", username="localowner",
            role="owner", password=OWNER_PW,
        )

    def enroll(self, username="reviewer1", role="reviewer", password=REVIEW_PW):
        return enroll_reviewer(
            self.store, scope="PhiOS", username=username, role=role,
            password=password, owner_username="localowner",
            owner_password=OWNER_PW,
        )

    def assess(self, reviewer="localowner", password=None, **kwargs):
        return annotate_relation(
            self.store, scope="PhiOS", relation_id=self.relation,
            outcome=kwargs.pop("outcome", "accepted"),
            reviewer=reviewer, reason="Checked both source citations",
            auth_password=password, **kwargs,
        )

    def test_no_accounts_keeps_prior_local_legacy_mode(self):
        self.assertFalse(review_gate_enabled(self.store, scope="PhiOS"))
        result = self.assess(reviewer="Human Label")
        self.assertFalse(result["credential_checked"])
        self.assertEqual(
            relation_detail(
                self.store, scope="PhiOS", relation_id=self.relation
            )["review_status"], "accepted",
        )

    def test_bootstrap_first_owner_enables_scope(self):
        owner = self.owner()
        self.assertTrue(review_gate_enabled(self.store, scope="PhiOS"))
        self.assertTrue(owner["enabled"])
        self.assertEqual(owner["role"], "owner")
        self.assertEqual(owner["policy"], "local_password_required")
        self.assertEqual(self.store.verify_audit()["ok"], True)

    def test_existing_scope_requires_enrolled_password_for_direct_api(self):
        self.owner()
        for password in (None, "incorrect"):
            with self.subTest(password=password):
                with self.assertRaises(ValueError):
                    self.assess(password=password)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)

    def test_authorized_owner_and_reviewer_can_review(self):
        self.owner()
        self.enroll()
        a = self.assess(reviewer="reviewer1", password=REVIEW_PW)
        self.assertTrue(a["credential_checked"])
        b = self.assess(
            reviewer="localowner", password=OWNER_PW,
            outcome="rejected", supersedes=a["review_id"],
        )
        self.assertTrue(b["credential_checked"])
        self.assertEqual(
            [r["outcome"] for r in relation_detail(
                self.store, scope="PhiOS", relation_id=self.relation
            )["reviews"]], ["accepted", "rejected"]
        )
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_observer_cannot_approve(self):
        self.owner()
        self.enroll("observer1", "observer", OBS_PW)
        with self.assertRaisesRegex(ValueError, "required role"):
            self.assess(reviewer="observer1", password=OBS_PW)

    def test_labels_are_not_impersonatable_after_gate(self):
        self.owner()
        self.enroll()
        with self.assertRaises(ValueError):
            self.assess(reviewer="localowner", password=REVIEW_PW)
        with self.assertRaises(ValueError):
            self.assess(reviewer="reviewer1", password=OWNER_PW)

    def test_bogus_owner_cannot_enroll_another(self):
        self.owner()
        with self.assertRaises(ValueError):
            enroll_reviewer(
                self.store, scope="PhiOS", username="rogue",
                role="reviewer", password=REVIEW_PW,
            )
        with self.assertRaises(ValueError):
            enroll_reviewer(
                self.store, scope="PhiOS", username="rogue",
                role="reviewer", password=REVIEW_PW,
                owner_username="localowner", owner_password="incorrect",
            )
        self.assertFalse(self.store.db.execute(
            "SELECT 1 FROM reviewer_accounts WHERE username='rogue'"
        ).fetchone())

    def test_duplicate_user_enrollment_is_refused(self):
        self.owner()
        with self.assertRaisesRegex(ValueError, "already exists"):
            enroll_reviewer(
                self.store, scope="PhiOS", username="localowner",
                role="reviewer", password=REVIEW_PW,
                owner_username="localowner", owner_password=OWNER_PW,
            )
        self.assertEqual(list_reviewers(
            self.store, scope="PhiOS"
        )["accounts"][0]["role"], "owner")

    def test_first_user_must_be_owner(self):
        with self.assertRaisesRegex(ValueError, "must be an owner"):
            enroll_reviewer(
                self.store, scope="PhiOS", username="reviewer1",
                role="reviewer", password=REVIEW_PW,
            )
        self.assertFalse(review_gate_enabled(self.store, scope="PhiOS"))

    def test_reviewer_can_be_disabled_and_reenabled_by_owner(self):
        self.owner()
        self.enroll()
        off = change_reviewer_status(
            self.store, scope="PhiOS", username="reviewer1", enabled=False,
            owner_username="localowner", owner_password=OWNER_PW,
        )
        self.assertFalse(off["enabled"])
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.assess(reviewer="reviewer1", password=REVIEW_PW)
        on = change_reviewer_status(
            self.store, scope="PhiOS", username="reviewer1", enabled=True,
            owner_username="localowner", owner_password=OWNER_PW,
        )
        self.assertTrue(on["enabled"])
        self.assertTrue(self.assess(
            reviewer="reviewer1", password=REVIEW_PW
        )["credential_checked"])

    def test_last_owner_cannot_be_disabled(self):
        self.owner()
        with self.assertRaisesRegex(ValueError, "last enabled"):
            change_reviewer_status(
                self.store, scope="PhiOS", username="localowner",
                enabled=False, owner_username="localowner",
                owner_password=OWNER_PW,
            )
        self.assertTrue(list_reviewers(
            self.store, scope="PhiOS"
        )["accounts"][0]["enabled"])

    def test_owner_can_disable_another_owner_when_one_survives(self):
        self.owner()
        self.enroll(username="owner2", role="owner")
        disabled = change_reviewer_status(
            self.store, scope="PhiOS", username="owner2",
            enabled=False, owner_username="localowner", owner_password=OWNER_PW,
        )
        self.assertFalse(disabled["enabled"])
        with self.assertRaises(ValueError):
            change_reviewer_status(
                self.store, scope="PhiOS", username="localowner",
                enabled=False, owner_username="owner2",
                owner_password=REVIEW_PW,
            )

    def test_observer_not_authorized_to_manage_accounts(self):
        self.owner()
        self.enroll(username="observer1", role="observer", password=OBS_PW)
        with self.assertRaisesRegex(ValueError, "required role"):
            enroll_reviewer(
                self.store, scope="PhiOS", username="another",
                role="reviewer", password=REVIEW_PW,
                owner_username="observer1", owner_password=OBS_PW,
            )

    def test_scope_isolation(self):
        self.owner()
        self.assertFalse(review_gate_enabled(self.store, scope="Other"))
        self.assertTrue(review_gate_enabled(self.store, scope="PhiOS"))
        with self.assertRaises(ValueError):
            authorize_review(
                self.store, scope="Other", username="localowner",
                password=OWNER_PW,
            ) if review_gate_enabled(self.store, scope="Other") else enroll_reviewer(
                self.store, scope="Other", username="notowner",
                role="reviewer", password=REVIEW_PW,
            )
        self.assertFalse(review_gate_enabled(self.store, scope="Other"))

    def test_password_hash_is_salted_and_no_plaintext_in_audit(self):
        self.owner()
        self.enroll()
        rows = self.store.db.execute(
            "SELECT salt,password_hash,iterations FROM reviewer_accounts "
            "WHERE scope='PhiOS' ORDER BY username"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({bytes(r["salt"]) for r in rows}), 2)
        self.assertTrue(all(len(bytes(r["password_hash"])) == 32 for r in rows))
        self.assertTrue(all(r["iterations"] >= 100_000 for r in rows))
        events = "\n".join(
            r["details_json"] for r in
            self.store.db.execute("SELECT details_json FROM audit_events")
        )
        self.assertNotIn(OWNER_PW, events)
        self.assertNotIn(REVIEW_PW, events)
        shown = json.dumps(list_reviewers(self.store, scope="PhiOS"))
        self.assertNotIn("password_hash", shown)
        self.assertNotIn("salt", shown)

    def test_reject_short_password_bad_name_and_role(self):
        for password in ("short", "", " " * 13):
            with self.assertRaises(ValueError):
                enroll_reviewer(
                    self.store, scope="PhiOS", username="localowner",
                    role="owner", password=password,
                )
        for username in ("../owner", "user name", "_notfirst"):
            with self.assertRaises(ValueError):
                enroll_reviewer(
                    self.store, scope="PhiOS", username=username,
                    role="owner", password=OWNER_PW,
                )
        with self.assertRaises(ValueError):
            enroll_reviewer(
                self.store, scope="PhiOS", username="localowner",
                role="administrator", password=OWNER_PW,
            )

    def test_failed_admin_audit_rolls_back_enrollment(self):
        with patch.object(self.store, "_event", side_effect=ValueError("audit failure")):
            with self.assertRaisesRegex(ValueError, "audit failure"):
                self.owner()
        self.assertFalse(review_gate_enabled(self.store, scope="PhiOS"))
        self.assertTrue(self.store.verify_audit()["ok"])

    def test_failed_review_audit_rolls_back_with_auth(self):
        self.owner()
        with patch.object(self.store, "_event", side_effect=ValueError("audit failure")):
            with self.assertRaisesRegex(ValueError, "audit failure"):
                self.assess(password=OWNER_PW)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)

    def test_cli_admin_requires_interactive_terminal(self):
        with patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            code = main([
                "--db", str(self.path), "reviewer-enroll",
                "--scope", "PhiOS", "--user", "localowner", "--role", "owner",
            ])
        self.assertEqual(code, 2)
        self.assertFalse(review_gate_enabled(self.store, scope="PhiOS"))

    def test_cli_bootstrap_hidden_password_and_review(self):
        def run(*args, passwords=(), confirmation=None):
            out = io.StringIO()
            with (patch("sys.stdin") as stdin,
                  patch("getpass.getpass", side_effect=list(passwords)) as prompts,
                  patch("builtins.input", return_value=confirmation),
                  redirect_stdout(out)):
                stdin.isatty.return_value = True
                rc = main(["--db", str(self.path), *args])
            return rc, json.loads(out.getvalue()) if out.getvalue() else None, prompts

        code, owner, prompts = run(
            "reviewer-enroll", "--scope", "PhiOS",
            "--user", "localowner", "--role", "owner",
            passwords=(OWNER_PW, OWNER_PW),
        )
        self.assertEqual(code, 0)
        self.assertEqual(prompts.call_count, 2)
        self.assertEqual(owner["role"], "owner")
        code, record, prompts = run(
            "relation-review", "--scope", "PhiOS", "--relation", self.relation,
            "--outcome", "accepted", "--reviewer", "localowner",
            "--reason", "Both claims inspected",
            confirmation=f"REVIEW {self.relation} ACCEPTED",
            passwords=(OWNER_PW,),
        )
        self.assertEqual(code, 0)
        self.assertEqual(prompts.call_count, 1)
        self.assertTrue(record["credential_checked"])

    def test_cli_wrong_password_cannot_approve(self):
        self.owner()
        with (patch("sys.stdin") as stdin,
              patch("builtins.input", return_value=f"REVIEW {self.relation} ACCEPTED"),
              patch("getpass.getpass", return_value="wrong")):
            stdin.isatty.return_value = True
            rc = main([
                "--db", str(self.path), "relation-review",
                "--scope", "PhiOS", "--relation", self.relation,
                "--outcome", "accepted", "--reviewer", "localowner",
                "--reason", "Wrong password",
            ])
        self.assertEqual(rc, 2)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM relation_reviews"
        ).fetchone()[0], 0)

    def test_cli_reviewer_list_is_read_only(self):
        self.owner()
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([
                "--db", str(self.path), "reviewer-list", "--scope", "PhiOS",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["accounts"][0]["username"], "localowner")


if __name__ == "__main__":
    unittest.main()
