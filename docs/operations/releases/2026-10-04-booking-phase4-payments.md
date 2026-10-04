# Rezerwacje uniwersalne, faza 4f-1: wpłaty ręczne — wydanie 2026-10-04

Zakres: pierwsza część plastra 4f fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§4 i „Rozstrzygnięcia plastra 4f-1”). Migracje `commerce` 0005, 0006 i 0007.
Dotyczy tylko profili z modułem `shared.commerce`.

## Co się zmieniło

- **Firma oznacza wpłatę w zamówieniu.** Na stronie zamówienia jest sekcja
  „Wpłaty” (wpłacono, zostało do zapłaty, lista wpłat z osobą, która je
  oznaczyła) i przycisk „Oznacz wpłatę”: kwota (domyślnie to, co zostało) i
  sposób — na miejscu (gotówka albo karta) albo przelew. Status zamówienia
  wynika z wpłat: „Opłacone częściowo”, „Opłacone”.
- **Księga tylko do dopisywania.** Każda wpłata to wpis księgi; o tym, ile
  wpłacono, rozstrzyga suma wpisów, nie pole, które ktoś poprawia. Wpłatę
  oznaczoną przez pomyłkę się wycofuje („Wycofaj”): zostaje w historii jako
  wycofana, a księga dostaje wpis przeciwny. To nie jest zwrot — zwroty to
  plaster 4h.
- **Przeniesienie i odwołanie rezerwacji nie ruszają wpłat.** Droższy termin
  po pełnej wpłacie daje „Opłacone częściowo”; anulowane zamówienie z wpłatą
  pokazuje „Wpłacono (do oddania klientowi)”.
- **API**: `POST /api/v1/commerce/orders/<id>/payments/` (z `…/preview/`
  bez zapisu) i `POST …/payments/<payment_id>/void/`; szczegół zamówienia
  niesie `paid_minor`, `due_minor` i `payments`, a `options` —
  `manual_methods`. Zapis podaje `expected_version`; nieaktualna wersja to 409
  `order_version_conflict` i nic się nie zapisuje.
- **Uprawnienie** `commerce.payments.manage` (kierownik, administrator,
  właściciel).

## Dla produktów

Produkt bez `shared.commerce` nie widzi żadnej zmiany. Produkt z modułem
dostaje ekran i API z `core:update`; role własnych typów organizacji, które
mają oznaczać wpłaty, dostają `commerce.payments.manage` w swoim profilu.

## Wdrożenie

1. `python manage.py migrate` — `commerce` 0005 (tabele `commerce_payment`,
   `commerce_ledgerentry`), 0006 (RLS, strażnik relacji, księga tylko do
   dopisywania), 0007 (uprawnienie `commerce.payments.manage` dla ról
   systemowych `manager`, `admin`, `owner`). Wszystkie odwracalne.
2. Backend i frontend przebudować razem.
