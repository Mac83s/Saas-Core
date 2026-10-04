# Rezerwacje uniwersalne, faza 4h: progi zwrotu, zwroty ręczne i dopłata przelewem — wydanie 2026-10-04

Zakres: plaster 4h fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
§8,
[ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§5, §8 i „Rozstrzygnięcia plastra 4h”). Migracje `booking` 0032, `commerce`
0009 i 0010.

## Co się zmieniło

- **Oferta ma progi zwrotu.** W „Cenniku” oferty, pod sposobem płatności:
  „Rezygnacja klienta i zwrot” — wiersze „co najmniej N dni przed początkiem
  → zwrot P%”, najwyżej sześć. Mniej dni niż w ostatnim progu to brak zwrotu;
  oferta bez progów oddaje klientowi wszystko. Przy przedpłacie przełącznik
  „Progi zwrotu obejmują też dopłatę” (domyślnie wyłączony: progi dotyczą
  samej przedpłaty, reszta wpłat wraca w całości).
- **Rezerwacja zachowuje warunki, na których ją złożono.** Progi trafiają do
  zamrożonej wyceny; klient widzi je przy cenie w formularzu i pod swoim
  linkiem. Zmiana progów w ofercie nie rusza istniejących rezerwacji.
- **Rezygnacja klienta rozlicza wpłatę według progów**, licząc dni kalendarza
  firmy do początku rezerwacji. Link klienta mówi przed kliknięciem, ile
  wróci. **Odwołanie przez firmę oddaje wszystko** — okno „Odwołać wizytę?”
  pokazuje, ile klient wpłacił i ile jest do oddania.
- **Zwrot ręczny w zamówieniu.** Anulowane zamówienie z wpłatą pokazuje „Do
  oddania klientowi” i — gdy coś zostaje — „Zostaje po anulowaniu”. Firma
  oddaje pieniądze sama (przelew, na miejscu) i klika „Oznacz zwrot”; zwrot
  ponad to, co wynika z warunków, wymaga powodu. Zwrot oznaczony przez pomyłkę
  się wycofuje. Zapis niczego nie przelewa.
- **Reszta ceny przelewem przed początkiem.** Przy „Przedpłata” oferta może
  kazać dopłacić resztę przelewem N dni przed początkiem rezerwacji. Po
  wpłacie przedpłaty klient dostaje dane do przelewu reszty, przed terminem
  przypomnienie (Ustawienia › Płatności klientów › „Dopłaty przelewem”,
  domyślnie 3 dni wcześniej), a po terminie wiadomość.
- **Spóźniona dopłata niczego nie odwołuje.** Rezerwacja zostaje potwierdzona;
  osoby oznaczające wpłaty dostają powiadomienie w panelu i e-mail. Firma,
  która zdecyduje się odwołać taką rezerwację, może w oknie odwołania
  zaznaczyć, że powodem jest niewpłacona dopłata — wtedy wpłata jest
  rozliczana według progów, jak przy rezygnacji klienta.
- **E-maile do klienta**: `commerce.balance_details`,
  `commerce.balance_overdue`, `commerce.refund_settled` (pl, en, de); do
  firmy: `commerce.office_balance_overdue` (pl, en).
- **API**: usługa — `cancellation_refunds`, `cancellation_applies_to`,
  `balance_due_days_before`; `GET /api/v1/booking/setup/options/` —
  `refund_thresholds`, `cancel_reasons`; wycena — `cancellation`,
  `prepayment.balance_due_days_before`; `POST
  /api/v1/booking/appointments/<id>/cancel/` przyjmuje `reason`
  (`balance_overdue`; 400 `balance_not_overdue`) i ma teraz identyfikator
  operacji `booking_appointment_cancel`; `GET
  /api/v1/booking/appointments/<id>/settlement/`; wizyta klienta —
  `settlement`, `payment.kind`; zamówienie — `refunded_minor`,
  `refund_owed_minor`, `refunds`; `POST
  /api/v1/commerce/orders/<id>/refunds/`, `…/refunds/preview/`,
  `…/refunds/<refund_id>/void/` (`refund_exceeds_paid`, `reason_required`,
  `refund_not_voidable`); grupa ustawień `commerce.balance`.

## Dla produktów

- Oferty produktu nie mają progów ani terminu dopłaty, więc nic się nie
  zmienia, dopóki firma ich nie wpisze. Bez `shared.commerce` pola oferty
  istnieją, ale nie ma wpłat, więc niczego nie rozliczają.
- `cancel_appointment` z `booking.api` ma nowy, opcjonalny argument `reason`;
  wywołania bez niego działają jak dotąd.
- Wycena w `Appointment.quote` ma nowy klucz `cancellation` (`null` bez
  progów). Skrót wyceny ofert bez progów się nie zmienia.
- Źródło zamówień, które rejestruje `OrderHandler`, może podać `link` —
  adres kupującego do późniejszych wiadomości; bez niego nic się nie zmienia.

## Wdrożenie

1. `python manage.py migrate` — `booking` 0032 (trzy pola usługi),
   `commerce` 0009 (`Order.refund_due_minor`, tabela `commerce_refund`) i
   0010 (RLS i strażnik relacji tabeli zwrotów). Odwracalne.
2. Backend, worker, scheduler i frontend przebudować razem. Harmonogram się
   nie zmienia: dopłaty ogląda to samo zadanie `commerce-expire-due-payments`.

## Czego wydanie nie robi

- Nie przelewa pieniędzy: zwrot i dopłata online przyjdą z operatorem
  płatności (faza 7).
- Nie daje asystentowi poleceń dla progów, zwrotów ani wpłat.
- Nie planuje dopłaty dla rezerwacji bez przedpłaty ani bez rachunku firmy —
  reszta idzie wtedy na miejscu.
- Żaden gotowy wzorzec oferty nie przynosi jeszcze progów.
