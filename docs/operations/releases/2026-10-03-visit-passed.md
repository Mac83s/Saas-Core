# Wizyta, która minęła, i nieobecność klienta (UX-031) — wydanie 2026-10-03

Zakres: UX-031 i rdzeniowa część W3 planu memex `saas-core-poprawki-ux-ui`,
uzgodnione z development-72 (HoofCare). Jedna migracja `organizations` (nowa
akcja audytu, bez zmiany danych). Produkty biorą to przez `core:update`.

## Co się zmieniło

- **Jedna reguła „wizyta minęła”** (`booking/passing.py`): status `confirmed`
  i koniec planowany za nami. Nic nie jest zapisywane — decyduje zegar.
  Wizyta, która minęła, nie jest „najbliższa”, wakat na niej nie jest już
  zadaniem (bez „Wakat” na karcie, w szczegółach i na tablicy dnia; kolejka i
  licznik w menu liczyły tak już wcześniej), a w Kalendarzu, na „Dziś” i na
  karcie osoby ma własny stan „Odbyta · do rozliczenia” z pozycją w legendzie.
- **Nieobecność klienta**: `POST /api/v1/booking/appointments/{id}/no-show/`
  (`booking_appointment_no_show`, `booking.api.mark_no_show`, w panelu
  „Oznacz nieobecność” w szczegółach wizyty). Tylko potwierdzona wizyta, od jej
  początku (wcześniej 409 `visit_not_started_yet`); bez cofania. Wizyta znika z
  kolejki, osoby i zasób są wolne od teraz, link klienta przestaje działać,
  zarezerwowane produkty wracają do magazynu.
- **Liczenie „Odbytych”**: jak dotąd (3A) — zakończone i te, których czas minął,
  ale bez nieobecności i odwołanych. Nowy wskaźnik `no_shows` („Nieobecności
  klientów”) obok „Odwołane”; tekst „Jak liczymy” idzie za regułą.

## Dla produktów

- **Nowy, opcjonalny klucz deskryptora `backend.appointmentKindsCompletedExplicitly`**:
  rodzaje wizyt, które moduł zamyka sam (np. po pracy w terenie). Dla nich
  wizyta, która minęła bez zakończenia, **nie** liczy się jako odbyta, a panel
  pokazuje ją jako „Niezakończona” (`closes_explicitly: true` w odpowiedzi).
  `""` oznacza zwykłą usługę bez rodzaju — produkt może ją wpisać, gdy wszystkie
  jego wizyty zamyka w ten sposób (HoofCare: rezerwacje sprzed 15a).
- **Wizyta w odpowiedzi API ma dwa nowe pola**: `passed` i `closes_explicitly`.
- **Obserwatorzy dostają nową zmianę `no_show`** (`booking.api.NO_SHOW`).
  Obserwator, który nie zna zmiany, ma ją pominąć; produkt, który odwzorowuje
  status wizyty (rejestr rolnika w HoofCare), dopisuje nieobecność u siebie.
- Etykiety akcji i stanu produkt może nadpisać w swoich komunikatach
  (`Calendar.noShow`, `Calendar.status.no_show`, `Calendar.status.unclosed`).

## Wdrożenie

`migrate` (organizations 0057 — wybory pola akcji audytu), przebudowa backendu
i frontendu. Bez zmian `.env` i sekretów.
