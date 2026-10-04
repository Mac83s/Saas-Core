# Rezerwacje uniwersalne, faza 4f-2: przelew z terminem — wydanie 2026-10-04

Zakres: druga część plastra 4f fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§5 i „Rozstrzygnięcia plastra 4f-2”,
[ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
§8–§9). Migracje `commerce` 0008 i `booking` 0030. Rezerwacja oczekująca
powstaje tylko w profilach z modułem `shared.commerce`.

## Co się zmieniło

- **Rachunek firmy do przelewów.** Ustawienia › „Płatności klientów”:
  właściciel rachunku, numer (26 cyfr albo IBAN, sprawdzany) i opcjonalnie
  bank. Zmiana wymaga kodu z aplikacji uwierzytelniającej. Zmienia go osoba z
  uprawnieniem `commerce.payments.manage`.
- **Oferta może prosić o wpłatę przed potwierdzeniem.** W „Cenniku” oferty,
  pod „Jak płaci klient”: „Całość przelewem przed wizytą”, „Przedpłata, reszta
  na miejscu” (z procentem, domyślnie 30) i „Całość z góry”, z liczbą dni na
  przelew (domyślnie 3). „Całość przelewem” wymaga rachunku; przedpłata i
  całość bez rachunku są płacone na miejscu, a rezerwacja jest potwierdzana od
  razu.
- **Rezerwacja czeka na wpłatę.** Rezerwacja takiej oferty ma status „Czeka na
  wpłatę”: trzyma termin jak potwierdzona, do terminu wpłaty (dni z oferty,
  nigdy później niż początek rezerwacji). Klient dostaje e-mail z danymi do
  przelewu i numerem zamówienia jako tytułem; widzi je też na stronie po
  rezerwacji i pod swoim linkiem. Potwierdzenie i przypomnienie przychodzą
  dopiero po wpłacie.
- **Wpłatę oznacza firma w zamówieniu.** Zamówienie pokazuje, ile i do kiedy
  jest oczekiwane; „Oznacz wpłatę” zaczyna od tej kwoty. Wpłata co najmniej
  tej kwoty potwierdza rezerwację; mniejsza zostaje zapisana, a reszta jest
  nadal oczekiwana.
- **Bez wpłaty rezerwacja wygasa.** Po terminie zadanie `commerce` anuluje
  zamówienie i zwalnia termin; klient dostaje e-mail o wygaśnięciu, a biuro —
  powiadomienie, gdy firma je włączyła.
- **Wizyta w kalendarzu prowadzi do zamówienia** (dla osób, które mogą czytać
  zamówienia).
- **API**: oferta — `payment_policy` (`transfer`, `deposit`, `full`),
  `deposit_percent`, `transfer_due_days`, odmowy `transfer_account_missing` i
  `orders_required`; wycena — `prepayment`; wizyta — status `pending_payment`,
  `hold_expires_at`, `order`; odpowiedź dla klienta — `payment` (dane do
  przelewu); zamówienie — wpłaty `requires_payment` z `due_at`, podgląd wpłaty
  z `prepayment_met`; `commerce/options` — `transfer_account_set`; ustawienia
  — grupa `commerce.transfer`.

## Dla produktów

- Produkt bez `shared.commerce` rezerwuje jak dotąd: polityk z wpłatą z góry
  jego oferty nie przyjmują (`orders_required`), więc `pending_payment` nie
  powstaje.
- **Zakresy kontraktów `service` deklaruje moduł.** Lista w
  `core.organizations.tasks._service_context` zniknęła. Wertykał, który
  podpisuje własną pracę kontraktem `service`
  (`issue_service_task_contract`), deklaruje jego rolę w `AppConfig.ready`:
  `register_service_scope(role_key, uprawnienia, exact=…)` z
  `core.organizations.api` — inaczej zadanie odrzuci kontrakt („niedozwolony
  zakres”). Role rdzenia (`public_booking`, `booking_reminder`,
  `booking_notify`, `public_site_inquiry`, `inventory_notifications`,
  `translation_notifications`) deklarują ich moduły.
- Obserwatorzy rezerwacji dostają `CREATED` dopiero przy potwierdzeniu; o
  rezerwacji, która wygasła albo z której klient zrezygnował, zanim została
  opłacona, nie dowiadują się niczego.
- `shared.commerce` zależy teraz także od `shared.notifications`.

## Wdrożenie

1. `python manage.py migrate` — `commerce` 0008 (tabela tras terminów
   `commerce_paymentroute`, bez danych osobowych) i `booking` 0030 (pola
   `hold_expires_at`, `deposit_percent`, `transfer_due_days`, nowe wartości
   statusu i polityki). Obie odwracalne.
2. Backend, worker, scheduler i frontend przebudować razem: zadanie
   `commerce-expire-due-payments` dochodzi do harmonogramu z deskryptora
   modułu, a artefakty profili (`module-artifact.json`) mają nowe skróty.
