# Rezerwacje, faza 3.0: presety i pracownik dla asystenta — wydanie 2026-10-03

Zakres: plaster 3.0 fazy 3 planu memex `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
§10–§11 i „Uzupełnienie 2026-10-03”). Migracja `booking` 0024, odwracalna
(same nowe kolumny usługi). Produkty biorą ją przez `core:update`.

## Co się zmieniło

- **Presety w obrazie.** `apps/backend/Dockerfile` kopiuje
  `packages/contracts/booking-presets` i ustawia
  `BOOKING_PRESET_CONTRACTS_PATH=/app/contracts/booking-presets` — nowej linii
  w `.env` nie trzeba. System check `booking.E010` zatrzymuje start, gdy
  katalogu albo pliku wersji z manifestu brakuje.
- **Lista presetów.** `GET /api/v1/booking/presets/` (dla ustawiających
  usługi): kolejność manifestu, najnowsza wersja każdego, `readiness`
  `ready` | `soon`. Polecenie asystenta `booking.preset.list@1`.
- **Zastosowanie presetu.** `presets.apply_preset` i `booking.preset.apply@1`:
  nowa usługa, zawsze wyłączona, z pochodzeniem (`preset_id`,
  `preset_version`, rozmowa asystenta). Dziś stosuje się tylko „Wizyta u
  specjalisty”; pozostałe odpowiadają `preset_not_ready`.
- **Szkic.** Usługa ma `draft` — nigdy niewłączona. `setup.discard_draft`
  usuwa szkic bez rezerwacji; usługa choć raz włączona zostaje. Konfiguracja
  (`GET /api/v1/booking/setup/`) zwraca przy usłudze `draft`, `preset_id`,
  `preset_version`.
- **Dodanie pracownika jest zapisem konfiguracji (§11).**
  `POST /api/v1/booking/staff/` wymaga `Idempotency-Key`; ten sam klucz
  odpowiada pierwszym wynikiem (200), klucz użyty do innego żądania — 409.
  `staff.add_person` nie przyjmuje już `request`, ma `preview` i zwraca
  `Saved[StaffMember]`; zaproszenie powstaje w tym samym zapisie, więc podgląd
  je pokazuje i wycofuje.

## Dla produktów

1. **Obraz backendu trzeba przebudować** po `core:update` — Dockerfile jest
   plikiem rdzenia i sam przyniesie kopię presetów, ale stary obraz jej nie ma
   i nie przejdzie kontroli startowej. Backend, worker i scheduler z jednego
   commita, jak zawsze.
2. Skrypty i fixture'y, które wołają `POST /booking/staff/`, wysyłają
   `Idempotency-Key`. Kod produktu nie woła `staff.add_person` (sprawdzone w
   HoofCare i MedPlano 03.10).
3. Usługi produktu sprzed migracji mają `draft = false` — nie da się ich
   usunąć, tylko wyłączyć, jak dotąd.
