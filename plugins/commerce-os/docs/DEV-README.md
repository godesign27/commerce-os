# How the Commerce OS plugin is built

## Mental model

```text
agents/     WHO does the work, and what context they load
skills/     THE CRAFT: workflow, outputs, boundaries, failure behavior
shared/     WHAT EVERYONE READS: policies and output templates
commands/   THIN pointers to a skill (no logic)
docs/       this guide
```

Craft goes in a skill, routing in an agent, reusable text in `shared/`, and a command only points at
a skill.

## The four specialists follow the pipeline

```text
intake-assets → product-intelligence → catalog-draft → review-publishing
```

Each stage's output (source manifest → product proposal → canonical draft and change sets → review
package) is the next stage's input. `commerce-lead` routes freeform requests and briefs specialists;
it is opt-in (`claude --agent commerce-os:commerce-lead`) rather than bound in `settings.json`, so the
plugin doesn't take over every session in a project that installs it (BACKLOG B-022).

## Subagents don't share context

Each specialist runs in its own context window. So every specialist re-reads the shared policies
itself, the router passes everything relevant in the dispatch message, and each specialist also works
when invoked directly.

## Every skill has the same sections

`Inputs`, `Outputs`, `Allowed tools`, `Forbidden actions`, `Workflow`, `Validation`, `Failure behavior`,
`Evidence requirements`, `Phase 0a status` (PRD §6.1). `tests/test_frontmatter.py` enforces this.

## What's deliberately absent

- **No `.mcp.json`.** A storefront database connector in the plugin would give agents direct write
  access. From Phase 1, agents reach data only through the authenticated workflow interface.
- **No `settings.json` default agent.** See above.
- **No `init` command.** Commerce OS is one deployable system, not a plugin scaffolded into many
  projects.
- **No write path.** Agents have `Read, Grep, Glob, Write` (and the router `Agent`); Write is for local
  drafts under `.commerce-os/out/` only. There is no Bash and no network tool.

## Agent tool lists are a boundary

The `tools:` frontmatter on each agent is the least-privilege list for that agent. Adding a tool,
especially `Bash` or any MCP tool, is a security change: record why in the CHANGELOG.

## Testing

From the repo root: `./run-tests.sh` (structure and consistency) and `./run-tests.sh --mutants`
(proves the suite catches each historical defect). The tests can't prove a model follows a skill;
that needs `claude plugin eval` cases (BACKLOG B-021).
