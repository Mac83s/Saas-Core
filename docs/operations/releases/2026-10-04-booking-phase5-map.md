# Rezerwacje uniwersalne, faza 5: blok mapy (5e) — wydanie 2026-10-04

Zakres: blok mapy plastra 5e planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia bloku mapy”). Jedna migracja: booking 0035.

## Co się zmieniło

- **Nowa sekcja „Mapa położenia”** w edytorze stron (Biblioteka › „Dodaj
  pustą sekcję”): pokazuje, gdzie jest jednostka. Pole „Jednostka” wymienia
  jednostki pokazane gościom; bez wyboru mapa bierze pierwszą, która ma
  miejscowość.
- **Mapa to OpenStreetMap i wczytuje się dopiero po kliknięciu „Pokaż
  mapę”.** Przed kliknięciem strona nie łączy się z nikim poza nami: widać
  nazwę, miejscowość, przycisk, zdanie o tym, czyja to mapa, i odnośnik
  „Otwórz w mapach”. Bez klucza, bez cookies, bez banera.
- **Domyślnie mapa pokazuje miejscowość** (środek miejscowości ze słownika,
  bez pinezki). Dokładny punkt z pinezką — dopiero gdy firma zaznaczy w oknie
  jednostki **„Pokaż dokładne położenie”** (Ustawienia › Usługi i grafik ›
  jednostka). Okno mówi, co to publikuje: współrzędne stają się czytelne dla
  każdego, kto otworzy stronę. Wymaga obu współrzędnych.
- **Strona jednostki** (`/stay/<adres>/`) ma mapę pod kartą, własny obraz
  udostępnień (okładka jednostki) i dane strukturalne `Accommodation`
  (nocleg); `geo` tylko przy włączonym przełączniku.
- **Współrzędne jednostki** nie pojawiają się w żadnej publicznej odpowiedzi,
  dopóki przełącznik jest wyłączony; po włączeniu — tylko w odpowiedzi bloku
  mapy i w danych strukturalnych strony jednostki.
- **API**: `show_exact_location` w jednostce (`/booking/setup/resources/`),
  400 `coordinates_missing`; kontrakt bloku `core.stay_map` v1; `live` strony
  niesie `place` dla bloku mapy.
- Skróty dni tygodnia w kalendarzu terminów nie łamią się na telefonie
  („NIEDZ.”).

## Wdrożenie

- Migracja **booking 0035** (`0035_unit_exact_location`): kolumna
  `show_exact_location` w `booking_resource`, domyślnie `false`; odwracalna,
  niczego nie przepisuje. Istniejące jednostki pokazują więc najwyżej
  miejscowość.
- Przebudowa backendu, workera i frontendu razem: kontrakt bloku jest czytany
  z obrazu backendu (`SITE_BLOCK_CONTRACTS_PATH`) — stary obraz odmówi zapisu
  strony z blokiem mapy (`unknown_site_block_type`).
- Bez nowych zmiennych środowiskowych. Przeglądarka gościa łączy się z
  `www.openstreetmap.org` dopiero po kliknięciu; serwer nie łączy się z nim
  nigdy.

## Dowody

- `tests/test_booking_site_blocks.py` (miejscowość domyślnie, punkt po
  przełączniku, współrzędne poza każdą publiczną odpowiedzią do tego czasu,
  mapa na stronie jednostki, dane strukturalne i obraz udostępnień, kontrakt
  bloku), `tests/test_booking_unit_content.py` (przełącznik wymaga
  współrzędnych), `stay-blocks.test.ts`, `site-stay-map.test.tsx`,
  `public-site.test.tsx`, `stay-offer-select.test.tsx`,
  `booking-settings.test.tsx`.
