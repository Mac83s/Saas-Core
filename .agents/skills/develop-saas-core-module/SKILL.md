---
name: develop-saas-core-module
description: Adding a module to SaaS Core, changing what a module declares, or changing how a deployment profile composes the product. Use when touching packages/contracts/modules, INSTALLED_APPS, the URL table, the beat schedule, module middleware, or the layer boundaries between core, shared, vertical and configuration.
---

# Modules and composition

One repository builds several products. A module is a unit of that composition,
and `deployments/<profile>/deployment.json` decides which units a given product
is made of. Nothing about that is advisory: the profile produces
`INSTALLED_APPS`, the middleware list, the URL table and the scheduled work.

Read `docs/architecture/module-contract.md` and
`docs/architecture/deployment-profile.md`. The layer rule —
configuration → vertical → shared → core, never outwards — is enforced by
import-linter and by the composition itself.

## What a module is

- a Django app under `apps/backend/src/saas_core/modules/<layer>/<name>/`;
- a descriptor at `packages/contracts/modules/<layer>.<name>.json` naming that
  app, its dependencies, its URL prefix, permissions, entitlements, event
  schemas, and its public and platform tables;
- optionally frontend routes, navigation entries and translation namespaces.

**The catalogue describes code that exists.** A descriptor for an app nobody has
written passes schema and graph checks and fails at boot; `pnpm deployment:check`
verifies `apps.py` is on disk and `apps/backend/tests/test_module_catalog.py`
verifies both directions.

## Adding or changing a module

1. `memex_pack(target: "…")`, then read the contract documents above.
2. Write the Django app first, descriptor second. A descriptor without code is
   a lie the validator will believe.
3. Declare dependencies explicitly. **They are not closed silently**: a profile
   that names `shared.billing` without `core.organizations` is refused rather
   than quietly completed, because the module list of a product is a decision
   somebody reviewed.
4. Add the module to the profiles that should have it, in
   `deployments/<profile>/deployment.json`.
5. Wire what the module owns, each keyed by module id:
   - routes in `apps/backend/src/saas_core/config/urls.py` (`MODULE_ROUTES`),
     built **inside a function** so a disabled module's views are never
     imported;
   - middleware in `_MODULE_MIDDLEWARE` in
     `apps/backend/src/saas_core/config/settings/base.py`;
   - scheduled work in `_MODULE_BEAT_SCHEDULE` in the same file, under the
     module whose code the task calls — not the module that motivated it.
6. Regenerate the artifact: `pnpm deployment:artifact`. It is committed, so the
   change shows up as a diff in every profile that uses the module.
7. Tables: read `change-tenant-data` before adding any model with an
   organization.

## Traps

- **A module not in the profile must register nothing.** No URL prefix, no beat
  entry, no middleware. `apps/backend/tests/test_deployment_composition.py`
  asks both profiles what they compose without booting a second Django.
- **Do not add a second list next to the composition.** `INSTALLED_APPS` *is*
  `django_apps_for(ACTIVE_MODULES, catalog)`; a hardcoded module beside it is
  what made "two products" untrue for months.
- **Settings that validate a module's configuration must ask whether the module
  is there.** A deployment without Billing demanded a full set of Stripe
  credentials and could not boot until the check was made conditional.
- **Importing across layers inside a function is still an import.** import-linter
  catches deferred imports too.
- **A public or platform table belongs to the module that declares it.** The
  validator refuses a descriptor declaring somebody else's table.

## Done means

```
pnpm deployment:check:all
pnpm backend:imports
pnpm backend:test
pnpm ai:validate
```

plus: the artifact is regenerated and committed, `core-only` still composes only
its three apps, and `docs/development/HANDOFF.md` records what the new module is
for.
