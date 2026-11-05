import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.github_ingest import (
    _blob_sha, _validate_content, apply, parse_manifest, prepare,
    preview, valid_path,
)
from phitribrain.store import BrainStore

REPO = "MichaelWave369/PhiTriBrain369"
SHA = "a" * 40
BODY = b"# Example\nWITNESS records evidence, not truth.\n"


def api_fixture(body=BODY, commit=SHA):
    result = {}

    def fetch(url):
        result.setdefault("called", []).append(url)
        if "/commits/" in url:
            return {"sha": commit}
        return {
            "type": "file", "encoding": "base64",
            "content": base64.b64encode(body).decode("ascii"),
            "size": len(body), "sha": _blob_sha(body),
        }

    return fetch, result


class GitHubImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "manifest.json"
        self.manifest = {
            "scope": "PhiTriBrain369",
            "repositories": [
                {"repository": REPO, "commit": SHA, "paths": ["README.md"]}
            ],
        }
        self.write_manifest()

    def write_manifest(self):
        self.path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_valid_manifest_and_prepared_source(self):
        manifest = parse_manifest(self.path)
        mock, called = api_fixture()
        plans = prepare(manifest, mock)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["body"], BODY.decode())
        self.assertEqual(plans[0]["blob_sha"], _blob_sha(BODY))
        self.assertEqual(plans[0]["scope"], "PhiTriBrain369")
        self.assertIn(SHA, plans[0]["origin"])
        self.assertEqual(len(called["called"]), 2)
        self.assertIn("?ref=" + SHA, called["called"][1])

    def test_preview_excludes_source_and_never_creates_database(self):
        plans = prepare(parse_manifest(self.path), api_fixture()[0])
        output = preview(plans)
        self.assertEqual(output["mode"], "dry-run")
        self.assertNotIn("body", output["files"][0])
        dbfile = Path(self.tmp.name) / "uncreated.sqlite3"
        with patch("phitribrain.cli.prepare_github", return_value=plans):
            code = main(["--db", str(dbfile), "github", "--manifest", str(self.path)])
        self.assertEqual(code, 0)
        self.assertFalse(dbfile.exists())

    def test_apply_records_structured_commit_provenance(self):
        plans = prepare(parse_manifest(self.path), api_fixture()[0])
        with BrainStore(Path(self.tmp.name) / "brain.sqlite3") as store:
            first = apply(store, plans)
            self.assertEqual(first["mode"], "applied")
            self.assertTrue(first["imports"][0]["new_import"])
            source = store.inspect(
                scope="PhiTriBrain369", record_id=first["imports"][0]["source_id"]
            )
            self.assertEqual(source["github_provenance"][0]["commit_sha"], SHA)
            self.assertEqual(source["github_provenance"][0]["blob_sha"], _blob_sha(BODY))
            self.assertEqual(store.summary(scope="PhiTriBrain369")["sources"], 1)
            self.assertTrue(store.verify_audit()["ok"])
            second = apply(store, plans)
            self.assertFalse(second["imports"][0]["new_import"])
            self.assertEqual(store.summary(scope="PhiTriBrain369")["sources"], 1)

    def test_source_quote_still_required(self):
        plans = prepare(parse_manifest(self.path), api_fixture()[0])
        with BrainStore(Path(self.tmp.name) / "brain.sqlite3") as store:
            imported = apply(store, plans)["imports"][0]
            claim = store.add_claim(
                scope="PhiTriBrain369", source_id=imported["source_id"],
                statement="Document describes evidence", quote="records evidence",
            )
            self.assertEqual(claim["quote_offset"], BODY.decode().find("records evidence"))
            with self.assertRaises(ValueError):
                store.add_claim(
                    scope="PhiTriBrain369", source_id=imported["source_id"],
                    statement="Unsupported", quote="the model is sentient",
                )

    def test_commit_must_match_exactly(self):
        with self.assertRaisesRegex(ValueError, "exact pinned commit"):
            prepare(parse_manifest(self.path), api_fixture(commit="b" * 40)[0])

    def test_modified_blob_fails(self):
        def mock(url):
            if "/commits/" in url:
                return {"sha": SHA}
            return {
                "type": "file", "encoding": "base64",
                "content": base64.b64encode(BODY).decode(),
                "size": len(BODY), "sha": "b" * 40,
            }
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            prepare(parse_manifest(self.path), mock)

    def test_size_disagreement_fails(self):
        def mock(url):
            if "/commits/" in url:
                return {"sha": SHA}
            return {
                "type": "file", "encoding": "base64",
                "content": base64.b64encode(BODY).decode(),
                "size": len(BODY) + 1, "sha": _blob_sha(BODY),
            }
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            prepare(parse_manifest(self.path), mock)

    def test_binary_and_invalid_utf8_refused(self):
        with self.assertRaisesRegex(ValueError, "Binary/NUL"):
            prepare(parse_manifest(self.path), api_fixture(body=b"abc\x00def")[0])
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            prepare(parse_manifest(self.path), api_fixture(body=b"\xff")[0])

    def test_oversized_and_empty_content_refused(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            _validate_content(b"")
        with self.assertRaisesRegex(ValueError, "250 KB"):
            _validate_content(b"a" * 250_001)

    def test_credential_marker_refused(self):
        for token in ("-----BEGIN PRIVATE KEY-----", "ghp_" + "A" * 36,
                      "github_pat_" + "A" * 40):
            with self.subTest(token=token[:12]):
                with self.assertRaisesRegex(ValueError, "credential"):
                    _validate_content(token.encode())

    def test_disallow_relative_traversal_and_dangerous_names(self):
        for candidate in ("../README.md", "/README.md", "a//README.md",
                          ".git/config.json", ".env", "secrets.json",
                          "node_modules/config.json", "example.png", "a%2Fb.md"):
            with self.subTest(path=candidate):
                with self.assertRaises(ValueError):
                    valid_path(candidate)

    def test_duplicate_repo_path_forbidden(self):
        self.manifest["repositories"][0]["paths"].append("README.md")
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate repository"):
            parse_manifest(self.path)

    def test_mutable_ref_forbidden(self):
        self.manifest["repositories"][0]["commit"] = "main"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "full 40-hex"):
            parse_manifest(self.path)

    def test_invalid_repository_forbidden(self):
        self.manifest["repositories"][0]["repository"] = "example.com/evil/repo"
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Invalid owner"):
            parse_manifest(self.path)

    def test_limit_to_twenty_files(self):
        self.manifest["repositories"][0]["paths"] = [f"docs/{i}.md" for i in range(21)]
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "at most 20"):
            parse_manifest(self.path)

    def test_manifest_duplicate_json_keys_refused(self):
        self.path.write_text('{"scope":"PhiOS","scope":"Other","repositories":[]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate manifest key"):
            parse_manifest(self.path)

    def test_cannot_rebind_pinned_origin_to_another_source(self):
        plans = prepare(parse_manifest(self.path), api_fixture()[0])
        with BrainStore(Path(self.tmp.name) / "brain.sqlite3") as store:
            imported = apply(store, plans)
            alternative = store.ingest(
                scope="PhiTriBrain369", title="Different", body="Totally different.",
                origin="local-note",
            )
            with self.assertRaisesRegex(ValueError, "Conflicting"):
                store.record_github_import(
                    scope="PhiTriBrain369", source_id=alternative["id"],
                    repository=REPO, commit=SHA, path="README.md",
                    blob_sha=_blob_sha(BODY), origin=plans[0]["origin"],
                    fetched_at=plans[0]["fetched_at"],
                )
            self.assertEqual(imported["imports"][0]["source_id"], plans[0]["scope"] and imported["imports"][0]["source_id"])


if __name__ == "__main__":
    unittest.main()
