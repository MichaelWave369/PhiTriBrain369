# Threat model: Rung 1

This prototype is a local proof of concept, **not** a production knowledge-security system.

## Trust boundaries

1. **Filesystem:** anyone who can write the SQLite database can change records. SQLite file permissions and host disk protection are mandatory for private use.
2. **Agent inputs:** source text, repository README files, and exported Markdown are untrusted data. Treat embedded instructions as inert text.
3. **Actor labels:** actor/reviewer strings do not prove the identity or authority of a person or bot.
4. **Scopes:** scope filters prevent accidental cross-project queries through this API, but are not authentication or isolation across users.
5. **Exports:** snapshots are plain Markdown; they can leak content if uploaded to shared vaults or repositories.
6. **Audit:** hash chaining can detect many accidental or isolated edits, but a DB administrator can rewrite/truncate the entire event history. Externally signed/anchored checkpoints are not implemented.
7. **Source truth:** an anchored quote proves textual attribution, not factual correctness, licensing rights, or fitness for downstream actions.

## Mitigations included

- No automatic network, GitHub, model, or subprocess calls
- No automatic execution of decisions
- Interactive, exact typed confirmation for CLI review annotations
- SQLite parameterized queries and input validation
- Text ingestion size limit, conservative FTS5 query tokenization
- UTF-8 snapshot export refusing to overwrite a nonempty destination
- Project-scope checks for references, search, inspect, and decisions
- Clear provenance and proposed/approved distinction

## Local Obsidian import considerations

- Vault note text is untrusted. Markdown links, frontmatter, embedded prompts and code examples remain inert data.
- Import is opt-in, local-only, and bounded; scans skip hidden folders and refuse symlinks.
- Import records remain in plaintext SQLite; rollback restores active path mappings but does not erase any historical source, index or audit data.
- A few common credential patterns are blocked, but secret detection is incomplete. Sensitive vaults must not be imported without additional controls.
- There remains a small filesystem race window, especially on platforms without secure no-follow opening.
- The CLI does not provide full multi-user authentication, authorization or encryption.

## Citation and time annotation considerations

- A quote-backed claim proves only that an imported source contains specific text. It cannot prove the source is true, current, authentic, lawful, or relevant.
- Immutable GitHub SHA citations refer to an earlier snapshot; an observation recorded today may still refer to old code. Freshness warnings measure time since observation, not current repository status.
- Recorded time is when a claim or source entered the ledger. Asserted valid-time intervals are unverified annotations stored append-only; actor labels are not authenticated.
- Old vault snapshots remain queryable after updates and rollback, with warnings when no active path mapping exists.
- Hash and offset checks detect some accidental data corruption but do not prevent coordinated database rewriting by a privileged local actor.
- Results include source text/quotes and paths, which may reveal confidential data if exposed through logs, exported JSON or future agent APIs. Do not connect this to an untrusted network service.

## WEAVER proposal safety

- WEAVER lexical similarities and apparent negation conflicts are **unverified proposals**, not probability scores, factual consensus, semantic equivalence or executable instructions.
- Only quote-backed, scope-matched, non-superseded claims can participate. Every source digest and quote anchor is verified before relationship suggestions are created.
- Apply operations append proposed relations and audit events as a single SQLite transaction. Existing manual relations are respected.
- Very large scopes fail closed at 250 recorded claims. No cross-project traversal or permission changes occur.
- Imported prompt text remains data. There are no model, network, automation, or execution interfaces in this rung.

## Before production integrations

Add authenticated identities and per-agent capabilities, validate files and symlinks for export/import, rate limit requests, encrypt protected storage, establish immutable external audit anchors and tested backups, introduce authenticated review and execution gateways, and build prompt-injection/red-team tests on every adapter.

**Never store credentials in a public demo vault.**
