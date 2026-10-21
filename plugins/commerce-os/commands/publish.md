---
description: Request server-side publication of a change set a human has already approved
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# /publish

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../shared/WORKFLOW.md)

## Usage

    /publish $ARGUMENTS

Examples:
- `/publish hat-two-colors storefront-a`

## What happens

Follow the **publishing** skill in `${CLAUDE_PLUGIN_ROOT}/skills/publishing/SKILL.md` in **request mode**
end to end. Do not summarise or shortcut it.

This command cannot approve and cannot write. It only asks the workflow service to queue a change set
that already holds a valid human approval; the server re-checks that approval (Gate 4) before any
write. Running this command is not approval, and a queued job is not a published product.
