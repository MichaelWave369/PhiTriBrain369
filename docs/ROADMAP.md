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

- [ ] Optional local embeddings plus hybrid search (FTS5 + vectors)
- [ ] Contradiction proposals and de-duplication of equivalent claims
- [ ] Confidence calibration; abstention when evidence is insufficient
- [ ] Authenticated human review queue and provenance-aware edits
- [ ] Retrieval evaluation: recall@k, MRR, citation precision, cross-scope leaks

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
