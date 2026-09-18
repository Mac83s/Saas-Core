---
name: change-api-and-events
description: Adding or changing an HTTP endpoint, a serializer, an error response, the generated OpenAPI contract, the TypeScript client, or a domain event and its outbox delivery in SaaS Core. Use when touching views.py, serializers.py, urls.py, packages/contracts/openapi, packages/api-client or an event schema.
---

# API and events

The contract is generated, never written by hand. Read
`docs/architecture/api-and-events.md` and
`docs/adr/ADR-024-API-OpenAPI-i-Zdarzenia.md`.

## The loop

```
# change the view or serializer, then:
pnpm api:schema     # regenerates packages/contracts/openapi/v1.yaml
pnpm api:client     # regenerates packages/api-client/src/schema.d.ts
pnpm api:check      # fails if either is stale
```

`pnpm api:check` is a gate. Never hand-edit the yaml or the `.d.ts`; both are in
`.prettierignore` so a formatter cannot fight the generator.

**Generation and the drift check use one settings module:**
`saas_core.config.settings.typecheck`, which composes the first profile in
`product.json` — `business` here, the product's own in a product repository
(ADR-049). It has to be the profile that composes the product's vertical, or
the vertical's endpoints never reach the contract or the generated client. The session cookie name carries the
deployment, so the two must match — they drifted apart on 2026-09-17 and CI
would have failed on the next push. One contract still serves every product;
splitting it per profile is recorded debt (HANDOFF). If you add a settings value
that reaches the schema, expect the same class of problem.

## Writing an endpoint

- the view belongs to its module, mounted from `MODULE_ROUTES` in
  `apps/backend/src/saas_core/config/urls.py`, so a deployment without the
  module answers nothing rather than 500;
- authorization happens in the service, not in the view. The view validates
  shape; `authorize(PERMISSION)` decides who may act, and the same service is
  reachable from a management command or a task;
- errors are Problem Details with a stable `code`. The frontend branches on the
  code, so renaming one is a contract change;
- the tenant comes from `TenantContext`, never from the request body. An id in
  the payload may point at a resource; it never establishes who is asking;
- a mutation carries audit, idempotency and a transaction; if it emits an event
  it goes through the outbox in the same transaction.

## Events

- a schema per event under the module that owns it, declared in the module
  descriptor's `eventSchemas`;
- versioned by name (`billing.subscription.changed.v1`); a breaking change is a
  new version, not an edited one;
- delivery is at-least-once, so consumers are idempotent;
- the outbox row is written in the transaction that caused it — never after
  commit, never from a signal.

## Traps

- **A new field in a serializer changes the published contract.** Run the loop
  above in the same commit, or CI fails on drift for whoever comes next.
- **`inline_serializer` names end up in the client.** Pick a name you can live
  with; renaming it is a client-visible change.
- **Endpoints exempt from tenant middleware** (the organization switcher,
  invitation acceptance) read before a tenant exists — see `change-tenant-data`
  before touching them.
- **The frontend uses the generated client only.** No hand-written fetch types,
  no duplicated response shapes.

## Done means

```
pnpm api:check
pnpm backend:test
pnpm --filter @saas-core/frontend test
```

plus a test for the new path, including its refusal case: a permission denied
and a tenant that may not see the resource.
