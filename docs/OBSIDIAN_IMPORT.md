# Rung 2b: Obsidian vault import

WITNESS can read a **local directory of Markdown notes** and store independent, source-attributed snapshots in the local SQLite ledger. Existing vault notes and Obsidian settings are never changed.

This is intentionally **not bidirectional Obsidian synchronization**. It is a local, opt-in importer.

## 1. Preview without modifying SQLite

From a terminal on the machine holding your notes:

~~~bash
phitribrain vault --scope PhiOS --vault-id LabNotes --directory "/path/to/your/ObsidianVault"
~~~

The preview lists relative paths, source SHA-256 digests and byte sizes. It does not print note bodies, modify your vault, create an SQLite database, or contact a server. The app does **not** automatically read any folder. You must provide a directory.

## 2. Import explicitly

~~~bash
phitribrain vault --scope PhiOS --vault-id LabNotes --directory "/path/to/your/ObsidianVault" --apply
~~~

The response includes a unique `batch_id` such as `vbatch_...`, with counts for new, updated and unchanged path mappings. Each imported snapshot is content-addressed and quote-anchorable through the existing WITNESS `claim` command. Your source files are not modified.

Running the same import twice is safe: unchanged note content is skipped.

## 3. Changed notes and conflicts

If a note was imported previously and now contains different text, the default import **refuses** to replace its active mapping. After inspecting the changed notes and choosing to accept them:

~~~bash
phitribrain vault --scope PhiOS --vault-id LabNotes --directory "/path/to/your/ObsidianVault" --apply --accept-updates
~~~

The old snapshot remains in the evidence history. The active path mapping now points to the new version. This does not mean the new note is factually correct.

Each batch is committed as one SQLite transaction. A conflict or invalid file aborts the batch. Any note changed between the scan and re-read immediately before import is rejected.

## 4. Roll back a batch's active mappings

~~~bash
phitribrain vault --scope PhiOS --vault-id LabNotes --rollback vbatch_REPLACE_WITH_ID
~~~

Rollback restores previous active path mappings, or removes the mapping for notes first imported by that batch. It does **not** delete source records, the search index, old snapshots, or audit events. Later updates prevent rolling back an earlier batch until the newer batch has been rolled back first.

**Rollback is not a secure erase, and it does not restore the files in your Obsidian vault.** The importer never writes those files in the first place. Protect the SQLite file and its backups, and do not ingest confidential data without proper safeguards.

## Boundaries and protections

- Only nonempty UTF-8 `.md` files in an explicitly supplied local vault are included.
- Hidden directories such as `.obsidian` and hidden files are skipped.
- Symlink roots, symlink note files, and symlink note directories are refused. Resolution is rechecked during scanning, though some filesystem race risks remain on platforms without no-follow file opens.
- Limits: 100 notes, 250 KB per note, 5 MB total per run.
- Basic known credential signatures are screened. **This is not full secret detection.** Review notes before importing.
- Each file preserves exact text and a SHA-256 digest; source path mappings, batch revisions and changes are recorded with audit events.
- Preview does not inspect existing database mappings; conflict checks occur on apply.
- Stored source text must be treated as **untrusted data**. No content inside a note is executed or interpreted as instructions to an agent.
- Vault IDs and scopes are organizational names, not authenticated permissions or encryption.
- Markdown, Obsidian wikilinks, tags and frontmatter are retained as plain text. The importer does not yet extract a knowledge graph from them.
- Binary attachments, external Markdown transclusions, plugin APIs, syncing, and automatic scanning are outside Rung 2b.
- No cloud services, credentials, external APIs or runtime package dependencies are required.

## Next work

The final part of Rung 2 will provide quote-backed citation formatting, recency metadata, and a retrieval evaluation set. Only then should we add higher-level reasoning and operator bridges.
