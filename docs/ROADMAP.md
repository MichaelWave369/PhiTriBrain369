# PhiTriBrain369 Roadmap

## Rung 1: local evidence ledger

- [x] Standard-library Python CLI and SQLite database
- [x] WITNESS: source ingestion, content digests, origins, attributed claims
- [x] WEAVER: proposed relation graph with explicit explanations
- [x] STEWARD: evidence-linked decision proposals and manual review annotation
- [x] Scoped FTS5 retrieval, inspect, audit, Markdown snapshot export
- [x] Regression tests and cross-platform CI
- [x] Document security and integrity limitations

## Rung 2: grounded source ingestion

- [x] Read-only public GitHub allowlist adapter with commit SHAs and retrieval timestamps (Rung 2a)
- [x] Local Obsidian Markdown vault importer with dry-run, atomic batches, mapping rollback, and conflict detection (Rung 2b)
- [x] Append-only, explicitly asserted claim valid-time annotations, alongside existing recorded-time fields (Rung 2c)
- [x] Quote-backed citation retrieval, abstention, source observation-age warnings (Rung 2c)
- [x] Initial deterministic quote-anchoring / retrieval fixture (smoke test); expand benchmark in Rung 3

## Rung 3: reviewable knowledge synthesis

- [x] Rung 3a: bounded deterministic duplicate-text, narrow negation and lexical-overlap proposals with source-integrity checks, preview-only default, idempotent audited apply
- [x] Rung 3b: local review queue, evidence-inspected accepted/rejected/needs_context annotations, append-only reassessment history and optimistic conflict protection
- [x] Rung 3e: opt-in, scope-local reviewer passwords and owner/reviewer/observer roles for WEAVER relation review (local application gate only)
- [x] Rung 3f: extend the same local credential gate to STEWARD decision reviews with verified source quote/digest attestations and atomic audit
- [ ] Verified identities, secure multi-user permissions, rate limiting, credential rotation/recovery, and network-service access controls
- [ ] Semantic contradiction reasoning, duplicate consolidation and contextual/temporal resolution (beyond Rung 3a heuristics)

- [x] Rung 3c: optional loopback Ollama embedding index, scoped FTS5 + cosine RRF retrieval and quote-backed matches (small local caches only)
- [x] Rung 3d: cached-vector semantic neighbor proposals, exact citations, Git commit and asserted validity-window cautions, and review-queue provenance
- [ ] Human-reviewed contradiction resolution and consolidation of equivalent claims (Rung 3a only proposes candidates)
- [ ] Confidence calibration; abstention when evidence is insufficient
- [ ] Authenticated human review queue as a secure service; Rungs 3e–3f add only local credential checks for relation and decision review, not full multi-user identity or permissions
- [x] Rung 3c: reproducible judged-corpus recall@k, precision@k, MRR and scope-leak checks (initial offline-fixture evaluation)
- [ ] Larger representative benchmark with citation precision judgments, quality thresholds and latency profiling

## Rung 4: Phi369 operator bridges

- [ ] MCP service with least-privilege scoped capabilities
- [ ] PhiMadaPrime WITNESS/WEAVER/STEWARD workspace
- [ ] PhiBots task handoff with idempotency and collision prevention
- [ ] PhiRSI experiment/results ledger and regression feedback
- [ ] Safe, audited event bus and explicit execution approval gateway

## Rung 5: resilient distributed memory

- [ ] Encrypted at-rest vault and explicit secret exclusion
- [ ] Externally anchored audit snapshots, backup verification, restore drills
- [ ] Offline synchronization with conflict resolution
- [ ] Opt-in Quest 3 Gen.E-Wrist viewer through trusted local pairing
- [ ] Time-aware graph traversal, semantic clustering, scaling tests

## First real integration

Start with **one non-sensitive architecture note and one verified CI result** from a single repo. Do not ingest hundreds of repositories or conversation transcripts blindly. We need trustworthy retrieval before scale.
