# Handoff następnej sesji

**Aktualizacja:** 2026-08-11

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj lokalną falę W6 z
`Plan/Wdrozenie/07-W6-Sites-Content-i-Media.md`. W6.0-W6.3 są ukończone
lokalnie, a **W6.4 — Media** jest w toku po ukończeniu przyrostów W6.4.1,
W6.4.2, W6.4.3a, W6.4.3b i W6.4.3c. Nie wracaj teraz do wdrożenia VPS: brakujące bramki stagingowe W2 i W3
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

W6.4.3a dodało chroniony CSRF i tenantowo izolowany
`POST /api/v1/media/uploads/{asset_id}/complete/`. Callback nie przyjmuje
metadanych obiektu od klienta: adapter S3 używa prywatnego endpointu do `HEAD`
i zapisuje stan `uploaded` wyłącznie przy zgodnym rozmiarze oraz MIME. Brak
obiektu, wygaśnięcie i rozbieżność zwracają stabilne Problem Details bez zmiany
`pending`. Powtórzenie po sukcesie nie odpytuje storage ponownie i nie duplikuje
audytu. OpenAPI oraz klient TypeScript są aktualne.

W6.4.3b dodało pełny fail-closed pipeline obrazu. Callback przedłuża rezerwację
quota i po commicie emituje Celery task z podpisanym tenant context oraz
`causation_id` związanym z ID assetu. Worker odczytuje obiekt z prywatnego S3 z
limitem, skanuje surowe bajty przez `clamd INSTREAM`, sprawdza magic bytes i
rzeczywiste dekodowanie Pillow, odrzuca animacje/HTML/JS/SVG i bomby
dekompresyjne, a następnie re-enkoduje obraz bez EXIF. Powstają deterministyczne
warianty WebP `thumbnail` i `preview`.

Sanityzowany oryginał dostaje osobny klucz `processed`; dopiero atomowy commit
bazy przełącza `MediaAsset` na ten klucz. Osobne retryowalne zadanie usuwa
zapamiętany klucz źródłowy po commicie, dzięki czemu retry nigdy nie interpretuje
przetworzonego obiektu jako surowego uploadu. `storage.bytes` jest dopasowywane
do faktycznej sumy sanityzowanego oryginału i wariantów, a następnie commitowane
idempotentnie dokładnie raz. Odrzucenie usuwa obiekty i zwalnia rezerwację.

Compose uruchamia oficjalny ClamAV `1.5.3-debian13-slim` wyłącznie w prywatnej
sieci i zatrzymuje worker, jeśli `check_malware_scanner` nie przejdzie. Staging
wymaga teraz jawnego zewnętrznego S3; lokalny SeaweedFS jest w override wyłączony
profilem. Deploy czeka na zdrowy ClamAV, a rollback nie może wrócić przed tę
granicę storage.

W6.4.3c dodało opcjonalny rejestr referencji zasobów w warstwie Core bez
bezpośredniego importu Sites -> Media. `shared.media` rejestruje typ
`shared.media.asset` i przechowuje tenantowy `MediaReference` z `FORCE RLS`.
Zapis `PageVersion` przyjmuje maksymalnie 100 unikalnych `media_asset_ids`,
wiąże je z hashem/idempotencją draftu i w tej samej transakcji akceptuje
wyłącznie assety `ready`, bez tombstone i z bieżącej organizacji. Błąd wycofuje
wersję, bloki, referencje oraz audyt. GET draftu i jawny preview zwracają
utrwaloną listę referencji.

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

Domknij W6.4 następującymi spójnymi przyrostami:

1. Dodaj atomową publikację snapshotu, ponownie waliduj assety `ready` i utrwal
   append-only referencje `sites.publication` przed przełączeniem
   `Site.current_publication`.
2. Zaimplementuj tombstone i asynchroniczne usunięcie oryginału oraz wariantów
   dopiero bez referencji z publikacji.
3. Dodaj testy odmowy publikacji assetu nie-`ready`, blokady delete przy
   referencji i idempotentnego ponowienia cleanup/tombstone.

Kontrakty obowiązkowe przed implementacją: ADR-027, ADR-022, ADR-025,
`docs/architecture/module-contract.md` oraz `docs/architecture/api-and-events.md`.
Lokalny SeaweedFS `4.41` jest zdrowym, uwierzytelnionym emulatorem S3 wyłącznie
dla Compose local; staging i production nadal wymagają zewnętrznego S3.

## Walidacja W6.4.3c

- celowane 32 testy integracyjne Sites/Media, w tym transakcyjna odmowa dla
  `pending`, tombstone i obcego tenanta oraz bezpośrednie RLS referencji;
- pełna bramka backendu: 249 testów;
- pełny Mypy: 0 błędów w 156 plikach;
- Ruff, import-linter i brak dryfu migracji;
- import-linter potwierdził kierunek dla 156 plików i 206 zależności;
- OpenAPI i wygenerowany klient TypeScript są aktualne;
- lokalny ClamAV jest zdrowy, a rzeczywisty INSTREAM zwrócił `clean|infected`
  dla bezpiecznego payloadu i standardowego testu EICAR;
- migracja `media.0002` zastosowana lokalnie, backend/worker/scheduler zdrowe;
- runtime smoke potwierdził role RLS, fail-closed skaner, frontend i API;
- lokalny i stagingowy Compose przechodzą `config --quiet`, a staging nie
  zawiera usługi SeaweedFS i używa wyłącznie jawnego zewnętrznego endpointu S3.

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
