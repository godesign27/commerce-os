# CLAUDE.md — maintaining Commerce OS

**Read [AGENTS.md](AGENTS.md) first.** It holds the operating boundaries; this file adds only the
maintainer workflow. Cursor also loads this file, so keep it free of anything Claude-specific that
would mislead another tool.

## Repo shape

- `plugins/commerce-os/`: the Claude Code plugin. This is the only part that ships when someone
  installs the plugin. Five layers: `agents/` (routing and context), `skills/` (the craft),
  `shared/` (policies and templates everyone reads), `commands/` (thin pointers to a skill), `docs/`.
- `apps/`, `services/`, `packages/`, `database/`, `resources/`: the runtime system (Phase 1 onward).
  Never shipped inside the plugin.
- `tests/`, `run-tests.sh`, `BACKLOG.md`, this file: maintainer-only.

Craft goes in a skill, routing in an agent, reusable text in `shared/`, and a command only points at a
skill. Workflow steps in an agent file, or routing in a `SKILL.md`, is in the wrong layer.

## Rules

1. **Run `./run-tests.sh` after every change**, including every fix. The pre-commit hook enforces it
   (`./tests/install-hooks.sh` once per clone).
2. **Bump the version for anything that ships** under `plugins/commerce-os/`: both
   `.claude-plugin/marketplace.json` and `plugins/commerce-os/.claude-plugin/plugin.json`, plus a new
   top entry in `plugins/commerce-os/CHANGELOG.md`. Plugin updates are detected by version number.
3. **Keep `BACKLOG.md` current.** Permanent `B-nnn` IDs; never delete or reuse one.
4. **Re-read the source.** Never trust a summary of the PRD, a schema, or a previous session.
5. **No real data in shipped or committed files.** No real storefront names, customer data, product
   images or schema dumps outside `discovery/raw/` (gitignored). Genericize before promoting content.
6. **A rule copied across files is copied everywhere.** Markdown has no includes. `grep` before you
   change one, and change them all. `tests/test_consistency.py` pins the important ones.
7. **When a review finds a defect, add a mutant** to `tests/mutants.py` that reintroduces it.
8. **Commit to a branch, not `main`**, and only when asked.

## Validate the plugin

```bash
./run-tests.sh
claude plugin validate .
claude plugin validate plugins/commerce-os
```

Load it for a session without installing: `claude --plugin-dir plugins/commerce-os`.
