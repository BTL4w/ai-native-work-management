# End-to-End AI-Native Work Management Platform

The repository is being built one focused vertical step at a time. It currently
contains the Phase 1 frontend foundation only; authentication, backend, database
and Docker are not implemented yet.

## Frontend development

Prerequisites:

- Node.js 24 LTS
- Corepack

Run the frontend:

```bash
cd frontend
corepack pnpm@10 install --frozen-lockfile
corepack pnpm@10 dev
```

Frontend quality checks:

```bash
cd frontend
corepack pnpm@10 lint
corepack pnpm@10 typecheck
corepack pnpm@10 test
corepack pnpm@10 build
```

The root-level `make` commands documented in `PLAN.md` will be added in a later
tooling-focused step after the corresponding backend and local infrastructure
exist.
