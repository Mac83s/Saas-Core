# ADR-029 — Powiadomienia, integracje i bezpieczny support

Status: Accepted

## Kontekst

W8 wymaga dostarczania wiadomości i webhooków co najmniej raz, bez podwójnego
skutku biznesowego, oraz narzędzi naprawczych niewyłączających tenant isolation.
Dostawca poczty dla środowiska staging nie został jeszcze wybrany.

## Decyzja

- wiadomość lub dostawa webhooka jest trwałym rekordem kolejki utworzonym w tej
  samej transakcji co reakcja na zdarzenie domenowe;
- worker otrzymuje podpisany `TenantTaskContract`, ponownie sprawdza aktywne
  membership i wykonuje operację w `TenantContext` oraz RLS;
- rekord ma stabilny klucz idempotencji, licznik prób, wykładniczy backoff i stan
  `dead_letter`; naprawa ponawia ten sam rekord, a nie tworzy nowej wiadomości;
- adapter e-mail gwarantuje idempotencję po kluczu aplikacyjnym. Runtime lokalny
  używa adaptera Django, a komercyjny provider jest wybierany konfiguracją po
  zatwierdzeniu DPA, regionu i konfiguracji DKIM/SPF/DMARC;
- treść szablonu jest wersjonowana w kodzie dla PL/EN i renderowana dopiero przy
  wysyłce. Nie przechowujemy wyrenderowanego body ani odpowiedzi providera;
- bounce i complaint tworzą suppression po skrócie odbiorcy. Statusy terminalne
  są monotoniczne: późniejsze `delivered` nie nadpisuje `bounced`/`complained`;
- publiczne webhooki wychodzące mają jawnie dozwolony payload, wersję, delivery
  ID, timestamp i podpis HMAC. URL musi być HTTPS, bez danych logowania, a DNS
  jest sprawdzany przy konfiguracji i bezpośrednio przed połączeniem; adresy
  niepubliczne, metadata, redirecty i DNS rebinding są odrzucane;
- klucze API są pokazywane raz, przechowywane jako hash i mają jawne scope,
  rotację oraz revocation;
- eksport danych jest asynchroniczny, ograniczony rozmiarem i udostępniany przez
  krótko żyjący, podpisany URL; zawartość jest czyszczona po wygaśnięciu;
- akcje supportowe działają wyłącznie w aktywnym tenancie, wymagają permissionu,
  potwierdzonego MFA, jawnego powodu i audytu. Impersonacja między tenantami nie
  jest częścią W8 i pozostaje wyłączona; jej pełny kontrakt powstanie w W11.

## Konsekwencje

Awaria brokera lub providera nie gubi intencji, a ponowienie jest obserwowalne i
bezpieczne. Wygasły podpisany kontekst wymaga jawnej naprawy operatora. Routing
webhooka przychodzącego może przechowywać wyłącznie nieosobowe, nieprzezroczyste
identyfikatory; właściwe dane tenantowe są przetwarzane dopiero w tasku z
poprawnym kontekstem.
