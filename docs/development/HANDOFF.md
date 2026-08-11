# Handoff następnej sesji

**Aktualizacja:** 2026-08-11

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj lokalną falę W6 z
`Plan/Wdrozenie/07-W6-Sites-Content-i-Media.md`. W6.0-W6.3 są ukończone
lokalnie, a **W6.4 — Media** jest w toku po ukończeniu przyrostów W6.4.1 i
W6.4.2. Nie wracaj teraz do wdrożenia VPS: brakujące bramki stagingowe W2 i W3
są świadomie odłożone do osobnej sesji z dostępem do hosta, domeny, GHCR i
GitHub Environment.

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

W6.4.2 rozdzieliło role PostgreSQL bez resetu istniejącego wolumenu. Idempotentny
`database-bootstrap` utrzymuje `saas_core_app` jako
`NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`, przyznaje DML
do istniejących tabel i ustawia default privileges dla kolejnych migracji.
Backend, worker, scheduler i celery-exporter otrzymują wyłącznie sekret roli
aplikacyjnej; `migrate` korzysta z osobnego sekretu roli migracyjnej. Start oraz
runtime smoke wywołują `check_database_role` i kończą się błędem dla roli
uprzywilejowanej. Rollback stagingu nie może wrócić przez tę granicę
bezpieczeństwa.

Test RLS używa prawdziwego PostgreSQL i tymczasowej roli
`NOSUPERUSER NOBYPASSRLS`: brak `SET LOCAL` i obcy tenant zwracają zero, własny
tenant widzi rekord, a cross-tenant `INSERT` jest odrzucany. Ten sam kontrakt
został potwierdzony na uruchomionym Compose dla backendu, workera i schedulera;
negatywny smoke odrzucił rolę migracyjną z `SUPERUSER/BYPASSRLS`.

Ostatnie commity punktu bazowego przed W6.3:

- `68be486 chore(memex): refresh project integration`;
- `bfbb4c7 feat(sites): add localized SEO metadata` — W6.2;
- `606284e feat(sites): implement versioned content drafts` — W6.1;
- `145295e feat(sites): establish W6 foundations` — W6.0.

## Następny cel wykonawczy

Kontynuuj W6.4 następującymi spójnymi przyrostami:

1. Dodaj idempotentny callback ukończenia uploadu i adapter odczytu/head/delete
   obiektu; task otrzymuje podpisany tenant task contract.
2. Waliduj rzeczywisty rozmiar, magic bytes i dekodowanie;
   blokuj HTML, JavaScript i SVG oraz usuwaj EXIF.
3. Dodaj allowlistowane warianty obrazów i stany
   `pending -> uploaded -> scanning -> ready` albo `rejected`.
4. Dopuszczaj do publikacji wyłącznie assety `ready`, a `storage.bytes` naliczaj
   idempotentnie dokładnie raz.
5. Zaimplementuj tombstone i asynchroniczne usunięcie obiektu dopiero bez
   referencji z publikacji.
6. Rozszerz testy o fałszywy MIME, malware, warianty, rozliczenie quota dokładnie
   raz i ponowienie callbacku. Cross-tenant RLS, nadmierny rozmiar, złośliwa
   nazwa, quota przy rezerwacji i ponowienie inicjowania uploadu są już pokryte.

Kontrakty obowiązkowe przed implementacją: ADR-027, ADR-022, ADR-025,
`docs/architecture/module-contract.md` oraz `docs/architecture/api-and-events.md`.
Lokalny SeaweedFS `4.41` jest zdrowym, uwierzytelnionym emulatorem S3 wyłącznie
dla Compose local; staging i production nadal wymagają zewnętrznego S3.

## Walidacja W6.4.2

- 222 testy backendu;
- pełny Mypy: 0 błędów w 145 plikach;
- Ruff, import-linter i brak dryfu migracji;
- testy oraz typecheck całego workspace;
- aktualny OpenAPI i wygenerowany klient TypeScript bez driftu;
- poprawne profile `core-only` i `medplano`;
- 21 celowanych testów media + tenant context, w tym bezpośredni SQL RLS.
- dwukrotny bootstrap roli na istniejącym wolumenie i migracje bez resetu danych;
- zdrowy Compose oraz runtime smoke roli dla backendu, workera i schedulera;
- negatywny smoke odrzucający rolę migracyjną z `SUPERUSER/BYPASSRLS`.

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
