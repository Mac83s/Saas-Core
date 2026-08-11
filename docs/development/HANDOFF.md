# Handoff następnej sesji

**Aktualizacja:** 2026-08-11

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj lokalną falę W6 z
`Plan/Wdrozenie/07-W6-Sites-Content-i-Media.md`. W6.0-W6.3 są ukończone
lokalnie, a **W6.4 — Media** jest w toku po ukończeniu przyrostu W6.4.1. Nie wracaj teraz do
wdrożenia VPS: brakujące bramki stagingowe W2 i W3 są świadomie odłożone do
osobnej sesji z dostępem do hosta, domeny, GHCR i GitHub Environment.

W6.3 dodało kanoniczne schema bloków i design tokens w
`packages/contracts/site-blocks`, walidację tych samych artefaktów w backendzie,
registry oraz bezpieczny renderer w `@saas-core/site-blocks`. `core.hero` ma
liniową migrację v1 -> v2 i fixture wstecznej zgodności. Chroniony endpoint
preview przyjmuje jawny `PageVersion`; publiczny interfejs renderera przyjmuje
wyłącznie dokument publikacji z ID oraz hashem snapshotu, a historyczne drafty
nie są dostępne przez publiczne API.

W6.4.1 dodało `shared.media`, tenantowy `MediaAsset`, politykę PostgreSQL
`ENABLE/FORCE ROW LEVEL SECURITY`, uprawnienia `media.read`/`media.manage`,
entitlement `storage.enabled` i idempotentną rezerwację `storage.bytes`.
`POST /api/v1/media/uploads/` wydaje krótko ważny signed PUT dla losowego klucza
z prefiksem organizacji; oryginalna, znormalizowana nazwa nie trafia do klucza,
URL ani audytu. `GET /api/v1/media/` jest tenantowo stronicowane. OpenAPI i klient
TypeScript są aktualne.

Test RLS używa prawdziwego PostgreSQL i tymczasowej roli
`NOSUPERUSER NOBYPASSRLS`: brak `SET LOCAL` i obcy tenant zwracają zero, własny
tenant widzi rekord, a cross-tenant `INSERT` jest odrzucany. Wykryty kontraktowy
dług: lokalny Compose nadal łączy backend rolą `saas_core`, która ma
`rolsuper=true` i `rolbypassrls=true`. Nie uznawaj RLS za operacyjnie domknięte,
dopóki runtime/worker nie użyją osobnej roli aplikacyjnej, a `migrate` roli
migracyjnej.

Ostatnie commity punktu bazowego przed W6.3:

- `68be486 chore(memex): refresh project integration`;
- `bfbb4c7 feat(sites): add localized SEO metadata` — W6.2;
- `606284e feat(sites): implement versioned content drafts` — W6.1;
- `145295e feat(sites): establish W6 foundations` — W6.0.

## Następny cel wykonawczy

Kontynuuj W6.4 następującymi spójnymi przyrostami:

1. Rozdziel w Compose rolę aplikacyjną PostgreSQL `NOBYPASSRLS` od roli
   migracyjnej i dodaj smoke, który zatrzymuje runtime przy superuser/BYPASSRLS.
2. Dodaj idempotentny callback ukończenia uploadu i adapter odczytu/head/delete
   obiektu; task otrzymuje podpisany tenant task contract.
3. Waliduj rzeczywisty rozmiar, magic bytes i dekodowanie;
   blokuj HTML, JavaScript i SVG oraz usuwaj EXIF.
4. Dodaj allowlistowane warianty obrazów i stany
   `pending -> uploaded -> scanning -> ready` albo `rejected`.
5. Dopuszczaj do publikacji wyłącznie assety `ready`, a `storage.bytes` naliczaj
   idempotentnie dokładnie raz.
6. Zaimplementuj tombstone i asynchroniczne usunięcie obiektu dopiero bez
   referencji z publikacji.
7. Rozszerz testy o fałszywy MIME, malware, warianty, rozliczenie quota dokładnie
   raz i ponowienie callbacku. Cross-tenant RLS, nadmierny rozmiar, złośliwa
   nazwa, quota przy rezerwacji i ponowienie inicjowania uploadu są już pokryte.

Kontrakty obowiązkowe przed implementacją: ADR-027, ADR-022, ADR-025,
`docs/architecture/module-contract.md` oraz `docs/architecture/api-and-events.md`.
Lokalny SeaweedFS `4.41` jest zdrowym, uwierzytelnionym emulatorem S3 wyłącznie
dla Compose local; staging i production nadal wymagają zewnętrznego S3.

## Walidacja W6.4.1

- 216 testów backendu;
- pełny Mypy: 0 błędów w 142 plikach;
- Ruff, import-linter i brak dryfu migracji;
- testy oraz typecheck całego workspace;
- aktualny OpenAPI i wygenerowany klient TypeScript bez driftu;
- poprawne profile `core-only` i `medplano`;
- 21 celowanych testów media + tenant context, w tym bezpośredni SQL RLS.

Lokalny `/usr/bin/node` ma wersję 22 i emituje ostrzeżenie `engines`; właściwy
runtime Node.js 24 został potwierdzony buildem obrazu frontendowego. Przy pracy
poza Dockerem wybierz Node.js 24.

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
