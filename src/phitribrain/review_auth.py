"""Rung 3e: opt-in, local-only, per-scope reviewer credential checks.

Credentials establish possession of a locally enrolled password, NOT a
verified real-world human identity. A process with SQLite write access can
bypass or alter this gate. No API server, sessions, bearer tokens, agents or
remote authentication are exposed. Passwords must never be logged or passed
via command-line flags.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from .store import BrainStore, utcnow, validate_scope

NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
ROLES = ("owner", "reviewer", "observer")
ITERATIONS = 310_000


def _username(value: str) -> str:
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ValueError("Reviewer username must be 1-64 letters, digits, periods, underscores or hyphens, beginning with a letter")
    return value


def _password(value: str) -> str:
    if not isinstance(value, str) or not 12 <= len(value) <= 512 or not value.strip():
        raise ValueError("Local reviewer password must contain 12 to 512 characters")
    return value


def _digest(password: str, salt: bytes, rounds: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)


def review_gate_enabled(store: BrainStore, *, scope: str) -> bool:
    scope = validate_scope(scope)
    return store.db.execute(
        "SELECT 1 FROM reviewer_accounts WHERE scope=? LIMIT 1", (scope,)
    ).fetchone() is not None


def _authorize(store: BrainStore, *, scope: str, username: str,
               password: str, roles: tuple[str, ...]) -> dict:
    scope = validate_scope(scope)
    username = _username(username)
    if not isinstance(password, str):
        raise ValueError("Local reviewer credentials are required")
    row = store.db.execute(
        "SELECT username,role,enabled,salt,password_hash,iterations "
        "FROM reviewer_accounts WHERE scope=? AND username=?",
        (scope, username),
    ).fetchone()
    # Perform a derivation even for unknown users to reduce obvious timing gaps.
    salt = bytes(row["salt"]) if row is not None else b"\x00" * 16
    rounds = int(row["iterations"]) if row is not None else ITERATIONS
    if rounds < 100_000 or rounds > 1_000_000 or len(salt) != 16:
        raise ValueError("Stored reviewer credentials are invalid")
    candidate = _digest(password, salt, rounds)
    expected = bytes(row["password_hash"]) if row is not None else b"\x00" * 32
    if not hmac.compare_digest(candidate, expected) or row is None or not row["enabled"]:
        raise ValueError("Invalid or disabled local reviewer credentials")
    if row["role"] not in roles:
        raise ValueError("Reviewer does not have the required role for this scope")
    return {"username": row["username"], "role": row["role"], "scope": scope}


def authorize_review(store: BrainStore, *, scope: str, username: str,
                     password: str | None) -> dict:
    """Called inside the SAME database transaction as the review mutation."""
    if not review_gate_enabled(store, scope=scope):
        return {"scope": scope, "username": username,
                "role": "legacy_unverified", "credential_checked": False}
    if password is None:
        raise ValueError("This scope requires an enrolled reviewer password")
    user = _authorize(
        store, scope=scope, username=username, password=password,
        roles=("owner", "reviewer"),
    )
    return {**user, "credential_checked": True}


def enroll_reviewer(store: BrainStore, *, scope: str, username: str, role: str,
                    password: str, owner_username: str | None = None,
                    owner_password: str | None = None) -> dict:
    """Initialize a scope owner once, then require an enrolled owner to add users."""
    scope = validate_scope(scope)
    username = _username(username)
    if role not in ROLES:
        raise ValueError("Role must be owner, reviewer or observer")
    password = _password(password)
    salt = secrets.token_bytes(16)
    verifier = _digest(password, salt, ITERATIONS)
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        has_accounts = review_gate_enabled(store, scope=scope)
        if not has_accounts:
            if role != "owner" or owner_username is not None or owner_password is not None:
                raise ValueError("First local account for a scope must be an owner")
        else:
            if owner_username is None or owner_password is None:
                raise ValueError("Enrolling additional users requires owner credentials")
            _authorize(
                store, scope=scope, username=owner_username,
                password=owner_password, roles=("owner",),
            )
        if store.db.execute(
            "SELECT 1 FROM reviewer_accounts WHERE scope=? AND username=?",
            (scope, username),
        ).fetchone():
            raise ValueError("Reviewer already exists; no automatic credential reset")
        now = utcnow()
        store.db.execute(
            "INSERT INTO reviewer_accounts(scope,username,role,enabled,salt,"
            "password_hash,iterations,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (scope, username, role, 1, salt, verifier, ITERATIONS, now, now),
        )
        store._event(scope, "reviewer.enroll", {
            "username": username, "role": role,
            "authorized_by": owner_username if has_accounts else "local_first_owner",
            "credential_scheme": "pbkdf2_hmac_sha256",
        })
    return {
        "scope": scope, "username": username, "role": role,
        "enabled": True, "policy": "local_password_required",
        "warning": "Local password possession only; not externally authenticated identity.",
    }


def change_reviewer_status(store: BrainStore, *, scope: str, username: str,
                           enabled: bool, owner_username: str,
                           owner_password: str) -> dict:
    """Owner-only enable/disable. Never allow disabling the last enabled owner."""
    scope = validate_scope(scope)
    username = _username(username)
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        _authorize(
            store, scope=scope, username=owner_username,
            password=owner_password, roles=("owner",),
        )
        target = store.db.execute(
            "SELECT role,enabled FROM reviewer_accounts "
            "WHERE scope=? AND username=?", (scope, username),
        ).fetchone()
        if target is None:
            raise ValueError("Reviewer does not exist in this scope")
        if not enabled and target["role"] == "owner" and target["enabled"]:
            n = store.db.execute(
                "SELECT COUNT(*) FROM reviewer_accounts WHERE scope=? "
                "AND role='owner' AND enabled=1",
                (scope,),
            ).fetchone()[0]
            if n <= 1:
                raise ValueError("Cannot disable the last enabled scope owner")
        if bool(target["enabled"]) == enabled:
            raise ValueError("Reviewer already has that enabled status")
        store.db.execute(
            "UPDATE reviewer_accounts SET enabled=?,updated_at=? "
            "WHERE scope=? AND username=?",
            (int(enabled), utcnow(), scope, username),
        )
        store._event(scope, "reviewer.status", {
            "username": username, "enabled": enabled,
            "authorized_by": owner_username,
        })
    return {"scope": scope, "username": username, "enabled": enabled}


def list_reviewers(store: BrainStore, *, scope: str) -> dict:
    """Local read-only metadata listing; password material is never returned."""
    scope = validate_scope(scope)
    rows = store.db.execute(
        "SELECT username,role,enabled,created_at,updated_at "
        "FROM reviewer_accounts WHERE scope=? ORDER BY username", (scope,),
    ).fetchall()
    return {
        "scope": scope,
        "enabled": bool(rows),
        "accounts": [
            {**dict(row), "enabled": bool(row["enabled"])}
            for row in rows
        ],
        "warning": "Local credential gate only, not a multi-user authorization service.",
    }
