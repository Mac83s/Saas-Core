# Handoff następnej sesji

**Aktualizacja:** 2026-08-11

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj lokalną falę W6 z
`Plan/Wdrozenie/07-W6-Sites-Content-i-Media.md`. W6.0, W6.1 i W6.2 są
ukończone i zatwierdzone commitami. Następnym pakietem jest **W6.3 - motyw i
renderer**. Nie wracaj teraz do wdrożenia VPS: brakujące bramki stagingowe W2 i
W3 są świadomie odłożone do osobnej sesji z dostępem do hosta, domeny, GHCR i
GitHub Environment.

Ostatnie commity punktu bazowego:

- `68be486 chore(memex): refresh project integration`;
- `bfbb4c7 feat(sites): add localized SEO metadata` - W6.2;
- `606284e feat(sites): implement versioned content drafts` - W6.1;
- `145295e feat(sites): establish W6 foundations` - W6.0.

## Pierwszy cel wykonawczy

Zrealizuj W6.3 jako jeden spójny, lokalnie zweryfikowany przyrost:

1. Dodaj kanoniczne JSON Schema bloków i design tokens w
   `packages/contracts/site-blocks`.
2. Rozwiń `@saas-core/site-blocks` o registry, typy, walidatory oraz liniowe
   migratory `vN -> vN+1` z fixture zgodności wstecznej.
3. Zapewnij walidację tego samego kontraktu przez backend bez tworzenia
   równoległego schematu.
4. Dodaj allowlistowany, deterministyczny renderer. Dane nie mogą sterować
   HTML-em, JavaScriptem, CSS-em ani dynamicznym importem.
5. Oddziel chroniony preview jawnej wersji draftu od publicznego renderowania
   wyłącznie bieżącej publikacji.
6. Zachowaj kierunek zależności: Shared nie importuje Vertical; rozszerzenia
   przechodzą przez publiczny manifest/registry.
7. Dodaj testy nieznanego typu i wersji, złośliwych payloadów, migracji starego
   schematu i deterministyczności snapshotu. Dopiero po dowodach zaznacz W6.3 w
   checkliście.

Kontrakty obowiązkowe przed implementacją: ADR-027, ADR-020 oraz
`docs/architecture/module-contract.md`. `packages/site-blocks` istnieje, lecz
obecnie eksportuje jedynie `SITE_BLOCK_SCHEMA_VERSION = 1`.

## Walidacja i środowisko

Wymagane są Node.js 24, pnpm 11, `uv` i Docker Desktop/WSL. Na końcu uruchom co
najmniej testy oraz typecheck `@saas-core/site-blocks`, testy dotkniętych
modułów, `pnpm api:check`, `pnpm deployment:check:all` i pełne kontrole adekwatne
do zakresu. Jeśli zmienia się backend, wymagane są także Ruff, Mypy,
import-linter, kontrola migracji i testy backendu.

W chwili tworzenia handoffu lokalny Compose działał; backend, frontend, Caddy,
worker, scheduler, PostgreSQL, Redis i object storage były healthy. Nie zakładaj
jednak, że ten stan przetrwa restart - rozpocznij od `git status --short` oraz
`docker compose ps`, a przed zmianami pobierz projektowy `memex_pack`.

## Niezmienne ograniczenia

- tenantowe operacje wymagają jawnego `TenantContext`;
- API osobno egzekwuje permission i entitlement;
- mutacje uwzględniają audyt, idempotencję i transakcję/outbox;
- typy API pochodzą z OpenAPI;
- UI korzysta wyłącznie z publicznego `@saas-core/ui`; shadcn/ui v4 z Base UI
  pozostaje systemem bazowym;
- nie zapisuj sekretów ani danych osobowych w repozytorium, fixture'ach i logach;
- stage'uj wyłącznie jawne ścieżki i commituj każdy spójny przyrost.

Po ukończeniu pakietu zaktualizuj checklistę W6, Memex (proces, task/worklog i
dowody), uruchom `index`, `build` oraz `doctor`, a następnie wykonaj commit.
