---
name: develop-saas-core-module
description: Adding a module to SaaS Core, changing what a module declares, or changing how a deployment profile composes the product. Use when touching packages/contracts/modules, INSTALLED_APPS, the URL table, the beat schedule, module middleware, or the layer boundaries between core, shared, vertical and configuration.
---

# Modules and composition

Saas-Core builds the core products (`business`, `core-only`); every product
with its own vertical is a separate repository copied from Saas-Core, which
takes the core by merge and never edits a core file (ADR-049, `pnpm
core:check`). A module is a unit of composition, and
`deployments/<profile>/deployment.json` decides which units a given product is
made of. Nothing about that is advisory: the profile produces
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
5. **A vertical (in a product repository) wires itself from its descriptor** —
   it may not edit core files:
   - routes: `backend.urlPrefix` + `djangoApp` (its `urls.py`), mounted by
     `config/urls.py` for any active vertical;
   - system-role permissions: `backend.roleGrants`, only permissions it
     declares; its own migration grants them in the database;
   - plan features: `backend.entitlements`; its own migration publishes a new
     plan version with the feature (plan versions are immutable);
   - visit kinds: `backend.appointmentKinds`;
   - panel menu, messages, marketing copy: `apps/frontend/src/product/index.ts`;
     its pages are new files under `apps/frontend/src/app/`.
   - middleware: `backend.middleware`, mounted after the tenant middleware;
   - scheduled work: `backend.beatSchedule` (`{name: {task, schedule}}`);
     `deployment-check` refuses middleware or tasks outside the module's app.
   Page templates and site blocks stay in core (they are part of the
   SeoContentRank contract): a product that needs one adds it to Saas-Core.
   Any other missing extension point is added to Saas-Core, never as a line in
   a core file of the product's copy.
6. A core or shared module wires what it owns, each keyed by module id:
   - routes in `apps/backend/src/saas_core/config/urls.py` (`MODULE_ROUTES`),
     built **inside a function** so a disabled module's views are never
     imported;
   - middleware in `_MODULE_MIDDLEWARE` in
     `apps/backend/src/saas_core/config/settings/base.py`;
   - scheduled work in `_MODULE_BEAT_SCHEDULE` in the same file, under the
     module whose code the task calls — not the module that motivated it.
7. Regenerate the artifact: `pnpm deployment:artifact`. It is committed, so the
   change shows up as a diff in every profile that uses the module.
8. Tables: read `change-tenant-data` before adding any model with an
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
