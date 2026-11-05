# Rung 4a: offline Phi369 operator snapshot bridge

The first operator bridge produces a **small, read-only, explicitly allowlisted JSON snapshot** with three lanes for a PhiMadaPrime, PhiBots, PhiOS, or PhiRSI workspace.

It does **not** start a server, expose an MCP endpoint, deploy an app, communicate with a PhiBot, trigger a GitHub action, or connect to a remote service. It is an information-export building block, **not a deployed application integration**.

## 1. Select a scope and exact record IDs

Use existing WITNESS, WEAVER and STEWARD commands to inspect source-linked records:

~~~bash
phitribrain evidence --scope PhiOS --query "architecture"
phitribrain relation-queue --scope PhiOS --status all
phitribrain stats --scope PhiOS
phitribrain show --scope PhiOS --id dec_REPLACE_ME
~~~

Create a small local JSON manifest such as `examples/operator-bridge.sample.json`. Replace the placeholder IDs with **actual existing records**:

~~~json
{
  "schema_version": 1,
  "consumer": "PhiMadaPrime",
  "scope": "PhiOS",
  "claims": ["clm_REPLACE_WITH_REAL_ID"],
  "relations": [],
  "decisions": []
}
~~~

The manifest must provide exactly these six fields and use exact record IDs, never wildcards. Limit: 20 WITNESS claims, 10 WEAVER relationships, and 10 STEWARD decisions. At least one explicit claim ID is required.

If you include a relationship, **both of its claims must appear in the \`claims\` allowlist**. If you include a decision, **all of its evidence claims must appear**. Missing evidence fails the entire preview/export, rather than silently expanding data access or returning an ungrounded record.

The consumer name is just descriptive metadata. It is **not an authenticated identity, permission grant, or access-control token**.

## 2. Preview without writing to disk

~~~bash
phitribrain bridge --manifest examples/operator-bridge.sample.json
~~~

Preview opens the existing SQLite file with read-only/query-only flags and prints the resulting JSON. It never changes any database records, launches a model, starts a server, or sends data over a network.

The three output lanes are:

| Lane | Includes | Explicit trust label |
|---|---|---|
| WITNESS | Verbatim bounded quote, source SHA-256, precise line/character anchor, observation age and warnings | `source_attribution_only: true` |
| WEAVER | Proposed claim link, review status, derivation method | `is_factual_truth: false` |
| STEWARD | Proposed or reviewed decision, explicitly allowlisted claim IDs, review attestation digest | `execution_authorized: false` |

Quoted material and record names may still contain personally sensitive or proprietary text. **Carefully select non-sensitive records** before printing or exporting. Source bodies, passwords and credential verifiers are not copied to the snapshot.

The snapshot has a content digest for integrity comparison, but **it is not cryptographically signed**. A malicious process with local file write access can modify the JSON and recompute its digest.

## 3. Explicitly create a new local JSON file

~~~bash
phitribrain bridge --manifest examples/operator-bridge.sample.json --output ./phi-operator-snapshot.json
~~~

The output directory must already exist. The exporter refuses to overwrite an existing destination or symlink and uses restrictive file permissions on systems that support them. No database write occurs, and there is no automatic transfer to PhiMadaPrime, PhiBots or the network.

The export file can be opened by a trusted, locally running visualization, **after that visualization independently validates the schema, source origin and trust policy**. Do not treat a user-supplied JSON object as proof of authorization.

A later rung can define an authenticated, least-privilege service protocol. This rung deliberately avoids exposing unprotected reads over HTTP or MCP.

## Constraints and safety

- Single explicitly chosen scope; no cross-scope discovery or automatic fallback.
- Only exact selected IDs. No wildcard, bulk repository scan, autosync, or automatic ingestion.
- At most 20 claims, 10 relations, 10 decisions, 16 KB manifest size and 256 KB exported payload.
- Exact source SHA-256 and quote offsets are revalidated. Invalid, missing, or corrupt evidence fails closed.
- Oversized statements, source quotes, and paths fail closed instead of being silently truncated.
- Default command prints JSON, which can itself leak sensitive data to terminal logs. Treat stdout and exported files as confidential when appropriate.
- No generic read API, external model, inference, background worker, remote endpoint, bearer token, tool-execution gateway, write permissions, or PhiBots task handoff.
- The local OS user controls access to source SQLite and the exported JSON. **This is not a secure multi-user authorization boundary.**
- An approved STEWARD review remains a local annotation; it **never authorizes execution**.
- The snapshot records only a point-in-time view; updates in SQLite are not synchronized automatically.
- The manifest is an explicit filter, not a secrecy guarantee: protect the source database and output files.

## Later Rung 4 work

Design a **read-only, authenticated local service boundary** and a PhiMadaPrime interface that renders the lanes separately. Only after independent authorization, audit, prompt-injection, and collision-control testing should PhiBots receive tightly scoped task handoff capabilities.

**GMED Rule #376: The bridge carries receipts, not launch codes.**
