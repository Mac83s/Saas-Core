# Asystent: zamówienia, wpłaty i prośby; e-mail o zwrocie, „Zwrócone” i Nocleg w wersji 4 — wydanie 2026-10-04

Zakres: drobne pozycje po fazie 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz` i faza A3-6 planu
`saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy`
([ADR-076](../../adr/ADR-076-Asystent-AI-Rejestr-Polecen.md) „Uzupełnienie
2026-10-04: zamówienia, wpłaty i prośby o rezerwację”,
[ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
„Uzupełnienie po 4h”). Bez migracji.

## Co się zmieniło

- **Asystent czyta zamówienia i oznacza wpłaty.** „Które zamówienia czekają na
  wpłatę?”, „Klient wpłacił 300 zł gotówką za R/2026/0007, oznacz” — odczyt od
  razu, wpłata po osobnym kliknięciu, ze zdaniem serwera: kwota, sposób,
  zamówienie, ile zostaje. Kwotę i sposób podaje osoba; bez nich asystent pyta.
  Wpłatę oznaczoną przez pomyłkę wycofuje tak samo. Asystent nie widzi, kto
  kupił: zamówienie nazywa numerem i tym, za co jest.
- **Asystent odpowiada na prośby o rezerwację.** Czyta prośby czekające na
  odpowiedź i — po osobnym kliknięciu — przyjmuje albo odmawia, z powodem
  słowami osoby (bez linków). Okno zgody mówi, co dostanie klient:
  potwierdzenie albo dane do przelewu przedpłaty.
- **„Dlaczego to nie zostało przetłumaczone?”** — odczyt stanu tłumaczeń podaje
  zmiany, na których stoi automat, z powodem i chwilą ponownej próby.
- **Klient dostaje e-mail o zwrocie.** Po „Oznacz zwrot”: kwota i sposób, bez
  powodu (`commerce.refund_marked`; pl, en, de). Po wycofaniu zwrotu
  oznaczonego przez pomyłkę — korekta (`commerce.refund_withdrawn`). Okna
  zwrotu mówią o tym przed zapisem.
- **Stan „Zwrócone”.** Anulowane zamówienie, któremu firma oddała pieniądze i
  nie ma nic więcej do oddania, ma na liście stan `refunded`; wycofany zwrot
  przywraca „Anulowane”.
- **Nocleg, wersja 4.** Nowa oferta noclegu startuje z warunkami do zmiany w
  „Cenniku”: przedpłata 30% przelewem (firma włącza ją sama), reszta 14 dni
  przed pobytem, zwrot przedpłaty 100% do 30 dni i 50% do 14 dni przed, potem
  bez zwrotu. Wersja 3 (faza 5b: rezerwacja przez stronę) przyszła tego samego
  dnia; oferty założone z wersji 2 i 3 zostają, jak były.
- **Ekran dokumentu bez stron www.** Tam, gdzie organizacja nie ma modułu
  stron, odnośnik do tłumaczeń czekających na akceptację nie nazywa menu
  „Strona internetowa”, a „Do akceptacji” i „Zadania” nie pokazują zakładki
  „Przegląd” stron.
- **Raport evali asystenta** podaje, ile definicji narzędzi niosło każde
  wywołanie modelu (`tools_per_call`, `registry`, `widened`).
- **API**: `Order.status` przyjmuje w praktyce `refunded`; opisy operacji
  zwrotu mówią o e-mailu. Polecenia rejestru: `commerce.orders.read@1`,
  `commerce.order.read@1`, `commerce.payment.record@1`,
  `commerce.payment.void@1`, `booking.requests.read@1`,
  `booking.request.accept@1`, `booking.request.decline@1`;
  `translation.status.read@1` zwraca też `held`, `held_count`,
  `waiting_count`.

## Dla produktów

- Produkt bez `shared.commerce` nie dostaje poleceń zamówień; polecenia próśb
  przychodzą z rezerwacjami i działają bez zamówień.
- Kod, który sprawdza „zamówienie anulowane” przez `status == "canceled"`,
  ma pytać o `ledger.CLOSED_STATUSES` (panel: `isClosed`).
- Produkt z własnym presetem noclegu nie musi nic zmieniać; opis presetu może
  mieć teraz 400 znaków.

## Wdrożenie

Backend, worker i frontend przebudować razem; bez migracji i bez zmian w
harmonogramie. Presety i manifest poleceń jadą w obrazie.
