# Plan rozwoju po audycie i autonomiczne Agent Skills

**Status:** approved for execution
**Data:** 2026-09-02
**Właściciel:** zespół SaaS Core
**Zakres:** domknięcie fundamentu wieloproduktowego, profili, rezerwacji,
płatności wizytowych, Site Studio i AI oraz ustanowienie repozytoryjnych Agent
Skills utrzymywanych przez agentów bez ręcznej edycji przez właściciela produktu

## 1. Cel i relacja do istniejących fal

Ten dokument porządkuje dalszą realizację po audycie. Nie zastępuje
szczegółowych checklist W9.5, W9.6, W10 ani W11. Ustala ich brakujące
poprzedniki, kolejność oraz równoległy tor Agent Skills.

Stan na 2026-09-02, sprawdzony w kodzie, a nie w checklistach: W9.6 jest
ukończone lokalnie (53 z 66 pozycji; pozostałe 13 to rollout wymagający
stagingu), W9.5 ma ukończone W9.5.1–W9.5.4, a backendowy model nawigacji z
W9.5.5 został dostarczony w ramach W9.6.3. Katalog modułów deklaruje Django
apps, które nie istnieją (`core.audit`, `vertical.medical`, `config.medplano`),
a import-linter był czerwony przez jeden import Core → Shared, usunięty tego
samego dnia. Etapy poniżej uwzględniają ten stan.

Plan kończy się dopiero wtedy, gdy z jednego repozytorium można zbudować i
niezależnie wdrożyć co najmniej `core-only` i generyczny profil `business`, z
którego później powstają serwisy — MedPlano, tanie strony i kolejne — na tej
samej głównej funkcjonalności. Pełna ścieżka użytkownika obejmuje profil,
stronę i rezerwację; płatność z prowizją platformy dołącza po bazie. Skills
deweloperskie mają w tym czasie ograniczać koszt ponownego poznawania
repozytorium i zapobiegać omijaniu jego kontraktów.

**Decyzje właściciela z 2026-09-02.** MedPlano przestaje być priorytetem;
szczegóły verticala wrócą później. Bazę zamyka **P0–P3**: kontrakty, realna
kompozycja deploymentów, skills z walidatorem oraz pełna tożsamość (profile i
konto klienta). P4 (ceny i polityki Booking) i płatności za wizyty (Connect,
ADR-037 — Deferred) są po bazie. Realny Stripe dla abonamentów (W9.5.2S)
wchodzi poza kolejnością etapów, gdy tylko właściciel dostarczy konto Stripe
(zapowiedziane na 2026-09-03). Drugim deploymentem dowodowym P1 jest
`business`; RLS rozstrzyga ADR-039 (reguła per tabela w deskryptorze); zmiany
skills wchodzą bez przeglądu, z powiadomieniem (ADR-038). Kolejność:
P0 → P1 → P2 → P3.

## 2. Niezmienne decyzje

1. SaaS Core, moduły Shared, verticale i konfiguracje produktów pozostają w
   jednym monorepo zgodnie z ADR-021. Nie tworzymy kopii ani forka Core dla
   każdej platformy.
2. Każda platforma otrzymuje osobny deployment, wersjonowany obraz, domenę,
   PostgreSQL, storage, Redis/kolejki, sekrety, backup i monitoring. Jeden commit
   może być wdrażany do produktów w różnym terminie; deployment przypina
   konkretny tag lub digest obrazu.
3. Dane produktowe platform nie są współdzielone. Ewentualne wspólne logowanie
   między platformami wymaga w przyszłości osobnego kontraktu tożsamości/SSO i
   nie jest realizowane przez wspólną bazę aplikacji.
4. Osobne repozytorium powstaje tylko dla samodzielnej usługi o niezależnym
   cyklu życia, granicy bezpieczeństwa albo stosie technicznym. Taka usługa ma
   własną bazę i integruje się przez wersjonowane API lub zdarzenia.
5. Billing abonamentu za SaaS i płatności klienta za wizytę pozostają osobnymi
   domenami. Płatności wizytowe nie rozszerzają po cichu `shared.billing`.
6. Repozytoryjne Agent Skills służą developmentowi i administracji. Skills
   produktowe asystenta klienta są częścią `shared.assistant` i podlegają
   TenantContext, permission, entitlementom, zgodom i audytowi z ADR-033.
7. Właściciel produktu nie edytuje ani ręcznie nie synchronizuje skills.
   Agenci dobierają je automatycznie, utrzymują i walidują. Nie oznacza to prawa
   do samodzielnej zmiany zaakceptowanych ADR-ów, użycia sekretów, wdrożenia na
   produkcję ani wykonania nieodwracalnej operacji bez wymaganej zgody.

## 3. Kolejność realizacji

Szacunki są orientacyjne dla 1–2 doświadczonych wykonawców wspieranych przez
agentów. Nie są terminem biznesowym; po P0 należy je ponownie oszacować na
podstawie zatwierdzonych kontraktów.

| Etap | Zakres | Szacunek | Blokuje | Może biec równolegle |
| --- | --- | ---: | --- | --- |
| P0 | decyzje i kontrakty po audycie | 1 tydzień | wszystkie dalsze mutacje modeli | analiza W9.6 bez zmian modeli |
| P1 | realna kompozycja deploymentów i naprawa granic | 1–2 tygodnie | nowe verticale i niezależne obrazy | P2 po zamrożeniu kontraktu katalogu modułów |
| P2 | fundament autonomicznych Agent Skills | 1–2 tygodnie | wykonywanie dalszych fal przez skills | końcówka P1 |
| P3 | tożsamość profilu i konto klienta | 2–3 tygodnie | pełny self-service i historia klienta | bezpieczne elementy W9.5.5–W9.5.6 |
| P4 | produktowe domknięcie Booking | 2–4 tygodnie | płatność wizytowa | W9.6 i Site Studio |
| P5 | W9.5.2S — gdy właściciel dostarczy konto Stripe (poza kolejnością); Appointment Commerce i Connect — po bazie | 4–6 tygodni | płatny pilot | W9.5.7 po ustabilizowaniu komend |
| P6 | Site Studio, generator AI i skills produktowe | 4–7 tygodni | pełny cel W9.5 | późna część P4–P5 |
| P7 | pierwszy serwis na bazie (MedPlano — odłożone decyzją z 2026-09-02) | 2–3 tygodnie | go-live | wyłącznie prace niezmieniające kontraktów P3–P6 |
| P8 | staging, rollout W9.6, hardening i go-live | 2–3 tygodnie | produkcja | brak dla bramek krytycznych |

Szeregowo etapy sumują się do około 19–31 tygodni, czyli od 4,5 do 7 miesięcy.
Kolumna równoległości może to skrócić, ale nie poniżej ścieżki krytycznej
P0 → P1 → P3 → P4 → P5 → P7 → P8, która sama ma 14–22 tygodnie. To wobec tej
sumy, a nie wobec pojedynczego etapu, należy planować termin płatnego pilota.

## 4. P0 — decyzje i kontrakty po audycie

- [x] zatwierdzić ADR rozdzielający `User`, `Organization`, `PublicProfile` i
  tenantowego `Customer`, wraz z zasadami dobrowolnej aktywacji konta klienta —
  ADR-036 Accepted 2026-09-02;
- [x] zdecydować, czy pierwsze wydanie ma konta wyłącznie per platforma; wspólne
  SSO pozostawić poza zakresem, dopóki nie powstanie jawny kontrakt — tak,
  per platforma (ADR-036 §2);
- [x] zatwierdzić ADR płatności wizytowych: usługodawca jako merchant of record,
  operator, prowizja, depozyt lub pełna płatność, zwroty, spory, no-show,
  podatki i dokumenty sprzedaży — ADR-037 zapisany i jawnie odłożony
  (Deferred) razem z P4/P5 poza bazę;
- [x] zatwierdzić ADR repozytoryjnych Agent Skills: źródło prawdy, routing,
  walidacja, aktualizacja, granice autonomii i rollback — ADR-038 Accepted;
- [x] rozstrzygnąć rozjazd RLS w `shared.sites` wobec ADR-022 — ADR-039
  Accepted: RLS domyślnie, tabele publiczne z deklaracji w deskryptorze;
- [ ] zamrozić publiczne komendy aplikacyjne wymagane przez profile, Booking,
  Commerce i `shared.assistant`; AI nie otrzymuje osobnej ścieżki zapisu;
- [ ] przypisać każdy brak po audycie do P1–P8 i wskazać bramkę dowodową zamiast
  deklaracji statusu.

### Bramka P0

- [x] nowe decyzje są zatwierdzone lub jawnie oznaczone jako blokujące —
  ADR-036/038/039 Accepted, ADR-037 Deferred z warunkiem powrotu;
- [ ] diagram właścicieli danych nie ma współdzielonej bazy między platformami;
- [ ] scenariusze płatności i zwrotów mają właściciela prawnego/księgowego;
- [x] zakres pierwszych skills oraz ich źródła są jednoznaczne — tabela w 6.2.

## 5. P1 — realna kompozycja produktów

- [ ] najpierw uzgodnić katalog modułów z kodem, bo dziś opisuje kod, którego
  nie ma: `core.audit`, `vertical.medical` i `config.medplano` deklarują
  `backend.djangoApp`, dla których nie istnieje pakiet, a `core.health` jest w
  `INSTALLED_APPS` bez deskryptora. `pnpm deployment:check` waliduje schemat i
  graf zależności, ale nie sprawdza istnienia aplikacji, więc profil `core-only`
  nie mógłby dziś wystartować w realnej kompozycji. Dodać test w obie strony:
  każdy zadeklarowany app jest importowalny, a każdy zainstalowany ma deskryptor;
- [ ] dodać profil `business` (pełny zestaw Shared, bez verticala, plany
  `profile`/`starter`/`pro`) jako drugi prawdziwy produkt; profil `medplano`
  przenieść do `deployments/_planned/`, a deskryptory `vertical.medical` i
  `config.medplano` usunąć z katalogu do czasu powstania kodu; dodać
  deskryptor `core.health`; rozstrzygnąć `core.audit` (deskryptor bez
  aplikacji — audyt żyje dziś w `core.organizations` i `core.identity`);
- [ ] wdrożyć ADR-039: pole `backend.publicTables` w schemacie deskryptora,
  klasyfikacja tabel Sites na podstawie zapytań renderera, migracja RLS dla
  tabel prywatnych i test kontraktowy na prawdziwym PostgreSQL;
- [ ] sprawić, aby `deployment.json` rzeczywiście składał backendowe Django apps,
  URL-e, zadania i frontendowe route/menu, a nie tylko walidował deskryptory;
- [x] usunąć niedozwolony import Core → Shared — jedyne naruszenie było w
  komendzie `provision_platform_workspace`, która z `core.organizations`
  importowała `shared.billing.overrides`; komenda przeniesiona do
  `shared.billing`, bo domu potrzebowało nadanie entitlementów, a nie utworzenie
  workspace'u (2026-09-02, `lint-imports`: 1 kept, 0 broken);
- [ ] utrzymywać zielony import-linter oraz ESLint boundaries; kontrakt warstw
  łapie także importy wewnątrz funkcji, więc odroczony import nie jest obejściem;
- [ ] dodać test, że `core-only` nie aktywuje Billing, Sites, Booking ani żadnego
  verticala, a MedPlano aktywuje wyłącznie zadeklarowany graf;
- [ ] generować artefakt modułów i hash profilu używany przez backend, frontend,
  workera i schedulera; niezgodny obraz ma odmówić startu;
- [ ] udokumentować i przetestować osobną bazę, użytkownika DB, storage, Redis,
  sekrety, backup, domenę i obserwowalność każdego deploymentu;
- [ ] utrzymywać macierz `deployment → wersja/digest → migracje → rollback`, aby
  produkty mogły aktualizować się niezależnie z jednego repozytorium.

### Bramka P1

- [ ] build i smoke test `core-only` oraz `business` dowodzą różnych aktywnych
  powierzchni API/UI;
- [ ] żaden wyłączony moduł nie rejestruje routingu, workera ani schedulera;
- [ ] test importów i kontraktów modułów jest zielony;
- [ ] katalog modułów i `INSTALLED_APPS` są zgodne w obie strony i pilnuje tego
  test;
- [ ] dwa środowiska testowe używają osobnych danych i sekretów.

## 6. P2 — autonomiczny system Agent Skills

### 6.1. Źródło prawdy i routing

- [ ] ustanowić `.agents/skills/<skill-name>/SKILL.md` jako kanoniczne skills
  projektu; reguły obowiązujące każde zadanie pozostają w `AGENTS.md`;
- [ ] dla klientów wymagających adapterów generować lub aktualizować cienkie
  odwołania, bez kopiowania pełnej treści skill; dopuścić wyłącznie zarządzane
  przez Memex dokładne mirrory, których integralność sprawdza integracja Memex;
- [ ] pamiętać, że Claude Code wykrywa automatycznie wyłącznie `.claude/skills/`,
  a o doborze skill decyduje `description` we frontmatterze, nie treść pliku:
  cienki adapter musi powtarzać dokładnie ten sam `name` i `description`, bo sam
  link do `.agents/` wyłączyłby routing po cichu. Zgodność tych dwóch pól jest
  pierwszą rzeczą, którą sprawdza walidator;
- [ ] dodać `docs/AI_AGENTS.md` opisujące podział instrukcji, automatyczny routing,
  granice uprawnień i procedurę naprawy;
- [ ] dodać obowiązkową mapę ścieżek w `AGENTS.md`: zmiana danego modułu wymaga
  odczytania odpowiadającego skill. Nie polegać wyłącznie na swobodnym
  rozpoznaniu intencji przez model;
- [ ] zachować domyślne implicit invocation; opisy skills muszą być krótkie i
  rozłączne, aby agent sam wybierał właściwy zestaw.

### 6.2. Pierwszy katalog

Skills powstają dopiero, gdy mają realne źródła i scenariusze. Ta zasada
obowiązuje także sam katalog: skill dla modułu, którego nie ma, opisywałby
zamiar, a walidator uznałby taki opis za aktualny. Pierwszy zestaw P2 obejmuje
więc wyłącznie skills z istniejącymi dziś źródłami:

| Skill | Kiedy ma się aktywować | Kanoniczne źródła |
| --- | --- | --- |
| `develop-saas-core-module` | dodanie lub zmiana modułu/deploymentu | ADR-021, module contract, deployment profile |
| `change-tenant-data` | model, migracja, manager, RLS lub zadanie tenantowe | ADR-022, tenant context, testing strategy |
| `change-api-and-events` | endpoint, schema, klient albo zdarzenie | ADR-024, OpenAPI, api-and-events |
| `develop-sites` | strony, domeny, media, publikacja i content operations | ADR-027–029, ADR-031, ADR-035 |
| `develop-booking` | usługi, grafik, klient i wizyty | ADR-030 i kontrakty Booking |
| `prepare-product-deployment` | nowy profil produktu, obraz, migracja lub rollout | ADR-021, ADR-025, deployment profile |
| `verify-saas-core-release` | odbiór przyrostu lub release candidate | testing strategy, W11 i runbooki |
| `maintain-saas-core-skills` | skill jest nieaktualny albo zmieniło się jego źródło | katalog skills, walidator i historia usterek |

Pozostałe skills są produktem etapu, który tworzy ich źródło, i wchodzą do jego
definicji ukończenia:

| Skill | Etap | Powstaje razem z |
| --- | --- | --- |
| `develop-commerce-payments` | P5 | ADR-037 i pierwszym adapterem providera płatności |
| `develop-assistant-runtime` | P6 | `shared.assistant` i rejestrem wersjonowanych narzędzi |
| `develop-medplano` | P7 | pierwszą realną implementacją verticala i deploymentu |

Skill aplikacyjny ma zawierać wyłącznie różnice branżowe i kierować do skills
Core/Shared; nie kopiuje ich treści. Dodanie kolejnego deploymentu uruchamia
kontrolę, czy potrzebny jest osobny skill produktowy.

### 6.3. Aktualizacja skills bez obsługi właściciela

`maintain-saas-core-skills` ma wykonywać kontrolowany cykl:

1. wykryć zmianę ADR-u, architektury wykonywalnej, manifestu modułu/deploymentu,
   OpenAPI, komendy jakościowej albo powtarzalną porażkę agenta;
2. wskazać skills zależne od zmienionego źródła;
3. zmienić tylko wymagane instrukcje lub referencje;
4. uruchomić walidację struktury, linków, nazw, triggerów, adapterów i rozmiaru;
5. wykonać scenariusze zachowania oraz właściwe testy repozytorium;
6. pokazać diff, zapisać dowody i utworzyć osobny commit z możliwością
   zwykłego revertu.

Meta-skill nie może sam uznać swojej zmiany za poprawną wyłącznie dlatego, że
plik przechodzi parser. Deterministyczny walidator i scenariusze regresyjne są
niezależną bramką. Zmiana skill nie może rozszerzać uprawnień, zastępować ADR-u
ani automatycznie autoryzować działań produkcyjnych.

### 6.4. Walidacja i obserwowalność

- [ ] dodać `pnpm ai:validate` i gate CI sprawdzający frontmatter, unikalność
  nazw, działające linki/ścieżki/komendy, cienkie adaptery, brak sekretów,
  nadmiarowe lub konfliktujące triggery oraz osierocone skills;
- [ ] sprawdzać, że każdy aktywny deployment i moduł wysokiego ryzyka ma
  przypisaną procedurę albo świadomie korzysta ze skill ogólnego;
- [ ] przygotować realistyczne evale: nowy endpoint, migracja tenantowa, zmiana
  Booking, webhook Connect, nowy deployment i aktualizacja nieaktualnego skill;
- [ ] uruchamiać kontrolę driftu przy zmianie źródeł oraz cykliczny przegląd
  katalogu wykonywany przez agenta; wykryty problem tworzy poprawkę i dowody,
  nie instrukcję ręcznej edycji dla właściciela;
- [ ] mierzyć dobór właściwego skill, liczbę korekt po review, nieudane bramki,
  czas do znalezienia kontraktu i regresje spowodowane nieaktualną instrukcją;
- [ ] brak wymaganej instrukcji lub niezgodność walidatora blokuje merge, ale nie
  dostępność uruchomionego produktu.

### Bramka P2

- [ ] agent potrafi wykonać reprezentatywne zadania bez ręcznego wskazywania
  skill przez właściciela;
- [ ] zmiana źródłowego ADR-u lub komendy powoduje wykrywalny drift;
- [ ] maintainer aktualizuje wskazany skill, a walidacja wykrywa celowo
  wprowadzony zły link, zduplikowany trigger i przekroczenie uprawnień;
- [ ] skills Codex i wspieranych klientów nie rozjeżdżają się treściowo;
- [ ] `pnpm ai:validate` działa lokalnie i w CI.

## 7. P3 — profile i konto klienta

- [ ] pozostawić `User` kontem uwierzytelniającym, a publiczne dane przenieść do
  jawnego modelu `PublicProfile` osoby lub organizacji;
- [ ] powiązać profil rozszerzony z Site bez duplikowania treści strony;
- [ ] umożliwić rezerwację gościnną, a następnie bezpieczną aktywację konta i
  przypięcie istniejących rekordów `Customer` po weryfikacji adresu;
- [ ] zbudować panel klienta: przyszłe i historyczne wizyty, przełożenie,
  anulowanie, płatności, eksport i usunięcie konta;
- [ ] zdefiniować role Owner, administrator, pracownik, specjalista, recepcja,
  klient i operator oraz ich negatywne testy exact-tenant;
- [ ] wdrożyć wersjonowane Terms/Privacy acknowledgement bez blokowania prawa do
  anulowania usługi, eksportu i usunięcia danych.

### Bramka P3

- [ ] użytkownik może mieć profil prosty bez strony albo rozszerzony z Site;
- [ ] klient może rezerwować bez konta i opcjonalnie odzyskać historię po jego
  aktywacji;
- [ ] połączenie `User`–`Customer` nie umożliwia przejęcia cudzych wizyt;
- [ ] usunięcie lub anonimizacja ma przetestowaną politykę retencji.

## 8. P4 — produktowe domknięcie Booking

- [ ] dodać do usługi cenę, walutę, stawkę podatku, warianty, bufor, minimalne
  wyprzedzenie i politykę płatności;
- [ ] obsłużyć depozyt, pełną płatność, bezpłatną rezerwację oraz płatność na
  miejscu jako jawne warianty organizacji/usługi;
- [ ] dodać zasady anulowania, zwrotu, przełożenia, no-show i spóźnienia;
- [ ] poprawić self-service tak, aby nowy termin pochodził z rzeczywistej
  dostępności;
- [ ] dodać synchronizację Google/Microsoft/iCal z jawną polityką konfliktu i
  ochroną przed podwójną rezerwacją;
- [ ] zdecydować osobno o rezerwacjach grupowych, cyklicznych i liście
  oczekujących; brak decyzji nie może rozszerzać pierwszego pilota;
- [ ] domknąć powiadomienia, zgody marketingowe/transakcyjne, SMS i lokalizację
  PL/EN bez zakodowanego na stałe locale.

## 9. P5 — Appointment Commerce i Stripe Connect

- [ ] wykonać W9.5.2S — realny Stripe dla subskrypcji SaaS — jako pierwszy pakiet
  P5, przed Connect: płatny pilot potrzebuje obu integracji, a konto Stripe,
  rozdział trybów test/live, sekrety, podpis webhooka, idempotencja, kolejność
  zdarzeń, rekonsyliacja i runbook są jednym wspólnym kosztem, który taniej
  zapłacić raz na prostszych subskrypcjach niż dwa razy w osobnych kwartałach;
  zakres i bramka pozostają w W9.5 i ADR-034, ten plan nadaje im tylko miejsce;
- [ ] utworzyć `shared.commerce` albo równoważny moduł płatności usługowych z
  własnym descriptor, API, zdarzeniami, permissions, entitlementami i RLS;
- [ ] zdefiniować tenantowe `PaymentProviderConnection`, `AppointmentPayment`,
  refund, dispute, fee i append-only ledger bez przechowywania danych kart;
- [ ] pozwolić organizacji włączyć lub wyłączyć płatności; pierwsze wydanie ma
  jednego aktywnego providera na deployment, bez dowolnego miksowania operatorów
  przez organizacje;
- [ ] wdrożyć Stripe Connect w modelu SaaS platform: usługodawca jako merchant of
  record i prowizja platformy jako application fee, jeżeli potwierdzi to przegląd
  prawny, księgowy i umowa z providerem;
- [ ] użyć hostowanego/embedded onboardingu KYB i nie przyjmować dokumentów
  weryfikacyjnych do własnej bazy, jeśli provider może być ich właścicielem;
- [ ] obsłużyć BLIK/karty/P24 zgodnie z realnymi capability oraz ograniczeniami
  capture, refund i dispute, nie tylko z listą metod w UI;
- [ ] zabezpieczyć webhooki podpisem, idempotencją, kolejnością zdarzeń,
  rekonsyliacją i exact-tenant; return URL nie potwierdza zapłaty;
- [ ] zwroty, chargebacki i korekty prowizji księgować wpisami kompensującymi;
- [ ] po stabilizacji kontraktu ocenić adapter Mollie Connect; nie wdrażać
  drugiego providera przed dowodem potrzeby biznesowej.

### Bramka P5

- [ ] W9.5.2S ma zaliczoną własną bramkę z ADR-034 z zachowanymi dowodami;
- [ ] jedna płatna i jedna bezpłatna organizacja działają równolegle;
- [ ] powodzenie, odmowa, timeout, retry, zwrot częściowy, spór i zdarzenia poza
  kolejnością mają testy sandbox i lokalną rekonsyliację;
- [ ] kwota usługi, prowizji, opłaty providera, zwrotu i wypłaty daje się
  odtworzyć z ledgeru;
- [ ] aplikacja nie nadaje dostępu ani nie potwierdza wizyty wyłącznie na
  podstawie przekierowania przeglądarki.

## 10. P6 — Site Studio, AI i skills produktowe

- [ ] dokończyć W9.5.5 na istniejącym modelu: wersjonowana nawigacja, atomowy
  snapshot, komendy `GET/PUT /api/v1/sites/<site_id>/navigation/` i audytowana
  zmiana URL zostały dostarczone w W9.6.3, więc brakuje wyłącznie studia w
  panelu — drzewa i mapy z reorderem, undo/redo, klawiaturowego odpowiednika
  drag and drop oraz widoku adresu, SEO i gotowości podstrony; drugie drzewo
  nawigacji jest zabronione;
- [ ] wykonać W9.5.6 w całości: biblioteka, canvas, inspector, responsive preview
  i edycja w kontekście na kontrakcie optimistic locka i publikacji ADR-027;
- [ ] wdrożyć `shared.assistant` z W9.5.7 oraz `site.generate_draft`, który wybiera
  tylko zatwierdzony PageTemplate i kontrolowane bloki;
- [ ] wersjonować prompty, narzędzia i runtime skills oraz przypisać im ryzyko,
  wymagane permission, entitlement, zgodę, idempotency key i budżet;
- [ ] zapewnić równoważną ręczną ścieżkę, gdy provider AI lub SeoContentRank jest
  niedostępny;
- [ ] rozdzielić skills produktowe per capability i per vertical, ale nie
  duplikować logiki domenowej: skill planuje, a komenda aplikacyjna waliduje i
  wykonuje;
- [ ] dodać evale PL/EN dla prompt injection, cross-tenant, halucynowanej
  komendy, zmiany planu po zgodzie, kosztu, latencji i awarii providera;
- [ ] utrzymać operacje wymagające człowieka z ADR-035; automatyczna aktualizacja
  repozytoryjnego skill nie rozszerza autonomii asystenta klienta.

## 11. P7–P8 — Vertical Medical, staging i go-live

- [ ] MedPlano nie jest priorytetem od 2026-09-02; W10 i `develop-medplano`
  czekają na decyzję właściciela po domknięciu bazy (P0–P3);
- [ ] wykonać W10 dopiero po minimalnych bramkach P1–P5 wymaganych przez zakres
  płatnego pilota;
- [ ] stworzyć `develop-medplano` z kontraktu realnego verticala i deploymentu,
  a nie z założeń przed implementacją;
- [ ] utrzymać MedPlano poza dokumentacją kliniczną, diagnozą i przekazywaniem
  danych zdrowotnych do AI bez osobnego ADR-u i oceny regulacyjnej;
- [ ] uruchomić osobny VPS MedPlano z bazą, storage, Redis, sekretami, monitoringiem
  i backupem oraz wykonać test odtworzenia całego środowiska;
- [ ] domknąć rollout W9.6 na stagingu — read-only i `suggest_only`, potem
  `publish_with_approval` na blogu systemowym, `autonomous` dopiero po
  udokumentowanym pilocie i rollback drillu; kod jest gotowy, a bramka wyjścia
  W9.6 zamyka się dopiero tutaj, bo wymaga stagingu i działającego connectora
  SeoContentRank po drugiej stronie;
- [ ] przejść W11 z dodatkowymi runbookami dla Connect, skills/AI, kosztów modeli,
  awarii providera i cofnięcia nieprawidłowej aktualizacji skill;
- [ ] wymagać wersjonowanego obrazu, migracji próbnej, smoke E2E i rollbacku
  aplikacji, bazy oraz DNS przed decyzją go-live.

## 12. Globalna definicja ukończenia

- [ ] każda funkcja ma właściciela danych i działa tylko w aktywnym deployment;
- [ ] backend egzekwuje TenantContext, permission i entitlement niezależnie od
  panelu, asystenta, MCP i skill;
- [ ] mutacje mają audit, idempotencję, transakcję/outbox oraz kompensację, gdy
  skutek zewnętrzny nie jest atomowy;
- [ ] API jest w OpenAPI, a klient TypeScript jest generowany;
- [ ] testy obejmują cross-tenant, współbieżność, retry i ścieżki odmowy;
- [ ] PL/EN, mobile, klawiatura i axe są częścią odbioru interfejsu;
- [ ] lokalne testy, staging smoke i dowody produkcyjne są raportowane osobno;
- [ ] repozytoryjne i produktowe skills mają osobne katalogi, odpowiedzialność i
  bramki bezpieczeństwa;
- [ ] aktualizacja skill jest automatyczna dla właściciela produktu, ale nadal
  pozostawia przeglądalny diff, testy, commit i możliwość rollbacku;
- [ ] go-live nie następuje bez działającego backupu, restore, monitoringu,
  obsługi incydentu i formalnego przeglądu privacy/płatności.

## 13. Źródła i zależności

- ADR-021 — monorepo, moduły i profile deploymentu;
- ADR-022 — tenancy i RLS;
- ADR-024 — API, OpenAPI i zdarzenia;
- ADR-025 — runtime, sekrety i odtwarzanie;
- ADR-026 i ADR-034 — billing SaaS oraz odroczenie realnego providera;
- ADR-027–ADR-031 — strony, domeny, komunikacja, Booking i Site Studio;
- ADR-033 — produktowy asystent AI, narzędzia, zgody i głos;
- ADR-035 — publikacja i granice automatyzacji;
- ADR-036 (Accepted), ADR-037 (Deferred), ADR-038 (Accepted) — decyzje P0:
  tożsamość i konto klienta, Appointment Commerce, repozytoryjne Agent Skills;
- ADR-039 (Accepted) — dwa reżimy izolacji: RLS domyślnie, tabele publiczne z
  deklaracji w deskryptorze;
- oficjalny model SaaS Platforms w Stripe Connect:
  https://docs.stripe.com/connect/saas-platforms-and-marketplaces;
- Mollie Connect jako kandydat drugiego adaptera:
  https://docs.mollie.com/docs/connect-overview.
