# Rezerwacje uniwersalne, faza 4b: dokumenty firmy i dziennik zgód — wydanie 2026-10-03

Zakres: plaster 4b fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§9 i „Uzupełnienie 2026-10-03: faza 4 w plastrach”). Migracje `customers`
0002, 0003 i 0004, wszystkie odwracalne. Produkty biorą je przez
`core:update`; **uprawnienia ról w pkt „Dla produktów”**.

## Co się zmieniło

- **Dokumenty dla klientów** (`shared.customers`): regulamin rezerwacji,
  regulamin sklepu, polityka prywatności i polityka anulowania. Każdy ma szkic,
  który pisze osoba z `customers.manage`, i wersje, które zatwierdza wyłącznie
  osoba po świeżym kodzie z aplikacji uwierzytelniającej (403
  `step_up_required`; automat dostaje `person_required`). Wersja obowiązuje od
  daty, ma tekst na język i jest tylko do dopisywania — baza odmawia zmiany i
  usunięcia wersji, tekstu i wpisu zgody (poza usunięciem całej firmy).
  Poprawka to nowy wiersz tekstu, zmiana treści to kolejna wersja.
- **API** pod `/api/v1/customers/documents/`: lista, odczyt, `…/draft/`,
  `…/approve/` z podglądem `…/approve/preview/` (`x-dry-run`), `…/texts/`.
  Zapisy są zablokowane wersją dokumentu (`expected_version`, 409
  `customers_document_version_conflict`).
- **Publiczny adres dokumentu**: strona platformy
  `/<język>/documents/<identyfikator>` (API
  `GET /api/v1/public/documents/<identyfikator>/`), firmę wyznacza indeks
  routingu bez danych osobowych `customers_documentroute`.
- **Panel**: Ustawienia › „Dokumenty dla klientów” (lista i strona dokumentu).
- **Dwa czytniki dla innych modułów** (`customers.api`), wołane w tenancie,
  który wywołujący już ma — wystarcza kontekst publicznego formularza:
  - `current_document(kind, locale)` → `DocumentInForce` (`document_id`,
    `kind`, `version`, `effective_from`, `text_id`, `locale`, `text`,
    `text_hash`, `url`) albo `None`, gdy nie ma obowiązującej wersji albo
    wersja nie ma tekstu w **tym** języku. Nigdy nie podstawia innego języka.
  - `record_consent(source=…, source_reference=…, customer=None, text_id=…,
    kind="document" | "marketing" | "field", wording="", locale="",
    granted=True)` — dopisuje wpis dziennika zgód w transakcji wywołującego.
    `customer` może być pusty: pytającego z formularza kontaktowego wskazuje
    wtedy sam `source` i `source_reference` (np. `sites.inquiry` i identyfikator
    zapytania). Wycofanie zgody to kolejny wpis z `granted=False`.
- **Uprawnienia**: `customers.read` (manager, admin, owner) i
  `customers.manage` (admin, owner).

## Dla produktów

1. Typ organizacji z własną listą ról (`organizationTypes[].roles`) dopisuje
   `customers.read` i `customers.manage` tym rolom, które mają widzieć i
   prowadzić dokumenty; role systemowe dostają je migracją `customers` 0004.
2. Moduł produktu, który pokazuje klientowi dokument albo zbiera zgodę, woła
   oba czytniki z `customers.api` — nie trzyma własnej kopii tekstu ani
   własnego dziennika.
3. Formularz publiczny rezerwacji jeszcze dokumentów nie pokazuje — to plaster
   4c.

## Wdrożenie

`migrate` wykona `customers` 0002 (tabele), 0003 (RLS, strażnik relacji,
wyzwalacze „tylko do dopisywania”) i 0004 (uprawnienia ról); wpis w
`memex ops` dla Saas-Core. Backend i frontend przebudować razem (nowe API,
nowy ekran, zmieniony artefakt profilu).
