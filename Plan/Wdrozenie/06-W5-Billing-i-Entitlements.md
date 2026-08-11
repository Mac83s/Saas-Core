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

**Stan:** zakończone lokalnie 2026-08-10. Lokalne, wyjaśnialne decyzje `can()`
i `limit()` są niezależnie komponowane z RBAC. Okresowe liczniki i idempotentne
rezerwacje quota są blokowane transakcyjnie; test współbieżny dowodzi, że tylko
jedno żądanie może zużyć ostatnią jednostkę. Walidacja: Ruff, import-linter,
punktowy mypy, brak dryfu migracji i 137 testów backendu.

> **FINDING W5.2-01 — rozwiązane 2026-08-10:** kontrakt modułu i dokumentacja
> używają teraz wdrożonego klucza `organization.billing.manage`. Profile
> deploymentu i test kontraktowy przechodzą.

- wdrożyć `can(feature)` i `limit(quota)` dla organizacji;
- łączyć wynik z permissions bez mieszania obu odpowiedzialności;
- dodać wyjaśnialny wynik decyzji do audytu i supportu;
- wprowadzić tryb read-only dla dozwolonych odczytów;
- zapewnić atomowe liczniki albo rezerwacje limitów dla operacji współbieżnych.

### W5.3 — Stripe

**Stan:** zakończone lokalnie 2026-08-11. Lokalny model Customer (przez `BillingProfile`), mapowanie
Stripe Price → `PlanVersion`, historia subskrypcji i trwały inbox eventów są
wdrożone. Endpoint zapisuje event dopiero po poprawnej weryfikacji podpisu na
surowym body, przypiętej wersji API i trybu test/live; dostawy są deduplikowane
po Stripe event ID. Asynchroniczny processor wiąże Customer i Price z tenantem,
aktualizuje subskrypcję i snapshot, ignoruje starsze eventy oraz utrwala błędy
do retry. Owner może idempotentnie utworzyć Customer i sesję Checkout oraz
otworzyć Customer Portal z kontrolowanym po stronie serwera return URL.
Walidacja: Ruff, mypy modułu, import-linter, brak dryfu migracji, zgodność
OpenAPI/klienta, poprawny Compose i 166 testów backendu.

> **FINDING W5.3-02 — rozwiązane 2026-08-11:** Stripe Checkout w trybie
> `subscription` z `trial_period_days` rozpoczyna trial przy zakończeniu Checkout,
> co narusza ADR-026. Checkout pilota używa więc trybu `setup`: zbiera metodę
> płatności i zapisuje wybrany `PlanVersion`, a subskrypcja z trzydniowym trialem
> powstaje dopiero podczas aktywacji pierwszego produktu w W5.4.

- tworzyć Customer i Checkout wyłącznie dla uprawnionego Ownera;
- mapować Price do wewnętrznego `PlanVersion`, bez traktowania Stripe jako SSOT;
- weryfikować podpis webhooka przed zapisem do inboxu;
- deduplikować event ID i przetwarzać zdarzenia asynchronicznie;
- obsłużyć co najmniej checkout, trial, paid, payment_failed, update i cancel;
- udostępnić Customer Portal z bezpiecznym return URL.

### W5.4 — trial i lifecycle subskrypcji

**Stan:** zakończone lokalnie 2026-08-11. Wewnętrzny kontrakt
`activate_trial_for_product()` trwale zapisuje pierwszy trigger produktu,
wymaga zakończonego Setup Checkout i idempotentnie tworzy subskrypcję Stripe z
trialem z bieżącej wersji planu. Lokalna subskrypcja, snapshot entitlementów i
wpis audytu powstają bez oczekiwania na webhook. Minutowy zegar Celery obsługuje
trwałe akcje ostrzeżeń i przejścia do `read_only`; notice outbox jest gotowy do
podłączenia przez przyszły `shared.notifications`. Godzinna rekonsyliacja pobiera
bieżący obiekt Stripe poza transakcją, naprawia brakujące webhooki i odrzuca
zapis, jeśli lokalna wersja zmieniła się podczas połączenia. Wynik, diff, retry i
błąd są trwałe oraz audytowalne. Walidacja: Ruff, mypy modułu, import-linter,
brak dryfu migracji, poprawny Compose i 181 testów backendu.

#### W5.4.1 — rozpoczęcie triala przy pierwszej aktywacji

- utrwalić dokładnie jeden pierwszy trigger produktu na organizację;
- wymagać wcześniej zakończonego Checkout i powiązanego SetupIntent;
- pobrać PaymentMethod po stronie serwera i utworzyć subskrypcję z trzydniowym
  trialem oraz stałym kluczem idempotencji organizacji;
- zapisać lokalną subskrypcję, snapshot i audyt przed zwróceniem sukcesu;
- udostępnić serwis domenowy dla przyszłego `shared.sites`, bez publicznego
  endpointu omijającego uprawnienie `site.publish`.

#### W5.4.2 — zegar lifecycle i ostrzeżenia

> **FINDING W5.4-02 — rozwiązane 2026-08-11:** wcześniejszy processor mapował
> `customer.subscription.deleted` bezpośrednio na `read_only`, mimo że ADR-026
> zachowuje pełny dostęp do końca opłaconego okresu, a `past_due` nie wyznaczał
> jawnej karencji. Processor utrwala teraz nieprzesuwalny `grace_period_end`;
> spóźnione błędy płatności nie otwierają karencji ponownie. Trwałe akcje Celery
> zmieniają snapshot na `read_only` dopiero na właściwej granicy i zapisują audyt.

- dodać idempotentne harmonogramy ostrzeżeń przed końcem triala i grace period;
- przełączać wygasły grace period do `read_only` bez usuwania danych;
- zachować pełny dostęp przy anulowaniu do końca opłaconego okresu;
- audytować każdą lokalną zmianę stanu wykonaną przez zegar.

#### W5.4.3 — rekonsyliacja Stripe

**Stan:** zakończone lokalnie 2026-08-11. Celery Beat tworzy jedną próbę na
subskrypcję i godzinne okno, ponawia błędy do limitu oraz zapisuje `no_change`,
`succeeded`, `conflict` albo `failed`. Rekonsyliacja weryfikuje Customer,
test/live i lokalne mapowanie Price; nie uczestniczy w ścieżce autoryzacji.

- cyklicznie pobierać bieżące subskrypcje wymagające potwierdzenia;
- porównywać wersję lokalną z obiektem Stripe bez używania Stripe w ścieżce
  autoryzacji;
- naprawiać brakujące webhooki przez ten sam idempotentny mechanizm aktualizacji;
- utrwalać wynik, retry i błąd rekonsyliacji do obsługi supportowej.

- zaimplementować jawne stany wewnętrzne;
- oddzielić datę rejestracji od aktywacji triala zgodnie z decyzją;
- zaplanować ostrzeżenia przed końcem triala i grace period;
- zapewnić retry oraz rekonsyliację ze Stripe;
- nie usuwać danych automatycznie przy utracie płatności.

### W5.5 — override, usage i fakturowanie

**Stan:** w toku. W5.5.1–W5.5.3 zakończone lokalnie 2026-08-11. Override wymaga
aktywnego operatora platformy i jawnego tenant context, ma przyczynę, zakres,
opcjonalne wygaśnięcie oraz klucz idempotencji. Aktywna wartość jest składana do
lokalnego snapshotu, decyzja potrafi bez Stripe bezpiecznie wrócić do planu na
granicy wygaśnięcia, a Celery czyści snapshot i zapisuje audyt. Równoległe
override'y tego samego pola są odrzucane. Istniejący `QuotaUsage` przechowuje
liczniki w okresach miesięcznych albo lifetime, a `consume_quota()` zapewnia
atomowe i dokładnie-jedno naliczenie po kluczu zdarzenia. Commit po wygaśnięciu
rezerwacji jest blokowany, a minutowy task zwalnia niezużyte rezerwacje. Testy
obejmują rollover okresu i downgrade poniżej zużycia. `invoice.paid` zapisuje
kanoniczne żądanie dokumentu z kopią danych nabywcy i pozycji, a konfigurowalny
adapter działa asynchronicznie z trwałym statusem, wynikiem, błędem i retry.
Adapter `internal` nie udaje integracji KSeF. Niekompletne dane lub błąd adaptera
nie cofają potwierdzonej płatności ani dostępu. Walidacja: Ruff, mypy modułu,
import-linter, brak dryfu migracji, 193 testy backendu oraz pełny Compose ze smoke
testami runtime, Identity i observability.

> **FINDING W5.5-01 — rozwiązane 2026-08-11:** middleware `next-intl`
> przechwytuje `/healthz` i przepisuje go na lokalizowaną trasę, przez co
> poprawnie uruchomiony frontend zwraca 404 w healthchecku, a pełny Compose nie
> uruchamia Caddy. Trasa techniczna omija teraz middleware lokalizacji; frontend
> i Caddy są healthy, a smoke runtime przechodzi.

- [x] dodać audytowane, wygasające override z uzasadnieniem operatora;
- [x] wdrożyć okresowe `UsageCounter` i ochronę przed podwójnym naliczeniem;
- [x] przygotować interfejs adaptera fakturowania;
- [x] odseparować błędy fakturowania od potwierdzonej płatności;
- [ ] dodać panel supportu pokazujący źródło efektywnego entitlementu.

## 4. Testy obowiązkowe

- wielokrotne dostarczenie i zmiana kolejności webhooków;
- brak albo błędny podpis Stripe;
- webhook dotyczący innej organizacji lub nieznanego Price;
- równoległe zużycie ostatniej jednostki quota;
- downgrade poniżej bieżącego zużycia;
- przejścia trial → active → grace_period → read_only → canceled;
- permission denied mimo aktywnego planu oraz entitlement denied mimo roli Owner.

## 5. Bramka wyjścia

- [x] lokalny stan wystarcza do decyzji dostępu bez zapytania do Stripe;
- [x] webhooki są podpisane, trwałe, idempotentne i rekoncyliowalne;
- [x] utrata płatności nie usuwa danych ani nie omija grace period;
- [x] katalog planów jest wersjonowany;
- [x] override ma autora, przyczynę, zakres i opcjonalne wygaśnięcie;
- [ ] support potrafi wyjaśnić wynik `can()` i `limit()`;
- [x] testy dowodzą niezależności RBAC i entitlementów.
