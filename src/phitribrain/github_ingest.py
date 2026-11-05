"""Explicit, public, commit-pinned GitHub file ingestion for WITNESS.

Network access is read-only to fixed GitHub REST endpoints. The manifest is an
allowlist of repository/commit/path triples. A preview never writes to SQLite.
No fetched content is executed, used as agent instructions, or interpreted as
trusted facts.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .store import BrainStore, sha, utcnow, validate_scope

MAX_MANIFEST_BYTES = 32_768
MAX_JSON_BYTES = 1_000_000
MAX_SOURCE_BYTES = 250_000
MAX_FILES = 20
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
SHA_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
SAFE_PATH_RE = re.compile(r"[A-Za-z0-9_./ +()-]{1,200}\Z")
ALLOWED_EXTENSIONS = {".md", ".markdown", ".rst", ".txt", ".json", ".yaml",
                      ".yml", ".toml", ".py", ".js", ".jsx", ".ts", ".tsx"}
DENIED_NAMES = {".env", ".npmrc", ".pypirc", "credentials.json", "secrets.json",
                "id_rsa", "id_ed25519", "config.json.key"}
DENIED_PARTS = {".git", "node_modules", ".venv", "dist", "build"}
SECRET_MARKERS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<!\w)ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<!\w)github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?<!\w)AKIA[0-9A-Z]{16}"),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are not permitted when reading GitHub API data")


def github_json(url: str) -> dict:
    """Fetch JSON from the API host only, without authentication or redirects."""
    if not url.startswith("https://api.github.com/repos/"):
        raise ValueError("Only GitHub repository API endpoints are permitted")
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": "PhiTriBrain369/0.2"},
        method="GET",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
            if response.geturl() != url:
                raise ValueError("Unexpected GitHub API response URL")
            data = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"GitHub API returned HTTP {exc.code}; verify public access and SHA") from exc
    except urllib.error.URLError as exc:
        raise ValueError("GitHub API connection failed") from exc
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("GitHub JSON response exceeds size limit")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub API response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("GitHub API response must be an object")
    return payload


def valid_path(path: str) -> str:
    if not isinstance(path, str) or not SAFE_PATH_RE.fullmatch(path):
        raise ValueError("GitHub file path contains unsupported characters")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("GitHub file path must be relative without traversal")
    if any(p.lower() in DENIED_PARTS or p.lower() in DENIED_NAMES for p in parts):
        raise ValueError("GitHub file path is excluded as potentially unsafe")
    if Path(path).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("Only allowlisted UTF-8 text file extensions are supported")
    return path


def parse_manifest(path: str | Path) -> dict:
    location = Path(path)
    if location.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("GitHub manifest exceeds size limit")

    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate manifest key: {key}")
            result[key] = value
        return result

    try:
        raw = json.loads(location.read_text(encoding="utf-8"),
                         object_pairs_hook=no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid GitHub manifest JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"scope", "repositories"}:
        raise ValueError("Manifest requires exactly 'scope' and 'repositories'")
    scope = validate_scope(raw["scope"])
    repos = raw["repositories"]
    if not isinstance(repos, list) or not 1 <= len(repos) <= 4:
        raise ValueError("Provide between 1 and 4 allowlisted repository entries")
    seen = set()
    normalized = []
    total = 0
    for entry in repos:
        if not isinstance(entry, dict) or set(entry) != {"repository", "commit", "paths"}:
            raise ValueError("Each repository requires repository, commit, paths")
        repo, commit, paths = entry["repository"], entry["commit"], entry["paths"]
        if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
            raise ValueError("Invalid owner/repository identifier")
        if not isinstance(commit, str) or not SHA_RE.fullmatch(commit):
            raise ValueError("Each repository must specify a full 40-hex commit SHA")
        if not isinstance(paths, list) or not paths:
            raise ValueError("Each repository needs at least one file path")
        for path in paths:
            valid_path(path)
            key = (repo.lower(), commit.lower(), path)
            if key in seen:
                raise ValueError("Duplicate repository/commit/path selection")
            seen.add(key)
            total += 1
        normalized.append({"repository": repo, "commit": commit.lower(), "paths": paths})
    if total > MAX_FILES:
        raise ValueError("A single import may include at most 20 files")
    return {"scope": scope, "repositories": normalized}


def _blob_sha(content: bytes) -> str:
    header = ("blob " + str(len(content))).encode("ascii") + b"\x00"
    return hashlib.sha1(header + content).hexdigest()


def _validate_content(body: bytes) -> str:
    if not body or len(body) > MAX_SOURCE_BYTES:
        raise ValueError("GitHub source must be nonempty and at most 250 KB")
    if b"\x00" in body:
        raise ValueError("Binary/NUL content cannot be imported")
    try:
        text = body.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("Only UTF-8 text can be imported") from exc
    for marker in SECRET_MARKERS:
        if marker.search(text):
            raise ValueError("Possible credential detected; import refused")
    return text


def prepare(manifest: dict, fetch_json: Callable[[str], dict] = github_json) -> list[dict]:
    """Fetch and verify selected public files; no local database operations."""
    fetched = []
    verified_commits = set()
    for entry in manifest["repositories"]:
        repo, commit = entry["repository"], entry["commit"]
        root = f"https://api.github.com/repos/{repo}"
        key = (repo, commit)
        if key not in verified_commits:
            metadata = fetch_json(f"{root}/commits/{commit}")
            if not isinstance(metadata, dict) or metadata.get("sha", "").lower() != commit:
                raise ValueError(f"GitHub did not return the exact pinned commit for {repo}")
            verified_commits.add(key)
        for path in entry["paths"]:
            encoded = urllib.parse.quote(path, safe="/")
            payload = fetch_json(f"{root}/contents/{encoded}?ref={commit}")
            if not isinstance(payload, dict) or payload.get("type") != "file":
                raise ValueError("GitHub file response was missing or not a regular file")
            if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
                raise ValueError("GitHub returned unsupported content encoding")
            expected_blob = payload.get("sha")
            if not isinstance(expected_blob, str) or not SHA_RE.fullmatch(expected_blob):
                raise ValueError("GitHub blob SHA is invalid")
            try:
                encoded_bytes = payload["content"].replace("\n", "").replace("\r", "")
                body = base64.b64decode(encoded_bytes, validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise ValueError("Malformed GitHub file content encoding") from exc
            if type(payload.get("size")) is not int or payload["size"] != len(body):
                raise ValueError("GitHub reported an inconsistent file size")
            if _blob_sha(body) != expected_blob.lower():
                raise ValueError("Git blob digest mismatch; refusing source")
            text = _validate_content(body)
            origin = f"https://github.com/{repo}/blob/{commit}/{encoded}"
            fetched.append({
                "scope": manifest["scope"], "repository": repo, "commit": commit,
                "path": path, "blob_sha": expected_blob.lower(),
                "origin": origin, "body": text, "digest": sha(text),
                "fetched_at": utcnow(),
            })
    return fetched


def preview(plans: list[dict]) -> dict:
    return {
        "mode": "dry-run", "count": len(plans),
        "files": [{k: item[k] for k in ("scope", "repository", "commit", "path",
                                      "blob_sha", "digest", "fetched_at", "origin")}
                  for item in plans],
        "message": "No files or database records were written. Use --apply to ingest.",
    }


def apply(store: BrainStore, plans: list[dict]) -> dict:
    """Write verified sources and their commit-pinned origins to local SQLite only."""
    items = []
    for item in plans:
        source = store.ingest(
            scope=item["scope"], title=f"{item['repository']} / {item['path']}",
            body=item["body"], origin=item["origin"], actor="github-witness",
        )
        link = store.record_github_import(
            scope=item["scope"], source_id=source["id"],
            repository=item["repository"], commit=item["commit"],
            path=item["path"], blob_sha=item["blob_sha"],
            origin=item["origin"], fetched_at=item["fetched_at"],
        )
        items.append({
            "source_id": source["id"], "new_content": source["new_content"],
            "new_import": link["new_import"], "origin": item["origin"],
        })
    return {"mode": "applied", "count": len(items), "imports": items}
