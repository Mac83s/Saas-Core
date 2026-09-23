# Style stron, kotwice sekcji i recepty pod konwersję (faza 3b) — wydanie 2026-09-23

Zakres: faza 3b planu memex `saas-core-site-studio-rich-content-and-full-width`
(kontrakt: [site-rich-content.md](../../architecture/site-rich-content.md),
lista kontrolna: [site-section-catalog.md](../../architecture/site-section-catalog.md)).
Wygląd strony v2 z 8 stylami, koperta sekcji v2 z kotwicą (`id` tylko w
publikacji), hero v6 i product v2 z przyciskiem „do formularza” i cichszym
drugim działaniem, recepty stron v5 z celem i etapami konwersji: 9 w galerii
(3 strony demonstracyjne w v2 i 6 nowych), 8 dawnych wycofanych z galerii i
katalogu blueprintów. Wdrożono **tylko** `saas.goldenstar.cloud`; HoofCare i
MedPlano dostaną to przez `core:update`.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `0de18de` | `0de18de` |

## Wdrożenie

- `843f95c`: obrazy z `git archive`, poprzednie jako
  `saas-core-{backend,frontend}:rollback-conversion-pages-20260923`; kopia
  bazy, brak migracji do wykonania, start czterech usług — 99,5 s,
  `check_database_role`, skaner `CLEAN`, obrazy zgodne z buildem, zero
  zaległych migracji, `/healthz` 200.
- `0de18de` (poprawka znaleziona przy odbiorze, niżej): ta sama procedura,
  146 s, poprzednie obrazy jako `…:rollback-inline-case-20260923`. Kod
  backendu jest ten sam co w `843f95c`; zmienił się tylko frontend. W trakcie
  `main` poszedł dalej (magazyn v2 innej sesji), więc na instancji jest
  `0de18de`, nie czubek `main`; skrypt sprawdza, że wdrażany commit należy do
  `main`.

## Odbiór

- [x] bramki na drzewie po scaleniu `main` (limit podstron): frontend
  **417/417**, renderer **182/182**, kontrakty **34/34**, UI **60/60**,
  backend `test_site_rich_content` **70**, `test_site_blueprints` **27**,
  `test_sites_api` **34**, `test_site_section_decoration` **23**,
  `test_sites_collections` **58**, `test_billing_catalog` **8**, Ruff, mypy
  (437), brak nowych migracji, zgodność API, lint, typecheck, prettier;
- [x] przegląd wizualny 9 recept PL/EN (Chromium 1440/390/320): bez
  poziomego przewijania, bez zerwanych linków do kotwic, jedno główne
  działanie na sekcję, zero błędów JS. Poprawki po przeglądzie: wypełniony
  główny przycisk w stylu premium, wygląd bloku opinii, pozycja bez pary w
  siatkach dwukolumnowych, linia pod nagłówkiem studio w sekcjach
  dwukolumnowych, karty mozaiki bez kropek i bez karty w karcie, strzałka
  materiałów bez osobnej linii; strona przeglądu dla właściciela;
- [x] zalogowany panel na koncie syntetycznym: galeria pustej strony pokazuje
  dokładnie 9 recept (bez wycofanych); import `core.premium_service` v1
  (styl premium, pełna szerokość, hero v6 z `#kontakt` i drugim działaniem,
  formularz z kotwicą `kontakt`, zdjęcie w referencjach), `core.technical_b2b`
  v1 i wycofanej `core.profile` v2 po identyfikatorze; katalog blueprintów
  zwraca te same 9; druga kotwica `kontakt` na stronie odrzucona (400
  `duplicate_rich_text_anchor`); publikacja; edytor pokazuje styl na płótnie
  i „Styl strony: Premium”; telefon 390 px bez poziomego przewijania; zero
  błędów JS;
- [x] strony publiczne przez Caddy z hostem witryny: `/`, `/rejestrator`,
  `/wizytowka` — 200; klasy stylów premium i technical, `id="kontakt"` na
  sekcji formularza i dwa linki do `#kontakt` na każdej stronie z recepty v5,
  unikalne `id`, strona z wycofanej recepty bez stylu; zdjęcie 200 `image/png`;
- [x] konto, organizacja i 3 obiekty magazynu (zdjęcia z importów) usunięte;
- [x] po `0de18de`: zaznaczona sekcja na płótnie pokazuje przyciski premium
  wersalikami (`text-transform: uppercase`), zero błędów JS.

## Znalezione przy odbiorze

- Zaznaczona sekcja na płótnie pokazywała wersaliki (przyciski premium,
  etykiety nad nagłówkiem) zwykłymi literami: tekst edytuje się przez
  przycisk, a przycisk nie dziedziczy `text-transform`. Poprawione w
  `0de18de` i sprawdzone na żywo.

## Uwagi

- Styl premium ma główny przycisk wypełniony, a nie z cienkim obrysem, jak
  zakładała specyfikacja: przy obrysie był mniej widoczny niż podkreślony link
  obok. Reguła konwersji wygrywa; to jedna reguła CSS, gdyby właściciel wolał
  obrys.
- Formularz kontaktu nie ma konfiguracji pól: telefon jest zawsze opcjonalny,
  więc prośba o oddzwonienie nie wymusi numeru.
- Nagłówki 800 w stylach studio i product renderują się jako 700 — dołączony
  Manrope kończy się na 700.
- Zdjęcia nadal jako oryginały PNG bez wariantów responsywnych (~2,6 MB).
- Na płótnie drugie działanie w stylu premium nie jest podkreślone (w
  publikacji jest): przycisk edycji tekstu nie przejmuje dekoracji rodzica.

Dowody (prywatne): `.runtime/releases/20260923-conversion-pages/` i
`.runtime/releases/20260923-inline-case/`.
