# STARTRACE-5 → Φ TriBrain WITNESS (preview-only bridge)

The original STARTRACE-5 experiment lives at [GMED](https://github.com/MichaelWave369/GMED/pull/3). It explores 5 BCE comet scenario geometry. Its **Rung 1 computations do not reconstruct Matney's ancient-sky orbit or authenticate a historical event**.

The bridge is *not* a truth-certification service and does not automatically ingest anything into TriBrain. It validates the receipt's declared schema and conservative flags, then renders a Markdown preview that attributes the source's claims and limitations.

## Usage

In the GMED browser lab, choose **Export research receipt**. The downloaded JSON should have schema \`gmed-startrace-5:research-receipt:v1\` and verdict \`ILLUSTRATIVE_PHYSICS_ONLY\`.

After \`python -m pip install -e .\` in the PhiTriBrain369 repository:

~~~bash
# Inspect without modifying the database:
python -m phitribrain.startrace_bridge STARTRACE-5-research-receipt.json

# Produce an attributed WITNESS source note; refuses overwrite:
python -m phitribrain.startrace_bridge STARTRACE-5-research-receipt.json --output startrace-note.md

# Separately decide whether to ingest:
phitribrain ingest --scope STARTRACE-5 --file startrace-note.md --title "STARTRACE-5 attributed research receipt"
~~~

Optional: make individual quote-anchored claims using \`phitribrain claim\` and the exact text visible in the source note. By design this bridge does **not** automatically promote the source's statements into claims or WEAVER relationships.

## What the validator checks

- JSON is UTF-8 and at most 1 MiB.
- Receipt type and conservative verdict match this integration's known contract.
- Historical identification, completed sky reconstruction, and independent verification fields all explicitly state **false**.
- Each source attribution has a unique ID, recognized status, bounded text, and an HTTPS link.
- The resulting note records the original receipt SHA-256 as a provenance clue.

**None of those checks authenticate the signer or prove the source file came from GMED.** An attacker can forge a syntactically conforming JSON file. The digest identifies the bytes provided, not their origin. Treat notes, sources, and URLs as untrusted data, never agent instructions.

## Why two distinct systems?

- **GMED STARTRACE-5:** quantitative exploratory model with fixed research-receipt outcome.
- **WITNESS:** source-attributed claims and exact quotes, preserving what was said, not guaranteeing that it is true.
- **WEAVER:** hypotheses and relationship proposals for later review.
- **STEWARD:** reviewed decision annotations that never become execution permissions.

This separation makes it harder for "a mathematical scenario can exist" to silently mutate into "the ancient event happened." The more sensational a hypothesis, the more valuable that distinction becomes.
