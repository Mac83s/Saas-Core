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
| [model-port.md](model-port.md) | port modeli AI: typy żądania i odpowiedzi, błędy, dopuszczenie i sufity, telemetria (ADR-068) |
| [translation-sources.md](translation-sources.md) | protokół źródeł tłumaczeń: fragmenty, pochodzenie, rejestr i obowiązki adaptera (ADR-069, ADR-070) |
| [product-public-site.md](product-public-site.md) | publiczne strony produktu na jego hoście: tabela adresów per język, stare adresy (308/410), sitemapa, słowa, zarezerwowane segmenty (ADR-080) |
| [product-content-read.md](product-content-read.md) | treść własna platformy na stronach produktu: odczyt opublikowanych wpisów po kluczu typu, języku i slugu (części adresu, nie ścieżki), listy, pozycje, wykaz do sitemapy, „przeniesione”, `/media` na hoście platformy, treść wpisu z bloków rdzenia (ADR-079 pkt 29–33) |
| [`packages/contracts/content-operations/`](../../packages/contracts/content-operations/) | kontrakt zmian treści dla SeoContentRank (W9.6.0) |

Prozę kontraktu z SeoContentRank — słownik, podział odpowiedzialności i
politykę wersjonowania — współredagujemy w
`SeoContentRank/Plan/saas-core-connector-plan.md`; tutaj żyje jego
wykonywalna połowa: schematy i fixture.

Wspólny kierunek trzech usług i granice pierwszego pilota opisuje
[Integracja SEO — I0 v1](seo-ecosystem-integration.md), na podstawie ADR-043.
Dokument jawnie wskazuje wymagania, które nie mają jeszcze implementacji;
nie zastępuje wykonywalnych schematów zmian treści.

Źródłem prawdy dla wersji technologii pozostaje
[ADR-019](../adr/ADR-019-Baseline-Technologiczny.md), a dla systemu UI
[ADR-020](../adr/ADR-020-Frontend-i-System-UI.md).
