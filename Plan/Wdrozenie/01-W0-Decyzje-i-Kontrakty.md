# W0 — decyzje i kontrakty architektoniczne

**Status:** complete  
**Szacunek:** 1 tydzień  
**Poprzednik:** brak  
**Rezultat:** zatwierdzony kontrakt techniczny umożliwiający utworzenie repozytorium

## 1. Cel i demonstracja

Celem nie jest produkcyjny kod, lecz usunięcie decyzji, których zmiana po
utworzeniu modeli i infrastruktury byłaby kosztowna. Demonstracją jest przegląd
kontraktów na przykładzie profilu MedPlano: aktywacja Core + Booking + Medical,
logowanie użytkownika oraz wywołanie wersjonowanego endpointu organizacji.

## 2. Pakiety pracy

### W0.1 — baseline technologiczny

- ustalić wspierane wersje Node.js, Python, Django, DRF, PostgreSQL i Redis;
- wybrać manager pakietów JavaScript oraz narzędzia Python;
- wybrać lint, formatter, type checker i runner testów dla obu stosów;
- ustalić politykę aktualizacji zależności oraz format lockfile;
- zapisać wybory jako ADR z okresem wsparcia i ścieżką aktualizacji.

### W0.2 — struktura monorepo i granice modułów

- zatwierdzić katalogi `apps/`, `packages/`, `deployments/`, `infra/`, `docs/`;
- opisać dozwolone kierunki zależności Core → Shared → Vertical;
- zdefiniować manifest modułu backendowego i frontendowego;
- określić mechanizm aktywowania modułów podczas build/deploymentu;
- zdefiniować test, który wykrywa zależność Core od verticala;
- określić właściciela migracji, permissions, entitlementów i tłumaczeń modułu.

### W0.3 — model danych bazowych

- rozstrzygnąć UUID v4 versus UUID v7;
- zatwierdzić minimalne pola `User`, `Organization`, `Membership`, `Role` i
  `BillingProfile`;
- zapisać unikalności, indeksy, statusy i reguły archiwizacji;
- zatwierdzić ADR-012 albo opisać warunek dalszego eksperymentu;
- zdecydować, które encje od początku wymagają soft delete lub optimistic lock;
- narysować migrację startową i regułę niezmienności customowego `User`.

### W0.4 — uwierzytelnianie i tenant context

- zatwierdzić lub odrzucić ADR-013;
- opisać domeny panelu i API, cookie scope, SameSite, CSRF i CORS;
- opisać wybór aktywnej organizacji oraz zmianę organizacji w sesji;
- zdefiniować zachowanie po odebraniu membership lub zawieszeniu organizacji;
- określić warstwę ustanawiającą tenant context w requestach i workerach;
- ustalić początkowy zakres RLS oraz testy cross-tenant.

### W0.5 — kontrakty API i zdarzeń

- zatwierdzić prefiks `/api/v1`, format błędów, pagination i correlation ID;
- ustalić sposób publikowania OpenAPI oraz generowania klienta TypeScript;
- zdefiniować kompatybilność zmian i politykę deprecacji;
- opisać envelope zdarzenia domenowego, outbox, idempotency key i retry;
- rozdzielić zdarzenia wewnętrzne od webhooków publicznych;
- przygotować przykładowy kontrakt `OrganizationCreated`.

### W0.6 — profile deploymentów

- zdefiniować typowany schemat konfiguracji produktu;
- przygotować minimalny profil MedPlano i profil testowy bez verticala;
- oddzielić konfigurację niesekretną od sekretów środowiska;
- opisać walidację niespójnych modułów i zależności;
- ustalić, które ustawienia są build-time, deploy-time i runtime.

### W0.7 — strategia jakości

- ustalić poziomy testów: unit, integration, contract, end-to-end i smoke;
- zdefiniować obowiązkową macierz testów tenant × permission × entitlement;
- określić minimalne bramki CI i zasady migracji;
- zdefiniować dane seed dla demonstracji bez danych osobowych;
- ustalić reguły logowania bez sekretów i danych wrażliwych.

## 3. Artefakty

- ADR-y dla wszystkich rozstrzygnięć blokujących W1–W4;
- diagram zależności modułów i kontrakt manifestu;
- ERD bazowych encji oraz opis tenant context;
- kontrakt auth, API, błędów, zdarzeń i OpenAPI;
- schemat profilu deploymentu z przykładem MedPlano;
- strategia testów i checklista review bezpieczeństwa;
- zaktualizowany rejestr decyzji i lista decyzji odroczonych.

## 4. Bramka wyjścia

- [x] nie istnieje nierozstrzygnięta decyzja blokująca utworzenie migracji `0001`;
- [x] wiadomo, jak backend i frontend aktywują moduły MedPlano;
- [x] Core nie może importować Shared ani Vertical w kierunku odwrotnym do kontraktu;
- [x] auth i tenant context mają diagram przepływu oraz scenariusze negatywne;
- [x] konfiguracja deploymentu odrzuca brak zależnego modułu;
- [x] strategia OpenAPI określa komendę generacji i kontrolę driftu w CI;
- [x] każdy ADR ma konsekwencje, alternatywy i właściciela;
- [x] W1 ma gotową listę katalogów i komend bootstrapu.

Dowody wykonania: `docs/adr/ADR-019`–`ADR-024` oraz kontrakty w
`docs/architecture/`. Decyzje produktowe ADR-015 i ADR-016 pozostają celowo
otwarte do W5 i nie blokują bootstrapu ani migracji bazowej.

## 5. Poza zakresem

- implementacja ekranów produktowych;
- integracja z prawdziwym kontem Stripe;
- wybór wszystkich dostawców produkcyjnych;
- model danych klinicznych, EDM i funkcje diagnostyczne.
