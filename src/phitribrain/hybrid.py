"""Rung 3c: opt-in local Ollama embeddings and evaluated hybrid retrieval.

No external provider, daemon, implicit indexing, claim promotion or execution.
The model endpoint is fixed to 127.0.0.1; imported text is untrusted data.
Vector similarity and retrieval rank are NOT factual confidence.
"""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .evidence import cited_claim, find_evidence
from .store import BrainStore, SEARCH_WORDS, canonical_json, sha, utcnow, validate_scope

OLLAMA_EMBED_URL = "http://127.0.0.1:11434/api/embed"
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,99}\Z")
MAX_CLAIMS = 250
MAX_TEXT_BYTES = 16_384
MAX_RESPONSE_BYTES = 1_000_000
MAX_EMBED_DIM = 4096
RRF_K = 60


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Local embedding service redirects are forbidden")


def _validate_model(model: str) -> str:
    if not isinstance(model, str) or not MODEL_RE.fullmatch(model):
        raise ValueError("Model must be a nonempty local Ollama model identifier")
    if model.lower().endswith(":cloud"):
        raise ValueError("Cloud-routed Ollama model names are forbidden")
    return model


def _unit_vector(values) -> list[float]:
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_EMBED_DIM:
        raise ValueError("Embedding must have 2 to 4096 numeric dimensions")
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in values):
        raise ValueError("Embedding contains nonfinite or nonnumeric values")
    length = math.sqrt(sum(float(x) * float(x) for x in values))
    if length <= 1e-12 or not math.isfinite(length):
        raise ValueError("Embedding magnitude must be finite and nonzero")
    return [float(x) / length for x in values]


def local_ollama_embed(text: str, model: str) -> list[float]:
    """Only explicit CLI use connects to a locally hosted embedding server."""
    _validate_model(model)
    if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Text sent for embedding must be nonempty and at most 16 KB")
    payload = json.dumps({
        "model": model, "input": text, "truncate": False,
        "keep_alive": "1m",
    }).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_EMBED_URL, data=payload, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "PhiTriBrain369/0.3"},
    )
    # Ignore HTTP(S)_PROXY and prevent redirects off loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            if response.geturl() != OLLAMA_EMBED_URL:
                raise ValueError("Unexpected local embedding response URL")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(
            f"Local Ollama returned HTTP {exc.code}; check the installed embedding model"
        ) from exc
    except urllib.error.URLError as exc:
        raise ValueError("Cannot reach local Ollama on 127.0.0.1:11434") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Local Ollama response exceeded size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Local Ollama returned malformed JSON") from exc
    returned_model = data.get("model") if isinstance(data, dict) else None
    acceptable = {model}
    if ":" not in model:
        acceptable.add(model + ":latest")
    if returned_model not in acceptable:
        raise ValueError("Local Ollama response model did not match the requested model")
    vectors = data.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise ValueError("Local Ollama did not return exactly one embedding")
    return _unit_vector(vectors[0])


def _claim_rows(store: BrainStore, scope: str) -> list[dict]:
    rows = store.db.execute(
        "SELECT c.id,c.statement,c.quote,c.source_id,s.digest "
        "FROM claims c JOIN sources s ON c.source_id=s.id "
        "WHERE c.scope=? AND c.state='recorded' AND s.scope=? "
        "ORDER BY c.id LIMIT ?",
        (scope, scope, MAX_CLAIMS + 1),
    ).fetchall()
    if len(rows) > MAX_CLAIMS:
        raise ValueError("Hybrid index supports at most 250 recorded claims per scope")
    return [dict(r) for r in rows]


def _record_text(row: dict) -> str:
    return row["statement"] + "\nQuoted evidence: " + row["quote"]


def _content_hash(row: dict) -> str:
    return sha(canonical_json([
        row["id"], row["source_id"], row["digest"],
        row["statement"], row["quote"],
    ]))


def index_plan(store: BrainStore, *, scope: str, model: str,
               limit: int = 20) -> dict:
    """Preview pending claims; no embedding requests or DB writes."""
    scope = validate_scope(scope)
    model = _validate_model(model)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    rows = _claim_rows(store, scope)
    pending = []
    for row in rows:
        cited_claim(store, scope=scope, claim_id=row["id"])
        text = _record_text(row)
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("Claim exceeds 16 KB embedding input: " + row["id"])
        current = store.db.execute(
            "SELECT content_sha256 FROM claim_embeddings "
            "WHERE scope=? AND claim_id=? AND model=?",
            (scope, row["id"], model),
        ).fetchone()
        if current is None or current["content_sha256"] != _content_hash(row):
            pending.append(row)
    return {
        "mode": "dry-run", "scope": scope, "model": model,
        "total_claims": len(rows), "pending": len(pending),
        "selected": pending[:limit], "truncated": len(pending) > limit,
        "limit": limit,
        "warning": (
            "Preview makes no model requests or writes. --apply sends the selected "
            "source-attributed claim text to the local Ollama service."
        ),
    }


def build_index(store: BrainStore, *, scope: str, model: str,
                limit: int = 20,
                embed_fn: Callable[[str, str], list[float]] = local_ollama_embed) -> dict:
    """Opt-in bounded embed calls then atomic, audited derived-index upserts."""
    plan = index_plan(store, scope=scope, model=model, limit=limit)
    selected = plan["selected"]
    prepared = []
    for row in selected:
        vec = _unit_vector(embed_fn(_record_text(row), model))
        prepared.append((row, vec))
    dimension = len(prepared[0][1]) if prepared else None
    if any(len(vec) != dimension for _, vec in prepared):
        raise ValueError("Embedding model returned inconsistent dimensions")
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        current_rows = {row["id"]: row for row in _claim_rows(store, scope)}
        for row, _ in prepared:
            actual = current_rows.get(row["id"])
            if actual is None or _content_hash(actual) != _content_hash(row):
                raise ValueError("Claim changed while embeddings were being computed")
            cited_claim(store, scope=scope, claim_id=row["id"])
        other = store.db.execute(
            "SELECT dimension FROM claim_embeddings "
            "WHERE scope=? AND model=? LIMIT 1",
            (scope, model),
        ).fetchone()
        if dimension is not None and other is not None and other["dimension"] != dimension:
            raise ValueError("Model dimension changed; use a distinct model identifier")
        for row, vec in prepared:
            # Derived embeddings may be refreshed; source and claim rows are immutable here.
            store.db.execute(
                "INSERT INTO claim_embeddings(scope,claim_id,model,content_sha256,"
                "dimension,vector_json,indexed_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(scope,claim_id,model) DO UPDATE SET "
                "content_sha256=excluded.content_sha256,"
                "dimension=excluded.dimension,vector_json=excluded.vector_json,"
                "indexed_at=excluded.indexed_at",
                (scope, row["id"], model, _content_hash(row), len(vec),
                 canonical_json(vec), utcnow()),
            )
            store._event(scope, "embedding.index", {
                "claim_id": row["id"], "model": model,
                "content_sha256": _content_hash(row), "dimension": len(vec),
            })
    return {
        "mode": "applied", "scope": scope, "model": model,
        "indexed": len(prepared), "remaining_estimate": plan["pending"] - len(prepared),
        "dimension": dimension,
        "warning": "Vectors are derived retrieval data, not verified knowledge.",
    }


def hybrid_search(store: BrainStore, *, scope: str, query: str, model: str,
                  limit: int = 10, min_cosine: float = 0.15,
                  embed_fn: Callable[[str, str], list[float]] = local_ollama_embed) -> dict:
    """RRF merge of lexical and local cosine results with exact WITNESS citations."""
    scope = validate_scope(scope)
    model = _validate_model(model)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("limit must be 1 to 30")
    if not isinstance(min_cosine, (float, int)) or not -1.0 <= min_cosine <= 1.0:
        raise ValueError("min_cosine must be in [-1, 1]")
    if not isinstance(query, str) or not query.strip() or len(query.encode("utf-8")) > 2048:
        raise ValueError("Query must be nonempty and at most 2048 bytes")
    rows = _claim_rows(store, scope)
    if not rows:
        return {"scope": scope, "query": query, "abstained": True, "matches": [],
                "reason": "No recorded claims in this scope"}
    by_id = {r["id"]: r for r in rows}
    saved = store.db.execute(
        "SELECT claim_id,content_sha256,dimension,vector_json "
        "FROM claim_embeddings WHERE scope=? AND model=?",
        (scope, model),
    ).fetchall()
    indexed = []
    for vector in saved:
        row = by_id.get(vector["claim_id"])
        if row is None or vector["content_sha256"] != _content_hash(row):
            continue
        embedding = _unit_vector(json.loads(vector["vector_json"]))
        if len(embedding) != vector["dimension"]:
            raise ValueError("Stored embedding dimension is inconsistent")
        indexed.append((vector["claim_id"], embedding))
    if not indexed:
        raise ValueError("No current embeddings for model; run embed-index --apply first")
    if len({len(vec) for _, vec in indexed}) != 1:
        raise ValueError("Stored embeddings have inconsistent dimensions")
    qvec = _unit_vector(embed_fn(query, model))
    if len(qvec) != len(indexed[0][1]):
        raise ValueError("Query embedding dimensions differ from stored model")
    sem = []
    for cid, vec in indexed:
        similarity = sum(a * b for a, b in zip(vec, qvec))
        if similarity >= min_cosine:
            sem.append((cid, similarity))
    sem.sort(key=lambda x: (-x[1], x[0]))
    semantic_ids = [cid for cid, _ in sem]
    similarity_by_id = dict(sem)
    tokens = SEARCH_WORDS.findall(query)[:16]
    lexical_ids = []
    if tokens:
        match = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        lexical_rows = store.db.execute(
            "SELECT record_id FROM search_fts WHERE search_fts MATCH ? "
            "AND scope=? AND kind='claim' ORDER BY bm25(search_fts),record_id LIMIT ?",
            (match, scope, MAX_CLAIMS),
        ).fetchall()
        lexical_ids = [r["record_id"] for r in lexical_rows if r["record_id"] in by_id]
    scores = {}
    provenance = {}
    for source_name, ids in (("lexical", lexical_ids), ("semantic", semantic_ids)):
        for rank, cid in enumerate(ids, 1):
            scores[cid] = scores.get(cid, 0) + 1 / (RRF_K + rank)
            provenance.setdefault(cid, []).append(source_name)
    ranked = sorted(scores, key=lambda cid: (-scores[cid], cid))[:limit]
    matches = []
    for cid in ranked:
        # Fail closed if any displayed claim/source quote is corrupted.
        receipt = cited_claim(store, scope=scope, claim_id=cid)
        matches.append({
            "claim_id": cid,
            "retrieval": {
                "rrf_rank_score_not_confidence": round(scores[cid], 8),
                "channels": provenance[cid],
                "cosine_if_indexed": round(similarity_by_id[cid], 5)
                if cid in similarity_by_id else None,
            },
            "evidence": receipt,
        })
    return {
        "scope": scope, "model": model, "query": query,
        "indexed_claims": len(indexed), "matches": matches,
        "count": len(matches), "abstained": not bool(matches),
        "reason": None if matches else "Neither retrieval channel found a match",
        "warning": (
            "Retrieval scores are not calibrated confidence. Results are source-"
            "attributed claims, not independently verified facts."
        ),
    }


def evaluate_hybrid(store: BrainStore, *, scope: str, model: str,
                    corpus: str | Path, k: int = 5,
                    embed_fn: Callable[[str, str], list[float]] = local_ollama_embed) -> dict:
    """Measure judged recall@k, MRR, precision@k; never writes to database."""
    scope = validate_scope(scope)
    model = _validate_model(model)
    if type(k) is not int or not 1 <= k <= 30:
        raise ValueError("k must be 1 to 30")
    path = Path(corpus)
    if path.stat().st_size > 64_000:
        raise ValueError("Evaluation corpus is too large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"scope", "cases"} or data["scope"] != scope:
        raise ValueError("Evaluation corpus scope mismatch or schema error")
    cases = data["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 50:
        raise ValueError("Evaluation needs 1-50 judged cases")
    actual_ids = {
        r["id"] for r in store.db.execute(
            "SELECT id FROM claims WHERE scope=?", (scope,)
        )
    }
    metrics = {"hybrid": [0, 0.0, 0], "lexical": [0, 0.0, 0]}
    leak_count = 0
    judged = 0
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"query", "relevant_claim_ids"}:
            raise ValueError("Each evaluation case requires query and relevant_claim_ids")
        query, relevant = case["query"], case["relevant_claim_ids"]
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError("Invalid evaluation query")
        if not isinstance(relevant, list) or not relevant or (
            any(type(cid) is not str or cid not in actual_ids for cid in relevant)
        ) or len(relevant) != len(set(relevant)):
            raise ValueError("Relevant claim IDs must be nonempty, unique and in scope")
        truth = set(relevant)
        judged += len(truth)
        hybrid = hybrid_search(
            store, scope=scope, query=query, model=model,
            limit=k, embed_fn=embed_fn,
        )
        lexical = find_evidence(store, scope=scope, query=query, limit=k)
        for name, claim_ids in (
            ("hybrid", [x["claim_id"] for x in hybrid["matches"]]),
            ("lexical", [x["claim_id"] for x in lexical["matches"]]),
        ):
            true_positives = len(truth.intersection(claim_ids))
            metrics[name][0] += true_positives
            metrics[name][2] += true_positives
            first = next(
                (rank for rank, cid in enumerate(claim_ids, 1) if cid in truth),
                None,
            )
            metrics[name][1] += (1 / first) if first else 0
            leak_count += sum(cid not in actual_ids for cid in claim_ids)
    n = len(cases)
    return {
        "scope": scope, "model": model, "k": k, "judged_queries": n,
        "judged_relevant_claims": judged,
        "hybrid": {
            "recall_at_k": round(metrics["hybrid"][0] / judged, 4),
            "precision_at_k": round(metrics["hybrid"][2] / (n * k), 4),
            "mrr": round(metrics["hybrid"][1] / n, 4),
        },
        "lexical": {
            "recall_at_k": round(metrics["lexical"][0] / judged, 4),
            "precision_at_k": round(metrics["lexical"][2] / (n * k), 4),
            "mrr": round(metrics["lexical"][1] / n, 4),
        },
        "cross_scope_leaks": leak_count,
        "warning": "Quality is measured only against the supplied manually judged corpus.",
    }
