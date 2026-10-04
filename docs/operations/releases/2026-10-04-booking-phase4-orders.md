# Rezerwacje uniwersalne, faza 4e: zamówienie — wydanie 2026-10-04

Zakres: plaster 4e fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§1, §3 i „Rozstrzygnięcia plastra 4e”). Nowy moduł `shared.commerce` z
migracjami `commerce` 0001, 0002, 0003 i 0004. Produkty biorą zmianę przez
`core:update`; **produkt, który nie dopisze modułu do profilu, działa jak
dotąd** (pkt „Dla produktów”).

## Co się zmieniło

- **Rezerwacja z ceną to zamówienie.** Gdzie profil ma `shared.commerce`, a
  plan firmy cechę `commerce.enabled`, nowa rezerwacja (wizyta albo pobyt) z
  wyceną zakłada w swojej transakcji zamówienie `R/<rok>/<NNNN>`: numer z
  licznika firmy (rok w strefie firmy), kupujący taki, jakim był w chwili
  rezerwacji, i pozycje dokładnie z zamrożonej wyceny — commerce niczego nie
  liczy. Rezerwacja bez ceny i rezerwacje sprzed wdrożenia zostają bez
  zamówień.
- **Przeniesienie po innej cenie** dopisuje zamówieniu kolejną rewizję pozycji;
  wcześniejsze pozycje zostają nietknięte (tabela pozycji jest tylko do
  dopisywania). **Odwołanie rezerwacji** anuluje zamówienie.
- **Panel „Zamówienia”** (kierownik, administrator, właściciel): lista z
  wyszukiwaniem po numerze, kupującym i e-mailu, filtrami statusu i kanału;
  szczegół z pozycjami, kwotami, odnośnikiem do dnia wizyty w kalendarzu i
  tym, co kupujący zaakceptował (wpisy dziennika zgód jego rezerwacji).
- **API**: `GET /api/v1/commerce/orders/`, `GET /api/v1/commerce/orders/<id>/`,
  `GET /api/v1/commerce/options/`; uprawnienie `commerce.orders.read`.
- **Kanał zamówienia**: `company_site` (formularz publiczny) albo `office`
  (rezerwacja zapisana przez zespół). Wartość `catalog` i podpisany token
  pochodzenia przyjdą z pierwszym odnośnikiem z katalogu do formularza (faza 5).
- **Anonimizacja klienta** czyści kupującego na jego zamówieniach; numery,
  pozycje i kwoty zostają. **Firma z zamówieniami nie zmieni waluty**
  (`currency_in_use`).
- Zamówienie nie ma jeszcze wpłat: status to „Do zapłaty” (albo „Opłacone”,
  gdy nie ma nic do zapłaty) i „Anulowane”. Wpłaty ręczne to plaster 4f.

## Dla produktów

1. `shared.commerce` jest opcjonalny dla rezerwacji: bez modułu w profilu nic
   się nie zmienia, a booking go nie importuje. HoofCare i MedPlano nie muszą
   robić nic.
2. Produkt, który chce zamówień, dopisuje `shared.commerce` do `modules`
   profilu (wymaga `shared.billing` i `shared.customers`) i do modułów typów
   organizacji, które mają rezerwacje, generuje artefakt
   (`pnpm deployment:artifact`) i uruchamia migracje.
3. Własny moduł sprzedający coś innego niż rezerwacje rejestruje się w
   `AppConfig.ready` przez `commerce.api.register_order_source(kind, prefix)`
   i składa zamówienie w swojej transakcji przez `place_order(...)`; skill
   `develop-commerce-payments`.

## Wdrożenie

1. `python manage.py migrate` — `commerce` 0001 (tabele), 0002 (RLS, strażnik
   relacji, pozycje tylko do dopisywania), 0003 (uprawnienie
   `commerce.orders.read` dla ról systemowych `manager`, `admin`, `owner`),
   0004 (cecha `commerce.enabled` w nowej wersji każdego planu). Wszystkie
   odwracalne.
2. Backend i frontend przebudować razem (nowy moduł, nowy ekran, nowy
   artefakt profilu).
3. **Firmy na dotychczasowej wersji planu nie mają cechy** — ich rezerwacje
   idą dalej bez zamówień, a ekran „Zamówienia” mówi o planie. Cechę daje
   zmiana planu albo nadpisanie operatora (`EntitlementGrant`).
