# Magazyn włączony wszędzie — wydanie 2026-09-23

Zakres: faza 8 planu memex `magazyn-materia-o-w-od-pakietu-korektora-do-kare`,
przesunięta przed fazę 6, żeby właściciel mógł przetestować magazyn na swoim
koncie. Decyzja z 23.09: moduł domyślnie włączony wszędzie, także tam, gdzie
może nie być używany.

| Aplikacja | Kod (backend i frontend) |
| --- | --- |
| Saas-Core / vps-dev | `5a00fed` |
| HoofCare | `5333f01` (rdzeń `5a00fed`) |
| MedPlano | `c47cdcb` (rdzeń `5a00fed`) |

## Co się zmieniło

- Profile `business` i `vps-dev` (Saas-Core) oraz `medplano` składają
  `shared.inventory`. Migracja modułu wydała nowe wersje wszystkich planów z
  cechą `inventory.enabled` (ceny, limity i okresy próbne bez zmian).
- HoofCare: typ `farm` (gospodarstwo) dostał moduł z kategoriami rdzenia;
  właściciel i administrator prowadzą magazyn, kierownik stada i pracownik
  widzą i zużywają swój zapas.
- Role systemowe rdzenia `staff`, `manager`, `admin`, `owner` mają
  `inventory.use`.

## Wdrożenie

- Trzy stacki po kolei: kopia bazy, migracje (`inventory 0001–0008` na
  Saas-Core i MedPlano), `check_database_role`, skaner `CLEAN`, zero zaległych
  migracji, `/healthz` 200.
- Abonamenty przeniesione na nowe wersje planów (spis → próba z wycofaniem →
  zastosowanie): Saas-Core 1 (Witryna v5 → v6, doszedł tylko magazyn; stan,
  termin i cena bez zmian; wpis `billing.reconciled`). HoofCare i MedPlano —
  nic do przeniesienia (plany HoofCare miały magazyn od 21.09, MedPlano nie ma
  organizacji).
- Obrazy do wycofania: `<projekt>-{backend,frontend}:rollback-inventory-everywhere-20260923`.

## Odbiór

- [x] backend rdzenia na profilu `vps-dev` **955 PASS, 29 SKIP**; MedPlano
  **957 PASS, 27 SKIP**; HoofCare gospodarstwa, role, typy i magazyn 59/59;
  kontrakty profili 35/35; frontend lib, i18n, HoofCare i gospodarstwa 139/139;
- [x] na żywo `saas.goldenstar.cloud` i `medplano.goldenstar.cloud` (konta
  testowe): „Magazyn” w menu panelu, kategorie rdzenia (Produkt, Materiał,
  Narzędzie, Inne), dodanie pozycji i przyjęcie 5 szt. widoczne w stanach;
  zero błędów strony; konta usunięte.

Uwaga: opis nagłówka panelu („…i z czym ludzie wyjeżdżają w teren”) i
podwójne „Magazyn” pasują do HoofCare bardziej niż do ogólnej firmy — do
poprawy przy następnej zmianie panelu.

Dowody (prywatne): `.runtime/releases/20260923-inventory-everywhere/`.
