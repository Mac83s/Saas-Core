# Rezerwacje uniwersalne, faza 4a: klient w `shared.customers` — wydanie 2026-10-03

Zakres: plaster 4a fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§2 i „Uzupełnienie 2026-10-03: faza 4 w plastrach”). Migracje `customers` 0001
i `booking` 0029 — obie zmieniają wyłącznie stan modeli i są odwracalne; do
bazy nie idzie żadne polecenie. Produkty biorą je przez `core:update`;
**zmiana profilu w pkt „Dla produktów”**.

## Co się zmieniło

- **Nowy moduł `shared.customers`** (`dependsOn: core.organizations`): klient
  końcowy firmy to jeden rekord dla rezerwacji, a potem zamówień i sklepu.
  `Customer` przeszedł z `shared.booking` samym stanem modelu: tabela
  `booking_customer`, jej dane, polityka RLS i strażnik relacji zostają tam,
  gdzie były. Na razie moduł nie ma adresu API ani uprawnień — dostanie je z
  dokumentami firmy (plaster 4b).
- **`shared.booking` zależy od `shared.customers`** i sięga do klienta przez
  `customers.api`: `match_or_create` (dawne `upsert_customer`),
  `strip_customer`, `Customer`, `CUSTOMER_MODEL`.
- **Czyszczenie danych klienta ma rejestr.** `customers.strip_customer` czyści
  wiersz klienta i woła moduły, które coś o nim trzymają
  (`register_customer_anonymizer`); booking zarejestrował czyszczenie wizyt
  (uwagi, ulica, link samoobsługi, zapisane e-maile). Ręczna anonimizacja z
  panelu i przebieg retencji działają jak dotąd.
- **`deployment-check`** odrzuca profil z `shared.customers` bez
  `shared.booking` (tabelę klienta zakładają migracje rezerwacji) oraz typ
  organizacji, który ma `shared.booking` bez `shared.customers`.

## Dla produktów — zmiana profilu

1. **Każdy profil z `shared.booking` dopisuje `shared.customers`** do `modules`
   (`deployments/<produkt>/deployment.json` i lokalny `<produkt>-local`), a
   **każdy typ organizacji z `shared.booking`** — do swoich `modules`
   (HoofCare: `trimming_company`, `farm`; MedPlano: `business`). Bez tego
   `pnpm deployment:check` zatrzyma się na „shared.booking wymaga modułu
   shared.customers” albo „typ … używa shared.booking bez shared.customers”.
   Po zmianie: `pnpm deployment:artifact` (także `--profile <produkt>-local`).
2. Kod produktu, który importował `Customer` z `booking.models` albo wołał
   `booking.services.upsert_customer` / `strip_customer`, bierze je z
   `saas_core.modules.shared.customers.api` (`match_or_create`,
   `strip_customer`). Dziś żaden wertykał tego nie robi; `create_appointment(
   customer_data=…)` z `booking.api` zostaje bez zmian.
3. Produkt, który dowiesza do wizyty własne dane klienta, rejestruje ich
   czyszczenie przez `register_customer_anonymizer` w `AppConfig.ready`.

## Wdrożenie

`migrate` wykona `customers` 0001 i `booking` 0029 (bez zmian w bazie); wpis w
`memex ops` dla Saas-Core. Backend i frontend przebudować razem, bo zmienia
się artefakt profilu.
