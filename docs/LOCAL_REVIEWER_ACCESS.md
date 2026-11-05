# Rung 3e: local reviewer roles and password gate

Rung 3e introduced an **optional, scope-specific local credential gate** for **WEAVER relation review annotations**. Rung 3f extends that same gate to **STEWARD decision reviews**. The local roles and enrolled passwords are shared by both review pathways. The main purpose is to stop someone from submitting an `accepted` or `rejected` relationship by typing an arbitrary reviewer label once a scope is enrolled.

It is a **local password-possession check**, not verified human identity, enterprise SSO, a network authentication server, multi-user tenant isolation, a secure key vault or protection from anyone with direct filesystem or Python/SQLite access.

## 1. Initialize the local database

~~~bash
phitribrain init
~~~

Use an existing non-sensitive local database. Keep the SQLite file and its backups under your operating-system account's file permissions.

## 2. Bootstrap the first owner for one scope

~~~bash
phitribrain reviewer-enroll --scope PhiOS --user localowner --role owner
~~~

This is a **one-time local bootstrap** for a scope with no accounts. It requires a real interactive terminal and prompts for a 12-512-character password twice, without echoing it or placing it in shell history or command-line arguments.

**Security warning:** the first process that can open the local DB and execute this command can become the scope owner. Keep the database private and initialize the owner **before** exposing the working folder to other users. This is not a cryptographic proof of who that first owner is.

Once at least one account is enrolled, review annotations in that scope now require a matching username and password. Existing scopes without a locally enrolled account continue operating in legacy unauthenticated mode for backward compatibility. Enabling the gate does not delete, validate or re-sign legacy review history.

## 3. Add a scope reviewer

~~~bash
phitribrain reviewer-enroll --scope PhiOS --user curator1 --role reviewer --owner localowner
~~~

The CLI prompts for the new reviewer's password twice and then for the owner's password. A verified enrolled owner is required for any later enrollment. Roles are:

| Role | Review links in scope | Manage accounts |
|---|---|---|
| `owner` | Yes | Yes |
| `reviewer` | Yes | No |
| `observer` | No | No |

The roles are per-scope. An identity enrolled in `PhiOS` does not automatically have credentials in another scope. All credentials are stored as per-account random-salted PBKDF2-HMAC-SHA256 password verifiers, not plaintext passwords.

## 4. Inspect and submit a review

~~~bash
phitribrain reviewer-list --scope PhiOS
phitribrain relation-queue --scope PhiOS
phitribrain relation-detail --scope PhiOS --relation rel_REPLACE_ME
phitribrain relation-review --scope PhiOS --relation rel_REPLACE_ME --outcome needs_context --reviewer curator1 --reason "Different build commits need comparison"
~~~

The `relation-review` CLI still requires the exact typed confirmation before the review. For an enrolled scope it also prompts for the **password of the exact username in `--reviewer`**. Neither the CLI nor the Python `annotate_relation` function will write a review after enrollment unless that password and the scope role are valid.

All reviews remain append-only and must refer to the latest review ID when revising earlier assessments (`--supersedes`). The audit event records whether local credentials were checked; it never records the password.

An `accepted` relationship remains an **unverified review annotation**, not a factual endorsement of either underlying claim.

## 5. Revoke or re-enable a reviewer

~~~bash
phitribrain reviewer-status --scope PhiOS --user curator1 --owner localowner --enabled no
phitribrain reviewer-status --scope PhiOS --user curator1 --owner localowner --enabled yes
~~~

These operations require the enrolled owner's password. Disabled accounts cannot submit reviews. The final enabled owner in a scope cannot be disabled through this function, preventing accidental lockout.

There is no password reset/recovery or rotation command in this rung. Back up and protect your access information. Safe credential rotation and recovery procedures belong in a subsequent security rung.

## What this DOES NOT protect

- It does **not** authenticate the reviewer to the operating system, verify legal identity, or protect against malicious local administrators or direct SQLite writes.
- Rung 3f also gates STEWARD decision-review writes after scope enrollment, and records a source-backed evidence attestation. It does not make approvals executable. See [STEWARD Review Gate](STEWARD_REVIEW_GATE.md).
- Other local mutation functions (sources, claims, vector indexing, proposal generation) are not protected by account roles. **Do not deploy this code as a shared server or network-facing service.**
- Existing legacy reviews stay visible; the system does not retroactively authenticate them.
- Anyone able to change the source code or SQLite database can bypass or replace password verifiers, review annotations, or audit history. The hash chain is not externally anchored or tamper-proof.
- There is no rate limiting, account lockout, MFA, recovery system, hardware-backed key storage, or external identity provider.
- Passwords and the derived hashes reside in memory while the CLI is running; SQLite contains salts and derived hashes. Protect disk, backups and terminal access.
- `reviewer-list`, `relation-queue` and `relation-detail` are local **read** operations and are not credential-gated. Local database access should be restricted to trusted OS users.
- Security testing focuses on local application behavior. It is not a professional security audit or an authorization layer for PhiBots/PhiMadaPrime yet.

**Future:** add safe password rotation and recovery, external identity and a properly authenticated service boundary before enabling multi-agent access.

**Ledger Above Ego.**
