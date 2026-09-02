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
| [ADR-027](ADR-027-Sites-Tresc-Media-i-Publikacja.md) | sites, treść, media i atomowa publikacja | Accepted |
| [ADR-028](ADR-028-Domeny-DNS-TLS-i-Publiczny-Routing.md) | domeny, DNS, TLS i publiczny routing | Accepted |
| [ADR-029](ADR-029-Notifications-Integrations-i-Support.md) | powiadomienia, integracje i bezpieczny support | Accepted |
| [ADR-030](ADR-030-Booking-Czas-Blokady-i-Self-Service.md) | Booking: czas, blokady i self-service | Accepted |
| [ADR-031](ADR-031-Panel-Klienta-i-Wizualny-Site-Studio.md) | panel klienta i wizualny Site Studio | Accepted |
| [ADR-032](ADR-032-Oferta-Plany-i-Customer-Billing.md) | oferta, plany i Customer Billing | Accepted |
| [ADR-033](ADR-033-Asystent-AI-Narzedzia-Zgody-i-Glos.md) | asystent AI: narzędzia, zgody i głos | Accepted |
| [ADR-034](ADR-034-Simulator-Billingu-i-Odroczenie-Stripe.md) | simulator billingowy i odroczenie Stripe | Accepted |
| [ADR-035](ADR-035-Publikacja-Systemowa-i-SeoContentRank.md) | publikacja systemowa i integracja z SeoContentRank | Accepted |
| [ADR-036](ADR-036-Tozsamosc-Profil-Publiczny-i-Konto-Klienta.md) | tożsamość: `User`, `Organization`, `PublicProfile` i konto klienta | Accepted |
| [ADR-037](ADR-037-Appointment-Commerce-i-Stripe-Connect.md) | Appointment Commerce i Stripe Connect | Deferred |
| [ADR-038](ADR-038-Repozytoryjne-Agent-Skills.md) | repozytoryjne Agent Skills: cykl życia i granice autonomii | Accepted |
| [ADR-039](ADR-039-Dwa-Rezimy-Izolacji-RLS-i-Tabele-Publiczne.md) | dwa reżimy izolacji: RLS domyślnie, tabele publiczne z deklaracji | Accepted |

Każda zmiana decyzji tworzy nowy ADR. Całkowicie zastąpiony dokument otrzymuje
status `Superseded`; przy częściowym zastąpieniu nowy ADR wskazuje dokładny
fragment, a wcześniejszy pozostaje obowiązujący w pozostałym zakresie. Nie
przepisujemy historii.
