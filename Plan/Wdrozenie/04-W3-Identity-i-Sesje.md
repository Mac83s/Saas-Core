# W3 — Identity i sesje

**Status:** in progress — implementacja lokalna, bramka stagingu odroczona  
**Szacunek:** 1,5–2 tygodnie  
**Poprzednicy:** W1, W2  
**Rezultat:** bezpieczne konto użytkownika i zarządzalna sesja

## 1. Scenariusz demonstracyjny

Użytkownik rejestruje konto, potwierdza e-mail, loguje się w panelu, odświeża
sesję bez utraty stanu, wylogowuje pojedyncze urządzenie i resetuje hasło.
Operator loguje się osobnym kanałem z obowiązkowym 2FA.

## 2. Pakiety pracy

### W3.1 — model Identity

- [x] utworzyć customowy `User` w pierwszej migracji domenowej;
- [x] wdrożyć normalizację i unikalność e-maila zgodnie z ADR;
- [x] dodać `UserSession`, `EmailVerification`, `PasswordReset` i `LoginAttempt`;
- [x] przechowywać jedynie hashe tokenów jednorazowych;
- [x] dodać daty wygaśnięcia, użycia oraz mechanizm unieważnienia.

### W3.2 — rejestracja i weryfikacja

- [x] endpoint rejestracji z ochroną przed enumeracją i nadużyciem;
- [x] asynchroniczna wiadomość weryfikacyjna przez interfejs providera;
- [x] idempotentne ponowienie wiadomości i jednorazowa aktywacja tokenu;
- [x] bezpieczne zachowanie dla istniejącego oraz nieistniejącego adresu;
- [x] rejestrowanie zdarzeń bezpieczeństwa bez zapisu tokenów.

### W3.3 — sesja panelu

- wdrożyć kontrakt cookie, CSRF i CORS zatwierdzony w W0;
- dodać login, logout, `me`, listę sesji i unieważnienie sesji;
- rotować identyfikator sesji po logowaniu i zmianie uprawnień;
- egzekwować timeout bezczynności i maksymalny czas życia;
- nie umieszczać tokenów uwierzytelniających w localStorage.

### W3.4 — reset hasła i zabezpieczenia

- dodać żądanie i finalizację resetu bez ujawniania istnienia konta;
- unieważniać właściwe sesje po zmianie hasła;
- zastosować rate limiting dla loginu, rejestracji i resetu;
- przygotować model MFA i wdrożyć 2FA dla operatorów;
- dodać audit event dla zmian krytycznych ustawień konta.

### W3.5 — frontend

- przygotować formularze rejestracji, logowania, weryfikacji i resetu;
- dodać centralną obsługę sesji i błędów API;
- zapewnić ochronę routingu panelu po stronie serwera;
- obsłużyć wygaśnięcie sesji bez pętli przekierowań;
- dodać ekran aktywnych urządzeń i wylogowania.

## 3. Testy bezpieczeństwa

- enumeracja konta daje równoważne odpowiedzi i czasy w granicach tolerancji;
- token wygasły, użyty lub zmieniony nie może zostać użyty ponownie;
- brak albo błędny CSRF blokuje operację modyfikującą;
- skradzione cookie nie działa po unieważnieniu sesji;
- session fixation jest niemożliwe po logowaniu;
- brute-force aktywuje limit bez blokowania całego systemu;
- logi i telemetry nie zawierają hasła, tokenu ani pełnego cookie.

## 4. Bramka wyjścia

- [ ] pełna ścieżka rejestracja → weryfikacja → login działa na stagingu;
- [ ] wszystkie tokeny są jednorazowe, wygasające i hashowane;
- [ ] użytkownik może zobaczyć i unieważnić swoje sesje;
- [ ] operator ma obowiązkowe 2FA oraz oddzielny dostęp administracyjny;
- [ ] testy CSRF, rate limiting i session fixation przechodzą;
- [ ] frontend nie przechowuje sekretów sesji w JavaScript storage;
- [ ] zdarzenia Identity są gotowe do podłączenia W8.

## 5. Poza zakresem

- social login i zewnętrzne SSO;
- konto portalu pacjenta (`CustomerPortalIdentity`);
- role organizacyjne, które należą do W4.

## 6. Dowody lokalne

### W3.1 — 2026-08-10

- migracja `identity.0001_initial` została zastosowana na czystej bazie
  `saas_core_w3`, bez fałszowania historii starej bazy lokalnej;
- modele korzystają z UUIDv7, constraintu unikalności `Lower(email)` i
  constraintu spójności `status` z flagą Django `is_active`;
- tokeny, identyfikatory logowania, adresy IP i klucze sesji są zapisywane jako
  keyed HMAC-SHA-256, a reprezentacja wydanego tokenu nie ujawnia wartości;
- backup nowej bazy przeszedł kontrolę SHA-256, a restore drill odtworzył 19
  migracji i Django system check w 7 sekund;
- smoke aplikacji i obserwowalności przeszedł po uruchomieniu nowej migracji.

### W3.2 — 2026-08-10

- publiczne endpointy `/api/v1/auth/` udostępniają CSRF, rejestrację, ponowienie
  wiadomości oraz jednorazowe potwierdzenie adresu;
- rejestracja i ponowienie zwracają tę samą odpowiedź dla kont istniejących i
  nieistniejących, wykonują koszt hashowania hasła na obu ścieżkach i mają limity
  per adres klienta za jednym zaufanym proxy;
- worker otrzymuje wyłącznie UUID rekordu i correlation ID, rekonstruuje token z
  HMAC, a w bazie pozostaje wyłącznie digest; hasło SMTP stagingu jest dostępne
  tylko dla workera;
- lokalny provider zapisuje wiadomości w ignorowanym `.runtime/emails`, do którego
  kontener API nie ma montowania; logi smoke testu nie zawierały adresu, hasła ani
  tokenu;
- 28 testów backendu przeszło, w tym CSRF, throttle, awaria brokera, token użyty,
  wygasły i zmodyfikowany; OpenAPI i klient TypeScript nie wykazują driftu;
- smoke przez Caddy → API → Redis/Celery → plik e-mail → aktywacja odrzucił brak
  CSRF kodem `403`, a następnie zakończył ścieżkę kodami `202`, `200` i odrzucił
  ponowne użycie tokenu kodem `400`;
- weryfikacja staging/VPS pozostaje odroczoną bramką i nie jest uznana za wykonaną.
