---
name: change-tenant-data
description: Adding or changing a model, migration, manager, row-level-security policy or background task that touches tenant data in SaaS Core. Use when the work involves organization_id, TenantContext, SET LOCAL, RLS policies, a new table under core.organizations or shared.*, or a Celery task that reads tenant rows.
---

# Changing tenant data

Every defect this project has shipped in tenant isolation had the same shape: a
green test over an open table. The test database connects as the owner of the
tables, and **row-level security does not apply to the owner**. So a passing
suite tells you the code runs; it does not tell you the data is separated.

Read `docs/adr/ADR-022-Identyfikatory-Tenancy-i-RLS.md` for the contract,
`docs/adr/ADR-039-Dwa-Rezimy-Izolacji-RLS-i-Tabele-Publiczne.md` for the two
regimes and `docs/adr/ADR-041-Izolacja-Tabel-Czytanych-Przed-Poznaniem-Tenanta.md`
for reads that happen before a tenant is known.

## The rules that decide the design

1. **A tenant table is any table with a foreign key to `Organization`** — not
   only a subclass of `TenantScopedModel`. The isolation test uses that rule
   because inheritance depends on somebody remembering it.
2. **Forced RLS is the default.** A table without a policy has to be declared
   in its module descriptor as `publicTables` (the renderer reads it without a
   tenant) or `platformTables` (the row belongs to the platform, not to a
   customer), and the declaration carries the reason.
3. **A read before the tenant is known goes through the door**, never through a
   widened policy: `Model.objects.using(PRE_TENANT_DB)`. Every such call site is
   listed in `apps/backend/tests/test_pre_tenant_door.py` with a reason, and the
   test fails when the list and the source disagree.
4. **The public renderer never uses the door.** A hostname resolves to an
   organization through `sites_domain`, which has no policy, so the renderer
   sets that tenant and reads from inside it. Giving the most exposed surface a
   connection that reads past policies is the thing ADR-041 exists to prevent.
5. **Writes need the tenant set first.** An identifier exists before its row
   does, so `set_local_organization_id(obj.id)` goes *before* `obj.save()` when
   creating an organization, or the `WITH CHECK` clause refuses the insert.

## Order of work

Paths first, policies second. A policy added before the reads are rewritten
does not raise — it returns an empty result, and login stops working silently.

1. `memex_pack(target: "…")`, then read the ADR the change touches.
2. Find every read and write of the table. `grep` for the model name across
   `apps/backend/src/saas_core`, including management commands, Celery tasks,
   middleware and the public views.
3. For each one, answer: *is a tenant set at this point?* If not, either set it
   from something already known (a hostname, a routing row, a command argument,
   a task payload) — always prefer this — or add it to the door list with a
   reason.
4. Write the migration: `ENABLE` + `FORCE ROW LEVEL SECURITY`, one policy on
   `organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid`,
   and a door policy naming the identity role only if step 3 needed one. Copy
   the shape from
   `apps/backend/src/saas_core/modules/core/organizations/migrations/0026_rls_membership_audit.py`.
5. Give the migration a reverse. An irreversible migration takes rollback away
   from every deployment past it — see `verify-saas-core-release`.
6. Remove the table from `KNOWN_OPEN_PRIVATE_TABLES` in
   `apps/backend/tests/test_tenant_isolation_regimes.py` if it was on the debt
   list. That list may only shrink.

## Proving it

The suite is necessary and not sufficient. Run it, then prove isolation where
policies actually apply:

```
pnpm backend:test
docker compose up --build -d backend worker scheduler
```

Then, inside the running backend, read the table three ways: with no tenant set
(expect zero rows), through the door (expect all of them), and with a tenant set
(expect that tenant's). A read that returns rows without a tenant is an open
table regardless of what the suite says.

For code that runs outside the request cycle — API-key middleware, management
commands, public views, Celery tasks — the regression that matters is *order*:
`SET LOCAL` before the first read. Assert it with `CaptureQueriesContext` and
compare indices, the way `apps/backend/tests/test_sites_grant_commands.py` does.

## Traps that have already cost a day

- **Reading before setting.** `ApiKeyTenantContextMiddleware` read the API key
  before `SET LOCAL`, so every integration request answered 401 while 352 tests
  were green. The same bug then appeared in `serve_public_media`, where every
  image on every published page answered 404.
- **Background sweeps.** A query that asks for every organization's rows at once
  returns *zero* under RLS instead of failing. Sweeps iterate organizations one
  at a time via `billing_organization_ids()` and `billing_tenant_scope()`. Index
  them by `Organization`, never by a table that only some organizations have.
- **Objects fetched through the door.** They carry `_state.db = "pre_tenant"`,
  so saving one writes through the door. Read the identifier through the door,
  then work on the ordinary connection under the tenant.
- **Global catalogue rows.** `organizations_role` allows `organization_id IS
  NULL` on read and refuses it on write, so no tenant can grant itself a global
  role. Copy that asymmetry if you add another shared catalogue.

## Done means

- `pnpm backend:test`, `pnpm backend:lint`, `pnpm backend:typecheck`,
  `pnpm backend:migrations` and `pnpm backend:imports` are green;
- isolation was demonstrated on a running stack, and the numbers are in the
  commit message or the handoff;
- the door list and the debt list match the source;
- `docs/development/HANDOFF.md` says what changed and what it means.
