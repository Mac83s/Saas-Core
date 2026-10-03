---
name: develop-organization-types
description: Declaring or changing the kinds of organization a product has (a trimming company and a farm, a clinic and a patient's household) and what each kind may use — its modules, plans, sign-up, panel menu and later its roles. Use when touching organizationTypes in a deployment profile, Organization.organization_type, the module gate, per-type plans or the onboarding screen.
---

# Organization types

A product declares its kinds of organization; core enforces what each kind may
use. The decision and its reasons are ADR-050
(`docs/adr/ADR-050-Typy-Organizacji-Definiowane-Przez-Produkt.md`); the stages
are `Plan/Wdrozenie/15-Typy-Organizacji-i-Rejestr-Gospodarstw.md`.

## Where each part lives

| Part | Place |
|---|---|
| declaration | `organizationTypes` in `deployments/<profile>/deployment.json`, schema `packages/contracts/deployment.schema.json` |
| validation and the default `business` type | `effectiveOrganizationTypes` and `assertOrganizationTypes` in `packages/contracts/scripts/deployment-check.mjs` |
| one resolved list for backend and frontend | the artifact (`deployments/<profile>/module-artifact.json`) and the public profile (`apps/frontend/src/generated/deployment.ts`) |
| backend settings | `ORGANIZATION_TYPES`, `DEFAULT_ORGANIZATION_TYPE`, read from the artifact by `organization_types_from` in `apps/backend/src/saas_core/config/composition.py` |
| the security boundary | `apps/backend/src/saas_core/config/module_gate.py`: a shared or vertical module outside the organization's type answers 404 `module_not_available` |
| plans per type | `apps/backend/src/saas_core/modules/shared/billing/plan_offer.py` |
| system roles per type | `apps/backend/src/saas_core/modules/core/organizations/role_catalog.py` (written after every `migrate` by `post_migrate`) |
| an organization's own roles | `apps/backend/src/saas_core/modules/core/organizations/custom_roles.py`, API `current/roles/`, page `apps/frontend/src/modules/core/organizations/roles-panel.tsx` |
| service templates | `serviceTemplates` of a type, offered in `apps/frontend/src/modules/shared/booking/booking-settings.tsx`; the visit kind is checked against the type's modules in booking's `_assert_appointment_kind_available` (called from `setup.save_service` and `create_catalog_item`) |
| frontend | `apps/frontend/src/lib/organization-types.ts` (`modulesFor`, `selfSignupTypes`), onboarding at `apps/frontend/src/app/[locale]/(auth)/onboarding/page.tsx` |

## Adding or changing a type in a product

1. Edit `organizationTypes` in the product's `deployment.json`. The first type
   is the default. `modules` lists shared and vertical modules only — core
   belongs to every organization. With `shared.billing`, give `planKeys`
   (1–3, all from `billing.planKeys`).
2. `pnpm deployment:check --all`, then `pnpm deployment:artifact` and
   `pnpm deployment:render`. The artifact hash changes: backend and frontend
   images must be rebuilt together, or the frontend's `/healthz` reports the
   mismatch.
3. Product menu entries that belong to one kind carry `organizationTypes` in
   `apps/frontend/src/product/index.ts`. Words that differ by kind („Wizytówka
   gospodarstwa” where a company has „Wizytówka firmy”) go to the slot
   `apps/frontend/src/product/organization-messages.ts`, keyed by type and
   locale (UX-080): only the panel of that type gets them. A panel server page
   reads its words through `getPanelTranslations` (`#lib/panel-messages`), not
   `getTranslations`, or its title keeps the generic word.
4. Roles: give the type `roles` with `owner` (every `core.organizations`
   permission) and `admin`; mark the ones a limited manager may hand out with
   `limited`. Label the product's own permissions in its messages
   (`Permissions.<key with dots as underscores>`) or the role editor shows raw
   keys. Run `migrate` (the sync) and check the roles and moved memberships.
5. Prove the gate on the running stack: an organization of the type without a
   module gets 404 from that module's API, and one with it gets through.

## Traps

- **`deployment.modules` in the frontend is the product, not the organization.**
  Gate panel pages and menu with `modulesFor(organization.organization_type)`.
  A page that checks only the deployment shows a farm a screen whose API
  answers 404.
- **The menu is not the boundary.** Anything a type may not use must be
  refused by the API — the module gate does it by URL prefix of the module's
  routes, so a new module's routes are covered only if they are registered
  through `MODULE_ROUTES` or the descriptor's `urlPrefix`.
- **Backfilling organizations under forced RLS.** `organizations_organization`
  has forced RLS, so an `UPDATE` in a migration sees no rows and succeeds. The
  type column was filled through `ADD COLUMN ... DEFAULT` (migration `0036`);
  do the same for any new column every organization needs.
- **A type the catalogue no longer has** reaches no optional module at all.
  Renaming a type key means migrating the organizations that carry it.
- **System roles are written by `migrate`, not by the app.** The app role cannot
  write global roles (RLS) and the immutability trigger guards them; the sync
  runs under the owner of the tables and lifts the trigger inside its own
  transaction. A role dropped from the catalogue is logged, never deleted —
  memberships may still point at it.
- **A core migration that grants a permission reaches only core's global
  roles.** A type with its own `roles` gets exactly what the profile lists, so a
  new permission for the owner or admin (booking 0011's
  `booking.staff.performance.read`) must also be added to every product
  profile's typed roles — HoofCare's company owner got 403 on Wydajność until
  it was. HoofCare's `test_hoofcare_facts` compares its types' owner and admin
  with core's and fails at `core:update`.
- **A role anybody ever held is not deleted.** Memberships and invitations keep
  their role for history (`PROTECT`); own roles in use answer 409.
- **Plans are offered per type.** `settings.BILLING_PLAN_KEYS` is still every
  plan of the profile (provisioning commands use it); what a customer may buy
  comes from `plan_keys_for_organization`.

## Operable by the AI assistant

The type catalogue (labels, modules, plans, service templates) reaches the panel
only through the build-time `apps/frontend/src/generated/deployment.ts`; no
endpoint lists it, so the assistant cannot choose a type or a service template.
When you touch it, expose what you add through the API as well
(`change-api-and-events` § "Operable by the AI assistant").

## Done means

```
pnpm deployment:check:all
pnpm backend:test
pnpm --filter @saas-core/frontend test
pnpm ai:validate
```

plus the gate demonstrated on a running stack, with the numbers in the commit
message or the handoff.
