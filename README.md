# Commerce OS

Commerce OS prepares new products for two independently operated storefronts. Product images arrive
in Google Drive; four specialized agents prepare images, identify and structure products, assemble
destination-specific drafts, and coordinate human-approved publication through a central review
dashboard. The specification is [PRD.md](PRD.md).

> **Status: Phase 0a, scaffold only.** The plugin's agents, skills, commands and policies exist as
> reviewable specifications. There is no workflow service, database, adapter, dashboard, or external
> connection yet. Nothing in this repository can write to a storefront or to Google Drive.

## What's here

| Path | What it is | Ships in the plugin? |
|---|---|---|
| `plugins/commerce-os/` | Claude Code plugin: agents, skills, commands, shared policies | Yes |
| `.claude-plugin/marketplace.json` | Marketplace listing for the plugin | Marketplace only |
| `AGENTS.md` | Tool-neutral operating boundaries (Claude Code, Cursor, others) | No |
| `.cursor/rules/commerce-os.mdc` | Cursor rule pointing at the canonical policies | No |
| `apps/`, `services/`, `packages/`, `database/`, `resources/` | Runtime system (Phase 1 onward) | No |
| `docs/` | Architecture, state machine, security, decision log | No |
| `tests/`, `run-tests.sh` | Structural test suite (stdlib Python) | No |

## Use it in Claude Code

Load the plugin for one session from a clone:

```bash
claude --plugin-dir plugins/commerce-os
```

Or install it from the local marketplace:

```bash
claude plugin marketplace add "/absolute/path/to/commerce-os"
```

```bash
claude plugin install commerce-os@commerce-os
```

Commands: `/commerce-os:intake`, `/commerce-os:review`, `/commerce-os:dry-run`, `/commerce-os:publish`.
To route freeform requests through the router agent, start a session with
`claude --agent commerce-os:commerce-lead`.

## Use it in Cursor

Cursor reads `AGENTS.md`, `CLAUDE.md` and `.cursor/rules/commerce-os.mdc`. It does not run the Claude
plugin manifest; ask the agent to follow a skill file directly (see the Cursor rule for examples).

## Develop

```bash
./tests/install-hooks.sh
```

```bash
./run-tests.sh
```

Maintainer rules are in [CLAUDE.md](CLAUDE.md); open work is in [BACKLOG.md](BACKLOG.md).
