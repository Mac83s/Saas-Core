---
name: verify-saas-core-release
description: Accepting an increment or a release candidate in SaaS Core — which gates to run, what a green suite does not prove, which evidence to record and whether the change can be rolled back. Use before handing work over, before a release, or when deciding that something is finished.
---

# Verifying an increment

Read `docs/architecture/testing-strategy.md` for the levels and the pull-request
gate, and `docs/operations/deployment-matrix.md` for the release row.

The rule this whole skill exists for: **a green suite proves the code runs, not
that the system is correct.** Every defect this project shipped passed a full
suite first. Know which questions the suite cannot answer, and answer those
separately.

## The gates, in the order that fails fastest

```
pnpm format:check
pnpm lint                 # profiles, artifacts, ai:validate, ESLint
pnpm backend:lint
pnpm backend:typecheck
pnpm backend:imports      # module layer contract
pnpm backend:migrations   # no drift
pnpm backend:test
pnpm test                 # every workspace, frontend components included
pnpm typecheck
pnpm api:check            # OpenAPI and the TypeScript client
```

`pnpm quality` runs the whole chain when you want one command. Report the
numbers, not the word "green": how many tests, how many files typechecked, how
many contracts kept.

## What the suite cannot tell you

1. **Tenant isolation.** The test database connects as the owner of the tables
   and row-level security does not apply to owners. Prove isolation on a running
   stack — no tenant set, through the door, with a tenant set — and put the three
   numbers in the commit message. See `change-tenant-data`.
2. **Anything behind Caddy.** The public renderer, media, feeds and the TLS
   decision are only exercised through a real host header. `pnpm runtime:smoke`
   and `pnpm runtime:smoke:identity` cover the basics; a published page, its
   sitemap and one image are worth fetching by hand when Sites changed.
3. **Whether the composition is real.** A profile is a claim until an image is
   built and booted. For a change to modules or deployment, build the affected
   profiles and record what each composed — apps, routes, scheduled jobs.
4. **Whether a contract read from disk is in the image.** It resolves in a
   checkout and fails in a container. Boot the container.
5. **Whether the frontend and backend are the same product.** Their profile
   hashes must match; `/healthz` says so.

## The authorization matrix

Every protected use case needs all six rows from
`docs/architecture/testing-strategy.md` §2: right tenant with and without the
permission, with and without the entitlement, a foreign tenant (404 or empty),
no context at all (a controlled error and **zero** domain queries), and a
suspended organization. Mutations additionally need CSRF, the idempotency key,
the optimistic lock and the audit row.

A use case that only has its happy path is not covered, however many assertions
the happy path has.

## Can it be rolled back

Three conditions, all answerable before the deploy:

1. every migration in the image is reversible —
   `apps/backend/tests/test_deployment_release.py` guards this, and the release
   row reports it;
2. the migrations were expand/contract, because rolling the application back
   does not roll the schema back;
3. backend and frontend go back together, or the frontend answers 503.

Capture the row with `manage.py deployment_release --image backend=sha256:…`,
and store it next to the release manifest described in
`docs/operations/staging.md`.

## Evidence

An increment is finished when somebody who was not here can tell what changed
and why it is believed to work:

- `docs/development/HANDOFF.md` gets a section: what changed, what it means in
  practice, and what was **left open** — naming the residue is part of the work,
  not an admission;
- a memex worklog with observable results in `changes` and commands in
  `evidence`; a decision recorded separately if one was made;
- the plan checklist updated. A gate is marked done only with a test or an
  unambiguous artifact. If part of the scope stayed open, say which part and
  why, in the same bullet.

## Traps

- **Marking a gate done because the code exists.** The gate asks for proof.
- **"All tests pass" as a report.** It hides which tests, and whether the new
  path has any.
- **Skipping the negative case.** A check nobody has seen fail is a check nobody
  knows works — break it on purpose once, then restore it.
- **Leaving the working tree dirty.** The session ends with everything committed
  in exact paths, and `git push` only when the owner asks.
