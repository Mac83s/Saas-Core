# ADR-034 — simulator billingowy i odroczenie Stripe

**Status:** Accepted
**Data:** 2026-08-13
**Właściciel:** zespół SaaS Core
**Częściowo zastępuje:** wymóg metody płatności przed trialem z ADR-026 oraz
ścieżkę Stripe Checkout/Portal i zdalną bramkę Price z ADR-032 wyłącznie dla
bieżących środowisk local i staging; docelowy kontrakt realnych płatności,
lokalny snapshot i entitlementy pozostają obowiązujące

## Kontekst

W5 dostarczył model subskrypcji, entitlementy i adapter Stripe, a pierwszy slice
W9.5 dostarcza klientowi wybór planu. Uruchomienie prawdziwej bramki wymaga
jednak osobnej konfiguracji konta Stripe, polityki sekretów, Product/Price,
podpisanych webhooków i odbioru zachowania dla kart, SCA oraz błędów płatności.
Nie są to warunki potrzebne do oceny obecnego panelu, katalogu i blokad dostępu.

Wymuszanie niezweryfikowanych placeholderów Stripe na local lub stagingu
tworzyłoby pozorną bramkę jakości. Z kolei oznaczenie Checkout jako gotowego bez
rzeczywistego przejścia przez zewnętrzny system byłoby fałszywym dowodem.

## Decyzja

### Bieżące środowiska

- wybór providera jest jawny przez `BILLING_PROVIDER`;
- local i staging W9.5 używają wartości `simulated`;
- simulator nie łączy się ze Stripe, nie żąda sekretów Stripe, nie zbiera danych
  karty, nie zapisuje realnej metody płatności i nie wykonuje obciążeń;
- identyfikatory i wyniki simulatora są techniczne. Nie wolno prezentować ich
  jako dowodu opłacenia planu ani pomyślnego przejścia realnego Checkout;
- `configure_simulated_prices` po migracjach idempotentnie konfiguruje lokalne
  mapowania dokładnie trzech planów wskazanych przez `billing.planKeys` profilu
  deploymentu. Ręczne wpisy w bazie nie są częścią procedury;
- wybór planu, aktywacja triala i snapshot entitlementów nadal przechodzą przez
  tenantowe use case'y z permission, audytem, idempotencją i transakcją. Frontend
  ani sam wynik powrotu nie nadają dostępu;
- brak lokalnego `sites.enabled` nadal blokuje mutację w API.

Staging pozostaje środowiskiem syntetycznym. Nie zawiera danych kart ani danych
realnych klientów, a deploy nie wykonuje wywołań do Stripe.

### Odroczona bramka W9.5.2S

Realny Stripe jest osobnym pakietem W9.5.2S. Pakiet nie blokuje dalszego
lokalnego rozwoju W9.5, ale blokuje pierwszy płatny pilot i każde środowisko
produkcyjne przyjmujące płatności. Jego odbiór wymaga łącznie:

1. jawnego przełączenia providera w kontrolowanym środowisku oraz fail-closed
   startu bez kompletnej konfiguracji;
2. sekretów dostarczonych przez secret store poza repozytorium;
3. dokładnie trzech aktywnych Product/Price zgodnych z lokalnymi
   `PlanVersion`, osobno dla trybu test i live;
4. rzeczywistego Setup Checkout bez przepływu danych karty przez aplikację oraz
   działającego Customer Portal;
5. zweryfikowanych podpisów webhooków, kolejności zdarzeń, retry,
   idempotencji, rekonsyliacji i izolacji tenantów;
6. testów nieudanej płatności, SCA/3DS, grace/read-only, anulowania oraz
   stagingowego smoke z zachowanymi dowodami.

Do zaliczenia tych punktów sam kod adaptera, mocki ani simulator nie wystarczą.
Po odbiorze powstaje operacyjny runbook aktywacji i rollbacku realnego providera.

## Konsekwencje

- local i aktualny staging nie przechowują placeholderów ani sekretów Stripe;
- deploy stagingu konfiguruje simulator po migracjach i może wystartować bez
  konta Stripe;
- testy produktu mogą deterministycznie przejść ścieżkę plan → trial →
  entitlement bez sugerowania pobrania pieniędzy;
- interfejs Stripe pozostaje docelowym adapterem płatniczym, ale nie jest
  oznaczony jako operacyjnie gotowy;
- przełączenie produkcji na `simulated` jest niedozwolone; produkcja billingowa
  pozostaje zamknięta do zaliczenia W9.5.2S.
