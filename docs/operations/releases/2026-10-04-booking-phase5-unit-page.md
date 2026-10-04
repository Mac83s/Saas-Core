# Rezerwacje uniwersalne, faza 5: strona jednostki (5e) — wydanie 2026-10-04

Zakres: plaster 5e planu memex `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5e”). Bez migracji. Blok mapy nie wchodzi — czeka na
decyzję o dostawcy map.

## Co się zmieniło

- **Każda jednostka pokazana gościom ma własną stronę** na opublikowanej
  stronie firmy: `https://<strona firmy>/stay/<adres jednostki>/` (adres
  jednostki to pole „Adres jednostki” w oknie jednostki). Strona pokazuje
  zdjęcia (każde otwiera dużą kopię), miejscowość i liczbę osób, opis, całe
  wyposażenie, „od X zł / noc” i kalendarz wolnych terminów z przyciskiem do
  formularza. Nikt jej nie publikuje i nie edytuje: istnieje, dopóki
  formularz rezerwacji pokazuje tę jednostkę.
- **Lista jednostek prowadzi do tej strony** — nazwa na karcie jest
  odnośnikiem.
- **Nowa sekcja „Karta jednostki”** w edytorze stron (Biblioteka ›
  „Potrzebujesz czegoś innego? Dodaj pustą sekcję”): ta sama karta na
  dowolnej podstronie firmy; pole „Jednostka” wymienia jednostki pokazane
  gościom.
- **Języki**: strona jednostki jest w języku strony firmy; w innym języku
  (`/en/stay/…`) tylko wtedy, gdy jednostka ma w nim przetłumaczoną nazwę —
  inaczej adres przekierowuje (308) do wersji w języku strony.
- **Mapa strony** (`sitemap.xml`) wymienia strony jednostek.
- **Adres `stay` jest zarezerwowany**: nowa podstrona ani blog nie dostaną
  adresu zaczynającego się od `stay` (`slug_reserved`). Podstrona, która już
  go ma, zostaje i ma pierwszeństwo.
- **API**: `public_slug` przy grupach w `stays` katalogu formularza; kontrakt
  bloków `core.stay_unit` (v1); `page_path` przy wyborach w `live` listy
  jednostek.

## Na co uważać przy wdrożeniu

- Bez migracji. Backend, worker i frontend z tego samego commita; kontrakt
  bloków jest czytany z obrazu backendu.
- Firma, która ma opublikowaną podstronę pod `/stay/…`, zachowuje ją — strona
  jednostki o tym samym adresie się nie pokaże.

## Dowody

- Testy: `tests/test_booking_site_blocks.py` (karta i strona jednostki,
  języki, mapa strony, zarezerwowany segment), `stay-blocks.test.ts`,
  `stay-offer-select.test.tsx`.
