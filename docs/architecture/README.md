# Kontrakty architektoniczne

Ten katalog opisuje reguły, które muszą być egzekwowane przez kod i CI. ADR-y
wyjaśniają podjęte decyzje, a poniższe dokumenty definiują ich wykonywalny
kontrakt.

| Kontrakt | Zakres |
| --- | --- |
| [module-contract.md](module-contract.md) | manifesty modułów, zależności i aktywacja |
| [deployment-profile.md](deployment-profile.md) | profil produktu, walidacja i sekrety |
| [data-model-and-tenancy.md](data-model-and-tenancy.md) | encje bazowe, tenant context i RLS |
| [auth-and-tenant-context.md](auth-and-tenant-context.md) | sesja, CSRF i zmiana organizacji |
| [api-and-events.md](api-and-events.md) | REST, błędy, OpenAPI, outbox i webhooki |
| [billing-lifecycle.md](billing-lifecycle.md) | stany planu, przejścia i dowód na każde z nich |
| [testing-strategy.md](testing-strategy.md) | poziomy testów oraz bramki CI |
| [`packages/contracts/content-operations/`](../../packages/contracts/content-operations/) | kontrakt zmian treści dla SeoContentRank (W9.6.0) |

Prozę kontraktu z SeoContentRank — słownik, podział odpowiedzialności i
politykę wersjonowania — współredagujemy w
`SeoContentRank/Plan/saas-core-connector-plan.md`; tutaj żyje jego
wykonywalna połowa: schematy i fixture.

Wspólny kierunek trzech usług i granice pierwszego pilota opisuje
[Integracja SEO — I0 v1](seo-ecosystem-integration.md), na podstawie ADR-042.
Dokument jawnie wskazuje wymagania, które nie mają jeszcze implementacji;
nie zastępuje wykonywalnych schematów zmian treści.

Źródłem prawdy dla wersji technologii pozostaje
[ADR-019](../adr/ADR-019-Baseline-Technologiczny.md), a dla systemu UI
[ADR-020](../adr/ADR-020-Frontend-i-System-UI.md).
