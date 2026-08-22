# ADR-033 — asystent AI: narzędzia, zgody i głos

**Status:** Accepted
**Data:** 2026-08-13
**Właściciel:** zespół SaaS Core
**Aktualizacja 2026-08-22:** dodano multi-provider routing (OpenRouter) i
generator stron z briefu/rozmowy zależny od SeoContentRank — sekcje
"Generator stron z briefu lub rozmowy" i zmieniony akapit o adapterach w
"Runtime i rozszerzalność". Baza ADR-u pozostaje Accepted; nowe sekcje wymagają
przeglądu przed rozpoczęciem W9.5.7.

## Kontekst

Przewagą produktu ma być możliwość zarządzania stroną, profilem, rezerwacjami i
wiadomościami w rozmowie tekstowej lub głosowej. Model językowy nie może jednak
stać się nową granicą bezpieczeństwa, wykonywać dowolnego kodu ani omijać
tenantów, permissionów, entitlementów, audytu i reguł domenowych.

Codex CLI i Claude Code są narzędziami pracy nad repozytorium. Produkcyjna
aplikacja dla klientów wymaga stabilnego API, kontroli kosztu, izolacji żądań i
deterministycznej warstwy wykonawczej.

## Decyzja

### Runtime i rozszerzalność

- powstaje moduł `shared.assistant` zależny od publicznych API modułów Shared i
  Core; jego descriptor, frontend manifest i test grafu deploymentu są częścią
  pierwszego pakietu implementacyjnego;
- produkcyjny runtime wywołuje modele przez provider-neutralny port z rejestrem
  adapterów, nie przez zależność na jednym dostawcy. Pierwszy zestaw adapterów
  obejmuje OpenRouter jako agregator wielu modeli (Claude, Kimi i inne) do
  wieloturowej rozmowy i function calling, a bezpośrednie API dostawcy jest
  osobnym adapterem tam, gdzie capability wymaga funkcji niedostępnej przez
  agregator (np. realtime audio z ADR-033 §Tekst i głos);
- wybór konkretnego modelu i adaptera jest konfiguracją per capability (rozmowa,
  generowanie strony, głos), nie globalnym ustawieniem, i podlega tym samym
  evalom co reszta narzędzi; port raportuje koszt i latencję per adapter, żeby
  awaria lub degradacja jednego dostawcy nie blokowała pozostałych capability;
- Codex CLI, Claude Code CLI i repozytoryjne skills służą do developmentu,
  administracji oraz budowania/evaluacji recept. Nie są procesem wykonawczym
  obsługującym sesje klientów;
- te same jawne komendy aplikacyjne mogą być wystawione jako ograniczony serwer
  MCP dla autoryzowanych agentów zewnętrznych. MCP ani skill nie daje szerszych
  praw niż sesja i zakres użytkownika;
- model nie otrzymuje shella, dowolnego HTTP, dynamicznego importu ani surowego
  ORM. Dostaje tylko wersjonowane narzędzia z allowlisty aktywnych modułów.

### Pipeline działania

Każda rozmowa przechodzi ten sam kontrakt:

```text
wiadomość lub transkrypcja
  -> rozpoznanie intencji
  -> ustrukturyzowany plan i propozycje komend
  -> deterministyczna walidacja
  -> podgląd zmian oraz wymagane zgody
  -> idempotentne wykonanie w TenantContext
  -> audit/outbox, rezultat i możliwość wycofania
```

- `TenantContext` pochodzi z uwierzytelnionej sesji lub podpisanego kontraktu,
  nigdy z argumentu wygenerowanego przez model;
- każda komenda deklaruje schema wejścia/wyjścia, wymagane permission,
  entitlement, poziom ryzyka, idempotency key i politykę audytu;
- odczyty i wyjaśnienia mogą wykonywać się automatycznie;
- odwracalne zmiany draftu wymagają podglądu i jednej świadomej akceptacji;
- publikacja, wysłanie wiadomości, anulowanie/przeniesienie rezerwacji, domena,
  billing i operacje masowe wymagają osobnego, dokładnego potwierdzenia. MFA jest
  wymagane tam, gdzie wymaga go ręczne API;
- model nie wykonuje akcji na podstawie samego tekstu „potwierdzam” po zmianie
  planu działania. Zgoda wskazuje jednorazowy digest związany z organizacją,
  aktorem, wersją narzędzia, dokładnym payloadem, wersjami zasobów i krótkim TTL.
  Edycja transkrypcji, planu albo zasobu unieważnia zgodę;
- timeout, retry i wznowienie nie mogą powtórzyć skutku biznesowego. Operacje
  odwracalne mają rollback, a skutki nieodwracalne — jawną kompensację albo
  trwały status wymagający interwencji; interfejs nie obiecuje cofnięcia
  wysłanej wiadomości;

### Generator stron z briefu lub rozmowy

- narzędzie `site.generate_draft` przyjmuje ustrukturyzowany brief z formularza
  albo transkrypcję rozmowy i przechodzi ten sam pipeline co reszta asystenta:
  rozpoznanie intencji, plan, walidacja, podgląd, zgoda, wykonanie w
  `TenantContext`, audyt;
- plan wskazuje `PageTemplate` (ADR-031) i konkretne kontrolowane bloki z jego
  receptury; narzędzie nie projektuje nowych bloków ani układów — dobiera
  wyłącznie z aktywnego katalogu szablonów i sekcji;
- treść każdego bloku, którego brief nie dostarczył wprost, zleca zewnętrznemu
  SeoContentRank: wysyła brief, słowa kluczowe i dane firmy, otrzymuje
  proponowany copy per blok, sugerowane linkowanie wewnętrzne i metadane SEO.
  SeoContentRank działa tu w trybie tworzenia nowej treści, nie tylko
  optymalizacji istniejącej — dokładny kontrakt żądania/odpowiedzi jest osobnym
  pakietem pracy w planie connectora SeoContentRank, zsynchronizowanym z tym
  ADR-em;
- wynik trafia do `shared.sites` przez te same komendy zapisu draftu co ręczny
  edytor i przyszły edytor wizualny z W9.5.6 — narzędzie nie ma równoległej
  ścieżki zapisu, optimistic locka ani wersjonowania. `shared.assistant`
  orkiestruje plan i wywołania SeoContentRank; `shared.sites` pozostaje jedynym
  właścicielem stanu draftu i publikacji;
- wygenerowany draft podlega tej samej zasadzie co inne odwracalne zmiany:
  wymaga podglądu i jednej świadomej akceptacji przed zapisem, a publikacja
  strony nadal wymaga osobnego, dokładnego potwierdzenia niezależnie od tego,
  czy draft powstał ręcznie, przez rozmowę czy przez formularz brief;
- generator wymaga uprzednio zbudowanego katalogu szablonów z W9.5.4; przed tym
  pakietem narzędzie nie ma z czego wybierać i nie powinno być włączane.

### Tekst i głos PL/EN

- rozmowa działa po polsku i angielsku, zgodnie z preferencją użytkownika, ale
  może płynnie rozpoznać drugie locale;
- kanał głosowy zamienia audio na bieżącą transkrypcję i przekazuje tekst do
  tego samego pipeline'u narzędzi. Synteza mowy jest warstwą prezentacji, nie
  osobnym agentem;
- użytkownik zawsze widzi edytowalną transkrypcję i dokładny zakres operacji
  przed jej zatwierdzeniem;
- dla publikacji, wiadomości, zmian rezerwacji, domeny i innych akcji wysokiego
  ryzyka wymagane jest kliknięcie kontrolki oraz reauth/MFA zgodnie z ręcznym
  API; samo głosowe „tak” nigdy nie jest wystarczającą zgodą;
- przeglądarka używa krótkotrwałej sesji audio lub proxy backendu; długotrwały
  klucz providera nie trafia do klienta;
- audio nie jest domyślnie przechowywane. Retencja transkrypcji, redakcja PII i
  region providera są jawne w polityce deploymentu;
- MedPlano nie przekazuje do modelu dokumentacji klinicznej, diagnoz ani innych
  danych zdrowotnych poza zatwierdzonym zakresem marketingu i organizacji
  rezerwacji.
- zwykłe dane osobowe klientów rezerwacji również podlegają minimalizacji:
  narzędzie dostaje tylko pola potrzebne do konkretnej intencji, a dostęp do
  list i szczegółów rezerwacji jest osobno autoryzowany i audytowany.

### Jakość i koszty

- narzędzia i prompty są wersjonowane, a każdy release przechodzi zestaw evali
  PL/EN: poprawność planu, odmowa cross-tenant, approval boundary, prompt
  injection, idempotencja oraz koszt/latencja;
- plan produktu ogranicza liczbę akcji i dostęp do głosu/automatyzacji;
- logi zachowują identyfikatory i metryki, ale nie sekrety, pełne prompty ani
  niepotrzebne dane osobowe;
- awaria modelu nie blokuje ręcznego panelu i nigdy nie pozostawia częściowo
  wykonanej wieloetapowej mutacji bez widocznego statusu.

## Konsekwencje

- wszystkie kanały — panel, AI, MCP i workflow — korzystają z tych samych
  serwisów domenowych, a nie z równoległej logiki;
- każda nowa funkcja zarządzana przez AI musi najpierw mieć bezpieczną komendę
  aplikacyjną i test deterministyczny;
- voice może korzystać z modelu realtime wspierającego audio i function calling,
  lecz decyzje biznesowe nadal przechodzą przez serwerowe narzędzia i zgody;
- narzędzia deweloperskie nie są zależnością dostępności produktu;
- provider port zależy teraz od dostępności OpenRouter jako głównego agregatora;
  awaria lub degradacja OpenRouter nie może cicho przełączyć się na szerszy
  dostęp — zatrzymuje capability i zgłasza status, zgodnie z fail-closed z
  ADR-035;
- generator stron wiąże `shared.assistant` z zewnętrzną dostępnością
  SeoContentRank i z katalogiem szablonów W9.5.4; brak jednego z nich blokuje
  wyłącznie tę capability, nie resztę asystenta ani ręczny panel.

## Źródła

- OpenAI, Model guidance — Responses API dla wieloturowych workflow i tool
  calling: https://developers.openai.com/api/docs/guides/latest-model
- OpenAI, Realtime audio model — audio input/output i function calling:
  https://developers.openai.com/api/docs/models/gpt-realtime-1.5
- OpenRouter, dokumentacja API i routingu modeli: https://openrouter.ai/docs
- ADR-021, ADR-024, ADR-027, ADR-029, ADR-030, ADR-031 i ADR-035.
