# Rezerwacje uniwersalne, faza 4c: rezerwacja zapisuje zgody — wydanie 2026-10-04

Zakres: plaster 4c fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§9 i „Rozstrzygnięcia plastra 4c”). Bez migracji. Produkty biorą zmianę przez
`core:update`; **uwaga dla własnych formularzy w pkt „Dla produktów”**.

## Co się zmieniło

- **Formularz publiczny rezerwacji** pokazuje regulamin rezerwacji i politykę
  prywatności firmy obowiązujące w języku strony: pole do zaznaczenia z
  oświadczeniem („Akceptuję regulamin”, „Zapoznałem się z polityką
  prywatności”) i odnośnik do strony dokumentu. Bez zaznaczenia nie da się
  zarezerwować. Dokument bez tekstu w tym języku nie jest pokazywany ani
  wymagany — nigdy nie podstawiamy innego języka.
- **API**: `GET /api/v1/booking/public/<slug>/consents/?locale=` oddaje język
  rezerwacji i dokumenty do pokazania; `POST …/appointments/` przyjmuje
  `consents.documents` (lista `text_id`). Brak obowiązującego dokumentu na
  liście albo inny tekst niż obowiązujący to 409 `documents_changed` z
  aktualną listą w `detail.documents` — formularz pokazuje ją i pyta ponownie.
- **Dziennik zgód**: każdy zaakceptowany dokument to wpis
  `source="booking.appointment"`, `source_reference=<id rezerwacji>`, ze
  wskazaniem klienta i wiersza tekstu, dopisany w transakcji rezerwacji.
- **Formularz rezerwuje w języku strony**: `customer.locale` to język strony
  (wcześniej formularz wysyłał tylko `pl` albo `en`, więc klient ze strony
  niemieckiej dostawał polskie potwierdzenie).
- Firma, która nie opublikowała dokumentów, nie widzi żadnej zmiany.

## Dla produktów

1. Formularz publiczny z rdzenia działa bez zmian po stronie produktu.
2. Własny formularz produktu, który rezerwuje w kontekście publicznym
   (`public_booking_context`), musi od teraz wysłać `text_id` dokumentów
   obowiązujących w języku rezerwacji — inaczej dostanie 409
   `documents_changed`, gdy tylko firma opublikuje regulamin albo politykę.
   Listę daje `booking.consents.shown(locale)`, zapis — parametr
   `consents=BookingConsents(documents=…)` w `create_appointment` i
   `book_stay`.
3. Rezerwacja robiona przez zespół (panel, API z członkostwem) niczego nie
   wymaga i niczego nie zapisuje w dzienniku.
4. Zgoda marketingowa: `BookingConsents(marketing="<treść zgody>")` dopisuje
   osobny wpis; formularz z rdzenia jej nie zbiera.

## Wdrożenie

Bez migracji i bez nowych ustawień. Backend i frontend przebudować razem
(nowe pole żądania i nowy odczyt).
