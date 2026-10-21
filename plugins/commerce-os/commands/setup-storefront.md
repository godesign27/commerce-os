---
description: Add or change a storefront (or the operational database) by choosing its database provider and catalog profile
argument-hint: "[storefront id | operational]"
---

# /setup-storefront

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Connectors: [CONNECTORS.md](../shared/CONNECTORS.md)

## Usage

    /setup-storefront $ARGUMENTS

Examples:
- `/setup-storefront storefront-c`
- `/setup-storefront operational`

## What happens

Follow the **storefront-setup** skill in `${CLAUDE_PLUGIN_ROOT}/skills/storefront-setup/SKILL.md` end to
end. Do not summarise or shortcut it. It writes a credential-free entry to
`config/storefronts.local.json` and never connects to a database.
