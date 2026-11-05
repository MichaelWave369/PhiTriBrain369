import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from phitribrain.cli import main
from phitribrain.store import BrainStore
from phitribrain.vault_import import (
    apply_vault, preview_vault, rollback_vault, scan_vault,
)


class VaultImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "notes"
        self.root.mkdir()
        self.note = self.root / "Project.md"
        self.note.write_text("# Project\nEvidence before action.\n", encoding="utf-8")
        self.database = Path(self.temp.name) / "brain.sqlite3"

    def plans(self):
        return scan_vault(directory=self.root, scope="PhiOS", vault_id="MainVault")

    def store(self):
        obj = BrainStore(self.database)
        self.addCleanup(obj.close)
        return obj

    def test_preview_does_not_create_database_or_modify_note(self):
        original = self.note.read_bytes()
        preview = preview_vault(self.plans())
        self.assertEqual(preview["mode"], "dry-run")
        self.assertNotIn("body", preview["notes"][0])
        code = main([
            "--db", str(self.database), "vault", "--scope", "PhiOS",
            "--vault-id", "MainVault", "--directory", str(self.root),
        ])
        self.assertEqual(code, 0)
        self.assertFalse(self.database.exists())
        self.assertEqual(self.note.read_bytes(), original)

    def test_creates_linked_source_without_modifying_vault(self):
        original = self.note.read_bytes()
        store = self.store()
        result = apply_vault(store, self.plans())
        self.assertEqual((result["new"], result["updated"]), (1, 0))
        self.assertIsNotNone(result["batch_id"])
        link = store.db.execute("SELECT * FROM vault_notes").fetchone()
        self.assertEqual(link["relative_path"], "Project.md")
        self.assertEqual(link["scope"], "PhiOS")
        self.assertEqual(len(store.inspect(scope="PhiOS", record_id=link["source_id"])["vault_paths"]), 1)
        self.assertTrue(store.verify_audit()["ok"])
        self.assertEqual(self.note.read_bytes(), original)

    def test_reimport_same_notes_is_idempotent(self):
        store = self.store()
        one = apply_vault(store, self.plans())
        two = apply_vault(store, self.plans())
        self.assertIsNotNone(one["batch_id"])
        self.assertIsNone(two["batch_id"])
        self.assertEqual((two["new"], two["updated"], two["unchanged"]), (0, 0, 1))
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_revisions").fetchone()[0], 1)

    def test_changed_note_requires_explicit_accept_updates(self):
        store = self.store()
        apply_vault(store, self.plans())
        self.note.write_text("# Project\nNew findings.\n", encoding="utf-8")
        second = self.plans()
        with self.assertRaisesRegex(ValueError, "accept-updates"):
            apply_vault(store, second)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_revisions").fetchone()[0], 1)
        imported = apply_vault(store, second, accept_updates=True)
        self.assertEqual(imported["updated"], 1)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_revisions").fetchone()[0], 2)

    def test_rollback_update_restores_old_active_mapping(self):
        store = self.store()
        first = apply_vault(store, self.plans())
        old = store.db.execute("SELECT * FROM vault_notes").fetchone()
        old_id = old["source_id"]
        self.note.write_text("# Project\nRevision B.\n", encoding="utf-8")
        second = apply_vault(store, self.plans(), accept_updates=True)
        new_id = store.db.execute("SELECT source_id FROM vault_notes").fetchone()["source_id"]
        self.assertNotEqual(old_id, new_id)
        restored = rollback_vault(store, scope="PhiOS", vault_id="MainVault", batch_id=second["batch_id"])
        self.assertEqual(restored["status"], "rolled_back")
        self.assertEqual(store.db.execute("SELECT source_id FROM vault_notes").fetchone()["source_id"], old_id)
        self.assertEqual(store.summary(scope="PhiOS")["sources"], 2)
        self.assertTrue(store.verify_audit()["ok"])
        self.assertIsNotNone(first["batch_id"])

    def test_rollback_initial_batch_removes_mapping_not_history(self):
        store = self.store()
        first = apply_vault(store, self.plans())
        result = rollback_vault(store, scope="PhiOS", vault_id="MainVault", batch_id=first["batch_id"])
        self.assertEqual(result["restored_paths"], 1)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0], 0)
        self.assertEqual(store.summary(scope="PhiOS")["sources"], 1)
        with self.assertRaisesRegex(ValueError, "No active"):
            rollback_vault(store, scope="PhiOS", vault_id="MainVault", batch_id=first["batch_id"])

    def test_rollback_rejects_later_active_update(self):
        store = self.store()
        original = apply_vault(store, self.plans())
        self.note.write_text("New version", encoding="utf-8")
        second = apply_vault(store, self.plans(), accept_updates=True)
        with self.assertRaisesRegex(ValueError, "later import"):
            rollback_vault(store, scope="PhiOS", vault_id="MainVault", batch_id=original["batch_id"])
        self.assertEqual(store.db.execute(
            "SELECT status FROM vault_batches WHERE id=?", (second["batch_id"],)
        ).fetchone()["status"], "active")

    def test_rollback_is_all_or_nothing_on_conflict(self):
        (self.root / "Other.md").write_text("Other original", encoding="utf-8")
        store = self.store()
        initial = apply_vault(store, self.plans())
        self.note.write_text("Updated Project", encoding="utf-8")
        newer = apply_vault(store, self.plans(), accept_updates=True)
        with self.assertRaisesRegex(ValueError, "later import"):
            rollback_vault(store, scope="PhiOS", vault_id="MainVault", batch_id=initial["batch_id"])
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0], 2)
        self.assertEqual(store.db.execute(
            "SELECT status FROM vault_batches WHERE id=?", (initial["batch_id"],)
        ).fetchone()["status"], "active")
        self.assertIsNotNone(newer["batch_id"])

    def test_detect_note_modified_after_preview(self):
        store = self.store()
        old = self.plans()
        self.note.write_text("Changed after scanning", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed since preview"):
            apply_vault(store, old)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0], 0)

    def test_skip_hidden_obsidian_and_non_markdown(self):
        folder = self.root / ".obsidian"
        folder.mkdir()
        (folder / "workspace.md").write_text("settings", encoding="utf-8")
        (self.root / "photo.png").write_bytes(b"\x00\x01")
        (self.root / ".private.md").write_text("invisible", encoding="utf-8")
        self.assertEqual([p["relative_path"] for p in self.plans()], ["Project.md"])

    def test_nested_notes_have_relative_paths(self):
        folder = self.root / "Nested"
        folder.mkdir()
        (folder / "Another.md").write_text("Nested", encoding="utf-8")
        paths = [p["relative_path"] for p in self.plans()]
        self.assertEqual(paths, ["Project.md", "Nested/Another.md"] if False else sorted(paths))
        self.assertIn("Nested/Another.md", paths)

    def test_refuse_symlinked_note(self):
        link = self.root / "Linked.md"
        try:
            link.symlink_to(self.note)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            self.plans()

    def test_refuse_symlinked_directory(self):
        target = Path(self.temp.name) / "elsewhere"
        target.mkdir()
        (target / "private.md").write_text("no", encoding="utf-8")
        link = self.root / "linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable on this platform")
        with self.assertRaisesRegex(ValueError, "Symlinked"):
            self.plans()

    def test_refuse_secret_pattern(self):
        self.note.write_text("ghp_" + "A" * 35, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "credential"):
            self.plans()

    def test_refuse_invalid_utf8(self):
        self.note.write_bytes(b"\xff\xfe\xfa")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            self.plans()

    def test_refuse_oversized_note(self):
        self.note.write_bytes(b"A" * 250001)
        with self.assertRaisesRegex(ValueError, "250 KB"):
            self.plans()

    def test_invalid_scope_or_vault_id(self):
        with self.assertRaises(ValueError):
            scan_vault(directory=self.root, scope="../bad", vault_id="MainVault")
        with self.assertRaises(ValueError):
            scan_vault(directory=self.root, scope="PhiOS", vault_id="../bad")

    def test_separate_notes_same_contents_share_source_not_path(self):
        (self.root / "Clone.md").write_bytes(self.note.read_bytes())
        store = self.store()
        result = apply_vault(store, self.plans())
        self.assertEqual(result["new"], 2)
        self.assertEqual(store.summary(scope="PhiOS")["sources"], 1)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0], 2)

    def test_cli_import_and_rollback(self):
        args = ["--db", str(self.database), "vault", "--scope", "PhiOS",
                "--vault-id", "MainVault", "--directory", str(self.root)]
        self.assertEqual(main(args + ["--apply"]), 0)
        store = self.store()
        batch = store.db.execute("SELECT id FROM vault_batches").fetchone()["id"]
        self.assertEqual(main([
            "--db", str(self.database), "vault", "--scope", "PhiOS",
            "--vault-id", "MainVault", "--rollback", batch
        ]), 0)
        self.assertEqual(store.db.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
