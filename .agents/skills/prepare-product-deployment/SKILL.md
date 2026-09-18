---
name: prepare-product-deployment
description: Creating or changing a deployment profile, building and tagging product images, recording a release row, or deciding whether a rollback is possible. Use when touching deployments/, the module artifact and profile hash, Dockerfiles, the images workflow, compose resources, or the separation between two products on one host.
---

# Preparing a product deployment

A deployment is a profile plus everything that has to be separate so two
products can stand next to each other. Read
`docs/architecture/deployment-profile.md` for the profile itself and
`docs/operations/deployment-matrix.md` for images, the release row and the
resource list.

## A new profile

A product with its own vertical is its own repository (ADR-049): its profile is
a new directory in that repository, never in Saas-Core. Saas-Core carries only
`business`, `core-only` and `vps-dev`.

1. `deployments/<name>/deployment.json` — id equal to the directory name,
   product metadata, the module list (dependencies named explicitly), and
   `billing.planKeys` with exactly three keys if the profile includes
   `shared.billing`.
2. `pnpm deployment:check --profile <name>` until it passes.
3. `pnpm deployment:artifact` — writes `deployments/<name>/module-artifact.json`
   and commits it. The hash is computed by that one generator; nothing else
   recomputes it.
4. Nothing to register: `deployment:check --all` and `deployment:artifact`
   discover every `deployments/<name>/deployment.json`. Which profiles the
   repository builds into images, tests and generates the OpenAPI contract for
   is `product.json` — the first entry is the main one. Do not add profile names
   to workflows or scripts; a product repository may not edit them.
5. A profile with no code yet is parked under `deployments/_planned/`, outside
   the pattern the validator accepts. Do not let it pretend to be valid.

## Images belong to products

Backend and frontend carry a profile, so one commit produces **one image per
profile**, tagged `sha-<commit>-<profile>`. Caddy and Redis carry none.

Building the backend without `DEPLOYMENT` produces a `core-only` image, which is
what CI did until 2026-09-05 — published next to a `business` frontend. That
pair no longer starts: both images carry the artifact and the profile hash, the
backend refuses when the artifact does not describe what it composed, and the
frontend's `/healthz` answers 503 when its hash differs from the backend's.

When you change how images are built, prove it the same way: run the image and
read what it composed, rather than trusting the build log.

## The release row

```
docker compose exec backend python manage.py deployment_release \
  --image backend=sha256:… --image frontend=sha256:…
```

The process does not know its own digest, so the deployer supplies it. Record
the row next to the release manifest on the host (`docs/operations/staging.md`).

**Rollback is decided before it is needed**, on three conditions:

1. `rollback.irreversible` is empty — guarded by
   `apps/backend/tests/test_deployment_release.py`;
2. migrations went expand/contract, because rolling the application back does
   not roll the schema back;
3. backend and frontend go back **together** — mismatched hashes mean a 503 on
   the frontend rather than a menu leading to 404s.

## A product on a server

The server gets images built from the product's repository, its compose overlay
(`compose.<product>.yaml`) and `.env.<product>`; runtime state and secrets live
in `.runtime-<product>/` next to that repository. No source code of the core or
of another product goes there.

## Two products on one host

The boundary is the Compose project (`COMPOSE_PROJECT_NAME`, which wins over
`name:` in the file): separate containers, network and volumes, therefore a
separate PostgreSQL, Redis and object storage. Beyond that, the sixteen
resources in `docs/operations/deployment-matrix.md` §4 each have a variable, and
`apps/backend/tests/test_deployment_isolation.py` compares that table with
`compose.yaml` in both directions.

If you parameterise a new per-deployment resource, add the row. If you document
a row, make sure compose actually honours it.

## Traps

- **Secrets never enter a profile.** The validator refuses any key that looks
  like one; secrets live in `${SAAS_CORE_SECRETS_DIR}` and reach the process as
  `*_FILE`.
- **The contracts a process reads at runtime must be in the image.** Every such
  directory needs a `COPY` in the Dockerfile *and* an `ENV` — in both stages,
  because the builder runs `collectstatic` with the same settings.
- **Do not regenerate the artifact by hand.** Prettier must not reformat it
  either; that is why it is in `.prettierignore`.

## Done means

```
pnpm deployment:check:all
pnpm backend:test
pnpm ai:validate
```

plus an image built for each affected profile and booted at least once, with
what it composed written into the commit message or the handoff.
