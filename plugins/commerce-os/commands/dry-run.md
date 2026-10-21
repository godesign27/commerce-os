---
description: Show exactly what publishing one storefront's change set would do, with no side effects
argument-hint: "<submission id> <storefront-a|storefront-b>"
---

# /dry-run

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../shared/WORKFLOW.md)

## Usage

    /dry-run $ARGUMENTS

Examples:
- `/dry-run hat-two-colors storefront-a`

## What happens

Follow the **publishing** skill in `${CLAUDE_PLUGIN_ROOT}/skills/publishing/SKILL.md` in **dry-run mode**
only. Do not summarise or shortcut it. A dry run never writes anywhere except `.commerce-os/out/`.
