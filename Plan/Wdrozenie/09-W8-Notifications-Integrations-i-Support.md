# W8 — Notifications, Integrations i Support

**Status:** zakończona lokalnie; aktywacja komercyjnego providera wymaga sekretów i DPA stagingu
**Szacunek:** 2 tygodnie  
**Poprzednicy:** W3, W4; wykorzystuje kontrakty W2  
**Rezultat:** niezawodna komunikacja i bezpieczna obsługa operacyjna

## 1. Scenariusz demonstracyjny

Zdarzenie domenowe tworzy wiadomość w wybranym języku, worker wysyła ją z
idempotency key, a webhook providera aktualizuje status. Tymczasowa awaria
dostawcy powoduje retry bez duplikatu. Operator widzi błąd i ponawia wyłącznie
bezpieczną operację, a każda akcja trafia do audytu.

## 2. Pakiety pracy

### W8.1 — outbox i kolejka wiadomości

- zapisywać zdarzenie i outbox w tej samej transakcji;
- przetwarzać rekordy z blokadą, retry, backoff i limitem prób;
- zapewnić idempotency po stronie aplikacji oraz providera;
- zdefiniować dead-letter workflow i ręczne ponowienie;
- propagować tenant oraz correlation ID do workera.

### W8.2 — e-mail transakcyjny

- wdrożyć `EmailProvider` z metodami send/status/webhook;
- przygotować wersjonowane szablony PL/EN i preview bez wysyłki;
- używać ogólnych tematów bez wrażliwych danych;
- obsłużyć bounce, complaint i suppression list;
- weryfikować podpis webhooka i ograniczyć retencję treści.

### W8.3 — integracje publiczne

- wdrożyć bezpieczne klucze API z hashami, scope i rotacją;
- wersjonować podpisane webhooki wychodzące;
- rejestrować próby, odpowiedzi skrócone/redagowane i retry;
- chronić przed SSRF przez walidację destination URL;
- dodać eksport danych asynchroniczny z wygasającym linkiem.

### W8.4 — audit i panel operatora

- rejestrować aktora, tenant, działanie, obiekt, czas i correlation ID;
- redagować wartości wrażliwe i nie przechowywać pełnych payloadów bez potrzeby;
- pokazać health integracji, kolejki, błędy i bezpieczne akcje naprawcze;
- zabezpieczyć impersonację dodatkowymi permissions, powodem i widocznym stanem;
- wymagać 2FA i audytować każdą operację operatora.

### W8.5 — preferencje i obserwowalność

- rozdzielić wiadomości obowiązkowe od marketingowych;
- respektować język i dozwolone preferencje odbiorcy;
- mierzyć opóźnienie kolejki, retry, bounce i complaint;
- alertować o zaległości, wyczerpaniu prób i błędach podpisu;
- przygotować runbook awarii dostawcy.

## 3. Testy obowiązkowe

- błąd przed i po przyjęciu wiadomości przez providera;
- wielokrotne dostarczenie webhooka statusowego;
- odwrócona kolejność delivered/bounced;
- SSRF do localhost, metadanych chmurowych i prywatnej sieci;
- rotacja i odebranie API key;
- operator bez właściwego permission lub 2FA;
- retry po dead-letter nie tworzy drugiej wiadomości.

## 4. Bramka wyjścia

- [x] awaria providera nie blokuje requestu użytkownika;
- [x] retry i webhooki są idempotentne;
- [x] szablony są wersjonowane i dostępne w PL/EN;
- [x] bounce, complaint i suppression wpływają na kolejne wysyłki;
- [x] webhooki wychodzące są podpisane i odporne na SSRF;
- [x] działania supportu są ograniczone, jawne i audytowane;
- [x] runbook pozwala zdiagnozować i bezpiecznie wznowić kolejkę.

Dowody lokalne: 278 testów backendu, obowiązkowy pakiet W8 10/10 na PostgreSQL
z FORCE RLS, testy komponentów PL/EN z axe, Ruff, mypy, import-linter, OpenAPI
drift, migracje bez dryfu, produkcyjny build Next.js, `promtool` (6 reguł) oraz
runtime smoke na przebudowanym i zdrowym stosie Compose.
