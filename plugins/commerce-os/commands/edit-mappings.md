---
description: Add, edit or retire a storefront's categories, tags and tier types, or Commerce OS's product types
argument-hint: "<storefront-id | product-types>"
---

# /edit-mappings

> Shared context: [COMMERCE-CONTEXT.md](../shared/COMMERCE-CONTEXT.md) · Connectors: [CONNECTORS.md](../shared/CONNECTORS.md)

## Usage

    /edit-mappings $ARGUMENTS

Examples:
- `/edit-mappings storefront-b`
- `/edit-mappings product-types`

## What happens

Follow the **catalog-mappings** skill in `${CLAUDE_PLUGIN_ROOT}/skills/catalog-mappings/SKILL.md` end to
end. Do not summarise or shortcut it. It edits local, versioned files only; nothing is created in a
storefront.
