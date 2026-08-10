# Architecture Decision Records

ADR-y są trwałym zapisem decyzji technicznych SaaS Core. Numeracja kontynuuje
rejestr z `Plan/SaaS-Core-06-Rejestr-Decyzji.md`.

## Statusy

- `Accepted` — obowiązuje w implementacji;
- `Proposed` — wymaga decyzji przed wskazaną falą;
- `Deferred` — świadomie odłożone z warunkiem ponownego rozpatrzenia;
- `Superseded` — zastąpione przez nowszy ADR.

## Indeks

| ADR | Decyzja | Status |
| --- | --- | --- |
| [ADR-019](ADR-019-Baseline-Technologiczny.md) | baseline technologiczny | Accepted |
| [ADR-020](ADR-020-Frontend-i-System-UI.md) | Next.js, shadcn/ui i system UI | Accepted |
| [ADR-021](ADR-021-Monorepo-Moduly-i-Deployment.md) | monorepo, moduły i profile deploymentu | Accepted |
| [ADR-022](ADR-022-Identyfikatory-Tenancy-i-RLS.md) | UUIDv7, tenant context i zakres RLS | Accepted |
| [ADR-023](ADR-023-Uwierzytelnianie-i-Sesje.md) | same-origin Django sessions | Accepted |
| [ADR-024](ADR-024-API-OpenAPI-i-Zdarzenia.md) | kontrakt API, klient i zdarzenia | Accepted |
| [ADR-025](ADR-025-Runtime-Staging-Sekrety-i-Odtwarzanie.md) | runtime staging, sekrety i odtwarzanie | Accepted |
| [ADR-026](ADR-026-Billing-Entitlements-i-Trial.md) | billing, entitlementy i trial pilota | Accepted |

Każda zmiana decyzji tworzy nowy ADR i oznacza poprzedni jako `Superseded`.
Nie przepisujemy historii.
