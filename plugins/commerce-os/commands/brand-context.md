---
description: Set up or change a storefront's voice for listing copy, record what an artwork means, or review what was learned from your edits
argument-hint: "<storefront id> [interview | meaning | lessons | import <file>]"
---

# /brand-context

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md)

## Usage

    /brand-context $ARGUMENTS

Examples:
- `/brand-context storefront-a interview`
- `/brand-context storefront-a meaning` (then say what the piece or series means)
- `/brand-context storefront-a lessons`

## What happens

Follow the **brand-context** skill in `${CLAUDE_PLUGIN_ROOT}/skills/brand-context/SKILL.md` end to end.
Do not summarise or shortcut it. It writes only `config/brand/`, archives the previous version, and
never approves a lesson or meaning for you.
