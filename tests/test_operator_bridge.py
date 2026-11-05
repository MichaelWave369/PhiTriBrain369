import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.operator_bridge import (
    create_bridge_snapshot, export_bridge_snapshot, parse_bridge_manifest,
)
from phitribrain.store import BrainStore


class OperatorBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "brain.sqlite3"
        self.store = BrainStore(self.db)
        self.addCleanup(self.store.close)
        src = self.store.ingest(
            scope="PhiOS", title="Nonsecret architecture note",
            body="The design preserves source-attributed evidence. No automatic execution.",
            origin="example:architecture",
        )
        self.claim = self.store.add_claim(
            scope="PhiOS", source_id=src["id"],
            statement="Source-attributed evidence is preserved",
            quote="preserves source-attributed evidence",
        )
        second = self.store.add_claim(
            scope="PhiOS", source_id=src["id"],
            statement="Automatic execution is excluded",
            quote="No automatic execution",
        )
        self.other_claim = second
        self.relation = self.store.add_relation(
            scope="PhiOS", left=self.claim["id"], right=second["id"],
            relation="related", rationale="Both describe safe memory",
        )
        self.decision = self.store.propose_decision(
            scope="PhiOS", title="Keep review manual",
            rationale="Claims should be inspected before action",
            claim_ids=[self.claim["id"]],
        )
        self.manifest_path = self.root / "operator.json"

    def manifest(self, *, claims=None, relations=None, decisions=None,
                 consumer="PhiMadaPrime", scope="PhiOS"):
        obj = {
            "schema_version": 1, "consumer": consumer, "scope": scope,
            "claims": claims if claims is not None else [self.claim["id"]],
            "relations": relations if relations is not None else [],
            "decisions": decisions if decisions is not None else [],
        }
        self.manifest_path.write_text(json.dumps(obj), encoding="utf-8")
        return parse_bridge_manifest(self.manifest_path)

    def snapshot(self, **kwargs):
        return create_bridge_snapshot(self.store, manifest=self.manifest(**kwargs))

    def test_preview_is_three_lanes_and_is_non_executable(self):
        before = self.store.db.execute(
            "SELECT COUNT(*) FROM audit_events"
        ).fetchone()[0]
        output = self.snapshot()
        self.assertEqual(output["schema_version"], 1)
        self.assertEqual(output["scope"], "PhiOS")
        self.assertEqual(output["consumer_label_not_authentication"], "PhiMadaPrime")
        self.assertEqual(len(output["lanes"]["WITNESS"]), 1)
        self.assertEqual(output["lanes"]["WEAVER"], [])
        self.assertEqual(output["lanes"]["STEWARD"], [])
        self.assertFalse(output["permissions"]["database_write"])
        self.assertFalse(output["permissions"]["network_access"])
        self.assertFalse(output["permissions"]["tool_execution"])
        self.assertFalse(output["permissions"]["autonomous_actions"])
        claim = output["lanes"]["WITNESS"][0]
        self.assertTrue(claim["source_attribution_only"])
        self.assertEqual(claim["citation"]["quote"],
                         "preserves source-attributed evidence")
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            before,
        )

    def test_lanes_have_only_explicitly_allowed_records(self):
        obj = self.snapshot(
            claims=[self.claim["id"], self.other_claim["id"]],
            relations=[self.relation["id"]],
            decisions=[self.decision["id"]],
        )
        self.assertEqual(len(obj["lanes"]["WITNESS"]), 2)
        self.assertEqual(len(obj["lanes"]["WEAVER"]), 1)
        self.assertEqual(len(obj["lanes"]["STEWARD"]), 1)
        relation = obj["lanes"]["WEAVER"][0]
        self.assertEqual(relation["review_status"], "pending")
        self.assertTrue(relation["review_required"])
        self.assertFalse(relation["is_factual_truth"])
        decision = obj["lanes"]["STEWARD"][0]
        self.assertEqual(decision["status"], "proposed")
        self.assertFalse(decision["execution_authorized"])
        self.assertFalse(decision["factual_truth_verified"])
        self.assertEqual(decision["evidence_claim_ids"], [self.claim["id"]])

    def test_relation_refuses_unlisted_claim(self):
        with self.assertRaisesRegex(ValueError, "not explicitly allowlisted"):
            self.snapshot(relations=[self.relation["id"]])

    def test_decision_refuses_unlisted_evidence(self):
        with self.assertRaisesRegex(ValueError, "not explicitly allowlisted"):
            self.snapshot(
                claims=[self.other_claim["id"]],
                decisions=[self.decision["id"]],
            )

    def test_reviewed_decision_still_grants_no_execution_authority(self):
        self.store.review_decision(
            scope="PhiOS", decision_id=self.decision["id"],
            outcome="approved", reviewer="local human",
        )
        output = self.snapshot(decisions=[self.decision["id"]])
        decision = output["lanes"]["STEWARD"][0]
        self.assertEqual(decision["status"], "approved")
        self.assertFalse(decision["credential_checked"])
        self.assertFalse(decision["execution_authorized"])
        self.assertIsNotNone(decision["review_attestation_digest"])

    def test_scope_isolation_and_missing_source(self):
        with self.assertRaisesRegex(ValueError, "requested scope"):
            self.snapshot(scope="AnotherScope")
        missing = "clm_" + "a" * 20
        with self.assertRaisesRegex(ValueError, "requested scope"):
            self.snapshot(claims=[missing])

    def test_source_integrity_fail_closed(self):
        source_id = self.store.db.execute(
            "SELECT source_id FROM claims WHERE id=?", (self.claim["id"],)
        ).fetchone()["source_id"]
        self.store.db.execute(
            "UPDATE sources SET body='altered' WHERE id=?", (source_id,)
        )
        self.store.db.commit()
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.snapshot()

    def test_manifest_requires_exact_schema_no_wildcards(self):
        bad = [
            {"schema_version": 1, "consumer": "PhiMadaPrime", "scope": "PhiOS",
             "claims": ["*"], "relations": [], "decisions": []},
            {"schema_version": 2, "consumer": "PhiMadaPrime", "scope": "PhiOS",
             "claims": [self.claim["id"]], "relations": [], "decisions": []},
            {"schema_version": 1, "consumer": "UnknownApp", "scope": "PhiOS",
             "claims": [self.claim["id"]], "relations": [], "decisions": []},
            {"schema_version": 1, "consumer": "PhiBots", "scope": "../bad",
             "claims": [self.claim["id"]], "relations": [], "decisions": []},
            {"schema_version": 1, "consumer": "PhiBots", "scope": "PhiOS",
             "claims": [self.claim["id"]] * 2, "relations": [], "decisions": []},
            {"schema_version": 1, "consumer": "PhiBots", "scope": "PhiOS",
             "claims": [], "relations": [], "decisions": []},
            {"schema_version": 1, "consumer": "PhiBots", "scope": "PhiOS",
             "claims": [self.claim["id"]], "relations": [], "decisions": [],
             "auto_execute": True},
        ]
        for test in bad:
            with self.subTest(test=test):
                self.manifest_path.write_text(
                    json.dumps(test), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    parse_bridge_manifest(self.manifest_path)

    def test_manifest_limit_symlink_and_invalid_encoding(self):
        self.manifest()
        self.manifest_path.write_bytes(b"x" * 16_385)
        with self.assertRaisesRegex(ValueError, "16 KB"):
            parse_bridge_manifest(self.manifest_path)
        self.manifest_path.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(ValueError, "UTF-8 JSON"):
            parse_bridge_manifest(self.manifest_path)
        self.manifest()
        target = self.root / "link.json"
        try:
            target.symlink_to(self.manifest_path)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            parse_bridge_manifest(target)

    def test_export_creates_new_json_file_no_overwrite(self):
        snapshot = self.snapshot()
        output_path = self.root / "export.json"
        response = export_bridge_snapshot(snapshot, output=output_path)
        self.assertEqual(response["mode"], "exported")
        self.assertEqual(response["content_sha256"], snapshot["content_sha256"])
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, snapshot)
        with self.assertRaisesRegex(ValueError, "overwrite"):
            export_bridge_snapshot(snapshot, output=output_path)
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), snapshot)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(output_path.stat().st_mode), 0o600)

    def test_export_does_not_create_output_directory(self):
        missing = self.root / "never" / "export.json"
        with self.assertRaisesRegex(ValueError, "parent"):
            export_bridge_snapshot(self.snapshot(), output=missing)
        self.assertFalse(missing.parent.exists())

    def test_export_refuses_symlink_destination(self):
        actual = self.root / "protected.json"
        actual.write_text("keep this", encoding="utf-8")
        symlink = self.root / "linked.json"
        try:
            symlink.symlink_to(actual)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            export_bridge_snapshot(self.snapshot(), output=symlink)
        self.assertEqual(actual.read_text(encoding="utf-8"), "keep this")

    def test_cli_preview_is_readonly_and_does_not_create_output(self):
        self.manifest()
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "--db", str(self.db), "bridge",
                "--manifest", str(self.manifest_path),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output.getvalue())["lanes"]["WITNESS"][0]["id"],
            self.claim["id"],
        )
        self.assertEqual(list(self.root.glob("export*.json")), [])

    def test_cli_explicit_export_and_repeat_no_overwrite(self):
        self.manifest()
        output_file = self.root / "export.json"
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([
                "--db", str(self.db), "bridge",
                "--manifest", str(self.manifest_path),
                "--output", str(output_file),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["mode"], "exported")
        self.assertTrue(output_file.is_file())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([
                "--db", str(self.db), "bridge",
                "--manifest", str(self.manifest_path),
                "--output", str(output_file),
            ]), 2)

    def test_cli_nonexistent_database_does_not_create_one(self):
        self.manifest()
        path = self.root / "missing.sqlite3"
        with redirect_stdout(io.StringIO()):
            code = main([
                "--db", str(path), "bridge",
                "--manifest", str(self.manifest_path),
            ])
        self.assertEqual(code, 2)
        self.assertFalse(path.exists())

    def test_extra_long_quote_is_not_silently_truncated(self):
        big = "X" * 800
        source = self.store.ingest(
            scope="PhiOS", title="Large note", body=big,
            origin="fixture:large",
        )
        claim = self.store.add_claim(
            scope="PhiOS", source_id=source["id"],
            statement="Long quote", quote=big,
        )
        with self.assertRaisesRegex(ValueError, "exact source quote"):
            self.snapshot(claims=[claim["id"]])

    def test_no_network_and_no_model_calls(self):
        self.manifest()
        with (
            patch("urllib.request.build_opener",
                  side_effect=AssertionError("network used")),
            patch("phitribrain.hybrid.local_ollama_embed",
                  side_effect=AssertionError("model used")),
        ):
            with BrainStore(self.db, readonly=True) as readonly:
                result = create_bridge_snapshot(
                    readonly, manifest=parse_bridge_manifest(self.manifest_path)
                )
        self.assertEqual(len(result["lanes"]["WITNESS"]), 1)
        self.assertFalse(result["permissions"]["network_access"])


if __name__ == "__main__":
    unittest.main()
