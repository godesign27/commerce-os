---
description: Inspect a product submission folder — readiness, file inventory, validation findings
argument-hint: "<submission folder path or Drive folder ID>"
---

# /intake

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Connectors: [CONNECTORS.md](../shared/CONNECTORS.md)

## Usage

    /intake $ARGUMENTS

Examples:
- `/intake ./submissions/hat-two-colors`

## What happens

Follow the **drive-intake** skill in `${CLAUDE_PLUGIN_ROOT}/skills/drive-intake/SKILL.md` end to end, then
the **asset-validation** skill in `${CLAUDE_PLUGIN_ROOT}/skills/asset-validation/SKILL.md`. Do not
summarise or shortcut them. Read-only on the submission; output goes to `.commerce-os/out/`.
