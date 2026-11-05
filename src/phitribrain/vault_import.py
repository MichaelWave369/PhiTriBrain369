"""Local Obsidian Markdown vault intake for WITNESS.

No vault file is modified. The default CLI operation previews paths/digests
without touching SQLite. An explicit apply records immutable source snapshots
and versioned path mappings. Rollback restores path mappings, never deletes
historical source text, and refuses to overwrite later imports.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

from .store import BrainStore, sha, utcnow, validate_scope

MAX_FILES = 100
MAX_NOTE_BYTES = 250_000
MAX_BATCH_BYTES = 5_000_000
VAULT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SECRET_MARKERS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<!\w)ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<!\w)github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?<!\w)AKIA[0-9A-Z]{16}"),
)


def validate_vault_id(vault_id: str) -> str:
    if not isinstance(vault_id, str) or not VAULT_ID_RE.fullmatch(vault_id):
        raise ValueError("vault ID must be 1-64 letters/digits/dots/underscores/hyphens")
    return vault_id


def _read_note(path: Path) -> bytes:
    """Read a regular file, excluding symlinks and oversized or unstable files."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise ValueError(f"Only regular non-symlink notes are supported: {path.name}")
    if before.st_size > MAX_NOTE_BYTES:
        raise ValueError(f"Note exceeds 250 KB: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev, opened.st_ino
        ) != (before.st_dev, before.st_ino):
            raise ValueError(f"File changed during read: {path.name}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_NOTE_BYTES + 1)
        after = os.fstat(fd)
        if (opened.st_size, opened.st_mtime_ns) != (
            after.st_size, after.st_mtime_ns
        ):
            raise ValueError(f"File changed during read: {path.name}")
    finally:
        os.close(fd)
    if not data or len(data) > MAX_NOTE_BYTES:
        raise ValueError(f"Note must be 1 to 250 KB: {path.name}")
    if b"\x00" in data:
        raise ValueError(f"Binary note refused: {path.name}")
    return data


def scan_vault(*, directory: str | Path, scope: str, vault_id: str) -> list[dict]:
    """Return bounded, content-hashed notes; never write to the vault or database."""
    scope = validate_scope(scope)
    vault_id = validate_vault_id(vault_id)
    root = Path(directory).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Vault root must be a real, existing directory (not a symlink)")
    root = root.resolve(strict=True)
    items: list[dict] = []
    total_bytes = 0
    for parent, directories, files in os.walk(root, topdown=True, followlinks=False):
        parent_path = Path(parent)
        if parent_path.is_symlink():
            raise ValueError("Symlinked note directory refused")
        directories[:] = sorted(
            name for name in directories if not name.startswith(".")
        )
        for name in directories:
            if (parent_path / name).is_symlink():
                raise ValueError("Symlinked note directory refused")
        for filename in sorted(files):
            if filename.startswith(".") or not filename.lower().endswith(".md"):
                continue
            path = parent_path / filename
            if path.is_symlink():
                raise ValueError("Symlinked Markdown note refused")
            relative = path.relative_to(root).as_posix()
            # Re-resolve the path to detect a directory being swapped for a symlink.
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("Note escaped the requested vault root")
            blob = _read_note(path)
            try:
                body = blob.decode("utf-8")
            except UnicodeError as exc:
                raise ValueError(f"Note is not UTF-8: {relative}") from exc
            for marker in SECRET_MARKERS:
                if marker.search(body):
                    raise ValueError(f"Possible credential detected in note: {relative}")
            total_bytes += len(blob)
            if total_bytes > MAX_BATCH_BYTES:
                raise ValueError("Vault import is limited to 5 MB total")
            items.append({
                "scope": scope,
                "vault_id": vault_id,
                "relative_path": relative,
                "file": str(path),
                "body": body,
                "digest": sha(body),
                "bytes": len(blob),
            })
            if len(items) > MAX_FILES:
                raise ValueError("Vault import is limited to 100 notes per run")
    if not items:
        raise ValueError("No nonempty UTF-8 Markdown notes were found")
    return items


def preview_vault(plans: list[dict]) -> dict:
    return {
        "mode": "dry-run", "count": len(plans),
        "bytes": sum(p["bytes"] for p in plans),
        "scope": plans[0]["scope"],
        "vault_id": plans[0]["vault_id"],
        "notes": [{k: p[k] for k in ("relative_path", "digest", "bytes")} for p in plans],
        "message": "No SQLite or vault writes. Existing database mappings are checked on --apply.",
    }


def apply_vault(store: BrainStore, plans: list[dict], *, accept_updates: bool = False) -> dict:
    """Atomically update active paths after verifying original previewed bytes.

    Calling this with a plan assembled from user input is unsafe: callers must
    pass results of scan_vault, which validates paths and file types.
    """
    if not plans:
        raise ValueError("No notes to import")
    scope, vault_id = plans[0]["scope"], plans[0]["vault_id"]
    validate_scope(scope)
    validate_vault_id(vault_id)
    seen = set()
    for note in plans:
        if (note["scope"], note["vault_id"]) != (scope, vault_id):
            raise ValueError("Mixed vault scopes are not supported")
        path = note["relative_path"]
        if path in seen:
            raise ValueError("Duplicate note path in the import plan")
        seen.add(path)
        # Prevent the original file being changed after preview and before apply.
        if sha(_read_note(Path(note["file"])).decode("utf-8")) != note["digest"]:
            raise ValueError(f"Note changed since preview: {path}")
    changed = []
    skipped = 0
    batch_id = "vbatch_" + uuid.uuid4().hex[:20]
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        for note in plans:
            current = store.db.execute(
                "SELECT source_id,digest FROM vault_notes "
                "WHERE scope=? AND vault_id=? AND relative_path=?",
                (scope, vault_id, note["relative_path"]),
            ).fetchone()
            if current and current["digest"] == note["digest"]:
                skipped += 1
                continue
            if current and not accept_updates:
                raise ValueError(
                    "Existing note has changed; preview and rerun with --accept-updates: "
                    + note["relative_path"]
                )
            changed.append((note, current))
        if not changed:
            return {"mode": "applied", "batch_id": None, "new": 0,
                    "updated": 0, "unchanged": skipped}
        store.db.execute(
            "INSERT INTO vault_batches(id,scope,vault_id,created_at,status) "
            "VALUES(?,?,?,?,'active')",
            (batch_id, scope, vault_id, utcnow()),
        )
        created = updated = 0
        for note, current in changed:
            origin = "obsidian-vault:" + vault_id + "/" + note["relative_path"]
            source = store.ingest(
                scope=scope, title=note["relative_path"], body=note["body"],
                origin=origin, actor="obsidian-witness", defer_commit=True,
            )
            if current:
                updated += 1
                store.db.execute(
                    "UPDATE vault_notes SET source_id=?,digest=?,updated_at=? "
                    "WHERE scope=? AND vault_id=? AND relative_path=?",
                    (source["id"], note["digest"], utcnow(),
                     scope, vault_id, note["relative_path"]),
                )
            else:
                created += 1
                store.db.execute(
                    "INSERT INTO vault_notes(scope,vault_id,relative_path,source_id,digest,updated_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (scope, vault_id, note["relative_path"], source["id"],
                     note["digest"], utcnow()),
                )
            store.db.execute(
                "INSERT INTO vault_revisions(batch_id,scope,vault_id,relative_path,"
                "previous_source_id,previous_digest,new_source_id,new_digest) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (batch_id, scope, vault_id, note["relative_path"],
                 current["source_id"] if current else None,
                 current["digest"] if current else None,
                 source["id"], note["digest"]),
            )
            store._event(scope, "vault.import", {
                "batch": batch_id, "vault_id": vault_id,
                "path": note["relative_path"], "source_id": source["id"],
                "previous_source_id": current["source_id"] if current else None,
            })
    return {"mode": "applied", "batch_id": batch_id, "new": created,
            "updated": updated, "unchanged": skipped}


def rollback_vault(store: BrainStore, *, scope: str, vault_id: str, batch_id: str) -> dict:
    """Undo only active path mappings from a batch, preserving all source history."""
    scope = validate_scope(scope)
    vault_id = validate_vault_id(vault_id)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        batch = store.db.execute(
            "SELECT status FROM vault_batches WHERE id=? AND scope=? AND vault_id=?",
            (batch_id, scope, vault_id),
        ).fetchone()
        if not batch or batch["status"] != "active":
            raise ValueError("No active matching vault batch to roll back")
        revisions = store.db.execute(
            "SELECT * FROM vault_revisions WHERE batch_id=? ORDER BY seq DESC",
            (batch_id,),
        ).fetchall()
        for revision in revisions:
            active = store.db.execute(
                "SELECT source_id,digest FROM vault_notes "
                "WHERE scope=? AND vault_id=? AND relative_path=?",
                (scope, vault_id, revision["relative_path"]),
            ).fetchone()
            if not active or (
                active["source_id"], active["digest"]
            ) != (revision["new_source_id"], revision["new_digest"]):
                raise ValueError(
                    "Cannot roll back a note changed by a later import: "
                    + revision["relative_path"]
                )
        for revision in revisions:
            if revision["previous_source_id"]:
                store.db.execute(
                    "UPDATE vault_notes SET source_id=?,digest=?,updated_at=? "
                    "WHERE scope=? AND vault_id=? AND relative_path=?",
                    (revision["previous_source_id"], revision["previous_digest"],
                     utcnow(), scope, vault_id, revision["relative_path"]),
                )
            else:
                store.db.execute(
                    "DELETE FROM vault_notes "
                    "WHERE scope=? AND vault_id=? AND relative_path=?",
                    (scope, vault_id, revision["relative_path"]),
                )
        store.db.execute(
            "UPDATE vault_batches SET status='rolled_back',rolled_back_at=? WHERE id=?",
            (utcnow(), batch_id),
        )
        store._event(scope, "vault.rollback", {
            "batch": batch_id, "vault_id": vault_id, "restored_paths": len(revisions),
        })
    return {"batch_id": batch_id, "status": "rolled_back",
            "restored_paths": len(revisions),
            "warning": "Historical sources, search records, and audit events are retained."}
