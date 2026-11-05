# Commerce OS

Commerce OS prepares new products for independently operated storefronts. It turns your photos into
framed listing images and drafted copy, checks them against your store's catalog, and gives you one place to
review and approve each listing. The specification is [PRD.md](PRD.md).

> **Status: Phase 3, on one computer.** Photos, drafts, the review dashboard, read-only catalog checks, approval of
> an exact change set and publishing all work. **Publishing only reaches a local test store:** no real storefront
> can be written to yet. Photos come from a local folder; Google Drive is a later enhancement.

## Start here

```bash
./start.sh
```

It checks that this computer has what's needed and gives the exact command for anything missing. Then it
installs the rest, builds the dashboard, and opens it at `http://127.0.0.1:8770`. The start page leads you
through connecting your store. You'll need:

- Access to your store's database, to create a read-only login. Commerce OS checks that login and refuses one
  that can change data or see customer tables.
- A Claude API key, for drafting ([console.anthropic.com](https://console.anthropic.com)).
- Postgres (`brew install postgresql@16`), only for publishing to the local test store.

To add pieces later, put one photo per piece in `inbox/`. The dashboard tells you when it sees them.

## What's here

| Path | What it is | Ships in the plugin? |
|---|---|---|
| `plugins/commerce-os/` | Claude Code plugin: agents, skills, commands, shared policies | Yes |
| `.claude-plugin/marketplace.json` | Marketplace listing for the plugin | Marketplace only |
| `AGENTS.md` | Tool-neutral operating boundaries (Claude Code, Cursor, others) | No |
| `.cursor/rules/commerce-os.mdc` | Cursor rule pointing at the canonical policies | No |
| `apps/`, `services/`, `packages/`, `database/`, `resources/` | Runtime system (Phase 1 onward) | No |
| `docs/` | Architecture, state machine, security, decision log | No |
| `start.sh`, `inbox/` | Start command, and the folder new photos go in | No |
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

The Python services need a project environment (B-052). The test runner uses it when it exists, and
skips the few tests that need it when it doesn't:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

```bash
./run-tests.sh
```

To review image conversions (crops and framed listing images) for the samples in `discovery/raw/`:

```bash
.venv/bin/python scripts/review_images.py build
```

```bash
.venv/bin/python scripts/review_images.py serve
```

Then open http://127.0.0.1:8765/. After fixing corners on the page, re-crop with `review_images.py apply`.

To draft titles, descriptions and tags with Claude in the storefront's voice (needs `ANTHROPIC_API_KEY`
in `.env` and a brand context in `config/brand/`; about 10 cents a piece):

```bash
.venv/bin/python scripts/draft_listings.py --limit 5
```

To review, edit and approve the copy, set up the voice, and see what was learned from your edits, build and
run the local dashboard (once: `npm install` in `apps/review-dashboard`):

```bash
cd apps/review-dashboard && npm run build
```

```bash
.venv/bin/python services/local_api/server.py
```

Then open http://127.0.0.1:8770/. The first visit asks whether this is an artist site or a product site.

Maintainer rules are in [CLAUDE.md](CLAUDE.md); open work is in [BACKLOG.md](BACKLOG.md).
