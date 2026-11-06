# Φ TriBrain 369

**Three brains. One accountable ledger.**

A local-first, model-independent knowledge store for the Phi369 ecosystem, designed to give PhiOS, PhiMadaPrime, PhiBots, and PhiRSI traceable project memory without locking the architecture to any single LLM provider.

**Status: Rungs 1–3 implemented through Rung 3f; Rung 4a provides an explicitly allowlisted, offline three-lane snapshot bridge for operator workspaces.** This is not an autonomous AI, Obsidian plugin, multi-user service, or complete three-agent system. The brains are distinct *logical responsibilities* backed by a common local store.

## STARTRACE-5: attribution-only research receipt bridge

The [STARTRACE-5 WITNESS bridge](docs/STARTRACE_INTEGRATION.md) takes an exported GMED historical-astronomy research receipt, validates its *illustrative-only* contract, and generates an attributed Markdown source note. It does **not** write SQLite data or establish the historical truth of claims. Preview with `python -m phitribrain.startrace_bridge receipt.json`; write a new note with `--output startrace-note.md`; opt into a separate WITNESS ingest afterward.

## Three brains

| Brain | Responsibility | Non-negotiable rule |
|---|---|---|
| **01 WITNESS** | Record exact source text, digests, provenance, and quote-anchored claims | An attributed claim is not automatically true |
| **02 WEAVER** | Propose relationships between claims (supports, contradicts, related) | Connections remain proposals, not assertions of fact |
| **03 STEWARD** | Propose evidence-linked decisions; record human review | A review annotation is never permission to execute |

All writes produce chained audit events. Local SQLite FTS5 provides lexical search. Markdown export produces a read-only snapshot compatible with Obsidian-style wikilinks. Runtime dependencies: Python standard library only.

## Run locally

Requirements: Python 3.10+ with SQLite FTS5. From the repository root:

```bash
python -m pip install -e .
phitribrain init
phitribrain ingest --scope PhiOS --file examples/first_source.md --title "First architecture note"
```

The ingest command returns a `src_...` ID. Replace `SOURCE_ID` with that value:

```bash
phitribrain claim --scope PhiOS --source SOURCE_ID --statement "Architecture separates responsibilities" --quote "three distinct responsibilities"
```

The claim command returns a `clm_...` ID. Replace `CLAIM_ID`:

```bash
phitribrain search --scope PhiOS --query "evidence decisions"
phitribrain show --scope PhiOS --id CLAIM_ID
phitribrain propose --scope PhiOS --title "Retain the local evidence ledger" --why "Sources need traceable provenance" --evidence CLAIM_ID
phitribrain stats --scope PhiOS
phitribrain audit
phitribrain export --scope PhiOS --directory ./vault-export
```

## Weaver example

After recording two quote-anchored claims in one scope:

```bash
phitribrain link --scope PhiOS --left CLAIM_ID_1 --right CLAIM_ID_2 --type supports --why "Both document local persistence"
```

The relation is created as **proposed**. No background fact-checker or autonomous execution occurs.

## Rung 2: read-only GitHub WITNESS import

Choose an explicit, commit-pinned allowlist of public GitHub files, preview without touching SQLite, and apply only after inspection:

```bash
phitribrain github --manifest examples/github-allowlist.sample.json
phitribrain github --manifest examples/github-allowlist.sample.json --apply
```

Sources now preserve Git blob SHA, full commit SHA, file path, and retrieval time as structured provenance. No background crawling, private repository access, GitHub writes, agent instructions, or automatic claim extraction occurs. See [GitHub ingestion guide](docs/GITHUB_IMPORT.md).

## Rung 2b: local Obsidian vault ingestion

Preview a local Markdown vault without creating or changing SQLite:

```bash
phitribrain vault --scope PhiOS --vault-id LabNotes --directory "/path/to/ObsidianVault"
```

Apply explicitly, preserving each note's immutable source snapshot and an active path mapping:

```bash
phitribrain vault --scope PhiOS --vault-id LabNotes --directory "/path/to/ObsidianVault" --apply
```

Changed notes are refused by default. You must opt into changed revisions with `--accept-updates`; every import batch is transactional and returns a rollback identifier. Rolling back restores earlier active path mappings, while keeping historical sources and audit events. **The importer never changes or restores the original Obsidian files.** See [Obsidian importer guide](docs/OBSIDIAN_IMPORT.md).

## Rung 2c: evidence with receipts

WITNESS now retrieves only **quote-anchored claims**, not unsupported model-generated answers. Each match includes exact source ID/digest, quote offsets and line numbers, GitHub commit links when available, observation-age warnings, and explicit attribution-only status.

```bash
phitribrain evidence --scope PhiOS --query "local architecture"
phitribrain cite --scope PhiOS --claim clm_REPLACE_ME
phitribrain claim-time --scope PhiOS --claim clm_REPLACE_ME --from 2026-01-01 --until 2026-12-31 --basis "Human-noted design window"
```

Claim valid-time intervals are append-only **assertions**, never truth verification. Retrieval abstains when no quote-backed claims exist. Read [Evidence Retrieval](docs/EVIDENCE_RETRIEVAL.md) for examples and limitations.

## Rung 3a: WEAVER review-only suggestions

WEAVER can now **preview possible duplicates, narrow contradictory phrases and vocabulary-overlapping claims**, using only existing quote-anchored WITNESS claims. No language model is required.

```bash
phitribrain weave --scope PhiOS
phitribrain weave --scope PhiOS --threshold 0.65 --limit 20
phitribrain weave --scope PhiOS --apply
```

Preview does not change relationships; `--apply` atomically creates **proposed** links only, with audit records. Similarity scores are lexical heuristics, **not truth/confidence estimates**. Existing manual links are respected, and imported sources are never altered. See [WEAVER Proposals](docs/WEAVER_PROPOSALS.md).

## Rung 3b: WEAVER's append-only review queue

Explore pending or previously reviewed links, inspect the exact sources, then make a local, explicitly confirmed assessment:

```bash
phitribrain relation-queue --scope PhiOS --status pending
phitribrain relation-detail --scope PhiOS --relation rel_REPLACE_ME
phitribrain relation-review --scope PhiOS --relation rel_REPLACE_ME --outcome needs_context --reviewer "Local human" --reason "Compare the commits and timestamps"
```

Review outcomes are `accepted`, `rejected` or `needs_context`. **Accepted is not proof of claim truth**, and the original relationship remains `proposed`. To revisit an outcome, specify the exact latest `--supersedes rrev_...` review ID. The CLI requires an interactive terminal; review labels are **not authenticated**. See [Relation Review](docs/RELATION_REVIEW.md).

## Rung 3c: opt-in local embedding and measured hybrid search

Use an installed **local Ollama embedding model** to add semantic matching without losing WITNESS citations. Preview does not contact a model. Indexing requires explicit `--apply`, which sends selected claim statements and quoted evidence only to `127.0.0.1:11434`.

```bash
phitribrain embed-index --scope PhiOS --model embeddinggemma
phitribrain embed-index --scope PhiOS --model embeddinggemma --apply
phitribrain hybrid --scope PhiOS --model embeddinggemma --query "offline memory design"
phitribrain hybrid-eval --scope PhiOS --model embeddinggemma --corpus ./my-evaluation.json --k 5
```

Hybrid search uses SQLite FTS5 + local cosine similarity with reciprocal rank fusion, then revalidates exact source hashes and quotes. An evaluated JSON corpus compares recall@k, precision@k and MRR against lexical search. Scores are retrieval heuristics, **never truth confidence**.

See [Hybrid Retrieval](docs/HYBRID_RETRIEVAL.md) for setup, scope limits and privacy implications.

## Rung 3d: semantic neighbors with historical context

WEAVER can now propose **review-only** relationships from already indexed, local embeddings. It flags different Git commits, non-overlapping asserted validity periods, and same-source evidence instead of confusing similarity with truth.

```bash
phitribrain weave-semantic --scope PhiOS --model embeddinggemma
phitribrain weave-semantic --scope PhiOS --model embeddinggemma --apply
phitribrain relation-queue --scope PhiOS --status pending
```

Preview is read-only and **neither preview nor apply calls Ollama**: this rung uses existing local vectors. Apply adds only `related` proposals that remain subject to human review. See [Contextual WEAVER](docs/CONTEXTUAL_WEAVER.md).

## Rung 3e: opt-in local relation-review credentials

Set up a **scope-local owner password** before using multiple reviewers. The first owner can enroll additional reviewers and observers, or disable an account. Passwords are entered through hidden terminal prompts, never command-line flags.

```bash
phitribrain reviewer-enroll --scope PhiOS --user localowner --role owner
phitribrain reviewer-enroll --scope PhiOS --user curator1 --role reviewer --owner localowner
phitribrain reviewer-list --scope PhiOS
phitribrain reviewer-status --scope PhiOS --user curator1 --owner localowner --enabled no
```

Once a scope has any enrolled account, **WEAVER relation-review annotations require that username's password and an owner/reviewer role** even when called through the Python review API. Legacy scopes without accounts remain unprotected for compatibility. This is a local password gate, not real-world identity verification, multi-user authentication, or protection against DB owners. The STEWARD decision review path is not covered. See [Local Reviewer Access](docs/LOCAL_REVIEWER_ACCESS.md).

## Rung 3f: STEWARD decision review with evidence attestation

STEWARD now uses the same optional owner/reviewer password gate as WEAVER. When a scope enrolls its first owner, both kinds of review require a valid enrolled password. Every STEWARD decision review checks the original quote-backed claims and records an audit-linked SHA-256 attestation of the evidence inspected.

```bash
phitribrain show --scope PhiOS --id dec_REPLACE_ME
phitribrain review --scope PhiOS --decision dec_REPLACE_ME --outcome approved --reviewer curator1
phitribrain audit
```

The CLI requires an interactive confirmation and prompts for the enrolled reviewer password when the scope is gated. Historical reviews are not reauthenticated. **Approved is an annotation, never a deployment or execution grant.** See [STEWARD Review Gate](docs/STEWARD_REVIEW_GATE.md).

## Rung 4a: read-only operator bridge

You can now assemble a small, evidence-cited WITNESS/WEAVER/STEWARD snapshot for a future PhiMadaPrime, PhiBots, PhiOS, or PhiRSI workspace. Select the exact record IDs in a local JSON manifest and preview without changing the database:

```bash
phitribrain bridge --manifest examples/operator-bridge.sample.json
phitribrain bridge --manifest examples/operator-bridge.sample.json --output ./phi-operator-snapshot.json
```

Replace the placeholder claim ID in the sample first. The export **never overwrites existing files**, does not send data to another application, and never provides execution permissions. Every linked WEAVER or STEWARD claim must be explicitly listed in the manifest. See [Operator Bridge](docs/OPERATOR_BRIDGE.md).

## Companion visualizer: PhiMadaPrime R38

The implementation is tracked in [PhiMadaPrime R38 consumer PR](https://github.com/MichaelWave369/PhiMadaPrime/pull/46) adds an on-demand three-lane WITNESS / WEAVER / STEWARD viewer to the existing ThinkTank. It reads only a manually exported Rung 4a JSON snapshot; this repo remains the local SQLite knowledge source. It does **not** automatically synchronize, authenticate this unsigned export, independently verify original source bytes, or authorize decisions. Details: [Operator bridge](docs/OPERATOR_BRIDGE.md). Once the consumer implementation is merged and deployed, use a local manifest with consumer PhiMadaPrime and explicitly import a non-sensitive snapshot.

## Manual review

`phitribrain review` requires an interactive terminal and an exact typed confirmation. It records only a **local review annotation**. Legacy scopes without enrolled accounts accept unauthenticated labels; enrolled scopes require scope-local reviewer passwords. Neither type of review grants any agent permission to execute actions.

## Capabilities

- Local UTF-8 file ingestion with 5 MB/source limit
- SHA-256 deduplication per scope and separate origin records
- Exact substring anchors for source-attributed claims
- Proposed supports/contradicts/related links, always within a single project scope
- Evidence-backed decision proposals with one-time human review annotations
- SQLite FTS5 search, scoped result inspection, record summaries
- Quote-backed citation search, observation age warnings and append-only claim validity annotations
- Deterministic, bounded WEAVER lexical link suggestions with explicit preview/apply and transaction rollback
- Append-only relation review annotations, full history, optimistic revision checks and interactive CLI confirmation
- Optional loopback Ollama embeddings, per-model cached vectors, hybrid ranked claim retrieval and judged evaluation metrics
- Offline semantic-neighbor proposal generation, commit/date/source context cautions, and review queue provenance
- Optional local PBKDF2-HMAC reviewer password gate for WEAVER and STEWARD reviews, owner/reviewer/observer roles, owner-authorized enrollment and disable controls
- Source-validated STEWARD decision attestations tied to the existing hash-chained audit trail
- Explicit-ID, read-only, offline Phi369 operator snapshots with three named lanes, provenance verification and fail-closed dependencies
- Transaction-coupled, hash-chained audit events
- Markdown/JSON snapshot export to an empty destination
- Local Obsidian Markdown vault preview, transactional import, conflict protection, and path-mapping rollback
- Standard-library Python implementation and cross-platform regression tests

## Important limitations

- **Not encrypted.** Do not ingest passwords, API keys, personal secrets, or sensitive project data. Protect the underlying disk and backups.
- **Not a security boundary.** Scopes organize content; they are not user/agent authorization boundaries. The optional local reviewer password gate covers WEAVER relationship and STEWARD decision review annotations, but not host identity, broader database access control or protection from direct SQLite access.
- **Not tamper-proof.** An owner with database write access can rewrite or truncate both records and audit history; externally anchored snapshots are future work.
- **Not an automatic truth engine.** Exact quoted text proves what a source says, not that the statement is accurate.
- **GitHub ingestion is limited.** Rung 2 supports public, immutable-commit, explicitly allowlisted UTF-8 files. Private GitHub data, CI event ingestion, and PhiOS integration remain future work.
- **Semantic matching is optional and bounded.** Standard WITNESS search remains FTS5 lexical. Rung 3c uses explicit local Ollama embeddings for hybrid retrieval of existing claims, not a truth engine. No model comes bundled.
- **Not two-way sync.** Editing exported Markdown does not update SQLite. Local Obsidian import is opt-in and snapshots source files; it never writes back to a vault.
- **Prompt-injection risk.** Imported text must always be treated as untrusted data, never agent instructions.

## Φ Standard Definer (experimental Rung 1)

See [Definition Genesis](docs/STANDARD_DEFINER.md) for a local, review-only candidate-definition protocol with explicit epistemic status, contexts, temporal perspectives and unverified source attributions. It validates and compares JSON definitions without changing the knowledge ledger, certifying claims, or approving standards.

Run: python -m phitribrain.standard_definer validate examples/standard-dimension.json

## Φ Standard Definer Rung 2 · local Evidence Genesis

Standard Definer now supports a **read-only, explicit WITNESS quote-audit** for candidate definitions. It checks that cited claim IDs, source IDs and exact quoted text correspond to one existing project scope and a local source digest. It does not determine factual truth or grant review/execution authority. Existing WEAVER relationships are displayed only as unapproved proposals.

```bash
python -m phitribrain.standard_definer evidence candidate.json --db .phitribrain/brain.sqlite3 --scope Physics
```

See [Standard Definer](docs/STANDARD_DEFINER.md). No background model calls, network, DB migrations or writes are added.

## Development

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs tests on Linux and Windows for Python 3.10 and 3.13.

See [Architecture](docs/ARCHITECTURE.md), [Threat model](docs/THREAT_MODEL.md), and [Roadmap](docs/ROADMAP.md).

**People Above Profit. Ledger Above Ego.**

MIT License.
