# Decision log

Confirmed facts, assumptions and open decisions, kept separate (PRD §23.3). Open decisions are tracked
with IDs in [BACKLOG.md](../BACKLOG.md).

## Confirmed (from the PRD's source conversation)

- Two ecommerce sites currently use Supabase.
- New product images originate in a Google Drive folder.
- Agents prepare images, identify product types (e.g. artwork, hats, blankets), use similar catalog
  entries to help populate product information, and handle multiple colors.
- Human review happens in a dashboard.
- Workflow initiation is event-driven.
- The two storefront catalogs stay separate.
- The repo exposes agents, skills, resources, docs and rules for Claude Code and Cursor.
- Commerce OS is independent of the sibling PM plugin repository.

## Decided in Phase 0a (2026-10-20)

| Decision | Why | Revisit when |
|---|---|---|
| Marketplace layout: plugin in `plugins/commerce-os/`, runtime at repo root | Only the plugin ships on install; runtime code and tests never do. Differs from PRD §18, which puts `.claude-plugin/` at root. | Never, unless distribution changes. |
| Router `commerce-lead` added, opt-in, not bound as default agent | Freeform routing without taking over every session. | B-022 |
| No MCP servers in the plugin | A storefront DB connector would bypass the workflow service. | Phase 1, when `~~workflow` exists. |
| All 12 PRD §6.1 skills scaffolded (§18 listed 9) | §6.1 is the requirement; §18 is illustrative. | — |
| Canonical agent-facing policies live in `plugins/commerce-os/shared/`; `AGENTS.md`, `CLAUDE.md`, the Cursor rule and `docs/` point to them | One source per rule; the plugin can't read outside its own folder once installed. | — |
| Agent tools limited to Read, Grep, Glob, Write (router adds Agent) | Least privilege; no shell, no network. | Phase 1 |

## Assumptions (unconfirmed)

- Submission unit is one product folder with an optional manifest; readiness is a ready manifest (B-003).
- MVP categories: artwork, hat, blanket (B-005).
- Create-only publication first (B-007).
- Cursor reads `AGENTS.md`, `CLAUDE.md` and `.mdc` rules with `alwaysApply` (checked against Cursor's
  rules documentation on 2026-10-20; re-verify before claiming AC-14).

## Open

PRD §22 questions 1–13 are BACKLOG B-001 to B-013.
