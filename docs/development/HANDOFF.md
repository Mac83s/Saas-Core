# Handoff następnej sesji

**Aktualizacja:** 2026-08-11

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj lokalną falę W6 z
`Plan/Wdrozenie/07-W6-Sites-Content-i-Media.md`. W6.0-W6.3 są ukończone
lokalnie. Następnym pakietem jest **W6.4 — Media**. Nie wracaj teraz do
wdrożenia VPS: brakujące bramki stagingowe W2 i W3 są świadomie odłożone do
osobnej sesji z dostępem do hosta, domeny, GHCR i GitHub Environment.

W6.3 dodało kanoniczne schema bloków i design tokens w
`packages/contracts/site-blocks`, walidację tych samych artefaktów w backendzie,
registry oraz bezpieczny renderer w `@saas-core/site-blocks`. `core.hero` ma
liniową migrację v1 -> v2 i fixture wstecznej zgodności. Chroniony endpoint
preview przyjmuje jawny `PageVersion`; publiczny interfejs renderera przyjmuje
wyłącznie dokument publikacji z ID oraz hashem snapshotu, a historyczne drafty
nie są dostępne przez publiczne API.

Ostatnie commity punktu bazowego przed W6.3:

- `68be486 chore(memex): refresh project integration`;
- `bfbb4c7 feat(sites): add localized SEO metadata` — W6.2;
- `606284e feat(sites): implement versioned content drafts` — W6.1;
- `145295e feat(sites): establish W6 foundations` — W6.0.

## Pierwszy cel wykonawczy

Zrealizuj W6.4 jako jeden spójny, lokalnie zweryfikowany przyrost:

1. Utwórz moduł `shared.media`, adapter S3 i tenantowy `MediaAsset` z RLS od
   pierwszej migracji.
2. Wydawaj krótkotrwały signed upload z losowym kluczem zawierającym ID
   organizacji; oryginalna nazwa pozostaje wyłącznie znormalizowaną metadaną.
3. Waliduj rozmiar, deklarowany MIME, magic bytes i rzeczywiste dekodowanie;
   blokuj HTML, JavaScript i SVG oraz usuwaj EXIF.
4. Dodaj allowlistowane warianty obrazów i stany
   `pending -> uploaded -> scanning -> ready` albo `rejected`.
5. Dopuszczaj do publikacji wyłącznie assety `ready`, a `storage.bytes` naliczaj
   idempotentnie dokładnie raz.
6. Zaimplementuj tombstone i asynchroniczne usunięcie obiektu dopiero bez
   referencji z publikacji.
7. Przetestuj cross-tenant/RLS, fałszywy MIME, nadmierny rozmiar, złośliwą
   nazwę, malware, quota oraz ponowienie callbacku.

Kontrakty obowiązkowe przed implementacją: ADR-027, ADR-022, ADR-025,
`docs/architecture/module-contract.md` oraz `docs/architecture/api-and-events.md`.
Lokalny SeaweedFS `4.41` jest zdrowym, uwierzytelnionym emulatorem S3 wyłącznie
dla Compose local; staging i production nadal wymagają zewnętrznego S3.

## Walidacja W6.3

- 209 testów backendu;
- pełny Mypy: 0 błędów w 129 plikach;
- Ruff, import-linter i brak dryfu migracji;
- testy oraz typecheck całego workspace;
- testy kontraktów i snapshot deterministycznego renderera;
- aktualny OpenAPI i wygenerowany klient TypeScript;
- poprawne profile `core-only` i `medplano`;
- produkcyjny build Next.js oraz obrazy backend/frontend na Node.js 24;
- zdrowy Compose, runtime smoke i podpisany smoke object storage.

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
