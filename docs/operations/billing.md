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

## Przeniesienie firm na bieżącą wersję planu

Opublikowana wersja planu się nie zmienia, a firma zostaje na tej, którą
dostała albo kupiła (ADR-032). To, co dokłada nowsza wersja, dociera do niej
dopiero wtedy, gdy operator ją przeniesie — celowo, nigdy samoczynnie (decyzje
właściciela z 04.10.2026). Służy do tego jedna komenda; bez `--apply` niczego
nie zapisuje:

```bash
# Podgląd: kto by się przeniósł i co każda firma zyska albo straci.
python manage.py plan_version_move [--plan <klucz>]

# Wykonanie — tylko firmy, których plan kosztuje w bieżącej wersji tyle samo.
python manage.py plan_version_move --apply --operator <e-mail> --reason "…"

# Inna cena: jedna wskazana firma, z kodem z aplikacji operatora.
python manage.py plan_version_move --organization <id>
python manage.py plan_version_move --organization <id> --apply \
  --operator <e-mail> --reason "…" --accept-price-change --code <kod>
```

- Przenosi operator poziomu 2 (`operator_level --grant`), z powodem. Każda
  firma idzie we własnej transakcji i dostaje wpis w historii „Plan
  zaktualizowany do bieżącej wersji przez operatora”; powtórne uruchomienie nie
  znajduje nic do zrobienia.
- „Ta sama cena” to ta sama kwota, waluta i okres. Przy innej cenie zbiorcze
  uruchomienie firmy nie rusza; przenosi ją tylko `--organization` z
  `--accept-price-change` i świeżym kodem (`--code`).
- Funkcje, które bieżąca wersja odbiera, oraz limity obniżone albo usunięte
  podgląd wypisuje wielkimi literami (`TRACI`, `NIŻSZE LIMITY`). Taka firma
  zostaje, dopóki operator nie doda `--accept-losses`.
- Plan nadany bez płatności i subskrypcja simulatora przenoszą się w całości
  lokalnie (subskrypcja simulatora razem ze swoim mapowaniem ceny).
- **Subskrypcji w Stripe komenda nie przenosi.** Jej wersję wyznacza cena u
  operatora płatności: każdy webhook i rekonsyliacja zapisują snapshot z tej
  ceny, a moduł nie ma wywołania, które zmienia cenę trwającej subskrypcji —
  lokalna zmiana cofnęłaby się przy najbliższym zdarzeniu. Taka firma zostaje
  na swojej wersji z tym zdaniem w wyniku; zmiana planu u Stripe pozostaje
  czynnością klienta w Customer Portal.
- Stan planu (aktywny, okres, dostęp) się nie zmienia: przeniesienie wymienia
  warunki planu, a nie to, czy plan obowiązuje. Wyjątki dostępu (override)
  zostają nałożone na nową wersję tak jak na starą.

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
