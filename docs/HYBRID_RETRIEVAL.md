# Rung 3c: optional local semantic + lexical retrieval

Rung 3c adds a bounded, **explicitly opt-in embedding index** alongside WITNESS's existing exact quote-backed evidence retrieval. The actual model must be installed and running locally in Ollama. No cloud account, API key, external Python packages, background indexing, or generative model is required.

WEAVER may use the results to explore potentially related evidence later, but this rung **does not automatically assert any new relationship**, resolve contradictions or promote claims to facts.

## Prepare local Ollama

Ollama's embeddings API is `POST /api/embed`, accepting `model`, `input` and `truncate`. This integration sends one source-attributed claim per request to **exactly** `http://127.0.0.1:11434/api/embed`. Redirects and HTTP proxies are disabled.

Install a locally available embedding model, for example:

~~~bash
ollama pull embeddinggemma
~~~

Check that Ollama itself is running on your computer and the selected embedding model is locally installed. **A loopback API connection alone does not cryptographically prove where your Ollama service runs inference.** Avoid remote/cloud-routed models and do not expose your Ollama daemon beyond localhost.

Do not use any secret, private or sensitive notes: the local embedding service receives claim statements and verbatim supporting quotes. Inspect records before indexing.

## Step 1: preview (no network or database changes)

~~~bash
phitribrain embed-index --scope PhiOS --model embeddinggemma
~~~

This lists the IDs of up to 20 recorded, quote-backed claims that need embeddings. No model requests are sent and no index rows are written.

Each scope is limited to 250 recorded claims, each embedding input to 16 KB. The command refuses source digest and quote-anchor mismatches rather than embedding corrupted evidence.

## Step 2: create only the selected derived index

~~~bash
phitribrain embed-index --scope PhiOS --model embeddinggemma --limit 20 --apply
~~~

**Only `--apply` sends** the selected local claim text to Ollama. Results are L2-normalized and saved as derived SQLite vectors with claim IDs, source-dependent content digests, model name, dimension and indexed time. An audit event records each index update without embedding the vector itself in the audit log.

Repeated indexing of unchanged claims is idempotent. Claim changes invalidate cached vectors. All vector writes for a batch are atomic and verified again against source hashes before commit.

The index is a retrieval aid, not an independent database of facts. Index data is neither encrypted nor automatically deleted on rollback of source-path mappings.

## Step 3: query with WITNESS citations

~~~bash
phitribrain hybrid --scope PhiOS --model embeddinggemma --query "knowledge saved without internet" --limit 5
~~~

Both channels are used:
1. SQLite FTS5 lexical claim matches.
2. Local Ollama query embedding compared by cosine similarity against current, scope-matched cached vectors.

Reciprocal rank fusion (RRF) combines candidate positions. Returned claims still pass WITNESS's original source SHA-256 and quote-anchor validation and include exact citations, timestamps and warnings.

Scores named `rrf_rank_score_not_confidence` and `cosine_if_indexed` are retrieval measures. **They are not probabilities that a claim is true, recent, or safe.** The output indicates whether each match came from `lexical`, `semantic`, or both. When no evidence is found, the result abstains.

Only previously recorded, non-superseded claims can be surfaced. Model-generated vectors do not cause raw source text to become a claim or introduce a new fact into the ledger.

## Step 4: judge retrieval quality on your own notes

Create a local JSON file that uses actual claim IDs in your chosen scope:

~~~json
{
  "scope": "PhiOS",
  "cases": [
    {
      "query": "offline memory design",
      "relevant_claim_ids": ["clm_REPLACE_WITH_REAL_ID"]
    }
  ]
}
~~~

Run a bounded evaluation against the same corpus using both hybrid and the existing lexical-only retrieval:

~~~bash
phitribrain hybrid-eval --scope PhiOS --model embeddinggemma --corpus ./my-evaluation.json --k 5
~~~

The report includes **recall@k, precision@k, mean reciprocal rank (MRR), and scope-leak counts**. Judged IDs must be unique, present and in scope, or the evaluation is rejected. Tests use deterministic fake vectors and never require a locally running model.

These scores are **only as meaningful as the judged test cases**. A tiny example corpus or a perfect mocked CI score does not prove real-world semantic recall, calibrated confidence, fact accuracy or production safety. Build a representative corpus for each integration.

## Limitations and security

- Requires a real, downloaded local embedding model and running Ollama for `--apply`, `hybrid`, or `hybrid-eval`. Preview and CI are offline.
- Only the **fixed loopback HTTP endpoint** is allowed; no configurable remote endpoint, tokens, redirects or proxy forwarding.
- No guarantees about Ollama's own routing or compromise; use a local model and ensure the daemon is bound to localhost.
- Each model is tracked by its **exact name**. Do not reuse one name with incompatible embedding dimensions or silently change model weights. Reindex under a different model tag if upgrading.
- Scope labels are not authenticated permissions or encryption. Protect database, backups and console output.
- At most 250 eligible claims are scanned per scope; 100 vectors per indexing call; 30 results per query; 50 judged benchmark cases; max vector dimension 4096.
- No vector approximation/search acceleration. Current cosine scoring scans the scope's small local vector cache in Python.
- No cross-project traversal, agent action execution, automatic truth promotion or automatic relation linking.
- Imported source text is untrusted data, including prompt injection content. The embedding API is used for numeric vectors only.
- Human review and permission design must precede a network service, multi-agent bridging, or public UI.

**People Above Profit. Ledger Above Ego.**
