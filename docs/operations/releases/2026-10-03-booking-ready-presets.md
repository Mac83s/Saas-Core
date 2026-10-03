# Rezerwacje: gotowe presety pobytów, kolejność cen, osoba dla asystenta — wydanie 2026-10-03

Zakres: decyzje właściciela 59a, 67a, 68a, 71a i 75b
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md),
trzy „Uzupełnienia 2026-10-03” na końcu; ADR-076 pkt 5 uzupełnienia o profilu).
Bez migracji. Produkty biorą zmianę przez `core:update`.

## Co się zmieniło

- **Która cena obowiązuje (75b).** Cena na wybrane dni — sezonu, dni tygodnia
  albo pory dnia — wygrywa z ceną podstawową niezależnie od zasięgu. Zasięg
  (jednostka przed grupą przed ofertą) rozstrzyga już tylko między dwiema
  cenami podstawowymi albo dwiema cenami na wybrane dni. „Domek 350, lipiec 500
  dla wszystkich” daje w lipcu 500. **To zmiana wyniku wyceny** dla firm, które
  mają cenę podstawową jednostki albo grupy i cenę sezonu oferty; rezerwacje
  już zapisane trzymają zamrożoną wycenę i się nie zmieniają.
- **Presety.** Nowe wersje 2, `ready`: „Nocleg”, „Wypożyczalnia”, „Pobyt z
  opieką” (okres na noce albo doby, jedna jednostka, płatność na miejscu) i
  „Usługa u klienta” (termin z osobą, 30 minut na dojazd przed wizytą).
  Wszystkie mają `onlineBooking: soon`: oferta powstaje jako niewidoczna w
  rezerwacji online, a rezerwacje wpisuje zespół w panelu. „Wynajem
  przestrzeni na godziny” zostaje `soon`. Schemat presetu ma dwa nowe,
  opcjonalne pola: `onlineBooking` i `buffers`.
- **API.** `GET /api/v1/booking/presets/` zwraca przy każdym presecie
  `online_booking` (`ready` | `soon`). Zastosowanie presetu
  (`presets.apply_preset`, polecenie `booking.preset.apply@1`) kopiuje z niego
  także jednostkę okresu z godzinami, przerwy, płatność na miejscu i widoczność
  online.
- **Asystent.** Nowe polecenie `booking.staff.add@1` (osoba bez konta: jedno
  kliknięcie zgody; z zaproszeniem do panelu: osobne kliknięcie). Zadania
  `assistant.conversation` i `assistant.extract_profile` mają w kodzie model
  Claude Sonnet 5.5; Claude Haiku 4.5 zostaje zapasem przez
  `MODEL_PORT_TASK_ASSISTANT_<ZADANIE>_MODEL`.
- **Katalog firm.** Słownik miast ma 17 kolejnych miejscowości Warmii i Mazur
  (Mikołajki, Ruciane-Nida, Ryn, Orzysz, Biała Piska, Olsztynek, Morąg, Lubawa,
  Nowe Miasto Lubawskie, Biskupiec, Reszel, Dobre Miasto, Frombork, Tolkmicko,
  Pasym, Barczewo, Lidzbark), każda ze współrzędnymi środka.

## Dla produktów

1. **Obraz backendu trzeba przebudować** po `core:update`: presety i słownik
   katalogu są kopiami w obrazie (`BOOKING_PRESET_CONTRACTS_PATH`,
   `CATALOG_CONTRACTS_PATH`). Backend, worker i scheduler z jednego commita.
2. Po wdrożeniu `manage.py reindex_catalog`, żeby wyszukiwarka katalogu znała
   nowe miejscowości.
3. Produkt z własnymi presetami w profilu (od fazy 5) trzyma się tej samej
   reguły: wersja `ready` używa tylko tego, co silnik umie; lista jest w
   `packages/contracts/tests/booking-preset-contracts.test.mjs` (`ENGINE`).
4. Kod produktu, który sam wybiera cenę (żaden dziś tego nie robi — cenę liczy
   `quote`), dostaje nową kolejność razem z `prices.price_for`.
