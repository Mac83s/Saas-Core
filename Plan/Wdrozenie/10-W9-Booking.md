# W9 — Booking

**Status:** blocked by W4, W8 and ADR-018  
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

- wdrożyć `Location`, `StaffMember`, `Service` i `Resource`;
- powiązać usługi z czasem, buforami, lokalizacją, personelem i zasobami;
- zastosować tenant scope do każdej encji;
- przygotować punkty rozszerzeń dla profili Medical i Beauty;
- dodać uprawnienia i entitlement `booking.enabled`.

### W9.2 — dostępność

- wdrożyć powtarzalne `AvailabilityRule` oraz konkretne `TimeOff`;
- przechowywać instants w UTC i interpretować reguły w strefie organizacji;
- obsłużyć DST, wyjątki, bufory i minimalne wyprzedzenie;
- generować dostępne sloty w ograniczonym horyzoncie;
- zapewnić deterministyczne wyniki oraz kontrolę wydajności.

### W9.3 — rezerwacja transakcyjna

- wdrożyć `Appointment` i historię statusów;
- egzekwować konflikt na poziomie bazy, nie tylko aplikacji;
- dodać idempotency key dla tworzenia i zmiany terminu;
- zdefiniować atomowy reschedule oraz bezpieczne anulowanie;
- nie niszczyć istniejących wizyt po zmianie grafiku.

### W9.4 — Customer i self-service

- wdrożyć tenantowego `Customer` niezależnego od `User`;
- zebrać minimalny zestaw danych kontaktowych;
- wydać wygasający, ograniczony token do zmiany/anulowania;
- chronić przed enumeracją wizyt i klientów;
- przygotować anonimizację zgodną z retencją oraz obowiązkami biznesowymi.

### W9.5 — panel, publiczny flow i wiadomości

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

- [ ] baza uniemożliwia podwójną rezerwację;
- [ ] reguły czasu przechodzą testy DST i stref czasowych;
- [ ] create, reschedule i cancel są idempotentne;
- [ ] zmiana grafiku nie modyfikuje historycznych rezerwacji;
- [ ] Customer nie jest automatycznie Userem;
- [ ] wiadomości nie ujawniają zbędnych danych;
- [ ] moduł można wyłączyć bez uszkodzenia Core i ukrywa się w panelu.

