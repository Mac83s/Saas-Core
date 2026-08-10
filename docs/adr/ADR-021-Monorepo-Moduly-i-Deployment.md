# ADR-021 — monorepo, moduły i profile deploymentu

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core

## Kontekst

Jedno repozytorium ma budować kilka osobno wdrażanych produktów. Core nie może
znać Medical ani Beauty, a profil produktu musi jednoznacznie aktywować te same
moduły w backendzie i frontendzie.

## Decyzja

### Struktura

```text
apps/
  backend/
    config/
    modules/core/
    modules/shared/
    modules/verticals/
  frontend/
packages/
  ui/
  api-client/
  contracts/
  site-blocks/
deployments/
  medplano/
  core-only/
infra/
docs/
```

Python i TypeScript pozostają w jednym repozytorium, lecz mają osobne lockfile.
Root zawiera jawne skrypty orkiestrujące, bez mieszania środowisk zależności.

### Identyfikator i kontrakt modułu

Każdy moduł ma stabilny identyfikator w formie `warstwa.nazwa`, np.
`core.identity`, `shared.booking`, `vertical.medical`. Moduł deklaruje:

- wersję kontraktu i zależności;
- Django apps, migracje i endpointy;
- permissions, features i quotas;
- publikowane i obsługiwane zdarzenia;
- zadania cykliczne i politykę retencji;
- frontend routes, navigation, widgets, site blocks i namespaces i18n;
- health contributors i wymagane ustawienia.

Backendowy descriptor jest typowaną dataclass/protocol. Frontendowy manifest
jest typem TypeScript. Oba są walidowane przeciwko wspólnemu JSON Schema z
`packages/contracts`.

### Kierunki zależności

```text
config/deployment composition
  -> vertical
      -> shared
          -> core

core -X-> shared
core -X-> vertical
shared -X-> vertical
vertical A -X-> vertical B
```

Zależności między modułami przechodzą przez publiczne `api`, zdarzenia albo
jawne ports/protocols. Import prywatnego modelu lub serwisu innego modułu jest
błędem architektury. Reguły kontrolują import-linter dla Python i ESLint
boundaries dla TypeScript.

### Profil deploymentu

`deployments/<slug>/deployment.json` jest wspólnym, niesekretnym manifestem:

- product id, nazwa i branding;
- aktywne moduły;
- locale i locale domyślne;
- hosty systemowe;
- klucze planów, bloków i integracji;
- identyfikatory polityk retencji.

JSON Schema jest źródłem walidacji w Python i TypeScript. Sekrety nigdy nie są
częścią profilu. Build otrzymuje `DEPLOYMENT=medplano`, waliduje graf modułów i
przerywa przy braku zależności, duplikacie lub rozjeździe kontraktu.

Katalog wszystkich modułów jest składany w warstwie `config`, poza Core.
Wyłączenie modułu usuwa jego route/menu/handler z aktywnego registry; kod może
pozostać w obrazie pierwszej wersji, ale nie jest wykonywany ani eksponowany.

## Konsekwencje

- nie powstają forki produktu ani warunki `if product == ...` w Core;
- graf zależności jest deterministyczny i testowalny przed startem aplikacji;
- jeden JSON manifest jest wspólną prawdą dla obu stosów;
- fizyczne usuwanie nieaktywnych modułów z obrazu jest odłożone do czasu, gdy
  rozmiar lub granice licencyjne uzasadnią dodatkowy build graph.

## Alternatywy odrzucone

- osobne repozytorium na produkt — prowadzi do forków i driftu;
- dynamiczne pluginy klientów — zwiększają powierzchnię wykonania obcego kodu;
- autodiscovery wszystkich pakietów — utrudnia przewidywanie aktywnego systemu;
- ręczne, niezależne listy modułów backend/frontend — łatwy drift kontraktu.

