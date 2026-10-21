---
description: Prepare the human review package for a submission — blockers, evidence, images, previews
argument-hint: "<submission id>"
---

# /review

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Workflow: [WORKFLOW.md](../shared/WORKFLOW.md)

## Usage

    /review $ARGUMENTS

Examples:
- `/review hat-two-colors`

## What happens

Follow the **review-packaging** skill in `${CLAUDE_PLUGIN_ROOT}/skills/review-packaging/SKILL.md` end to
end. Do not summarise or shortcut it. The package informs a human decision; it never records one.
