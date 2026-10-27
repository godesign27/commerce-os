# resources/

Versioned runtime resources. Every draft records the versions it used. Populated in Phase 0b after
discovery; empty now.

- `providers/`: database provider types a storefront or the operational database can use
  (see [docs/storefront-connections.md](../docs/storefront-connections.md)).
- `catalog-profiles/`: product-data shapes of storefront applications.
- `product-types/`: Commerce OS's shared product types and their option rules, e.g. which types can
  have colors (B-030).
- `image-recipes/`: versioned derivative recipes (B-006). `framed-oak-white-mat` is the framed listing
  image (B-050): artwork, white bottom-weighted mat, thin oak frame and soft shadow, measured from the
  owner's example, on a canvas shaped like the artwork (portrait, square or landscape). Frame textures
  are local assets in `.commerce-os/assets/`, never committed. `crop-perspective` finds the artwork in a
  photo and straightens it (B-053); it is consequential, so a reviewer accepts every crop.
- Per-storefront categories, tags and tier types are not here: they hold real IDs, so they live in
  gitignored `config/mappings/<storefront-id>.local.json`.

The evidence policy is not here: it lives in `plugins/commerce-os/shared/evidence-policy.md` so the
installed plugin can read it.
