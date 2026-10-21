# Security

Status: Phase 0a. Requirements from [PRD.md](../PRD.md) §17, and how this scaffold already applies them.

## Applied now

| Requirement | How |
|---|---|
| No secrets in the repo | `.env` gitignored; `.env.example` holds fake values; `tests/test_guardrails.py` rejects real-looking secrets. |
| Agents can't write externally | No MCP servers shipped; agent tool lists exclude Bash and network tools; tests pin both. |
| Untrusted input | Every agent and skill reads COMMERCE-CONTEXT.md, which forbids following embedded instructions. |
| Independence (AC-01) | Tests reject references to the sibling repository from shipped and runtime folders. |
| No real data committed | `discovery/raw/` is gitignored for schema dumps and real images. |

## Required before Phase 2

- Separate read and write identities per storefront; write identities only in the publishing worker.
- Dashboard authentication with server-enforced roles (submitter, reviewer, approver, administrator,
  operator).
- Isolation keys on every tenant-sensitive record, enforced in database policies.
- Asset visibility policy: draft images are private; signed URLs only.
- Image-processing resource limits (bytes, decoded pixels, time) and a sandboxed decoder.
- Outbound fetch allowlist for workers and agent tools.
- Redaction of secrets and unnecessary personal data in logs and audit.

## Required before production (Phase 4)

Retention for originals, rejected drafts, logs and backups; verified restore; incident response and
credential-revocation runbooks under `docs/runbooks/`.
