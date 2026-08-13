# ADR-032 — oferta, plany i Customer Billing

**Status:** Accepted
**Data:** 2026-08-13
**Właściciel:** zespół SaaS Core
**Zastępuje:** w ADR-026 punkty o dwóch poziomach Starter/Pro, trzydniowym trialu
i dostępności domen oraz tabelę „Katalog pilota v1”; pozostały lifecycle,
lokalny snapshot i integracja Stripe pozostają obowiązujące

## Kontekst

ADR-026 przyjął dwa plany pilota i trzydniowy trial uruchamiany po aktywacji
pierwszego produktu. Implementacja zawiera Checkout w trybie Setup, Customer
Portal, webhooki, rekonsyliację i lokalne entitlementy, ale nie ma klienckiego
widoku wyboru planu, płatności ani zmiany planu.

Produkt potrzebuje dokładnie trzech czytelnych poziomów, aby docelowo
rozdzielić prosty profil na subdomenie, pełną stronę firmy oraz automatyzację AI.
Ceny i granty są wersjonowanymi danymi katalogu, nie kodem interfejsu.

## Decyzja

### Ścieżka klienta

- po utworzeniu lub wybraniu organizacji Owner trafia do onboardingu planu,
  jeżeli lokalny snapshot nie daje dostępu do produktu;
- strona **Plan i płatności** pokazuje bieżący stan, termin triala/rozliczenia,
  wykorzystanie najważniejszych limitów oraz porównanie publicznych planów;
- nowy klient wybiera plan, uzupełnia dane firmy i przechodzi do Stripe Checkout
  w celu zapisania metody płatności. Aplikacja nie przyjmuje danych karty;
- po zakończeniu Setup Checkout Owner jawnie uruchamia dostęp do wybranego planu
  w onboardingu. Idempotentny use case wiąże dokładny, ukończony Checkout z
  bieżącym tenantem, tworzy subskrypcję trial i lokalny snapshot z
  `sites.enabled`; dopiero wtedy kreator może utworzyć pierwszą stronę;
- aktywny klient zmienia metodę płatności, faktury, anulowanie i — do czasu
  wdrożenia natywnego schedule — plan przez Stripe Customer Portal;
- wynik Checkout/Portal jest zawsze potwierdzany przez webhook i lokalny
  snapshot. Powrót z zewnętrznego URL nie nadaje dostępu;
- brak `sites.enabled` blokuje mutację także w API i kieruje UI do wyboru planu.

### Poziomy oferty

Deployment publikuje dokładnie trzy poziomy. Poniższy podział jest stanem
docelowym po wdrożeniu szablonów i platformy AI w W9.5.4–W9.5.8:

1. **Profil** — jedna strona/profil na subdomenie platformy, jedna domyślna
   rodzina szablonu, podstawowe rezerwacje i ograniczona pula tekstowych akcji
   AI. Ten poziom ma bezpłatny okres próbny zapisany w `PlanVersion`.
2. **Firma** — większe limity, pełniejszy katalog bloków i szablonów,
   personalizacja wizualna oraz tekstowy asystent AI.
3. **Pro** — własna domena, warianty premium, większy zespół/lokalizacje oraz
   głos, automatyzacje i najwyższe limity AI.

Do czasu dostarczenia tych pakietów Checkout i panel mogą prezentować wyłącznie
funkcje faktycznie obecne w `feature_keys` i `quotas`; nie wolno reklamować
szablonów, głosu ani automatyzacji samą nazwą przyszłego poziomu.

Stabilne klucze techniczne nie muszą być tekstem marketingowym. Ceny, trial i
granty pochodzą z bieżącej, niemutowalnej `PlanVersion`, a kolejność i zakres
widocznego katalogu z `billing.planKeys` profilu deploymentu. Do czasu
wersjonowanego kontraktu prezentacji lokalizowane nazwy i krótkie opisy mogą być
utrzymywane w komunikatach deploymentu pod stabilnym `plan.key`; nie mogą
zmieniać ceny, grantów ani obiecywać nieistniejącego entitlementu. Opublikowana
subskrypcja nie zmienia się po edycji oferty; nowa oferta tworzy kolejną wersję.

Pierwsza robocza wersja poziomu Profil może być wyceniona poniżej istniejącego
Startera. Ostateczne kwoty i długość triala są decyzją sprzedażową przed
stagingiem, a nie stałą architektury.

Katalog ma dokładnie trzy aktywne poziomy: nowy klucz `profile`, istniejący
klucz `starter` prezentowany klientowi jako **Firma/Witryna** oraz istniejący
`pro`. Publikacja czwartego poziomu wymaga osobnej decyzji produktowej, a nie
przypadkowego pozostawienia historycznego planu jako publicznego.

### Entitlementy produktu

- dostęp do szablonów, personalizacji, tekstowego AI, głosu i automatyzacji jest
  osobnym entitlementem, niezależnym od permission użytkownika. Stabilne klucze
  obejmują `sites.templates.personalized`, `assistant.text.enabled`,
  `assistant.voice.enabled` i `assistant.site_generation.enabled`;
- `sites.max`, `pages.max`, `locations.max`, `team_members.max` i
  `storage.bytes` są limitami pojemnościowymi. `assistant.actions.monthly`,
  `assistant.voice_minutes.monthly`, wiadomości i rezerwacje są quota
  okresowymi. Jeden `Site` może zawierać wiele podstron, jeśli pozwala na to
  osobny limit `pages.max`;
- frontend może prezentować upgrade, lecz każde narzędzie i mutacja API
  ponownie sprawdzają entitlement;
- downgrade nigdy nie usuwa treści. Niedostępne elementy pozostają tylko do
  odczytu i nie mogą być ponownie publikowane, dopóki plan ich nie obejmuje.

## Konsekwencje

- potrzebny jest customer-facing endpoint katalogu i statusu subskrypcji;
- każdy publiczny bieżący `PlanVersion` musi mieć aktywne mapowanie Stripe dla
  trybu deploymentu; deterministyczna komenda konfiguracji i check startowy
  zastępują ręczne wpisy w bazie i nie hardkodują Price ID w repozytorium;
- dwa istniejące plany pozostają ważne; rozszerzenie katalogu tworzy nowy plan
  albo nowe wersje, nie mutuje historycznych `PlanVersion`;
- własna domena pozostaje opcjonalna, a subdomena platformy działa na każdym
  planie ze stroną;
- Stripe nadal nie jest źródłem definicji produktu ani decyzji dostępowej.
