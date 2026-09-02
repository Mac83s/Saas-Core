# Billing — simulator i odroczona aktywacja Stripe

Lokalny `PlanVersion` pozostaje źródłem ceny, triala i entitlementów. W lokalnym
runtime i na obecnym stagingu provider jest ustawiony jawnie jako
`BILLING_PROVIDER=simulated`. To środowisko odbioru produktu, a nie bramka
płatnicza: nie przyjmuje danych karty, nie wykonuje obciążeń i nie potwierdza
realnej płatności.

## Konfiguracja simulatora

Profil deploymentu z `shared.billing` publikuje dokładnie trzy stabilne klucze
w `billing.planKeys`. Dla `business` są to `profile`, `starter` i `pro`. Po
migracjach skonfiguruj odpowiadające im mapowania lokalne:

```bash
uv run --project apps/backend python apps/backend/manage.py \
  configure_simulated_prices
```

Polecenie jest deterministyczne i idempotentne. `compose.yaml` wykonuje je po
migracji, a standardowy deploy stagingu powtarza je przed startem usług
aplikacyjnych. Nie dodawaj ręcznie mapowań w bazie.

Local i staging nie wymagają klucza API Stripe, sekretu webhooka ani
identyfikatorów Product/Price. Identyfikatory techniczne utworzone przez
simulator nie są dowodem zapisania metody płatności ani opłacenia subskrypcji.

## Przepływ odbioru W9.5.2

1. Owner porównuje publiczne plany ograniczone przez profil deploymentu.
2. Simulator przeprowadza wewnętrzny, deterministyczny etap wyboru planu bez
   formularza karty i bez wyjścia do zewnętrznego providera.
3. Backend aktywuje lokalny trial i snapshot entitlementów przez te same
   tenantowe, audytowane i idempotentne use case'y co integracja zewnętrzna.
4. Dopiero lokalny snapshot z `sites.enabled` odblokowuje utworzenie witryny.

Powtórzenie nie może utworzyć drugiej subskrypcji ani nadać dostępu innemu
tenantowi. Nie naprawiaj przepływu przez ręczne tworzenie snapshotu lub edycję
danych subskrypcji.

## Realny Stripe — W9.5.2S

Aktywacja Stripe jest świadomie odłożona. Sam obecny w repozytorium adapter,
Checkout, Portal lub komenda mapowania nie stanowią dowodu gotowości. Przed
pierwszym płatnym pilotem trzeba osobno zaliczyć W9.5.2S: skonfigurować dokładnie
trzy zewnętrzne Product/Price, bezpiecznie dostarczyć sekrety poza repozytorium,
zweryfikować podpisane webhooki, retry i rekonsyliację oraz przejść rzeczywisty
Setup Checkout i Customer Portal w izolowanym środowisku testowym Stripe.

Provider `simulated` nie jest dozwolony w środowisku obsługującym realne
płatności. Przełączenie providera wymaga osobnego runbooka, dowodów stagingowych
i decyzji go-live zgodnie z ADR-034.
