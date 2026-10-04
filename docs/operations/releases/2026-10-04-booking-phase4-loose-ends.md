# Rezerwacje uniwersalne, faza 4: zaległości plastrów 4b–4g — wydanie 2026-10-04

Zakres: drobne zaległości po plastrach 4b, 4d-2 i 4g fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
„Uzupełnienie plastrów 4b–4g”). Bez migracji.

## Co się zmieniło

- **Nowa wersja dokumentu nie wchodzi w życie przed wersją już zatwierdzoną.**
  Zatwierdzenie z datą wcześniejszą niż najpóźniejsza data zatwierdzonej
  wersji jest odrzucane (`before_latest_version`), a okno zatwierdzenia mówi,
  od którego dnia nowa wersja może obowiązywać, i proponuje ten dzień.
- **Tłumaczenie dokumentu wpisane ręcznie można potwierdzić bez zmian.** Gdy
  tekst w języku wersji został poprawiony, tłumaczenie ma znaczek „tekst
  źródłowy poprawiono” i przycisk „Potwierdź bez zmian” (z kodem z aplikacji,
  jak każdy tekst dokumentu).
- **Kalendarz › „Prośby”**: lista rezerwacji klientów czekających na
  odpowiedź firmy, z terminem odpowiedzi, „Przyjmij rezerwację” i „Odmów”.
  Strona i licznik w menu są widoczne dla osób zarządzających rezerwacjami,
  gdy firma ma usługę „na prośbę” albo jakaś prośba czeka.
- **Odmowa z powodem.** W oknie „Odmówić tej rezerwacji?” (w wizycie i na
  liście próśb) firma może dopisać klientowi kilka zdań — zwykły tekst bez
  linków, do 300 znaków. Trafia do e-maila o odmowie.
- **Okna „Odwołać wizytę?” i „Przełóż” mówią prawdę o wiadomości do klienta**:
  klient z adresem e-mail dostaje wiadomość automatycznie; bez adresu trzeba
  dać mu znać.
- **Dzwonek** nazywa powiadomienia biura o rezerwacjach (nowa rezerwacja
  online, wizyta czeka na osobę, klient odwołał, rezerwacja albo prośba
  wygasła, prośba czeka), a powiadomienie o prośbie prowadzi do listy próśb.
- **API**: `effect.not_before` w podglądzie i wyniku zatwierdzenia dokumentu;
  `stale` w wierszu tekstu wersji; `POST …/appointments/<id>/decline/`
  przyjmuje `reason` (400 `links`, `max_length`); `GET
  /api/v1/booking/requests/`; `requests` w `GET /api/v1/booking/overview/`.

## Dla produktów

- Nic do zrobienia. Produkt bez usług „na prośbę” nie pokazuje „Próśb”.
- `answer_request` z `booking.services` ma nowy, opcjonalny argument `reason`.

## Wdrożenie

Backend, worker i frontend przebudować razem; bez migracji i bez zmian w
harmonogramie.
