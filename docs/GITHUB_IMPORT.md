# GitHub WITNESS adapter (Rung 2, part 1)

This adapter reads **only public, explicitly selected GitHub files** via GitHub's REST API. It stores original UTF-8 file text with SHA-256 source digests, SHA-1 Git blob digests, an exact immutable commit reference, and an import timestamp.

It **does not** connect your account, read private repositories, deploy anything, run workflows, write to GitHub, make claims automatically, or execute instructions found inside sources.

## Quick start

1. Install with Python 3.10+ from the repo root: `python -m pip install -e .`
2. Review and edit `examples/github-allowlist.sample.json` if needed. It is pinned to one known commit and two public files of this project. The manifest is an explicit allowlist.
3. Preview (makes public HTTPS reads but **no local SQLite changes**):

   ~~~bash
   phitribrain github --manifest examples/github-allowlist.sample.json
   ~~~

4. If the preview shows exactly the files you meant to import:

   ~~~bash
   phitribrain github --manifest examples/github-allowlist.sample.json --apply
   phitribrain stats --scope PhiTriBrain369
   phitribrain search --scope PhiTriBrain369 --query "WITNESS evidence"
   phitribrain audit
   ~~~

A source can be inspected with `phitribrain show --scope PhiTriBrain369 --id src_...`; the result includes `github_provenance`, with repository, path, pinned SHA, blob SHA, and timestamp. Claims must **still be added and quote-anchored manually**: importing is not automatic fact extraction.

### Allowlist format

~~~json
{
  "scope": "PhiTriBrain369",
  "repositories": [
    {
      "repository": "MichaelWave369/PhiTriBrain369",
      "commit": "336a479b1b301cf3e7404890f5923a4adeee4c72",
      "paths": ["README.md", "docs/ARCHITECTURE.md"]
    }
  ]
}
~~~

`commit` must be the complete **40-hex immutable commit SHA**. Do not supply `main`, `HEAD`, a tag, a branch name, or a shortened SHA. Preview always re-fetches content; repeated `--apply` does not duplicate the same commit/path provenance.

### Model and data boundaries

- This adapter performs **public read-only** GitHub API calls only, without credential headers.
- Strict repository and file-path validation; no traversal or redirects.
- File types are restricted to common UTF-8 text; non-UTF-8, NUL bytes, mismatched Git object digests, inconsistent size, and empty files are refused.
- Each source is limited to 250 KB; each run to 20 files across up to four repository entries.
- A small set of obvious key/token patterns is rejected as a precaution. This is **not comprehensive secret scanning**.
- Only explicit `--apply` writes a local database. Default preview does not even create the DB.
- Imported text is untrusted data. No LLM APIs or tool-calling logic are involved.
- Project scopes are labels, **not access control**. Never import private or confidential content into an unsecured database.
- The SHA-1 Git blob check verifies bytes against GitHub's reported blob SHA, not GitHub's identity or truthfulness. HTTPS, the remote API, and the local machine are still trusted dependencies.
- The source import is idempotent, and audit events are hash-chained, but the local database is not tamper-proof or cryptographically externally anchored.

### Failure modes

The command fails closed on unknown repository selectors, mutable revisions, traversal, unsupported extensions, response mismatches, credential markers, and access/API errors. A multi-file apply is currently sequential: if a later file fails after an earlier file is stored, earlier successful imports remain. Inspect `stats` and `audit`, then safely rerun; already committed source/path rows are not duplicated.

### Next pieces of Rung 2

- Add explicit retrieval/evaluation tests using selected real GitHub files and CI events.
- Build reversible Obsidian vault import with dry-run, version/conflict checks, and backup.
- Add source recency warnings and distinction between observation time and validity time.
- Add citation rendering and tests for source-attributed answers.
