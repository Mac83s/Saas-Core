# W5 — Billing i Entitlements

**Status:** in progress — decyzje wejściowe zamknięte w ADR-026; staging odłożony
**Szacunek:** 2–3 tygodnie  
**Poprzednik:** W4  
**Rezultat:** audytowalny dostęp organizacji zsynchronizowany ze Stripe

## 1. Decyzje wejściowe

**Stan:** zatwierdzone w [ADR-026](../../docs/adr/ADR-026-Billing-Entitlements-i-Trial.md).

Przed rozpoczęciem trzeba zatwierdzić:

- plany, funkcje i limity pilota;
- moment rozpoczęcia i długość triala;
- czy metoda płatności jest wymagana przed trialem;
- jednostkę sprzedaży: organizacja, strona czy lokalizacja;
- grace period, przejście do read-only i retencję po anulowaniu;
- minimalny zakres adaptera fakturowania/KSeF.

## 2. Scenariusz demonstracyjny

Owner wybiera plan, przechodzi Checkout, a podpisany webhook aktywuje lokalny
snapshot entitlementów organizacji. Ponowienie tego samego zdarzenia nie
duplikuje skutków. Po symulowanej nieudanej płatności organizacja przechodzi
przez grace period do trybu read-only bez usunięcia danych.

## 3. Pakiety pracy

### W5.1 — katalog produktu

**Stan:** zakończone lokalnie 2026-08-10. Katalog Starter/Pro jest seedowany,
wersje planów są niemutowalne także na poziomie PostgreSQL, a granty i snapshoty
są izolowane per tenant. Walidacja: Ruff, brak dryfu migracji i 122 testy backendu.

- wdrożyć `Plan`, niemutowalny `PlanVersion`, `Feature` i `QuotaDefinition`;
- reprezentować granty z planu, triala, promocji i override;
- przechowywać efektywny, lokalny snapshot dostępu;
- zapewnić wersjonowanie oferty bez zmiany istniejącej subskrypcji;
- przygotować seed katalogu pilota jako dane kontrolowane.

### W5.2 — centralna autoryzacja planowa

**Stan:** w toku. Lokalne, wyjaśnialne decyzje `can()` i `limit()` oraz kompozycja
z RBAC są wdrożone; pozostały atomowe liczniki/rezerwacje quota.

> **FINDING W5.2-01 — rozwiązane 2026-08-10:** kontrakt modułu i dokumentacja
> używają teraz wdrożonego klucza `organization.billing.manage`. Profile
> deploymentu i test kontraktowy przechodzą.

- wdrożyć `can(feature)` i `limit(quota)` dla organizacji;
- łączyć wynik z permissions bez mieszania obu odpowiedzialności;
- dodać wyjaśnialny wynik decyzji do audytu i supportu;
- wprowadzić tryb read-only dla dozwolonych odczytów;
- zapewnić atomowe liczniki albo rezerwacje limitów dla operacji współbieżnych.

### W5.3 — Stripe

- tworzyć Customer i Checkout wyłącznie dla uprawnionego Ownera;
- mapować Price do wewnętrznego `PlanVersion`, bez traktowania Stripe jako SSOT;
- weryfikować podpis webhooka przed zapisem do inboxu;
- deduplikować event ID i przetwarzać zdarzenia asynchronicznie;
- obsłużyć co najmniej checkout, trial, paid, payment_failed, update i cancel;
- udostępnić Customer Portal z bezpiecznym return URL.

### W5.4 — trial i lifecycle subskrypcji

- zaimplementować jawne stany wewnętrzne;
- oddzielić datę rejestracji od aktywacji triala zgodnie z decyzją;
- zaplanować ostrzeżenia przed końcem triala i grace period;
- zapewnić retry oraz rekonsyliację ze Stripe;
- nie usuwać danych automatycznie przy utracie płatności.

### W5.5 — override, usage i fakturowanie

- dodać audytowane, wygasające override z uzasadnieniem operatora;
- wdrożyć okresowe `UsageCounter` i ochronę przed podwójnym naliczeniem;
- przygotować interfejs adaptera fakturowania;
- odseparować błędy fakturowania od potwierdzonej płatności;
- dodać panel supportu pokazujący źródło efektywnego entitlementu.

## 4. Testy obowiązkowe

- wielokrotne dostarczenie i zmiana kolejności webhooków;
- brak albo błędny podpis Stripe;
- webhook dotyczący innej organizacji lub nieznanego Price;
- równoległe zużycie ostatniej jednostki quota;
- downgrade poniżej bieżącego zużycia;
- przejścia trial → active → grace_period → read_only → canceled;
- permission denied mimo aktywnego planu oraz entitlement denied mimo roli Owner.

## 5. Bramka wyjścia

- [ ] lokalny stan wystarcza do decyzji dostępu bez zapytania do Stripe;
- [ ] webhooki są podpisane, trwałe, idempotentne i rekoncyliowalne;
- [ ] utrata płatności nie usuwa danych ani nie omija grace period;
- [ ] katalog planów jest wersjonowany;
- [ ] override ma autora, przyczynę, zakres i opcjonalne wygaśnięcie;
- [ ] support potrafi wyjaśnić wynik `can()` i `limit()`;
- [ ] testy dowodzą niezależności RBAC i entitlementów.
