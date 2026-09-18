# ADR-049: Produkty w osobnych repozytoriach, rdzeń Saas-Core aktualizowany przez merge

Status: zaakceptowana, 2026-09-18 (decyzja właściciela). Zmienia ADR-021 w
zakresie topologii repozytoriów; warstwy modułów, profile i kompozycja z
ADR-021 zostają bez zmian.

## Kontekst

ADR-021 zakładał jedno monorepo dla rdzenia, modułów shared, wertykałów i
konfiguracji produktów. Po 17.09 stanęły w nim HoofCare i MedPlano. Przegląd z
18.09 pokazał skutki: obraz MedPlano niósł kod HoofCare, rola w rdzeniu miała
na sztywno uprawnienia `hoofcare.herd.*`, migracja billingu rdzenia dawała
cechę „Korekcja racic” planom każdego produktu, a menu, routing i treści
marketingowe znały produkty z nazwy.

Właściciel chce, żeby Saas-Core był podstawą, na której stawia kolejne
aplikacje — jak SEOSiteAudit i SeoContentRank na NextJs-Boilerplate — z tą
różnicą, że rdzeń da się w produkcie aktualizować. Produkt ma być osobnym
repozytorium, które można postawić na osobnym serwerze bez kodu innych
produktów.

## Decyzja

1. **Saas-Core to rdzeń:** `core`, `shared` i produkt ogólny Business (profile
   `business`, `core-only`, `vps-dev`). Nie zna żadnego produktu z nazwy.
2. **Każdy produkt to osobne repozytorium** założone jako kopia Saas-Core, z
   Saas-Core jako zdalnym `upstream`. Aktualizacja rdzenia to `pnpm core:update`
   (merge z `upstream/main`).
3. **Produkt nie zmienia plików, które dostał z Saas-Core.** Dokłada wyłącznie
   nowe pliki: moduł wertykalny (aplikacja Django, deskryptor, migracje,
   testy), profil w `deployments/`, overlay compose, trasy i moduł frontendu,
   dokumentację w `PRODUCT.md` i `docs/product/`. Wyjątki są zamkniętą listą w
   `scripts/core-check.mjs`:
   - sloty: `product.json`, `apps/frontend/src/product/`, `README.md`,
     `.mcp.json`;
   - pliki generowane, odtwarzane po każdym merge'u: kontrakt OpenAPI, typy
     `api-client`, `apps/frontend/src/generated/deployment.ts`.
4. **`pnpm core:check`** porównuje drzewo z zapisanym commitem rdzenia
   (`.saas-core-upstream`) i zatrzymuje build, gdy zmieniony jest plik rdzenia
   spoza listy. Bez tego zasada zależy od pamięci, a w SSA i SCR to zawiodło.
5. **Punkty rozszerzeń rdzenia:**
   - deskryptor modułu: `urlPrefix` (routing), `roleGrants` (uprawnienia ról
     systemowych), `appointmentKinds` (typy wizyt), `entitlements`,
     `middleware` (montowane po middleware tenanta), `beatSchedule` (zadania
     cykliczne) — `deployment-check` odrzuca uprawnienia, middleware i taski
     spoza własnego modułu;
   - własne migracje wertykału nadają uprawnienia rolom i cechy planom — rdzeń
     nie ma migracji nazywającej produkt;
   - slot frontendu `apps/frontend/src/product/index.ts`: pozycje menu,
     tłumaczenia, treść stron marketingowych;
   - `product.json`: profile, które repo buduje, testuje i publikuje jako obrazy.
6. **Najpierw upstream.** Funkcja potrzebna więcej niż jednemu produktowi
   (czaty, asystent AI) powstaje w Saas-Core i schodzi do produktów merge'em.
   Coś, co urodziło się w produkcie i okazało się wspólne, przenosimy do
   Saas-Core, zamiast kopiować.
7. **Wdrożenie produktu** to obrazy z jego repozytorium plus compose i `.env`.
   Serwer produktu nie dostaje kodu źródłowego ani innych produktów.

## Konsekwencje

- Zmiana w kształcie punktów rozszerzeń (deskryptor, slot frontendu,
  `product.json`) jest zmianą łamiącą dla produktów i wymaga wpisu w
  dokumentacji wydania rdzenia.
- Zależność npm lub Python potrzebna produktowi wchodzi przez Saas-Core,
  bo manifesty pakietów są plikami rdzenia. Świadomy koszt: zależność trafia do
  wszystkich produktów.
- Szablony stron i bloki stron należą do rdzenia (kontrakt z SeoContentRank i
  renderer stron klientów). Produkt, który potrzebuje własnego, dodaje go w
  Saas-Core.
- Pliki generowane konfliktują przy merge'u; rozwiązaniem jest wygenerowanie
  ich od nowa (`pnpm api:schema`, `pnpm deployment:render`), nie ręczna edycja.
- Dług „OpenAPI per profil” znika: każde repo generuje kontrakt swojego profilu.
- Migracje `organizations.0035` i `billing.0023` stają się w rdzeniu pustymi
  węzłami grafu; ich treść przechodzi do `vertical.hoofcare`. Cechę
  `medical.enabled` usuwamy z seedów billingu rdzenia; nie wraca, dopóki nic nią
  nie jest bramkowane. Istniejące bazy deweloperskie wyczyszczono jednorazowo
  18.09 (HANDOFF).

## Alternatywy odrzucone

- **Jedno monorepo z produktami w katalogach (ADR-021).** Kto ma repo, widzi
  wszystkie produkty; produkt nie może zostać na starszym rdzeniu.
- **Rdzeń jako paczki pip/npm.** Next.js wymaga pliku trasy w aplikacji, więc
  każdy produkt powtarzałby kilkadziesiąt tras rdzenia i dopisywał każdą nową.
- **Kopia szablonu bez upstream (jak SSA/SCR).** Poprawki rdzenia rozjeżdżają
  się między kopiami i nie da się ich już zaktualizować.

## Relacje

ADR-021 (zmieniony: topologia repozytoriów), ADR-048 (strony marketingowe —
treść produktu przez slot frontendu).
