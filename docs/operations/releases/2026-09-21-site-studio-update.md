# Site Studio update — VPS release, 2026-09-21

The owner authorized container deployment and database migrations on this VPS.
All three profiles now run the merged update, including section decoration,
separators, catalogue configuration and the narrow approved-photo import permission.

## Images and configuration

| Profile | Image source | Main at deployment | Backend image ID (prefix) | Frontend image ID (prefix) | Pending migrations |
| --- | --- | --- | --- | --- | --- |
| vps-dev | `b3448ec` | `2e8f177` | `921734e91151` | `bc120698d9ae` | 0 |
| hoofcare | `3cee006` | `991ebc7` | `c16df0fa225b` | `770868fe59e7` | 0 |
| medplano | `20d0f19` | `60b34e4` | `fe82eff78fe4` | `37b4012728e4` | 0 |

The image sources are exact Git archives. Subsequent commits only connect the
API backend to its existing private scanner network and synchronize this Compose
change into products; `apps`, `packages`, `deployments` and `scripts` match the
image sources. This report adds documentation only. Backend, worker and scheduler
use the same image per product. Frontend builds used Node 24.17.0.

Full image IDs, profile hashes, migration heads and composition are recorded in
`/root/Saas-Core/.runtime/releases/20260921-update-b3448ec/*-live-release.json`.
These local image IDs are not registry-published digests.

## Release checks

- [x] Six product-scoped images built successfully; each profile booted.
- [x] All three PostgreSQL snapshots restored into an isolated PostgreSQL 18;
  all pending migrations applied there, with zero pending and no irreversible
  migration. Live databases then migrated through Sites `0031`.
- [x] Fresh consistent database dumps taken after stopping application writers,
  before live migration. Previous backend/frontend image pairs tagged for rollback.
- [x] API, frontend, worker and scheduler healthy; `check_database_role` passes
  on all backend processes. Scanner returns `CLEAN` from API and worker in each profile.
- [x] Public HTTPS `/`, `/en`, `/login`, `/healthz`, API liveness/readiness return 200.
  The frontend health check enforces the backend/frontend profile-hash match.
- [x] Real browser login and actual API calls, without Sites mocks: create site,
  import approved photos through storage and ClamAV, save and reload decorations,
  translate and publish. Three profiles passed; no page errors or horizontal
  overflow at 1440 and 390 px.
- [x] Actual editor opens the decoration inspector with saved tint/drift values;
  its decorated preview stays motionless. Desktop/mobile screenshots retained.
- [x] A temporary `content:draft` key imports the latest `core.profile` v2 recipe
  (201), replays idempotently (200), leaves `published=false`, and gets 403 on
  arbitrary media upload. Tested separately in every product.
- [x] Published HTML, sitemap and an actual PNG return 200 through each app's
  Caddy with the published hostname. HTML includes ornament motion and its pause
  control. This uses internal HTTP routing to avoid issuing disposable TLS certs.
- [x] Live RLS under `saas_core_app` (neither superuser nor BYPASSRLS): organization
  counts without tenant / through the named door / with the synthetic tenant:
  **0/2/1** (vps-dev), **0/7/1** (hoofcare), **0/1/1** (medplano).
- [x] HoofCare's public dictionary exposes `korekcja-racic`, labels PL/EN.
- [x] All three synthetic accounts, tenants and API credential routes removed;
  all six stored objects deleted, with zero pending objects on their erasure receipts.
- [x] Eighteen infrastructure containers, including existing databases, storage,
  scanners and the shared edge/frontend, retain their original IDs and start times.

The MedPlano photo-import request completed in 30.96 seconds (201), slightly
beyond the verification client's initial 30-second timeout. Repeating its same
idempotency key returned 200 in 97 ms; remaining verification passed. No duplicate
page or image was created by the retry.

Pre-release code gates are recorded in the handoffs and
`/root/update-gates-20260921/`: core backend 899 PASS / 2 SKIP, HoofCare 938 PASS,
MedPlano 866 PASS / 35 SKIP; HoofCare frontend 430 PASS. Skips reflect profile
composition. Static, type, migration drift and API-contract checks passed.

## Recovery and remaining scope

Private backups, restore logs, image metadata, release rows and browser evidence:
`/root/Saas-Core/.runtime/releases/20260921-update-b3448ec/` (root-only directory).
Rollback image tags: `<project>-backend:rollback-20260921-update` and
`<project>-frontend:rollback-20260921-update`. Restore both application images
as a pair, including worker/scheduler from the backend image. Database restore
requires a separate decision about writes since the backup; an image rollback
does not automatically restore or reverse the database.

Existing plan versions remain immutable. Runtime inspection found one older
plan snapshot in Saas-Core and three in HoofCare with unchanged prices/limits;
their `profiles.enabled` remains false. HoofCare also has a snapshot without a
plan version. MedPlano has no pre-existing tenant snapshot. Moving existing
subscriptions to new plan versions is pending the owner's separate answer;
no real tenant entitlement was altered for this verification.

**Subsequent owner-approved activation, 2026-09-21:** the four older plan
snapshots and three subscription mappings have now been advanced with unchanged
prices, quotas and lifecycle dates. See the separate
[plan inventory and activation report](2026-09-21-plan-access.md).
The paragraph above describes the state at container deployment.

The four previous infrastructure follow-ups remain open: separate staging and
rollback through GHCR, external alert receipt, encrypted offsite backup/restore,
and the custom-domain/On-Demand TLS drill. This local release does not establish
those gates or actual SMTP delivery. The broader Site Studio roadmap remains open.
