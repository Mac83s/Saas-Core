# Rezerwacje uniwersalne, faza 5: jednostka jako treść (5c) — wydanie 2026-10-04

Zakres: plaster 5c planu memex `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5c”). Migracja: booking 0033.

## Co się zmieniło

- **Jednostka ma treść dla gości.** W Ustawienia › Usługi i grafik, w oknie
  jednostki (firmy z ofertą okresu), jest sekcja „Co widzi gość”: „Pokaż
  jednostkę gościom”, adres jednostki, miejscowość ze słownika, współrzędne
  (tylko dla firmy), wyposażenie z listy i do 12 zdjęć (pierwsze to okładka).
  Lista jednostek oznacza te widoczne dla gości.
- **Formularz rezerwacji pokazuje treść przy wyborze**: miniaturę, miejscowość,
  „od X zł za noc” i wyposażenie; pod wyborem zdjęcia, które otwierają się w
  dużej kopii. Grupa identycznych jednostek pokazuje treść pierwszej jednostki
  widocznej dla gości. Jednostka niewidoczna rezerwuje się jak dotąd — po
  nazwie.
- **„od X zł za noc”** to najniższa cena jednej nocy albo dnia dla jednej osoby
  w najbliższym roku, policzona funkcją wyceny (brutto, bez dopłat). To
  zapowiedź; cenę terminu mówi wycena po wyborze dat.
- **Oferta okresu ma własne okno rezerwacji** („Okno rezerwacji (dni)” w oknie
  usługi): na ile dni naprzód można zarezerwować, gdy sezon nie ma własnego
  okna. Puste — jak dotąd, granica platformy.
- **Lista usług mówi, co formularz robi z ofertą**: oferta okresu widoczna
  online to „Tak, gość wybiera daty” (dotąd „Nie — rezerwacje wpisuje
  zespół”, choć od 5b formularz ją rezerwuje), a oferta na prośbę — „Tak, na
  prośbę — firma odpowiada”.
- **Zdjęcie usunięte z biblioteki mediów zostaje tam, gdzie pokazuje je
  jednostka**, dopóki firma nie zdejmie go z jednostki (jak zdjęcie na
  opublikowanej stronie).
- **API**: `public`, `public_slug`, `amenities`, `city_slug`, `latitude`,
  `longitude`, `photo_ids` w zapisach i odczycie jednostki
  (`/api/v1/booking/setup/resources/…`), `unit_options` w
  `GET /api/v1/booking/setup/`, `booking_window_days` usługi; w katalogu
  formularza `photos`, `amenities`, `town`, `from_price` przy grupach i
  jednostkach oferty okresu; nowy publiczny adres zdjęcia
  `GET /api/v1/booking/public/<slug>/photos/<id>/<thumbnail|preview>/`.

## Na co uważać przy wdrożeniu

- **Migracja booking 0033** (`0033_unit_content_and_offer_window`) dodaje
  kolumny do `booking_resource` i `booking_service` oraz trzy ograniczenia;
  odwracalna, bez przepisywania danych. Istniejące jednostki zostają
  niewidoczne dla gości (bez treści), a oferty bez własnego okna.
- Backend, worker i frontend z tego samego commita: worker sprząta media i
  musi znać rejestr źródeł, inaczej usunie obiekt zdjęcia, które pokazuje
  jednostka.
- Współrzędne jednostki nie wychodzą w żadnej publicznej odpowiedzi.

## Dowody

- Testy: `tests/test_booking_unit_content.py` (zapis i odmowy pól treści,
  panel przez API, katalog formularza, „od X”, macierz autoryzacji adresu
  zdjęcia z kolejnością `SET LOCAL`, sprzątanie mediów, okno oferty),
  `booking-settings.test.tsx`, `public-stay-flow.test.tsx`.
