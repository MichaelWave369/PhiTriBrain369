# Rung 3f: STEWARD decision review credentials and evidence attestation

STEWARD now shares the optional **scope-local reviewer password gate** introduced for WEAVER in Rung 3e. A decision review becomes a human-labelled, source-verified **annotation**, never authority to execute code or deploy software.

## 1. Enable local password checks for a scope

~~~bash
phitribrain reviewer-enroll --scope PhiOS --user localowner --role owner
phitribrain reviewer-enroll --scope PhiOS --user curator1 --role reviewer --owner localowner
~~~

Password prompts are hidden from the terminal echo and never placed into CLI flags or audit records. Existing scope-local owner/reviewer/observer roles apply to **both** WEAVER relation annotations and STEWARD decision reviews.

- Owners and reviewers can approve/reject a decision after supplying their own enrolled password.
- Observers and disabled accounts cannot review.
- Credentials do not transfer across scopes.
- A scope without enrolled reviewer accounts remains in legacy unauthenticated local mode for backward compatibility.

See [Local Reviewer Access](LOCAL_REVIEWER_ACCESS.md).

## 2. Review supporting evidence

First open the decision and inspect its claim references:

~~~bash
phitribrain show --scope PhiOS --id dec_REPLACE_ME
phitribrain cite --scope PhiOS --claim clm_REPLACE_ME
~~~

Check each citation and its warnings. Source attribution means the note contains the claim; it **does not establish that the claim is true or current**.

## 3. Approve or reject interactively

~~~bash
phitribrain review --scope PhiOS --decision dec_REPLACE_ME --outcome approved --reviewer curator1
~~~

The CLI requires an interactive terminal and exact confirmation text:

~~~text
APPROVE dec_REPLACE_ME
~~~

When a scope has enrolled reviewers it then requests the password for the reviewer named in the command. The lower-level Python `BrainStore.review_decision` API also checks scope-local credentials, so skipping the CLI prompt doesn't skip the password requirement.

The action is executed in one SQLite transaction:

1. Verify the enrolled user's scope and owner/reviewer role, if the scope is gated.
2. Reject missing, previously reviewed, or wrong-scope decisions.
3. Revalidate the exact WITNESS source hash and quote anchor for every linked evidence claim.
4. Save the decision review status and an evidence attestation with source IDs, source SHA-256 values and quote offsets.
5. Append an audit event containing the review label, credential-check status and digest of the inspected evidence.

The evidence attestation is visible through:

~~~bash
phitribrain show --scope PhiOS --id dec_REPLACE_ME
phitribrain audit
~~~

A failed password, corrupt source, missing evidence, or audit write rolls back the entire decision review.

## 4. Intentional limitations

- `approved` is a **review annotation**. It is not factual verification, an instruction to PhiBots, authorization to deploy, or approval to execute a command.
- Decision reviews remain **single-shot**: a reviewed decision cannot be re-approved or overwritten by the standard command. Reassessment and superseding decisions require a separately designed history workflow.
- Old reviewed decisions and their original audit entries remain unchanged. Pre-Rung-3f decisions may have no evidence-attestation row. Enrolling accounts does **not** retroactively authenticate historical reviews.
- Enrolled credentials prove local password possession only, not physical identity. Database and Python module owners can bypass application-level checks.
- This protects **decision review writes**, not read access, source ingestion, decision proposal creation, or other APIs. Never expose SQLite or the CLI to untrusted users.
- No MFA, rate limiting, password recovery, service-bound identity, multi-tenant isolation, encryption, or tamper-proof external audit anchors yet.
- Review outputs reveal source citations and organizational labels. Use non-sensitive project evidence.

**Next:** independently verified role/permission boundaries for PhiMadaPrime and PhiBots before allowing remote or autonomous operators near these review controls.

**GMED Rule #375: A rubber stamp is not evidence.**
