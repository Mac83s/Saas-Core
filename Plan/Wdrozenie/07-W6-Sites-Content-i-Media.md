# W6 — Sites, Content i Media

**Status:** in progress — W4 zakończone lokalnie, ADR-017 rozwinięty przez ADR-027;
staging pozostaje odłożony
**Szacunek:** 2–3 tygodnie  
**Poprzednik:** W4  
**Rezultat:** wersjonowana, wielojęzyczna strona organizacji

## 1. Scenariusz demonstracyjny

Uprawniony członek organizacji tworzy stronę, dodaje kontrolowane bloki PL/EN,
przesyła obraz, podgląda draft, publikuje atomową wersję i przywraca poprzednią
publikację. Inna organizacja nie widzi draftu ani mediów.

## 2. Pakiety pracy

### W6.0 — odblokowanie fali i kontrakty

**Stan:** zakończone lokalnie 2026-08-11. ADR-027 ustanawia wykonywalny kontrakt
draftów, publikacji, bloków, tłumaczeń i mediów. SeaweedFS `4.41` działa jako
nie-rootowy, uwierzytelniony emulator wyłącznie w lokalnym Compose; sekrety są
generowane poza repozytorium, podpisany smoke SigV4 potwierdza bucket, a
żądanie bez podpisu otrzymuje `403`.
Walidacja: pełny Mypy 0 błędów w 113 plikach, Ruff, import-linter, brak dryfu
migracji, 195 testów backendu, testy i typecheck workspace, profile `core-only`
i `medplano`, aktualny OpenAPI oraz zdrowy pełny Compose ze smoke aplikacji i
storage.

- [x] potwierdzić zakończenie lokalnej bramki W4 i dostępność entitlementów W5;
- [x] przyjąć ADR-027 dla niemutowalnych wersji, atomowej publikacji,
  tłumaczeń, kontrolowanych bloków i lifecycle mediów;
- [x] wybrać lokalny emulator S3 bez zmiany zewnętrznego storage dla
  staging/production: przypięty SeaweedFS `4.41` tylko w Compose local;
- [x] przywrócić zielony pełny Mypy backendu przed dodaniem nowych modułów;
- [x] wygenerować lokalne sekrety storage poza repozytorium i uruchomić
  uwierzytelniony bucket testowy w Docker Desktop;
- [x] dodać deterministyczny smoke listujący bucket przez AWS Signature V4;
- [x] potwierdzić poprawny Compose i dotychczasowy runtime smoke.

W6 realizujemy pionowymi, wdrażalnymi przyrostami. Każdy pakiet kończy się
migracją od pustej bazy, testami tenant/permission/entitlement, aktualnym
OpenAPI/klientem oraz lokalnym buildem odpowiedniego profilu.

### W6.1 — model strony i treści

**Stan:** zakończone lokalnie 2026-08-11. Moduł udostępnia cursorowe API Sites,
Pages i draftów z Problem Details, idempotencją, optimistic lockiem, audytem,
permissionami `site.content.edit`/`site.publish`, entitlementem `sites.enabled`
i limitem `sites.max`. PostgreSQL pilnuje zgodności tenantowych relacji oraz
append-only dla wersji, bloków i publikacji. Migracje są rozszerzające; rollback
aplikacji pozostawia nowe tabele, a migracji nie cofamy po zapisaniu danych.
Walidacja: migracja od pustej bazy, 201 testów backendu, pełny Mypy 0 błędów w
126 plikach, Ruff, import-linter, brak dryfu migracji, aktualny OpenAPI i klient
TypeScript, pełny `pnpm check`, build profilu `medplano`, zdrowy Compose oraz
smoke aplikacji i object storage.

- [x] utworzyć moduł `shared.sites` i publiczne API zgodne z deskryptorem;
- [x] wdrożyć tenantowe `Site`, `Page`, niemutowalne `PageVersion` i
  `PageBlock` oraz append-only `Publication`;
- [x] zapisywać kolejną wersję draftu z optimistic lockiem zamiast aktualizować
  istniejący snapshot;
- [x] zapewnić stabilne slug, kolejność bloków i constrainty rozpoczynające się
  od `organization_id`;
- [x] dodać API listy, utworzenia i zapisu draftu z Problem Details oraz
  wygenerowanym klientem TypeScript;
- [x] pokryć brak tenant context, obcego tenanta, permission, entitlement,
  konflikt wersji, idempotencję i audyt.

### W6.2 — tłumaczenia i SEO

**Stan:** zakończone lokalnie 2026-08-11. `PageTranslation` przechowuje osobne
rekordy PL/EN oraz wersjonowane, idempotentne zapisy metadanych z audytem.
Raport kompletności rozróżnia wymagane locale bazowe od opcjonalnych wariantów,
stosuje jawny fallback per pole i wylicza ścieżki canonical, `hreflang` oraz
`x-default`. PostgreSQL pilnuje locale, relacji tenantowych, unikalności trasy,
append-only receiptów i niezmienności sluga po jego zablokowaniu przez pierwszą
publikację. Walidacja: migracja od pustej bazy, 207 testów backendu, Ruff, pełny
Mypy, import-linter, brak dryfu migracji, aktualny OpenAPI i klient TypeScript,
pełny `pnpm check`, build profilu `medplano`, zdrowy Compose oraz smoke runtime,
storage i nowej trasy API.

- [x] przechowywać tłumaczenia jako osobne rekordy ograniczone do locale
  deploymentu;
- [x] zdefiniować locale bazowe, dozwolony fallback i raport kompletności;
- [x] dodać title, description, canonical metadata i social preview;
- [x] generować adres bez prefiksu dla locale bazowego, prefiks dla pozostałych,
  canonical, hreflang i `x-default`;
- [x] walidować unikalność slug w obrębie site i locale oraz blokować zwykłą
  zmianę slug po pierwszej publikacji;
- [x] przetestować brakujące PL/EN, fallback i kolizje adresów.

### W6.3 — motyw i renderer

**Stan:** zakończone lokalnie 2026-08-11. Kanoniczny manifest udostępnia
schematy `core.hero` v1/v2, `core.rich_text` v1 i allowlistowane design tokens;
backend waliduje dokładnie te same artefakty przed zapisem. Registry przyjmuje
statyczne manifesty aktywnych modułów, wykonuje wyłącznie liniowe migracje w
pamięci i renderuje zaufane komponenty React bez HTML/CSS/JavaScriptu z danych.
Chroniony preview wymaga jawnego `PageVersion`, natomiast publiczny interfejs
renderera przyjmuje wyłącznie dokument publikacji z ID i hashem snapshotu;
historyczne drafty nie są dostępne przez publiczne API.
Walidacja: 209 testów backendu, pełny Mypy w 129 plikach, Ruff, import-linter,
brak dryfu migracji, testy i typecheck workspace, aktualny OpenAPI i klient,
build Next.js oraz obrazy backend/frontend na Node.js 24, poprawne profile
`core-only`/`medplano`, zdrowy Compose i smoke aplikacji oraz storage.

- [x] dodać kanoniczne JSON Schema bloków i design tokens do
  `packages/contracts/site-blocks`;
- [x] wdrożyć registry, typy i walidatory w `@saas-core/site-blocks`;
- [x] dodać liniowe migratory `vN -> vN+1` oraz fixture zgodności wstecznej;
- [x] renderować wyłącznie allowlistowane komponenty bez interpretacji
  HTML/JavaScript/CSS z danych;
- [x] oddzielić renderer publiczny bieżącej publikacji od chronionego preview;
- [x] zapewnić deterministyczny render i rozszerzenia bloków przez manifest
  modułu/verticala bez importu Shared -> Vertical;
- [x] przetestować złośliwe payloady, nieznany typ/wersję i identyczny wynik dla
  tego samego snapshotu.

### W6.4 — Media

- **Stan:** zakończone lokalnie 2026-08-11 — W6.4.1 (inicjowanie uploadu),
  W6.4.2 (operacyjne RLS) oraz
  W6.4.3a (callback uploadu), W6.4.3b (bezpieczny pipeline obrazu), W6.4.3c
  (tenantowe referencje draftu), W6.4.3d (atomowa publikacja z outboxem) i
  W6.4.3e (tombstone oraz cleanup) są ukończone. `MediaAsset`, polityka
  `FORCE RLS`, uprawnienia,
  entitlement, rezerwacja `storage.bytes`, losowy klucz tenantowy, signed PUT i
  list API mają testy PostgreSQL oraz aktualny kontrakt OpenAPI. Compose tworzy
  idempotentnie osobną rolę aplikacyjną `NOBYPASSRLS`; backend, worker i scheduler
  zatrzymują start dla roli uprzywilejowanej. Idempotentny callback wykonuje
  `HEAD` prywatnym endpointem S3 i przechodzi do `uploaded` tylko dla zgodnego
  rozmiaru i MIME. Podpisany task tenantowy skanuje surowe bajty przez prywatny
  ClamAV, sprawdza magic bytes i dekodowanie, usuwa EXIF przez re-encoding,
  tworzy allowlistowane warianty i rozlicza faktyczne bajty dokładnie raz.
  Niemutowalny draft zapisuje referencje przez rejestr rozszerzeń Core wyłącznie
  dla assetów `ready` z tego samego tenanta. Publikacja ponownie waliduje media,
  utrwala append-only referencje i kanoniczny snapshot, przełącza Site oraz
  zapisuje podpisany outbox w jednej transakcji. Chroniony `DELETE` zapisuje
  nieodwracalny tombstone i audyt, a podpisany task po wygaśnięciu signed PUT
  usuwa oryginał i warianty wyłącznie bez referencji publikacji oraz zwalnia
  rozliczone `storage.bytes` dokładnie raz.

- [x] utworzyć moduł `shared.media`, adapter S3 i `MediaAsset` z RLS od pierwszej
  migracji;
  - [x] dodać model, migrację `FORCE RLS` i bezpośrednie testy SQL pod rolą
    `NOSUPERUSER NOBYPASSRLS`;
  - [x] uruchamiać backend/worker rolą aplikacyjną bez `BYPASSRLS`, a migracje
    oddzielną rolą;
- [x] wydawać krótkotrwały signed upload z losowym kluczem tenantowym;
- [x] walidować rozmiar, nazwę, deklarowany MIME, magic bytes i rzeczywiste
  dekodowanie;
  - [x] walidować limit rozmiaru, bezpieczną nazwę-metadane i allowlistę
    deklarowanego MIME przed wydaniem URL;
  - [x] po uploadzie sprawdzać rozmiar obiektu, magic bytes i dekodowanie;
    - [x] sprawdzać przez prywatny `HEAD` obecność, rozmiar oraz zapisany MIME;
    - [x] sprawdzać magic bytes i rzeczywiste dekodowanie;
- [x] usuwać EXIF, blokować HTML/JS/SVG i tworzyć allowlistowane warianty
  obrazów;
- [x] wdrożyć stany `pending/uploaded/scanning/ready/rejected` i skaner plików;
- [x] dopuszczać do publikacji wyłącznie `ready` i egzekwować `storage.bytes`
  dokładnie raz;
  - [x] dopasować rezerwację do sanitizowanego oryginału i wariantów oraz
    commitować ją idempotentnie dokładnie raz;
  - [x] walidować `ready` przy zapisie referencji i publikacji;
    - [x] zapisywać tenantowe referencje draftu wyłącznie do assetów `ready`;
    - [x] ponownie walidować i utrwalać referencje w atomowej publikacji;
- [x] dodać tombstone oraz asynchroniczne usunięcie obiektu bez referencji;
- [x] przetestować RLS, fałszywy MIME, przekroczenie quota, malware i
  idempotentne ponowienie callbacku.
  - [x] przetestować RLS read/write, przekroczenie quota, złośliwą nazwę i
    idempotentne inicjowanie uploadu;
  - [x] przetestować brak obiektu, rozbieżność metadanych, wygaśnięcie, izolację
    tenantów i idempotentne ponowienie callbacku;

### W6.5 — panel edycji i publikacja

**Stan:** w toku — W6.5.1 udostępnia tenantowy workspace `/panel/sites` z
listą i tworzeniem sites/pages, wyborem locale, wyszukiwalną nawigacją,
raportem gotowości PL/EN oraz atomową publikacją. Klient korzysta z
wygenerowanych kontraktów OpenAPI, a formularze z React Hook Form, Zod i
Problem Details. W6.5.2 dodaje tenantową, cursorową historię publikacji z
autorem oraz idempotentny rollback jako nową publikację z audytem, outboxem i
kopią referencji mediów bez zmiany nowszego draftu. Edycja metadanych, bloków,
preview oraz interfejs historii i konfliktu optimistic lock pozostają do
realizacji w kolejnych przyrostach.

- [ ] zbudować listę stron, formularz metadanych i edytor kontrolowanych bloków
  w publicznym API `@saas-core/ui`;
  - [x] dodać listę oraz tworzenie sites/pages w panelu;
  - [ ] dodać formularz metadanych i edytor kontrolowanych bloków;
- [ ] użyć `Select` dla locale oraz `Combobox` dla wyszukiwalnych stron, bloków
  i mediów zgodnie z ADR-020;
  - [x] użyć `Select` dla locale oraz `Combobox` dla sites/pages;
  - [ ] dodać `Combobox` dla bloków i mediów;
- [ ] zastosować React Hook Form, Zod, Problem Details i widoczny konflikt
  optimistic lock bez nadpisania cudzej zmiany;
  - [x] zastosować React Hook Form, Zod i Problem Details w formularzach
    tworzenia;
  - [ ] obsłużyć widoczny konflikt optimistic lock w edycji draftu;
- [ ] dodać chroniony preview, raport gotowości PL/EN i atomową publikację;
  - [x] pokazać raport gotowości PL/EN i uruchamiać atomową publikację;
  - [ ] dodać chroniony preview konkretnej wersji draftu;
- [ ] rejestrować autora, pokazywać historię oraz tworzyć rollback jako nową
  publikację bez utraty nowszego draftu;
  - [x] udostępnić API historii z autorem oraz bezpieczny rollback jako nową
    publikację bez zmiany draftu;
  - [ ] pokazać historię i akcję rollbacku w panelu;
- [ ] przetestować klawiaturę, focus, axe, PL/EN i krytyczną ścieżkę E2E.

## 3. Testy obowiązkowe

- odczyt i modyfikacja draftu innego tenanta;
- konflikt dwóch edytorów tego samego draftu;
- migracja starego `schema_version` bloku;
- publikacja z brakującym tłumaczeniem i zachowanie fallbacku;
- upload z fałszywym MIME, nadmiernym rozmiarem i złośliwą nazwą;
- rollback publikacji bez utraty nowszego draftu;
- renderer nie wykonuje danych dostarczonych jako JavaScript/HTML.

## 4. Bramka wyjścia

- [ ] draft, preview, publication i rollback są odrębnymi stanami;
- [ ] snapshot publikacji jest niezmienny i możliwy do odtworzenia;
- [ ] bloki są wersjonowane i mają testowane migratory;
- [ ] PL/EN ma poprawne URL, canonical i hreflang;
- [ ] upload przechodzi walidację, skan i limity organizacji;
- [ ] testy cross-tenant obejmują treści, publikacje i media;
- [ ] Site Renderer nie wykonuje dowolnego kodu klienta.
