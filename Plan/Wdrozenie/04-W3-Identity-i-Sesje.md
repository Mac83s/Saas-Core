# W3 — Identity i sesje

**Status:** blocked by W1 and W2  
**Szacunek:** 1,5–2 tygodnie  
**Poprzednicy:** W1, W2  
**Rezultat:** bezpieczne konto użytkownika i zarządzalna sesja

## 1. Scenariusz demonstracyjny

Użytkownik rejestruje konto, potwierdza e-mail, loguje się w panelu, odświeża
sesję bez utraty stanu, wylogowuje pojedyncze urządzenie i resetuje hasło.
Operator loguje się osobnym kanałem z obowiązkowym 2FA.

## 2. Pakiety pracy

### W3.1 — model Identity

- utworzyć customowy `User` w pierwszej migracji domenowej;
- wdrożyć normalizację i unikalność e-maila zgodnie z ADR;
- dodać `UserSession`, `EmailVerification`, `PasswordReset` i `LoginAttempt`;
- przechowywać jedynie hashe tokenów jednorazowych;
- dodać daty wygaśnięcia, użycia oraz mechanizm unieważnienia.

### W3.2 — rejestracja i weryfikacja

- endpoint rejestracji z ochroną przed enumeracją i nadużyciem;
- asynchroniczna wiadomość weryfikacyjna przez interfejs providera;
- idempotentne ponowienie wiadomości i jednorazowa aktywacja tokenu;
- bezpieczne zachowanie dla istniejącego oraz nieistniejącego adresu;
- rejestrowanie zdarzeń bezpieczeństwa bez zapisu tokenów.

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

