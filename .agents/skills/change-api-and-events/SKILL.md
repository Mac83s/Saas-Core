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
`saas_core.config.settings.typecheck`. It starts as the first profile in
`product.json` (`agro` here, the product's own in a product repository,
ADR-049) and then installs **every module in the catalogue**: the contract,
mypy and `makemigrations --check` cover all code the repository ships, not only
what its main profile runs. A shared module a product leaves out (MedPlano
without `shared.farms`) still has core's api-client and panel typed against it;
under the main profile alone its endpoints vanished from the product's
`schema.d.ts` and mypy reported its querysets as ambiguous. The session cookie name carries the
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

## Operable by the AI assistant

Owner rule, 2026-10-01. An in-product assistant (ADR-033, memex plan
`saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy`) will set up and run a
company's account in a chat, acting as the signed-in user through the same
services the panel uses. Until its command registry exists, every new or
changed operation must already be callable that way, or it becomes debt the
assistant cannot reach:

- **No UI-only flow.** Business logic lives in the service the view calls, not
  in the view or the frontend. No wizard whose state exists only in the
  browser, no step reachable only by a button. Long work is a job with a
  status to poll.
- **Typed and described — the OpenAPI floor (ADR-076 §7).** Input and output
  are serializers with field `help_text`, enums for closed sets, units and
  bounds. Every new or changed operation has an explicit `operation_id`
  (snake_case, not drf-spectacular's automatic `api_v1_…`), `summary`,
  `description`, a required `Idempotency-Key` header on POST/PUT/PATCH/DELETE,
  and a 400 → `ProblemDetailsSerializer` when it takes data. A side-effect-free
  preview declares `extend_schema(extensions={"x-dry-run": True})` and needs no
  key; a justified exception for `idempotency-key` or `error-400` only is
  `extensions={"x-quality-exempt": {"<rule>": "<reason>"}}`. `pnpm api:check`
  runs the drift check and `pnpm api:quality`; today's debt sits in
  `packages/contracts/openapi/quality-baseline.json`, which only shrinks —
  touching an old operation's parameters, request fields or success responses
  brings it up to the floor. After fixing debt, `pnpm api:quality --write-baseline`.
- **Errors a model can act on (ADR-076 §5).** Every 400 and 422 carries
  `errors: [{field, code, message}]`, built from a `ValidationError` only: raise
  `ValidationError({"slug": ["…"]}, code="slug_taken")` or with `ErrorDetail`
  codes per field, so the code reaches the client. A domain top-level code is a
  `ValidationError` subclass with `problem_code`; another exception names its
  field with `problem_field`. Use 400 for anything the caller can fix in the
  input; 422 only for content-operations refusals. Never raise Django's
  `ValidationError` from a service an API calls — it ends as a 500.
- **Preview before write.** A configuration operation can run as a dry run —
  validate and describe the effect without saving — or its docstring says why
  it cannot (an external side effect, for example).
- **Actor in the audit (ADR-076 §6).** `record_audit` writes the principal in
  `channel` and, under `acting_context(context, via=…, ref=…, trigger=…)`, the
  `acting_via` (`assistant`, `ai_translation`), `acting_ref` and
  `acting_trigger` columns; the person stays `actor_user` ("on behalf of").
  `user` = panel without acting, `assistant` = `acting_via=assistant`,
  `integration` = `api_key`, `system` = a service principal. Acting never widens
  rights: person-only gates (`assert_person_required`) refuse it unless
  `ACTING_PERSON_GATE_ALLOWED` opens the label for that channel. Background work
  re-applies acting through `deferred_tenant_context(..., acting_*)`; a task
  contract cannot be issued under acting yet.
- **Discoverable choices.** Allowed values and defaults (presets, plan limits,
  templates) are readable from an endpoint, not hard-coded in a component.
- **Idempotent and versioned.** Mutations take an idempotency key; where two
  writers can collide, the resource carries a version and a stale write is a
  conflict, not a silent overwrite.
- **Reads that summarise.** Lists are paginated and filterable with stable ids,
  so a caller can find "the cottage named Domek 2" without loading everything.

When the command registry lands, the same increment that adds a configuration
operation also adds its registry entry (schema, risk level, preview, eval).

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
