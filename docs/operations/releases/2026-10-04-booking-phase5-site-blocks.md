# Rezerwacje uniwersalne, faza 5: bloki strony firmy (5d) — wydanie 2026-10-04

Zakres: plaster 5d planu memex `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5d”). Bez migracji.

## Co się zmieniło

- **Trzy nowe sekcje w edytorze stron** (Strona internetowa › strona ›
  Biblioteka › „Potrzebujesz czegoś innego? Dodaj pustą sekcję”): „Lista
  jednostek”, „Rezerwacja pobytu” i „Kalendarz terminów”. Każda ma nagłówek,
  tekst, napis przycisku i pole
  „Oferta” (wszystkie oferty z rezerwacji online albo jedna); lista ma dwa
  układy. Jednostki, ceny i wolne dni nie są zapisane w stronie — opublikowana
  strona czyta je z rezerwacji przy każdym wejściu.
- **Lista jednostek** pokazuje okładkę, nazwę, miejscowość i liczbę osób,
  opis, wyposażenie, „od X zł / noc” i przycisk do formularza z wybraną
  jednostką. **Widget** pyta o termin i liczbę osób, **kalendarz** pokazuje
  miesiące z dniami, w które można przyjechać; oba prowadzą do formularza
  rezerwacji z tym, co gość wybrał.
- **Formularz rezerwacji wybiera daty w kalendarzu** (siatka miesiąca zamiast
  dwóch list) i **otwiera się na tym, co wybrał odnośnik**:
  `?offer=…&group=…|unit=…&from=…&to=…&people=…`.
- **Blok, który nie ma czego pokazać, nie pojawia się na stronie**: firma bez
  formularza albo bez rezerwacji w planie, oferta zdjęta z rezerwacji online.
- **Firma, której języków wdrożenie nie obsługuje**, ma formularz w pierwszym
  języku produktu (dotąd strona formularza odpowiadała 404).
- **API**: `live` w `GET /api/v1/public/site/`; odczyty
  `GET /api/v1/booking/public/<slug>/…` odpowiadają także pod hostem strony
  firmy (zapisy nie); `GET /api/v1/public/site/media/<id>/<thumbnail|preview>/`
  serwuje także zdjęcia jednostek, które firma pokazuje gościom.
  Kontrakt bloków: `core.stay_units`, `core.stay_search`,
  `core.stay_calendar` (v1).

## Na co uważać przy wdrożeniu

- Bez migracji. Backend, worker i frontend z tego samego commita: strona
  firmy czyta `live` z nowego backendu, a nowy frontend bez niego nie
  narysuje bloków.
- Kontrakt bloków jest czytany z obrazu backendu (`SITE_BLOCK_CONTRACTS_PATH`):
  stary obraz odmówi zapisu strony z nowym blokiem
  (`unknown_site_block_type`).
- Produkt bez publicznych rezerwacji (`features.publicBooking`) nie pokazuje
  tych bloków w edytorze.

## Dowody

- Testy: `tests/test_booking_site_blocks.py` (odpowiedź `live`, firma bez
  formularza i bez planu, języki, zdjęcia pod hostem strony, bramka hostów),
  `stay-blocks.test.ts`, `stay-date-picker.test.tsx`,
  `site-stay-blocks.test.tsx`, `public-stay-flow.test.tsx`,
  `stay-offer-select.test.tsx`.
