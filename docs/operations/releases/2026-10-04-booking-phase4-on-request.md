# Rezerwacje uniwersalne, faza 4g: rezerwacja „na prośbę” — wydanie 2026-10-04

Zakres: plaster 4g fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
§8–§9,
[ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
„Rozstrzygnięcia plastra 4g”). Migracja `booking` 0031. W tym wydaniu także
poprawka ustawień firmy (niżej).

## Co się zmieniło

- **Usługa może być potwierdzana „na prośbę”.** W „Edytuj usługę”, w części o
  rezerwacji online: „Potwierdzenie rezerwacji” — „Od razu” albo „Na prośbę”,
  z liczbą godzin na odpowiedź (domyślnie 24).
- **Prośba klienta trzyma termin i czeka.** Rezerwacja takiej usługi z
  formularza na stronie ma status „Czeka na odpowiedź”: termin jest zajęty do
  czasu odpowiedzi (godziny z usługi, nigdy później niż początek rezerwacji).
  Klient dostaje e-mail z terminem odpowiedzi i linkiem, pod którym może z
  prośby zrezygnować. Rezerwacje wpisane przez zespół w panelu nie czekają.
- **Firma odpowiada w oknie wizyty.** W kalendarzu wizyta ma „Czeka na
  odpowiedź” i „Odpowiedz do…”, a w jej oknie są „Przyjmij rezerwację” i
  „Odmów”. Przyjęta rezerwacja jest potwierdzona (klient dostaje
  potwierdzenie) albo — gdy oferta prosi o wpłatę z góry — czeka na wpłatę
  (klient dostaje dane do przelewu). Odmowa zwalnia termin i klient dostaje
  wiadomość.
- **Bez odpowiedzi prośba wygasa.** Po terminie zadanie `booking` zwalnia
  termin; klient i osoby zarządzające rezerwacjami dostają wiadomość. O nowej
  prośbie i o jej wygaśnięciu osoby zarządzające rezerwacjami dowiadują się
  zawsze, także przy wyłączonych powiadomieniach biura.
- **Zamówienie prośby jest szkicem bez numeru.** Numer dostaje przy przyjęciu
  rezerwacji; do tego czasu nie przyjmuje wpłat. Odmowa i wygaśnięcie anulują
  szkic, więc numeracja zamówień nie ma dziur.
- **API**: usługa — `confirmation`, `response_hours`; wizyta — status
  `pending_request`; `POST /api/v1/booking/appointments/<id>/accept/` i
  `…/decline/` (z `Idempotency-Key`; 409 `appointment_not_changeable`, gdy
  rezerwacja już nie czeka na odpowiedź); katalog publiczny — `confirmation` i
  `response_hours` usługi; zamówienie — status `draft`, odmowa wpłaty
  `order_not_placed`.
- **Poprawka ustawień firmy**: zmiana jednego pola grupy ustawień nie pokazuje
  już pozostałych pól firmy jako przywróconych do wartości domyślnych
  (podgląd, historia zmian, sprawdzenia grupy). Zapisane wartości nie były
  naruszane; błędny był opis zmiany i sprawdzenie — przy rachunku do przelewów
  odmawiało zmiany nazwy banku, gdy czekała wpłata.

## Dla produktów

- Usługi produktu zostają „Od razu”; nic się nie zmienia, dopóki firma nie
  wybierze „Na prośbę”. Rezerwacja oczekująca działa także bez
  `shared.commerce` — wtedy bez zamówienia.
- Obserwatorzy rezerwacji dostają `CREATED` dopiero przy potwierdzeniu; o
  prośbie odrzuconej, wygasłej albo wycofanej nie dowiadują się niczego.
- Kod produktu, który pyta „czy ta rezerwacja się odbędzie”, porównuje status
  z `confirmed` i pozostaje poprawny; kto pyta „czy termin jest zajęty”, czyta
  alokacje.

## Wdrożenie

1. `python manage.py migrate` — `booking` 0031 (pola `confirmation` i
   `response_hours` usługi, status `pending_request`, tabela tras
   `booking_requestroute` bez danych osobowych). Odwracalna.
2. Backend, worker, scheduler i frontend przebudować razem: do harmonogramu
   dochodzi zadanie `booking-expire-requests`.
