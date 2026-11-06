# Φ Standard Definer: Definition Genesis (Rung 1)

This module extends PhiTriBrain369 with a local, deterministic, review-only standard-definition format. It is not a truth oracle, scientific certifier, AI inference service, or live interface to the existing evidence ledger.

## Use

Install the repository with Python 3.10+ and run these commands:

    python -m pip install -e .
    python -m phitribrain.standard_definer draft --concept-id physics.dimension --term Dimension --domain physics --context spacetime
    python -m phitribrain.standard_definer validate examples/standard-dimension.json
    python -m phitribrain.standard_definer compare examples/standard-dimension.json examples/standard-dimension-alternative.json
    python -m unittest discover -s tests -v

Draft prints an intentionally incomplete JSON object. Fill out the definition and supporting context before it can validate. Validate returns a content fingerprint (SHA-256), but no authenticity guarantee or scientific verdict. Compare distinguishes identical wording, competing wording, different contexts, and different concepts. Wording disagreements are never automatically labeled contradictions.

## Record contract

The schema identifier is phi369.standard-definition.v0.1.

Each record contains a scoped concept ID, revision, term, domain, context, proposed definition, epistemic status, temporal perspectives (was, is, might_become), assumptions, evidence attribution pointers, alternatives with proposed distinguishing tests, typed proposed relationships, unanswered questions, and review_state.

The only allowed Rung 1 review state is unreviewed. Status labels draft/model_supported/hypothesis/speculative/unknown are supplied by the operator; they are not inferred or independently certified. A model_supported label requires at least one supporting attributed citation. Source and claim IDs, quoted text and stance are metadata only; Rung 1 does NOT read the referenced source or verify that it says what is claimed.

Local input must be UTF-8 JSON. Records greater than 256 KiB, duplicate JSON object keys, nonfinite numeric constants, extra or missing schema keys, excessive list entries, wrong status labels and self-referential links are rejected. Neither command writes to the SQLite ledger, contacts models or performs network requests.

## Integrations deferred deliberately

Rung 2: selected WITNESS source/claim verification by exact quote, source digest and scope; review-only WEAVER links and auditable human input. Later: external GMED test receipts, Altermath/NBG model adapters, and PhiMadaPrime ThinkTank visualization. None are live in Rung 1.

Principle: a standard is a tool for investigating reality, not a declaration that reality must conform to it.


## Rung 2: local WITNESS Evidence Genesis

Rung 2 adds an explicitly requested, **read-only** audit of an existing complete
Standard Definer JSON record against one existing PhiTriBrain SQLite database.
It uses the existing WITNESS citation verifier. There is **no** automated retrieval,
candidate generation, agent, database migration, or remote service.

After using the ordinary TriBrain commands to ingest a non-sensitive local
source and record an exact-quote claim, put its real returned source_id, claim_id,
verbatim quote and supplied stance in the candidate's evidence array:

    {
      "source_id": "src_REAL_LOCAL_ID",
      "claim_id": "clm_REAL_LOCAL_ID",
      "quote": "A verbatim excerpt from the stored source.",
      "stance": "supports"
    }

Run the check with an *existing* database:

    python -m phitribrain.standard_definer evidence candidate.json --db .phitribrain/brain.sqlite3 --scope Physics

An optional --as-of argument accepts a timezone-aware ISO 8601 timestamp;
--stale-after-days defaults to 180. The command exits 0 only when all explicitly
selected source/claim/quote bindings match local WITNESS. It exits 2 for missing
evidence, failed structure or anchor checks, or missing database. Neither the
CLI nor audit function inserts data or grants permissions.

The report contains a hash of the candidate JSON; each successfully checked
binding contains the locally recomputed source digest, quote offset and line,
claim status, observation-age metadata and warnings. Existing WEAVER proposals
between the explicit referenced claims may be shown as **proposed, not facts**;
the audit never creates or approves WEAVER relationships. For bounded reporting,
only up to 20 explicit evidence items and 20 existing proposals are shown.

**Trust boundaries:** LOCAL_QUOTE_ANCHORS_MATCHED means only that an existing
local source body matches its recorded digest and the selected quote matches
the stored claim at its recorded offset. It does not authenticate the outside
world, verify external citations, establish scientific truth, endorse the
claimed epistemic status, approve a standard, certify an AI model, or authorize
STEWARD decisions and tool execution. Disputed/stale claims stay visible with
warnings; a successful anchor check still requires human review.
