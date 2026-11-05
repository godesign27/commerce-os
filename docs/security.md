# Security

Status: Phase 0a. Requirements from [PRD.md](../PRD.md) §17, and how this scaffold already applies them.

## Applied now

| Requirement | How |
|---|---|
| No secrets in the repo | `.env` gitignored; `.env.example` holds fake values; `tests/test_guardrails.py` rejects real-looking secrets. |
| Agents can't write externally | No MCP servers shipped; agent tool lists exclude Bash and network tools; tests pin both. |
| Untrusted input | Every agent and skill reads COMMERCE-CONTEXT.md, which forbids following embedded instructions. |
| Independence (AC-01) | Tests reject references to the sibling repository from shipped and runtime folders. |
| Read-only catalog role | docs/runbooks/read-only-role.md creates it; `scripts/check_read_role.py` proves it reads only products, categories and tags, holds no write privilege or elevated attribute, and runs in a read-only session. |
| No real data committed | `discovery/raw/` is gitignored for schema dumps and real images. |

## Required before Phase 2

Phase 2 is proceeding in legs, and the owner decided on 2026-11-04 to keep it on one computer for now
(see the decision log). Where each requirement stands:

| Requirement | Status |
|---|---|
| Separate read and write identities per storefront; write identities only in the publishing worker | Read: done. Each catalog read checks the login and refuses one that can write or can see beyond the catalog tables. Write: built and checked at every worker start; the owner creates it (`docs/runbooks/write-role.md`). |
| Image-processing limits (bytes, decoded pixels) | Done for the inbox (`packages/image_pipeline/intake.py`), checked before decoding. Time limit: not enforced. |
| Redaction of secrets and unnecessary personal data in logs and audit | Catalog reads never put the connection string in a message, and they read no customer or price data. A wider review of logs comes with hosting. |
| Dashboard authentication with server-enforced roles (submitter, reviewer, approver, administrator, operator) | **Deferred until hosted or a second person joins (B-008).** Today: 127.0.0.1 only, and writes need the `X-Commerce-OS` header. |
| Isolation keys on every tenant-sensitive record, enforced in database policies | **Deferred until the operational database is in use.** Catalog copies and answers are kept per storefront, and a copy stamped for another storefront is refused. |
| Asset visibility policy: draft images are private; signed URLs only | **Deferred.** On a live store, a Draft's images are public under unguessable names, because the store serves only those (decision log). |
| A sandboxed decoder for images, and a time limit | **Deferred until photos come from anyone but the owner.** |
| Outbound fetch allowlist for workers and agent tools | **Deferred until workers exist.** The only outbound calls are the model API and the catalog read. |

## Publishing

Only the publishing worker writes, as a separate program from the dashboard, which can only ask. Its target is a local
test store unless the owner has turned the live store on with `scripts/go_live.py` (`docs/runbooks/write-role.md`).
The adapter refuses any target but a local Unix socket, or the one encrypted host `packages/publisher/live_store.py`
names after its checks. Only that file reads the write and upload logins, and it stops the worker if a login can do
more than the runbook allows. On a live store, the write login can add products and read the catalog, nothing else,
and the database refuses any status but Draft. The upload login can only add files to the uploads folders, and never
overwrites. Writes use parameters only, so listing text can never run as SQL. The kill switch stops writing, and fails
safe if its file is unreadable.

## Credentials on the local page

The read-only login and the Claude API key are entered on the dashboard's Getting started page (owner decision
2026-11-04). The rules: the page runs only on 127.0.0.1; both are checked before anything is saved; a login that
can change data or see beyond the catalog tables is refused; they're saved in `.env`, readable by this user
only; no response, message, log or audit record holds them; and a login already used elsewhere here is
refused. Write logins never come through this page, and agents still never handle a credential.

## Required before production (Phase 4)

Retention for originals, rejected drafts, logs and backups; verified restore; incident response and
credential-revocation runbooks under `docs/runbooks/`.
