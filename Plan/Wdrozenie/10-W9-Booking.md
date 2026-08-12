# W9 — Booking

**Status:** zakończone lokalnie (2026-08-12); staging odłożony
**Szacunek:** 3–5 tygodni  
**Poprzednicy:** W4, W8  
**Rezultat:** neutralny branżowo system rezerwacji odporny na wyścigi

## 1. Decyzje wejściowe

- źródło prawdy czasu i zasady stref czasowych;
- granularność slotów, bufory i reguły nakładania zasobów;
- mechanizm blokady: constraint/range/exclusion plus transakcja;
- statusy i dozwolone przejścia rezerwacji;
- retencja danych `Customer` oraz anonimizacja;
- czy płatność/zaliczka należy do pierwszego używalnego zakresu.

## 2. Scenariusz demonstracyjny

Organizacja definiuje lokalizację, usługę, pracownika, zasób i grafik. Klient
końcowy wybiera termin bez konta, otrzymuje potwierdzenie i może zmienić lub
anulować wizytę. Dwie równoległe próby nie tworzą konfliktujących rezerwacji.

## 3. Pakiety pracy

### W9.1 — model katalogu

**Stan:** zakończone lokalnie; ADR-030 definiuje neutralny model i rozszerzenia.

- wdrożyć `Location`, `StaffMember`, `Service` i `Resource`;
- powiązać usługi z czasem, buforami, lokalizacją, personelem i zasobami;
- zastosować tenant scope do każdej encji;
- przygotować punkty rozszerzeń dla profili Medical i Beauty;
- dodać uprawnienia i entitlement `booking.enabled`.

### W9.2 — dostępność

**Stan:** zakończone lokalnie; reguły IANA/DST, horyzont 62 dni i bufory mają
testy deterministyczne.

- wdrożyć powtarzalne `AvailabilityRule` oraz konkretne `TimeOff`;
- przechowywać instants w UTC i interpretować reguły w strefie organizacji;
- obsłużyć DST, wyjątki, bufory i minimalne wyprzedzenie;
- generować dostępne sloty w ograniczonym horyzoncie;
- zapewnić deterministyczne wyniki oraz kontrolę wydajności.

### W9.3 — rezerwacja transakcyjna

**Stan:** zakończone lokalnie; PostgreSQL exclusion constraints blokują wyścig
pracownika i zasobu, a mutacje są idempotentne.

- wdrożyć `Appointment` i historię statusów;
- egzekwować konflikt na poziomie bazy, nie tylko aplikacji;
- dodać idempotency key dla tworzenia i zmiany terminu;
- zdefiniować atomowy reschedule oraz bezpieczne anulowanie;
- nie niszczyć istniejących wizyt po zmianie grafiku.

### W9.4 — Customer i self-service

**Stan:** zakończone lokalnie; Customer pozostaje niezależny od User, token jest
ograniczony, wygasający i routowany przez PII-free digest.

- wdrożyć tenantowego `Customer` niezależnego od `User`;
- zebrać minimalny zestaw danych kontaktowych;
- wydać wygasający, ograniczony token do zmiany/anulowania;
- chronić przed enumeracją wizyt i klientów;
- przygotować anonimizację zgodną z retencją oraz obowiązkami biznesowymi.

### W9.5 — panel, publiczny flow i wiadomości

**Stan:** zakończone lokalnie; panel `/panel/calendar`, publiczny `/book/:slug`,
rate limiting i ogólne potwierdzenia/przypomnienia korzystają z W8.

- zbudować konfigurację grafiku i kalendarz organizacji;
- udostępnić publiczne wyszukiwanie terminów z rate limitingiem;
- obsłużyć create/reschedule/cancel w panelu i self-service;
- wysyłać potwierdzenia oraz przypomnienia przez W8;
- używać ogólnych treści bez danych medycznych.

## 4. Testy krytyczne

- co najmniej dwie równoległe transakcje na ostatni slot;
- konflikt pracownika i współdzielonego zasobu;
- zmiana czasu zimowy/letni, strefy organizacji i klienta;
- retry requestu po timeout bez duplikatu;
- zmiana grafiku po utworzeniu wizyty;
- token self-service dla obcej albo anulowanej wizyty;
- cross-tenant dla wszystkich encji i wyszukiwania;
- wydajność wyszukiwania w ustalonym horyzoncie.

## 5. Bramka wyjścia

- [x] baza uniemożliwia podwójną rezerwację;
- [x] reguły czasu przechodzą testy DST i stref czasowych;
- [x] create, reschedule i cancel są idempotentne;
- [x] zmiana grafiku nie modyfikuje historycznych rezerwacji;
- [x] Customer nie jest automatycznie Userem;
- [x] wiadomości nie ujawniają zbędnych danych;
- [x] moduł można wyłączyć bez uszkodzenia Core i ukrywa się w panelu.

Walidacja lokalna: 10 krytycznych testów Booking (w tym dwie faktycznie
równoległe transakcje, DST, RLS, tokeny i stały budżet zapytań dla 31-dniowego
horyzontu), 288 testów pełnej regresji backendu, pełny mypy, Ruff,
import-linter, drift migracji i API, walidacja obu profili deploymentu oraz
produkcyjny build Next.js w obrazie Node 24. W tym samym obrazie przeszły 4/4
testy komponentów W9: axe dla PL/EN, publiczne wyszukiwanie terminu bez konta
oraz self-service reschedule.
