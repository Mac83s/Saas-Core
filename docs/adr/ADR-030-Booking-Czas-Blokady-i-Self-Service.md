# ADR-030 — Booking: czas, blokady i self-service

**Status:** Accepted
**Data:** 2026-08-12
**Właściciel:** zespół SaaS Core

## Kontekst

W9 wymaga neutralnych branżowo rezerwacji, poprawnych stref czasowych oraz
odporności na równoległe próby zajęcia pracownika lub współdzielonego zasobu.
Publiczny klient nie ma konta panelowego, ale dane nadal wymagają jawnego tenant
context i RLS.

## Decyzja

- instants wizyt i nieobecności zapisujemy jako UTC, a tygodniowe reguły jako
  dzień i czas lokalny interpretowany w `Organization.timezone` przez IANA
  `zoneinfo`;
- nieistniejące czasy podczas przejścia DST są pomijane, a czas dwuznaczny daje
  dwa różne instants. Wynik jest sortowany po UTC i deduplikowany;
- slot obejmuje długość usługi oraz bufory. Publiczny horyzont ma najwyżej 62
  dni i twardy limit wyników;
- `Appointment` zachowuje snapshot czasu i nazwy usługi. Późniejsza zmiana
  katalogu lub grafiku nie zmienia istniejącej wizyty;
- zajętość pracownika i zasobu materializujemy w osobnych alokacjach.
  PostgreSQL `EXCLUDE USING gist` na `(organization, staff/resource, tstzrange)`
  dla aktywnych alokacji jest ostateczną blokadą wyścigu;
- create, reschedule i cancel mają klucz idempotencji i hash żądania.
  Reschedule atomowo dezaktywuje stare i tworzy nowe alokacje;
- `Customer` jest tenantową encją niezależną od `User`. Anonimizacja czyści dane
  kontaktowe bez usuwania historii biznesowej;
- self-service używa losowego tokenu o co najmniej 256 bitach. Baza przechowuje
  digest w globalnym, PII-free indeksie routingu; token jest ograniczony do
  jednej wizyty, wygasa i jest unieważniany po anulowaniu;
- publiczny routing zaczyna od nieosobowego `public_slug`, a następnie aktywuje
  jawny tenant context typu `service` z minimalnym zakresem. Nie jest to
  membership ani globalny fallback;
- potwierdzenia i przypomnienia przechodzą przez trwałą kolejkę W8. Treści są
  ogólne: organizacja, termin i bezpieczny link, bez danych medycznych;
- płatność i zaliczka są poza pierwszym zakresem W9.

## Konsekwencje

Baza rozstrzyga konflikt niezależnie od liczby procesów. Publiczne żądanie nie
dostaje dostępu do dowolnego tenanta. Dwa wystąpienia lokalnego czasu w dniu
cofnięcia zegara są widoczne jako dwa sloty o różnych offsetach.

## Alternatywy odrzucone

- `select_for_update` na wyszukiwaniu wolnego slotu — brak wiersza do blokady;
- kontrola konfliktu wyłącznie w Pythonie — wyścig check/insert;
- reguły grafiku w UTC — przesuwają lokalne godziny po DST;
- publiczny fallback do pierwszego tenanta lub tenant z nagłówka;
- fikcyjne membership dla klienta końcowego;
- bezpośrednia wysyłka e-mail w request.
