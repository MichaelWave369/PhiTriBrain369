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

## Local relation review ledger

- Review status is a local annotation about a proposed relationship, **not** independent verification of either claim or execution authority.
- Reviewer names are arbitrary strings. Interactive typed confirmation prevents accidental CLI automation but **does not authenticate a person** or restrict code with database access.
- Every review rechecks original claim quotes and source digests and writes a versioned review plus audit event transactionally.
- Later reviews require the exact previous review ID; lost updates fail closed. No source or original relation history is deleted.
- Rejected contradiction proposals are not presented as active contradiction warnings, but remain visible in review history.
- This is not a secure multi-user review service. Implement authenticated identities, roles, and authorization before exposing it to agents or a network.

## Optional local embedding service

- Only explicit `embed-index --apply`, `hybrid`, or `hybrid-eval` sends text to `127.0.0.1:11434`; preview never sends text. Redirects and HTTP proxy forwarding are blocked.
- A loopback network address is not a cryptographic guarantee that the Ollama daemon uses only local weights. Users must choose a downloaded local embedding model and secure the service against cloud routing or exposure.
- The embedding input contains stored statements and quoted source text. It may contain secrets or sensitive material. Index **only non-sensitive, reviewed claims** and protect the local daemon.
- Derived vector rows are plaintext and keyed by scope, model and claim content digest; cache invalidation is not secure deletion.
- Embedding-based similarity and fused rankings have no calibrated relationship to truth, evidence quality, authority or recency. Exact citations are verified before displaying results.
- Judged retrieval scores apply only to the supplied evaluation corpus; no accuracy promise follows from mocked tests.
- The prototype scans a small scope-local vector cache in Python, not a production vector database. No multi-user ACLs or authenticated agent permissions.

## Offline semantic relationship proposals

- Semantic WEAVER uses cached embeddings only. Its preview and apply commands never request a model or contact the network.
- Cosine similarity does not establish entailment, contradiction, independence, or factual reliability. Every suggestion is `related`, unverified, and manually reviewable.
- Provenance comparisons flag different immutable GitHub commits, common source snapshots and nonoverlapping **asserted** validity windows. These annotations are not independently verified.
- All source hashes and exact quote anchors are checked, while stale/missing cache entries are skipped. Model dimension errors and corrupted indexed evidence fail closed.
- Original claims and manual relationships are not rewritten; an explicit apply adds only proposed, audited links. Scopes are labels, not permissions.
- This is not an automated contradiction-resolution engine, authenticated review service, or execution authorization gateway.

## Before production integrations

Add authenticated identities and per-agent capabilities, validate files and symlinks for export/import, rate limit requests, encrypt protected storage, establish immutable external audit anchors and tested backups, introduce authenticated review and execution gateways, and build prompt-injection/red-team tests on every adapter.

**Never store credentials in a public demo vault.**
