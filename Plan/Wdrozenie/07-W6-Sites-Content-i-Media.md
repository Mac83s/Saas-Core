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

- [ ] utworzyć moduł `shared.sites` i publiczne API zgodne z deskryptorem;
- [ ] wdrożyć tenantowe `Site`, `Page`, niemutowalne `PageVersion` i
  `PageBlock` oraz append-only `Publication`;
- [ ] zapisywać kolejną wersję draftu z optimistic lockiem zamiast aktualizować
  istniejący snapshot;
- [ ] zapewnić stabilne slug, kolejność bloków i constrainty rozpoczynające się
  od `organization_id`;
- [ ] dodać API listy, utworzenia i zapisu draftu z Problem Details oraz
  wygenerowanym klientem TypeScript;
- [ ] pokryć brak tenant context, obcego tenanta, permission, entitlement,
  konflikt wersji, idempotencję i audyt.

### W6.2 — tłumaczenia i SEO

- [ ] przechowywać tłumaczenia jako osobne rekordy ograniczone do locale
  deploymentu;
- [ ] zdefiniować locale bazowe, dozwolony fallback i raport kompletności;
- [ ] dodać title, description, canonical metadata i social preview;
- [ ] generować adres bez prefiksu dla locale bazowego, prefiks dla pozostałych,
  canonical, hreflang i `x-default`;
- [ ] walidować unikalność slug w obrębie site i locale oraz blokować zwykłą
  zmianę slug po pierwszej publikacji;
- [ ] przetestować brakujące PL/EN, fallback i kolizje adresów.

### W6.3 — motyw i renderer

- [ ] dodać kanoniczne JSON Schema bloków i design tokens do
  `packages/contracts/site-blocks`;
- [ ] wdrożyć registry, typy i walidatory w `@saas-core/site-blocks`;
- [ ] dodać liniowe migratory `vN -> vN+1` oraz fixture zgodności wstecznej;
- [ ] renderować wyłącznie allowlistowane komponenty bez interpretacji
  HTML/JavaScript/CSS z danych;
- [ ] oddzielić renderer publiczny bieżącej publikacji od chronionego preview;
- [ ] zapewnić deterministyczny render i rozszerzenia bloków przez manifest
  modułu/verticala bez importu Shared -> Vertical;
- [ ] przetestować złośliwe payloady, nieznany typ/wersję i identyczny wynik dla
  tego samego snapshotu.

### W6.4 — Media

- [ ] utworzyć moduł `shared.media`, adapter S3 i `MediaAsset` z RLS od pierwszej
  migracji;
- [ ] wydawać krótkotrwały signed upload z losowym kluczem tenantowym;
- [ ] walidować rozmiar, nazwę, deklarowany MIME, magic bytes i rzeczywiste
  dekodowanie;
- [ ] usuwać EXIF, blokować HTML/JS/SVG i tworzyć allowlistowane warianty
  obrazów;
- [ ] wdrożyć stany `pending/uploaded/scanning/ready/rejected` i skaner plików;
- [ ] dopuszczać do publikacji wyłącznie `ready` i egzekwować `storage.bytes`
  dokładnie raz;
- [ ] dodać tombstone oraz asynchroniczne usunięcie obiektu bez referencji;
- [ ] przetestować RLS, fałszywy MIME, przekroczenie quota, malware i
  idempotentne ponowienie callbacku.

### W6.5 — panel edycji i publikacja

- [ ] zbudować listę stron, formularz metadanych i edytor kontrolowanych bloków
  w publicznym API `@saas-core/ui`;
- [ ] użyć `Select` dla locale oraz `Combobox` dla wyszukiwalnych stron, bloków
  i mediów zgodnie z ADR-020;
- [ ] zastosować React Hook Form, Zod, Problem Details i widoczny konflikt
  optimistic lock bez nadpisania cudzej zmiany;
- [ ] dodać chroniony preview, raport gotowości PL/EN i atomową publikację;
- [ ] rejestrować autora, pokazywać historię oraz tworzyć rollback jako nową
  publikację bez utraty nowszego draftu;
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
