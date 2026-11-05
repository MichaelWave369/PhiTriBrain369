# Rung 2c: WITNESS evidence retrieval

The new `evidence`, `cite`, and `claim-time` commands provide **attributed, inspectable evidence**, not a natural-language answer generator.

The only search results returned by `evidence` are **claims that already have exact source quotes**. Text existing solely in an imported source is not promoted into an asserted claim. A matching source with no quote-backed claim yields `abstained: true` rather than an invented answer.

## Example

Prepare a source and record a claim:

~~~bash
phitribrain ingest --scope PhiOS --file examples/first_source.md --title "Architecture note"
phitribrain claim --scope PhiOS --source src_REPLACE_ME --statement "The design separates responsibilities" --quote "three distinct responsibilities"
~~~

Inspect the claim with exact character and line locations:

~~~bash
phitribrain cite --scope PhiOS --claim clm_REPLACE_ME
~~~

Retrieve only cited claims:

~~~bash
phitribrain evidence --scope PhiOS --query "responsibilities" --limit 10
~~~

Specify a historical evaluation time and age warning threshold:

~~~bash
phitribrain evidence --scope PhiOS --query "responsibilities" --as-of "2026-11-05T17:00:00Z" --stale-after-days 90
~~~

## What each returned match contains

- Claim text and recorded state, with an exact verbatim quote
- Source ID, SHA-256 of imported text, Unicode character offset/length, start/end line
- An immutable GitHub commit URL and blob SHA if the source came through GitHub WITNESS
- Active vault note path if the source still has a live imported vault mapping
- A stable internal source locator even when no external GitHub path exists
- Source observation timestamp and days since that observation
- Warnings for stale observations, superseded/disputed claims, historical vault snapshots, or proposed contradictions
- Explicit marker `attribution_only: true`

A GitHub SHA points to an immutable *snapshot*. A recent fetch of an old SHA **does not mean the default branch is current**. Observation age measures when this system last recorded the source, not the age of the information in it or whether the underlying fact is still correct.

The quote anchor is checked again at retrieval time. If the stored original bytes or claim quote offset no longer match, the API fails rather than returning a broken citation.

## Asserted validity interval

Claim creation already records *recorded time*. The new append-only annotation command records an optional, **asserted** valid-time interval:

~~~bash
phitribrain claim-time --scope PhiOS --claim clm_REPLACE_ME --from 2026-01-01 --until 2026-12-31 --basis "Historical design interval noted by human reviewer"
~~~

- Dates must be ISO calendar dates `YYYY-MM-DD`.
- You may supply only one boundary.
- Every annotation is append-only with its own recording timestamp and hash-chained audit event.
- Only the latest interval assertion is presented in a standard citation; earlier annotations remain in SQLite.
- The interval's status is `before_asserted_interval`, `within_asserted_interval`, or `after_asserted_interval` relative to the requested `--as-of` timestamp.
- **No interval is independently verified.** The basis and actor are free-text labels, not authentication.

## Evaluation and limits

`python -m unittest discover -s tests -v` includes regression tests for:

- source hash and exact quote mismatch
- line/character provenance
- scope isolation and empty-result abstention
- FTS query tokenization and bounded search limits
- GitHub pinned commit links
- stale observation flags and timestamp validation
- asserted valid intervals, history, and invalid dates
- proposed contradiction flags and historical vault snapshots
- a small pinned query-to-claim retrieval corpus

This evaluation set is only a local correctness smoke test; it is **not a measured real-world retrieval benchmark**. Rung 3 will expand to a larger reviewed dataset with recall@k, precision and cross-scope leakage metrics.

**Security:** Scopes are organizational labels, not authenticated authorization. Do not expose this CLI as a network service or to untrusted multi-user workloads. The local SQLite ledger is not encrypted or externally tamper-proof. No imported document is interpreted as instructions to any model.
