# Rezerwacje uniwersalne, faza 5: wzorce ofert przy ręcznym zakładaniu firmy (5g) — wydanie 2026-10-04

Zakres: plaster 5g planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5g”). Jedna migracja: booking 0036.

## Co się zmieniło

- **Nowy ekran „Wzorce ofert”** (Ustawienia › Usługi i grafik › „Zacznij od
  wzorca”, adres `/panel/settings/services/presets`): lista rodzajów
  rezerwacji — wizyta u specjalisty, usługa u klienta, nocleg, wypożyczalnia,
  pobyt z opieką i te zapowiedziane. Przy każdym: jak się go rezerwuje i czy
  jest gotowy.
- **Gotowy wzorzec zakłada ofertę**: „Użyj wzorca” pyta o nazwę (i czas
  wizyty przy terminach) i tworzy ofertę-szkic, wyłączoną. Potem ekran mówi,
  co dalej: dodać jednostki i ceny albo osoby i miejsce, a przy „Noclegu” —
  że w katalogu firm pasuje kategoria „Turystyka i noclegi” i że na stronę
  jest szablon „Noclegi”. Niczego z tego wzorzec nie ustawia sam.
- **Wzorzec „wkrótce” przyjmuje zapis**: „Daj znać, gdy będzie gotowy” z
  polem „Czego Ci brakuje?”. Zapis można zmienić albo wycofać.
- **Lista „Na start” ma krok „Ustaw pierwszą ofertę”** (przed „Zaplanuj
  pierwszą wizytę”), zrobiony, gdy firma ma jakąkolwiek usługę.
- Produkt, którego typ organizacji ma własne gotowe usługi („Gotowe
  usługi:”), nie pokazuje przycisku ani kroku — ekran działa, ale nikt do
  niego nie prowadzi.
- „Nocleg” jest w wersji 5: to wersja 4 z podpowiedzią szablonu strony.
- Nowe adresy API: `POST /api/v1/booking/presets/apply/`,
  `POST /api/v1/booking/presets/apply/preview/`,
  `PUT` i `DELETE /api/v1/booking/presets/<id>/interest/`; lista wzorców
  oddaje `page_template` i `interest`.

## Wdrożenie

- **Migracja booking 0036** (`0036_preset_interest`): nowa tabela
  `booking_presetinterest` z wymuszonym RLS; odwracalna (usuwa tabelę z
  zapisami).
- Bez nowych zmiennych środowiskowych.
- Przebudowa backendu i frontendu razem: katalog wzorców jest czytany z
  obrazu backendu (`BOOKING_PRESET_CONTRACTS_PATH`).
- Operator czyta, kto czeka:
  `docker exec <backend> python manage.py booking_preset_interest`
  (opcjonalnie `--preset core.hourly_space`).

## Dowody

- `tests/test_booking_preset_interest.py` (zastosowanie przez API z kluczem
  i podglądem, odmowy na polu, zapis „wkrótce”, izolacja firm, kolejność
  `SET LOCAL` w poleceniu operatora, usunięcie firmy),
  `tests/test_booking_presets.py`, `offer-presets.test.tsx`,
  `getting-started.test.tsx`, `booking-settings.test.tsx`,
  `packages/contracts/tests/booking-preset-contracts.test.mjs`.
- Przejście w Chromium: `.local-dev/resume/package-m/walk-5g.mjs` — wynik w
  worklogu memex.

## Czego nie ma

- Ekranu listy zapisów w panelu „Platforma” (jest polecenie).
- Powiadomienia firm z listy, gdy wzorzec stanie się gotowy.
- Polecenia asystenta dla zapisu „wkrótce” i presetów produktu w profilu.
- Ustawienia kategorii i importu szablonu jednym kliknięciem z ekranu
  wzorców.
