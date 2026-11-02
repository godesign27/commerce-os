---
description: Change a listing's title, descriptions, tags or keywords in your own words, without opening the dashboard
argument-hint: "<listing> <what to change>"
---

# /listing-edit

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md)

## Usage

    /listing-edit $ARGUMENTS

Examples:
- `/listing-edit wolf title "The Wolf's Gaze"`
- `/listing-edit wolf use this collector description instead: …`
- `/listing-edit wolf pick the second title`
- `/listing-edit wolf go back to the drafted short description`

## What happens

Follow the **listing-edit** skill in `${CLAUDE_PLUGIN_ROOT}/skills/listing-edit/SKILL.md` end to end.
Do not summarise or shortcut it. It saves your words exactly as given, runs the checks, and never
approves, unlocks, redrafts or publishes.
