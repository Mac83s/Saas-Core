# Rezerwacje uniwersalne, faza 2 (ADR-072) — wydanie 2026-10-03

Zakres: kawałek ADR-072 §11 i plastry 2a–2c fazy 2 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md),
[ADR-078](../../adr/ADR-078-Ustawienia-Platformy-i-Firmy-Jeden-Rejestr.md) pkt 17).
Migracje `booking` 0015–0018, wszystkie odwracalne. Produkty biorą je przez
`core:update`; **zmiana kształtu danych w pkt „Dla produktów”**.

## Co się zmieniło

- **Zapisy konfiguracji (§11).** Usługa, miejsce, zasób, grupa, tydzień osoby,
  blokada jednostki, sezon i dzień zamknięty: każdy zapis ma wymagany
  `Idempotency-Key` (pokwitowanie `BookingSetupMutation`), każda zmiana podaje
  `expected_version` (nieaktualna — 409 `booking_version_conflict`), a obok
  każdego zapisu jest `…/preview/` (`x-dry-run`) — ten sam zapis w wycofanym
  savepoincie. Warianty i domyślne usługi: `GET /api/v1/booking/setup/options/`.
  Błędy tygodnia wskazują regułę: `rules.<i>.location_id`, `.local_end`,
  `.local_start`.
- **Jednostki i grupy (2a).** Zasób ma grupę, miejsce, pojemność i opis;
  `ResourceGroup` to pula takich samych jednostek. Blokada jednostki trzyma
  czas własną alokacją pod tym samym `EXCLUDE` co rezerwacja; migracja 0016
  nadaje alokacje istniejącym blokadom zasobów i wypisuje, ile nachodziło na
  rezerwację (te zostają nieaktywne, ale dalej zajmują termin).
- **Sezony i dni zamknięte (2b).** `BookingRule` — warstwa datowana oferty,
  grupy albo jednostki; `BookingClosure` — dni zamknięte firmy albo miejsca,
  które wyłączają starty wizyt (strona i panel). „Skopiuj na kolejny rok” dla
  obu.
- **Pobyty (2c).** Usługa ma `time_model` (`slot` — wizyta, `range` — pobyt
  albo wynajem od–do) i dla `range`: `range_unit` (`night`, `day`), godziny
  zameldowania i wymeldowania (odbioru i zwrotu) oraz grupy jednostek.
  Pobyt to `Appointment` bez osoby: `staff_required` 0, puste `staff`.
  `POST /api/v1/booking/stays/` (z podglądem), dni przyjazdu
  `GET …/stays/starts/`, dni wyjazdu `GET …/stays/ends/`, przełożenie
  `POST …/appointments/{id}/stay/`. Sezon dnia przyjazdu decyduje o regułach.
- **Link samoobsługi** żyje co najmniej do końca rezerwacji (wcześniej 30 dni
  od jej utworzenia).

## Dla produktów — zmiana kształtu danych

1. **`Appointment.staff` może być puste** — wtedy i tylko wtedy, gdy
   `staff_required = 0` (CHECK `booking_appointment_staff_ck`), czyli dla
   pobytu (`service.time_model == "range"`). Kod produktu, który dostaje
   dowolną rezerwację (obserwator zmian, `list_appointments` bez filtra
   rodzaju, `appointment_for_tenant`), **najpierw sprawdza rodzaj**
   (`appointment.service.appointment_kind` należy do produktu) albo
   `appointment.staff is not None`, a dopiero potem czyta `appointment.staff`.
   Wizyty rodzajów produktu (`appointmentKinds`) zawsze mają osobę.
2. **`Service.duration_minutes` może być puste** dla `range`. Długość wizyty
   bierz z `service.slot_duration` (podnosi wyjątek dla oferty okresu).
3. **Katalog kalendarza** (`list_catalog`, `GET /booking/catalog/`) i
   publiczny katalog formularza zwracają tylko usługi `slot`; pobyty mają
   własne endpointy.
4. **API konfiguracji** wymaga `Idempotency-Key` i `expected_version` —
   skrypty i fixture'y produktu, które wołają `/booking/setup/…` albo
   `/booking/staff/{id}/hours/`, muszą je wysyłać.
5. `create_appointment` odmawia usługi `range` (400 `not_a_slot_offer`),
   `reschedule_appointment` odmawia pobytu (400 `stay_moves_by_dates`), a
   przydział osób odmawia pobytu (400 `no_people_needed`).

## Wdrożenie

`memex ops` dla Saas-Core: mac-20261002-26 (0015), -27 (0016), -31 (0017) i
wpis 0018 z tym wydaniem; backend i frontend razem (panel wysyła klucz i wersję).
