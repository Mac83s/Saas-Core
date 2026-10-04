# Rezerwacje uniwersalne, faza 5: strona prawna witryny z dokumentów firmy (5f, część 2) — wydanie 2026-10-04

Zakres: druga część plastra 5f planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5f, część 2”). Bez migracji.

## Co się zmieniło

- **Dokument firmy ma stronę na witrynie firmy.** Regulamin rezerwacji,
  regulamin sklepu, polityka prywatności i polityka anulowania — każdy, który
  ma dziś obowiązującą wersję — odpowiada na opublikowanej stronie firmy pod
  `/documents/booking-terms/`, `/documents/shop-terms/`,
  `/documents/privacy-policy/` i `/documents/cancellation-policy/`. Firma
  niczego nie publikuje: strona pokazuje tekst wersji, którą zatwierdziła
  osoba („Dokumenty dla klientów”), z numerem wersji i dniem wejścia w życie,
  i zmienia się sama, gdy zacznie obowiązywać następna wersja. Dokument bez
  obowiązującej wersji nie ma strony (404).
- **Tekst jest per język.** Strona w innym języku witryny ma tekst tylko
  wtedy, gdy wersja ma go w tym języku. Gdy nie ma — strona nie pokazuje
  tekstu z innego języka: mówi, że dokument nie ma wersji w tym języku, i
  podaje odnośniki do języków, w których jest. Dla regulaminu rezerwacji mówi
  to słowami formularza („W tym języku nie można zarezerwować online…”).
  Taka strona nie trafia do wyszukiwarek ani do mapy strony.
- **Szablon „Noclegi” prowadzi do dokumentów**: pod „Cena i zasady pobytu”
  jest przycisk „Przeczytaj regulamin rezerwacji”, a formularz pytania ma
  odnośnik „Informacje o prywatności” do polityki prywatności. Galeria
  szablonu nie przynosi już ilustracji spoza noclegów (krowy, pracownia):
  jej pozycje czekają na zdjęcia obiektu, a pusta galeria nie trafia na
  opublikowaną stronę.
- **Karta „Gotowość” (Strony › Publikacja) nazywa odnośnik do strony, której
  nie ma** — np. do dokumentu, którego firma jeszcze nie zatwierdziła — z
  odnośnikiem do „Dokumenty dla klientów”. Publikacji to nie blokuje.
- **Odnośnik do strony dokumentu albo jednostki idzie za językiem
  czytelnika**: w wersji językowej strony `/documents/…` i `/stay/…` dostają
  prefiks języka.
- **Rzecz wynajmowana na dni** (kajak) ma na swojej stronie dane
  strukturalne: produkt z ofertą wynajmu i ceną „od” za dzień. Bez ceny w
  cenniku — bez węzła.
- Nowe pole API: `missing_pages` przy stronie w
  `GET /api/v1/sites/<id>/localization/`. Nowy kod błędu: 400
  `server_built_site_block` (zapis treści z blokiem `core.document`).

## Wdrożenie

- Bez migracji i bez nowych zmiennych środowiskowych.
- Przebudowa backendu i frontendu razem: backend czyta manifest bloków i
  receptę „Noclegi” z obrazu (`SITE_BLOCK_CONTRACTS_PATH`,
  `PAGE_TEMPLATE_CONTRACTS_PATH`), a frontend rysuje nowy blok — stary
  frontend pokazałby na stronie dokumentu pustą stronę.
- Adres `/documents` jest odtąd zarezerwowany dla nowych podstron i kolekcji.
  Istniejąca podstrona albo kolekcja o takim adresie działa dalej i zasłania
  strony dokumentów — `python manage.py sites_reserved_slugs` je wymienia.

## Dowody

- `tests/test_customers_site_pages.py` (strona dokumentu, języki, mapa
  strony, kolejność `SET LOCAL`, odmowa zapisu bloku, odnośniki w języku
  czytelnika, raport gotowości), `tests/test_sites_api.py` (import
  „Noclegi”), `tests/test_booking_site_blocks.py` (węzeł wynajmu),
  `document-block.test.ts`, `entry-editor.test.tsx`,
  `sites-panel.test.tsx`, `packages/contracts/tests/`.
- Przejście w Chromium: `.local-dev/resume/package-m/walk-5f2.mjs` (1280 i
  390 px) — wynik w worklogu memex.

## Czego nie ma

- Formularz rezerwacji i e-maile linkują dokument nadal pod adresem
  platformy (`/<język>/documents/<identyfikator>`).
- Stopka witryny nie dostaje odnośników do dokumentów sama; firma dodaje je
  jak każdy odnośnik.
- Dokument jako sekcja własnej podstrony firmy i wersje archiwalne dokumentu.
