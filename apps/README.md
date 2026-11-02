# apps/

Runtime applications.

- `review-dashboard/`: the central human review dashboard (PRD §12). A local version runs now (B-057):
  React and TypeScript, built to static files and served by `services/local_api/server.py` on
  127.0.0.1. `npm install` once, then `npm run build` (or `npm run dev` with the API running). Screens:
  Setup, Listings, listing review, Artist/Brand context, Learning. Sign-in, roles and the operational
  database arrive in Phase 2.
