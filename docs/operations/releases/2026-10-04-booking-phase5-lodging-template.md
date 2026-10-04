# Rezerwacje uniwersalne, faza 5: sekcje pobytów w bibliotece i szablon „Noclegi” (5f, część 1) — wydanie 2026-10-04

Zakres: pierwsza część plastra 5f planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5f, część 1”). Bez migracji. Strona prawna witryny
z dokumentów firmy to część 2 — nie wchodzi.

## Co się zmieniło

- **Biblioteka sekcji ma sekcje pobytów**: „Rezerwacja pobytu: termin i
  liczba osób”, „Domki i pokoje — karty”, „Domki i pokoje — wiersze ze
  zdjęciem z boku”, „Kalendarz wolnych terminów”, „Mapa położenia”. Dotąd te
  bloki dodawało się tylko z „Dodaj pustą sekcję”. Sekcja przynosi nagłówek,
  zdanie i napis przycisku; jednostki, ceny i wolne dni pokazuje sama, z
  ustawień rezerwacji.
- **Nowy szablon strony „Noclegi”** („Całe strony”, cel: rezerwacja): start z
  obietnicą i przyciskiem do wyboru terminu, wybór terminu, jednostki z ceną
  „od”, okolica, galeria, cena i zasady pobytu, pytania, mapa, kalendarz i
  formularz pytania. Miejsca `[Uzupełnij: …]` firma wypełnia sama; zdjęcia w
  galerii są poglądowe.
- **Wszystko, co dotyczy pobytów, edytor oferuje firmie, która ma ofertę
  rezerwowaną od–do**: bloki w „Dodaj pustą sekcję”, sekcje biblioteki i
  szablon „Noclegi”. Firma bez takiej oferty ich nie widzi (dotąd widziała
  bloki, choć na opublikowanej stronie nic by nie pokazały). Sekcje, które
  strona już ma, zostają.
- **Układ listy jednostek** (karty albo wiersze) wybiera się tam, gdzie układ
  każdej sekcji; osobne pole „Układ listy” zniknęło.
- Cel szablonu „rezerwacja wizyty” nazywa się teraz „rezerwacja”.

## Wdrożenie

- Bez migracji i bez nowych zmiennych środowiskowych.
- Przebudowa backendu i frontendu razem: katalog szablonów stron jest czytany
  z obrazu backendu (`PAGE_TEMPLATE_CONTRACTS_PATH`) — stary obraz odpowie
  `page_template_not_found` na „Użyj szablonu Noclegi”.
- Import szablonu „Noclegi” wymaga `booking.enabled` w planie firmy (403
  `entitlement_required`).

## Dowody

- `packages/contracts/tests/` (recepta i sekcje wobec schematów, kotwice,
  ścieżka konwersji, zdjęcia poglądowe, przypięte wersje sekcji),
  `section-templates.test.ts`, `stay-offers.test.tsx`,
  `section-library.test.tsx`, `page-editor.test.tsx`,
  `tests/test_sites_api.py` (import „Noclegi” z uprawnieniem i bez).
