# Handoff następnej sesji

## Odbiór integracji trzech repozytoriów, 2026-09-06

Bieżący zakres i jego granice opisuje
[SEO-INTEGRATION-ACCEPTANCE.md](SEO-INTEGRATION-ACCEPTANCE.md).
Poniższe checkpointy są historią wcześniejszych pakietów, nie aktualną listą WIP.

Core `186157d` ma zamówienia audytów z kredytami/panelem, delegację GSC
i blokadę erasure przed odłączeniem, przegląd propozycji treści oraz kontrolowany
odbiór strony z briefu. Pełne testy: 690 PostgreSQL, 171 JS w całym monorepo
(128 frontend, 21 kontraktów, 8 UI, 14 bloków); po poprawce mediów końcowy
frontend ponownie 131 passed / 34,37 s. OpenAPI/client bez driftu.
RLS nowych tabel ma rzeczywisty dowód bez BYPASSRLS, nie tylko test właściciela bazy.

SCR `971acae` obejmuje wcześniejsze `f1d9c95`, `1bc2bcc`, `e8db148`, `6c621de`:
brief, projekty, neutralne propozycje, dostawę, GSC, harmonogramy i pomiary,
WordPress opisów meta oraz jawnie uruchamiane workery. Końcowy backend
383 PostgreSQL / 19,65 s; frontend 134 testy, lint/typy/build Node 24.
Obraz workerów ma 19 asercji bez sieci, z kontrolą konfiguracji i zatrzymania.
SSA `3123ca2` po `60a84db`/`c05919e` ma osobne źródła/tenantów, trwałe zlecenia,
delegowane GSC i kontrolowane wyniki dokładnego wykonania; 578 PostgreSQL.

Pilot wszystkich API: osiem przypadków / 188,94 s; po strumieniowym ograniczeniu
transportu osobny test obserwacji ponownie przeszedł / 39,47 s. WordPress 6.9.1,
PHP 8.3, MariaDB 11.4: 127 asercji usług, identyczny receipt dwóch równoległych
procesów, 26 asercji HTTP z native login/nonce i publicznym opisem. Granice
Google/model/crawl są syntetyczne; nie wydano pieniędzy u dostawców.

Core-only uruchomiony w osobnym stacku: trzy moduły core, brak tras SEO/Sites,
pusty harmonogram, zdrowe API/frontend o zgodnym profilu, rola aplikacyjna RLS,
zero różnic plików Pythona obrazu wobec checkoutu. Business `0c07d0f`:
siedem kontroli HTTP strony, sitemap, rzeczywistego PNG i odmowy dla obcego
hosta oraz health frontend/backend. 344 pliki Pythona obrazu zgodne z checkoutem,
brak oczekujących migracji. Test wykrył i zamknął brak route publicznych obrazów.
Oba lokalne stosy zachowane do przeglądu. Nie potwierdzono DNS ani procesu
uploadu/skanowania plików — fixture tworzy zatwierdzony obraz w lokalnym S3.

Zbiorczy artefakt bez sekretów:
[seo-integration-2026-09-06.json](evidence/seo-integration-2026-09-06.json).
Odtworzenie publicznego testu: [runtime/README.md](runtime/README.md).
Pierwsza wersja integracji I0–I5 jest odebrana lokalnie. Następne prace to
skonfigurowany pilot na instancjach oraz wymienione niżej rozszerzenia produktu.
Jawna lista I6 i backlog produktu są w
[planie 14](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md), a przebieg
testu dla właściciela produktu w
[SEO-INTEGRATION-MANUAL-TEST.md](SEO-INTEGRATION-MANUAL-TEST.md).

To pierwsza wersja integracji, nie cały docelowy produkt SEO. Brief startuje
w SCR dla istniejącego Site/połączenia/grantu Core; nie ma jeszcze asystenta
startującego ten proces wyłącznie z konta Core. A4/WordPress edytują opis meta,
nie artykuły ani strukturę. GA, pełna strategia i automatyczna publikacja są
osobnymi rozszerzeniami. Sekrety/provider OAuth, realny projekt i produkcyjny
deployment wymagają konfiguracji właściwych instancji. Główne repozytoria
Core `4cc8684`, SCR `b42e284`, SSA `ba197d7` pozostają nietknięte.

Worktrees: `.runtime/worktrees/seo-integration-i0-i1`,
`.runtime/worktrees/scr-integration-i0-i1`, `.runtime/worktrees/ssa-ecosystem-integration`.
Nie przenosić starego HANDOFF ponad nowszymi zmianami głównej gałęzi. Przed
scaleniem ponownie sprawdzić stan Claude; zakresy commitów i testy są oddzielne
od dowodów wdrożenia na serwerach produktów.

## Checkpoint integracji I2–I5, 2026-09-06 19:25

To jest bieżący punkt wznowienia; kolejne sekcje zachowują dowody wcześniejszych pakietów.
Core `65a931b`/`8feb931`/`463f2c5` ma `shared.seo`: trwałe zamówienie audytu,
rezerwację i pojedyncze rozliczenie kredytów, uzgadnianie po timeout, podpisany
callback i panel PL/EN z potwierdzeniem aktualnej ceny. Lista zamówień nie pobiera
pełnych raportów; raport szczegółowy zachowuje wszystkie strony paginacji.
Dowody: 654 PostgreSQL przed UI, następnie 29 testów SEO, 120 frontend i build.
Źródło/cena/feature są jawną konfiguracją operatora, nie automatyczną zmianą planów klientów.

SCR `c7ffc84` i SSA `c05919e` mają delegację GSC (Google tokeny wyłącznie w SSA),
ograniczone granty, cofnięcie i usunięcie prywatnych kopii. SSA `60a84db` dodaje
trwałe operacje ośmiu modułów i bezpieczne ponowienie przekazania tego samego run ID
do brokera. SSA: 560 PostgreSQL + 8 wariantów wyścigu worker/broker. SCR zamknięty
pakiet: 280 PostgreSQL, 104 frontend i build. GSC w Core jest nadal WIP agenta.

Koordynator dodał I4 po stronie Core: katalog kontrolowanych pól szablonów,
odbiór nowej strony jako szkicu oraz niemutowalne `BlueprintImportReceipt` z RLS.
Powtórzenie zachowuje ten sam page/proposal; istniejący klucz strony, zmieniony
katalog, obce pola i naruszenia grantu są odrzucane. Akceptacja w SCR nie publikuje
strony i nie zastępuje przeglądu w Core. Kolejka pokazuje również zagnieżdżone FAQ
i listy cech. ADR-046 opisuje kontrakt oraz obowiązek przeglądu przykładowych
kontaktów i odnośników. Schemat można cofnąć tylko przed zapisaniem receiptów;
po użyciu wycofujemy aplikację przy zachowaniu rozszerzonego schematu.

Piloty rzeczywistych procesów HTTP: wcześniejsze 4 scenariusze 62,16 s obejmują
podgląd, niezależne projekty oraz completed/partial i rozliczenie audytu; następnie
pełna dostawa metadanych i akceptacja w Core 1 passed / 32,40 s; brief bez audytu
→ generacja SCR → draft Core → przegląd → powtórzenie 1 passed / 29,80 s.
Google, model i zakończenie audytu są syntetycznymi granicami testu; nie wykonano
płatnych wywołań ani produkcyjnego deploymentu. Ścieżki odtworzenia w lokalnym pilocie.

Nadal autoryzowane i realizowane: Core I3 panel/zgody GSC, SCR I4 panel briefu,
SCR I5 harmonogramy i rzeczywiste utrwalone pomiary, WordPress v1 (obecna komenda
A4 `set_meta_description`, bez zmian struktury CMS), końcowa zgodność API, obrazy
i testy całych pakietów. Nie kończyć pracy z pytaniem o kontynuację. Główne katalogi
trzech repo pozostają oddzielone od izolowanych gałęzi integracyjnych.

## Integracja SEO — aktywna kontynuacja całości, 2026-09-06

Maciej polecił pracować aż do zakończenia całego zakresu I0–I5. Nie zatrzymywać
pracy po pojedynczym pakiecie z pytaniem o kontynuację. Koordynator prowadzi
trzy osobne worktrees; główny Core `4cc8684` pozostaje nietknięty. Poniższy
starszy wpis `7dc4604` opisuje poprzedni zamknięty pakiet, nie bieżący WIP.

Ukończone pakiety: SCR `455981e` (A4, panel PL/EN, Projects/provisioning,
resolver i CLI `preview_proposal`), SSA `d8d12f2` (callbacki wg źródła,
powiązania/historia, idempotentne zamówienie audytu), Core `b284533`
(baza treści, tokeny, przegląd metadanych), scalenie main `96c4a6a` i migracja
łącząca `a43aacf`. Obecny WIP: agent Core wdraża shared.seo i rozliczenia I2;
agenci SSA/SCR wdrażają I3 OAuth/granty GSC i panel. Koordynator domyka panel
przyjęcia propozycji w Core i piloty HTTP. I4/I5 nadal otwarte. Wszystko w
osobnych katalogach, bez deployu i wywołań płatnych dostawców.

Nowe dowody: SCR backend **251 passed PostgreSQL** (w tym współbieżne decyzje
A4 i provisioning), frontend **91 passed**, ESLint/TypeScript i webpack build poprawne.
Resolver/pilot/paginacja po dodatkowych testach: **32 passed SQLite**.
Core baza treści i pełny cykl review: **612 passed PostgreSQL**, po scaleniu
ukończonego usuwania tenanta **618 passed**, **154 testy JS**,
mypy 302 pliki, import-linter 302/517 i jeden zachowany kontrakt; lint, typy,
formatowanie, migracje i generowany kontrakt API zgodne. Osobna rola PostgreSQL
NOLOGIN/NOSUPERUSER/NOBYPASSRLS z SELECT tylko na `sites_contentproposal`
zwróciła kolejno bez tenanta / tenant A / tenant B: **0 / 1 / 1**; rola usunięta
po teście. Migracja `sites.0025` odmawia cofnięcia schematu po zapisaniu historii
review. Panel Core przyjęcia do szkicu i porównania metadanych jest w bieżącym
pakiecie koordynatora; 7 testów (PL/EN, axe bez dowodu kontrastu, wyścig odczytów),
pełny frontend 114 passed / 29,12 s, TypeScript i ESLint przechodzą.
SSA: **517 passed PostgreSQL** i jeden dodatkowy test stabilnej paginacji.
Nie sumować tych wyników jako końcowego suite całego bieżącego WIP.

Pilot przez trzy rzeczywiste lokalne API: **1 passed / 25,16 s**,
101 ustaleń z paginacją, propozycja SCR 201, podgląd Core 200, cofnięcie grantu
403, brak zmiany draftu i publikacji. Odtworzenie i granice dowodu:
[lokalny pilot](SEO-INTEGRATION-LOCAL-PILOT.md). Memex checkpoint:
`2026-09-06-mac-155517`. Drugi pilot: provisioning SCR→SSA **1 passed / 18,01 s**,
dwa workspace/tenants na tym samym URL, ponowienie bez duplikatu i obcy projekt
404, bez audytów. Po ukończeniu kolejnych gałęzi przypiąć commity i aktualne
bramki. Źródła referencyjne GSC i decyzja: grant ograniczony do projektu;
domain property wymaga filtra page we wszystkich agregatach, nie tylko w
wierszach URL. Jedno połączenie Google na workspace pozostaje jawnym limitem.

## Integracja SEO — osobna gałąź, 2026-09-06

**Najnowszy pakiet:** SCR `7dc4604`, na gałęzi `codex/seo-integration-i0-i1`
w `.runtime/worktrees/scr-integration-i0-i1` (worktree repozytorium SeoContentRank).
Połączenia i generacja mają jawny workspace; wysyłka sprawdza aktualne cofnięcie,
powiązanie payloadu/trybu/celu i zgodność transportu. Import sprawdza projekt oraz
instancję SSA. Trzy migracje zachowują historię bez zgadywania właściciela;
rollback odmawia przy kolizjach między workspace/źródłami. Nie uruchomiono migracji
na bazach produktu ani płatnych dostawców.

Dowody SCR: 170 testów na SQLite i osobno 170 na PostgreSQL (bez skipów), w tym
rzeczywiste MigrationExecutor forward/backward i odmowy rollbacku; 69 testów
frontendu, lint, typy i OpenAPI/klient bez driftu. `SAAS_CORE_CONTRACTS_DIR`
wskazuje kontrakt naszej gałęzi Core, a vendor ma LF wymuszone przez `.gitattributes`.
Testy PG: `PYTHONPATH=<SCR worktree>/apps/backend/src;<SCR worktree>/.runtime`,
`python -m pytest apps/backend/tests --ds=scr_pg_settings`; lokalny nieśledzony
moduł `.runtime/scr_pg_settings.py` wybiera bazę `test_scr_integration_20260906`,
nie bazę produktu. Standardowy suite używa SQLite memory.

Gałąź Core zawiera ukończony commit Claude `9d9f916` (profiles), bez jego późniejszego
WIP usuwania tenanta. Po synchronizacji: backend 579 passed, mypy 301 plików,
import-linter 1 kontrakt, lint/typy/formatowanie, migracje i OpenAPI/klient zgodne.
JavaScript: 21 kontraktów, 8 UI, 14 bloków, 111 frontendu; frontend powtórzony
z `--maxWorkers=2 --no-file-parallelism` po zawieszeniu zamykania równoległego runnera.
Test listy modułów uwzględnia `shared.profiles`. Integracyjny ADR ma teraz numer
**043**, ponieważ 042 jest użyty przez równoległą decyzję Claude o usuwaniu tenanta.

Aktywny punkt wznowienia integracji to
[plan 14](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md),
[ADR-043](../adr/ADR-043-Integracja-SaaS-Core-SCR-i-SSA.md) i
[kontrakt I0](../architecture/seo-ecosystem-integration.md).
Gałąź `codex/seo-integration-i0-i1` powstała z `3a5391b` w
`.runtime/worktrees/seo-integration-i0-i1`. Claude prowadzi równolegle P3
w głównym katalogu. Przed scaleniem porównać bieżący main i przenieść tę sekcję,
zachowując jego nowszy handoff; opis starszego stanu poniżej pozostaje historyczny.

Ustalono wspólny podział danych, grantów, kosztów i historii trzech produktów.
W kodzie SaaS Core naprawiono podgląd zmian: `content:read` może wykonać dokładnie
POST `/api/v1/sites/changes/`, a serwis sprawdza uprawnienie, entitlement oraz
grant konkretnej witryny/kolekcji przed odczytem prywatnych bloków. Powiązanie
wpisu z witryną jest sprawdzane przez jego rzeczywistą kolekcję. Nie zmieniono
wire schema, publicznego klienta, modeli ani migracji.

Dowody pierwszego pakietu `e1d16d6`: 570 testów backendu na świeżej osobnej bazie PostgreSQL, w tym 14 nowych
przypadków autoryzacji podglądu; mypy 288 plików, import-linter 1 kontrakt;
Ruff i kontrola migracji bez driftu. Node 24.13.0: lint, typy TypeScript,
formatowanie oraz 111 testów frontendu, 8 UI i 14 bloków stron. Regeneracja
OpenAPI i klienta przez drf-spectacular/openapi-typescript jest zgodna bajtowo
po normalizacji końców linii z oboma plikami kanonicznymi.
Testy kontraktów: 21/21. Przy odbiorze ujawniono cztery zastane błędy testów
deploymentu na bazie `3a5391b`; trzy fixture pomijały wymagane `platformTables`,
a oczekiwany profil publiczny pomijał `profileHash`. Zaktualizowano tylko fixture
i asercję (6 linii), zachowując pierwotne przypadki odmowy oraz sprawdzając hash.
Kolejność zapytań testuje ustawienie tenanta przed odczytem bloków;
testowa rola właściciela bazy nie dowodzi zachowania produkcyjnego RLS.

Do powtórzenia testów użyć interpretera z głównego `.venv`, ale `PYTHONPATH`
ustawić na **src tego worktree**. Użyta nazwa `POSTGRES_DB=saas_core_i1_20260906`
tworzy osobną bazę `test_saas_core_i1_20260906`; sekret przez `POSTGRES_PASSWORD_FILE`.
Polecenie: `python -m pytest apps/backend/tests -q --reuse-db --create-db
--basetemp=.runtime/pytest-i1-fresh` (najpierw utworzyć rodzica `.runtime`).
`--create-db` jest potrzebne po pełnym przebiegu: testy transakcyjne usuwają
seed ról i kolejny `--reuse-db` bez odtworzenia traci role. Statyczna kontrola
migracji używa `PGCONNECT_TIMEOUT=2`, bo celowo pyta nieczynny port.

Otwarte: uruchomiony pilot SSA → SCR → SaaS Core; w tej sesji brak skonfigurowanych
kluczy i konkretnego powiązania zasobów. Nie wykonano deployu, testów przez Caddy
ani publikacji. I0 ma zapisany kierunek, a I1 ma sprawdzony warunek wstępny
po stronie SaaS Core — cały przepływ nie jest jeszcze odebrany.
Następny pakiet SCR: trwała neutralna propozycja A4, która wiąże właściciela
kandydata z generacją i celem, oraz resolver inventory dla docelowego zasobu.
Scoped helpery i `ContentChangeSet` nie są jeszcze pełnym modelem tej propozycji.
Przed zapisem treści: kontrakt hasha bazy, granty pozostałych odczytów draftu
i przegląd zatwierdzania. Przed płatnymi analizami: routing callbacków SSA.

## Wcześniejszy stan prac głównego repozytorium

**Aktualizacja:** 2026-09-03

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Audyt z 2026-09-02 i decyzja właściciela dodały nadrzędny
[plan rozwoju po audycie i Agent Skills](../../Plan/Wdrozenie/13-PLAN-ROZWOJU-PO-AUDYCIE-I-AGENT-SKILLS.md).
Tego samego dnia plan przeszedł przegląd wobec kodu i dostał poprawki: W9.5.5
ma już model nawigacji z W9.6.3, rollout W9.6 jest umieszczony w P8, W9.5.2S
jest pierwszym pakietem P5, a P1 zaczyna od uzgodnienia katalogu modułów z
kodem. Naruszenie Core → Shared zostało usunięte (komenda
`provision_platform_workspace` przeniesiona do `shared.billing`); import-linter
jest znów zielony.

P0 jest zamknięte decyzjami właściciela z 2026-09-02: ADR-036 (tożsamość,
profile, konto klienta), ADR-038 (repozytoryjne Agent Skills) i ADR-039 (dwa
reżimy izolacji: RLS domyślnie, tabele publiczne z deklaracji w deskryptorze)
są `Accepted`; ADR-037 (płatności za wizyty) jest `Deferred` razem z P4/P5.
MedPlano nie jest priorytetem — celem jest Core, z którego później powstają
serwisy (MedPlano, tanie strony i kolejne). Baza = P0–P3, kolejność
P0 → P1 → P2 → P3.

P1 jest w toku. Zrobione: katalog modułów zgodny z kodem (deskryptory
`vertical.medical`, `config.medplano` i `core.audit` usunięte, `core.health`
dodany, profil `medplano` zaparkowany w `deployments/_planned/`), nowy profil
`business` jako drugi produkt dowodowy, `pnpm deployment:check` odrzuca
deskryptor aplikacji bez kodu, `tests/test_module_catalog.py` pilnuje obu
kierunków, obraz frontendu w CI buduje się dla `business`. ADR-039 dla Sites:
`backend.publicTables` jest w schemacie i w każdym deskryptorze (sześć tabel
publicznych w `shared.sites`: domain, site, publication, contentcollection,
contententry, contententrypublication — dokładnie to, co renderer czyta bez
kontekstu), migracja `sites.0024` wymusza RLS na 11 tabelach prywatnych, test
`tests/test_tenant_isolation_regimes.py` sprawdza oba reżimy na prawdziwym
PostgreSQL, a `issue_content_grant`/`revoke_content_grant` wymagają
`--organization` i ustawiają tenant przed pierwszym odczytem (test kolejności
zapytań w `tests/test_sites_grant_commands.py`).

ADR-039 obowiązuje też w `shared.billing` (2026-09-03). Nowy
`billing/tenant_scope.py` daje `billing_tenant_scope` i `billing_organization_ids`;
pięć przemiatań (lifecycle, rekonsyliacja, wygaszanie override'ów, zwalnianie
rezerwacji, faktury) pracuje organizacja po organizacji, procesor Stripe
wyznacza tenant z `BillingProfile` po `external_customer_id` przed dotknięciem
tabeli tenantowej, a zadanie faktury dostaje `organization_id` w payloadzie.
Migracja `billing.0013` zakłada polityki na 11 tabelach i sześć wyzwalaczy
relacji rodzic–dziecko.

**Reguła wykrycia w teście izolacji miała lukę** (znalezione 2026-09-03 przy
przeglądzie kont). Test pytał, czy model dziedziczy `TenantScopedModel`, więc
tabela niosąca organizację zwykłym kluczem obcym była dla niego niewidoczna.
Pusta lista `KNOWN_OPEN_PRIVATE_TABLES` znaczyła więc mniej, niż brzmiała.
Sprawdzenie wprost na bazie pokazało siedem tabel bez ani jednej polityki:
sześć w `core.organizations` (`membership`, `organization`, `role`,
`invitation`, `billingprofile`, `organizationauditentry`) i
`billing_stripewebhookevent`. Odczyt członkostw z ustawionym
`app.organization_id` zwraca członkostwa wszystkich organizacji naraz — dziś
izolację tych tabel trzyma wyłącznie kod aplikacji, bo `Membership` nie ma
menedżera tenantowego i każde zapytanie musi samo filtrować.

Reguła jest już mechaniczna (klucz obcy do `Organization` albo sam rejestr
organizacji), a te siedem tabel stoi na liście długu z uzasadnieniem: każda
jest czytana lub zapisywana przed poznaniem tenanta — logowanie pyta o
członkostwa, nie znając jeszcze organizacji; role globalne mają
`organization IS NULL`; zaproszenie czyta się po tokenie; procesor Stripe
rozpoznaje tenanta po `BillingProfile`; zdarzenie webhooka zapisujemy przed
odczytaniem payloadu. Zamknięcie wymaga decyzji per tabela i osobnego ADR-u
(ADR-039 §6, pozycja P1) — nie jednej migracji.

Uwaga wykonawcza: indeksem przemiatania jest `Organization`, nie
`BillingProfile` — profil powstaje tylko dla organizacji z serwisu onboardingu,
więc użycie go pomijałoby resztę (to był pierwszy błąd tej zmiany, złapany
przez testy lifecycle).

Do zrobienia w P1, w tej kolejności: (1) `deployment.json` składa
`INSTALLED_APPS`, URL-e, zadania i frontendowe route/menu — dziś
`INSTALLED_APPS` jest stałą listą, więc `core-only` ma zainstalowane wszystkie
moduły Shared; (2) artefakt modułów i hash profilu; (3) macierz
wersja/migracje/rollback. Potem P2 (skills, `pnpm ai:validate`, CI) i P3.

**Kredyty** (2026-09-03) — domena gotowa w `shared.billing`. Decyzje
właściciela: kupione kredyty nie wygasają; plan daje miesięczną pulę, która się
odnawia i nie przechodzi dalej; zużycie bierze najpierw pulę planu, potem
kupione; kredytują operacje AI (W9.5.7) i content operations (W9.6). Wyłącznie
dla naszych klientów — kredyty klientów końcowych tych firm są poza zakresem.

Model: katalog `CreditPack` i `CreditOperation` (niezależny od tenanta),
tenantowe `CreditBalance`, `CreditPurchase`, `CreditReservation` i append-only
`CreditLedgerEntry`. Ledger jest prawdą, saldo jest jego cache'em — test
odbudowuje jedno z drugiego. Serwisy w `billing/credits.py`: rezerwacja →
rozliczenie/zwolnienie (jak przy quotach, bo operacja AI może paść), zwrot
przez wpis kompensujący, zakup, korekta operatora, dwa przemiatania.

Dwie rzeczy zostały świadomie niedokończone:

1. **Pula w planach nie jest jeszcze zapisana w katalogu.** Opublikowana wersja
   planu jest niemutowalna w modelu i w bazie (wyzwalacz z migracji
   `billing.0003`), więc zmiana tego, co plan daje, wymaga nowej wersji planu.
   Zamierzone wartości (`profile` 50, `starter` 200, `pro` 1000) czekają w
   `PLAN_ALLOWANCES` w migracji `billing.0016` i mają wejść **razem z W9.5.2S**,
   gdy realne Stripe Product/Price i tak wymuszą nowe wersje planów. Do tego
   czasu pula z planu wynosi 0, a działają kredyty kupione i korekta operatora.
   Mechanizm jest kompletny: czyta `credits.monthly` ze snapshotu entitlementów,
   więc zadziała w chwili, gdy wersja planu to zadeklaruje.
2. **Operacje content operations są zaseedowane jako nieaktywne**, czyli
   darmowe. Naliczanie ich zmienia ekonomię connectora SeoContentRank, który
   odmawia fail-closed na nieznaną odpowiedź — włączenie wymaga uzgodnienia
   kontraktu po obu stronach (kod odmowy `credits_exhausted`, HTTP 402).

Do zrobienia dalej przy kredytach: API panelu (saldo, historia, pakiety,
zakup), zakup przez port providera (simulator teraz, Stripe z W9.5.2S) i
podpięcie zużycia w W9.5.7.

Testy backendu da się uruchomić z Windows bez WSL: venv poza repo przez
`UV_PROJECT_ENVIRONMENT=<katalog>` (`uv sync --project apps/backend`), hasło
bazy przez `POSTGRES_PASSWORD_FILE=.runtime/secrets/postgres_password`, a
PostgreSQL z `docker compose up -d postgres database-bootstrap redis`.

Skills mają być utrzymywane przez agentów; właściciel produktu nie
synchronizuje ani nie edytuje ich ręcznie.

Repozytoryjne skills deweloperskie i produktowe skills `shared.assistant` są
dwoma osobnymi systemami. Pierwsze pomagają zmieniać kod, drugie działają w
TenantContext przez wersjonowane komendy aplikacyjne. Żaden skill nie zmienia
zaakceptowanego ADR-u ani nie autoryzuje wdrożenia produkcyjnego.

Istniejące W9.5 i W9.6 pozostają planami szczegółowymi. Nie duplikuj ich modeli
ani kontraktów w planie poaudytowym.

W9.5 (`Plan/Wdrozenie/10A-W9.5-Customer-Experience-Commerce-i-AI.md`) ma
ukończone W9.5.1–W9.5.4; W9.5.5–W9.5.8 są po bazie (P6). W9.5.2S — realny
Stripe dla abonamentów — wchodzi poza kolejnością, gdy tylko właściciel
dostarczy konto Stripe (zapowiedziane na 2026-09-03); patrz sekcja niżej.

W9.6 — Publication Platform i gotowość na SeoContentRank — jest ukończone
lokalnie (kod, testy, panel). Zostały wyłącznie rolloutowe pozycje W9.6.8 i
bramka wyjścia, które wymagają stagingu i connectora po drugiej stronie; żyją w
P8. Model nawigacji jest jeden i powstał w W9.6.3.

Nie wracaj teraz do bramek wymagających prawdziwego stagingu/VPS. Są odłożone do
sesji z dostępem do hosta, domeny, GHCR i GitHub Environment.

## Realny Stripe (W9.5.2S) — w toku od 2026-09-03

Klucze testowe są na miejscu: `.runtime/secrets/stripe_secret_key` (wklejony
przez właściciela) i `.runtime/secrets/stripe_webhook_secret` (pobrany przez
`stripe listen --print-secret`, Stripe CLI 1.28.0 z `A:\AAAExtensions`).
Decyzje podatkowe i zakres portalu są w ADR-040.

Zrobione: compose montuje oba sekrety do backendu, workera i schedulera i
przekazuje `STRIPE_PORTAL_CONFIGURATION_ID` oraz `STRIPE_LIVEMODE`; start
odmawia przy `BILLING_PROVIDER=stripe` bez kompletu (klucz, sekret webhooka,
konfiguracja portalu), z wyjątkiem środowiska testowego; adapter wysyła adres
przy tworzeniu Customer, Checkout zbiera adres i NIP i zapisuje je z powrotem,
subskrypcja ma `automatic_tax`, a portal jest otwierany na przypiętej
konfiguracji.

**Zweryfikowane bezpośrednio na koncie testowym** (sondy, obiekty posprzątane):

- setup-mode Checkout **wymaga `currency`** w bieżącej wersji API
  (`2026-07-29.dahlia`) — dotychczasowy kod nie wysyłał jej wcale, więc
  pierwsze prawdziwe wywołanie by padło. Naprawione;
- `tax_id_collection` w setup mode działa **tylko** z
  `customer_update[name] = auto`;
- `automatic_tax` na subskrypcji, `tax_behavior: exclusive` na cenach
  (jednorazowych i cyklicznych) oraz portal z parametrem `configuration`
  przechodzą;
- **konto nie ma żadnej rejestracji podatkowej**, więc Stripe Tax nie naliczy
  VAT, dopóki właściciel nie doda co najmniej Polski;
- konfiguracja portalu `bpc_1UBYhcPI8KcdVPQw6znPqGxc`: anulowanie
  `at_period_end` (zgodnie z ADR-040), `customer_update` bez `tax_id`,
  `subscription_update` wyłączone.

**Konto testowe jest skonfigurowane** (2026-09-03, wszystko przez API):

- Stripe Tax `active`; siedziba Condictor Sp. z o.o., Kościuszki 3/4, 38-300
  Gorlice, PL; domyślne zachowanie `exclusive`;
- rejestracja VAT PL `active` w wariancie `small_seller` — poniżej progu
  10 000 EUR sprzedaż transgraniczna B2C jest opodatkowana stawką polską;
- trzy produkty `saas_core_plan_{profile,starter,pro}` z cenami 99/149/299 PLN
  netto miesięcznie, `tax_behavior: exclusive`, zmapowane na wersje planów v2;
- portal: `tax_id` w `customer_update`, anulowanie `at_period_end`, zmiana
  planu włączona z prorata.

Dowód, że VAT liczy się naprawdę (`tax.calculations` na starterze 149 zł netto):
firma z PL 183,27 zł (23%), firma z DE z ważnym NIP-em UE 149,00 zł (0%,
odwrotne obciążenie), konsument z DE 183,27 zł (stawka polska, bo `small_seller`).

Nowe wersje planów v2 z `credits.monthly` (50/200/1000) są opublikowane
migracją `billing.0017`; wersje v1 zostają niezmienne i subskrypcja na nich po
prostu nie ma puli, dopóki nie przejdzie na bieżącą.

Do zrobienia po stronie właściciela: rejestracja OSS albo włączenie
monitorowania progu 10 000 EUR (gdy zbliżymy się do progu), potwierdzenie
modelu z księgową, decyzja o własnych dokumentach sprzedaży obok faktur Stripe.
Konto live to osobny świat — trzeba je skonfigurować od nowa kluczem live po
aktywacji konta i przy publicznym adresie na webhooki.

Pakiety kredytów też są w Stripe (49/199/699 zł netto, jednorazowe) i mają
własną tabelę mapowań `CreditPackPrice` — świadomie osobną od
`StripePriceMapping`, bo subskrypcja i checkout wskazują mapowanie planu, a
wspólna tabela pozwalałaby na stan „subskrypcja wyceniona jak pakiet kredytów".
Zakup działa: `services.create_credit_checkout` otwiera Checkout w trybie
płatności jednorazowej z `automatic_tax`, zapisuje sesję na `CreditPurchase`, a
pulę powiększa **wyłącznie webhook** (`checkout.session.completed` z
`saas_core_credit_purchase_id` w metadanych). Symulator rozlicza od razu,
prawdziwy Stripe nigdy.

Do zrobienia w repo: ścieżka end-to-end na prawdziwym Stripe przez
`stripe listen` (wybór planu → Checkout → webhook → entitlementy oraz zakup
kredytów), testy podpisu, kolejności zdarzeń, retry, SCA/3DS i grace/read-only,
API panelu dla kredytów (saldo, historia, pakiety, zakup), prezentacja kwoty
brutto dla konsumenta (ADR-040 §2), runbook aktywacji i rollbacku.

### Lokalny podglad frontendu

`pnpm runtime:up`, potem panel na `http://localhost:8080`. Uruchomienie
2026-09-03 na profilu `business` wykryło trzy błędy, których nie widział żaden
z 491 testów — wszystkie naprawione:

1. **`deployment-check` nie mógł działać w buildzie frontendu.** Sprawdzenie
   istnienia Django app szukało `apps/backend/src`, a obraz frontendu kopiuje
   tylko `apps/frontend`, `deployments` i `packages`. Build padał. Teraz
   sprawdzenie pomija się tam, gdzie nie ma drzewa backendu, i mówi o tym
   wprost; tę samą gwarancję trzyma z drugiej strony
   `tests/test_module_catalog.py`.
2. **Kontener `migrate` nie dostawał sekretów Stripe.** Nadpisuje własną listę
   `secrets:`, więc wpisy z anchora go nie dotyczyły, a ustawienia czytają
   klucz przy importie — migracje nie startowały wcale. Sekrety dopisane; skrypt
   sprawdzający pokazuje, że mają je wszystkie usługi backendowe.
3. **`sites_e2e_fixture` nie ustawiał tenanta** przed zapisem
   `EntitlementSnapshot`, który od `billing.0013` ma wymuszone RLS. Baza
   odmawiała wstawienia — głośno, więc w dobrym kierunku, ale komenda była
   martwa. Naprawione; wszystkie komendy zarządzające, które dotykają tabel
   tenantowych, ustawiają teraz tenanta.

Konto do podglądu (dane syntetyczne, tylko lokalnie):
`w6-e2e-podglad@example.test` / `PodgladLokalny2026!`, rola `owner`, z profilem
billingowym. Usunięcie: `sites_e2e_fixture cleanup --email … --slug …`.
Zweryfikowane ekrany: strona główna (profil `business`), panel Start, Plan i
płatności (trzy plany 99/149/299 zł **netto**), kreator witryny (adres
`.business.localhost`). Panel nie ma jeszcze niczego o kredytach — API panelu
dla nich jest wciąż do zrobienia.

### Prawdziwy Stripe włączony lokalnie (2026-09-04)

Stack stoi teraz na `BILLING_PROVIDER=stripe` w trybie testowym. Przełączenie
wymagało trzech rzeczy, z których dwie były błędami:

1. `stripe listen --forward-to http://localhost:8080/api/v1/billing/webhooks/stripe/`
   (CLI 1.28 z `A:\AAAExtensions\stripe.exe`, klucz czytany z pliku sekretu, nie
   z linii poleceń). Sekret podpisu okazał się ten sam, który już leżał w
   `.runtime/secrets/stripe_webhook_secret` — CLI wydaje go per konto, nie per
   uruchomienie. Zmienne `BILLING_PROVIDER`, `STRIPE_LIVEMODE` i
   `STRIPE_PORTAL_CONFIGURATION_ID` dopisane do `.env` (plik jest gitignorowany;
   wzorzec stoi w `.env.example`).
2. **Bootstrap uruchamiał katalog symulatora niezależnie od dostawcy.** Serwis
   `migrate` miał zaszyte `configure_simulated_prices`, a ta komenda odmawia
   pracy przy `BILLING_PROVIDER=stripe` — cały stack nie wstawał. Obie komendy
   wygaszają nawzajem swoje mapowania cen, więc uruchomienie niewłaściwej
   zostawia panel bez ceny do sprzedania. `migrate` wybiera teraz komendę
   pasującą do dostawcy; ceną jest kontakt z API Stripe przy starcie.
3. **Identyfikator klienta z symulatora został podany Stripe'owi.**
   `BillingProfile.external_customer_id` trzymał `sim_customer_…`, Stripe
   odpowiedział `No such customer`, a checkout wracał jako 502. Identyfikator
   klienta nie znaczy nic poza przestrzenią, która go wydała — ta sama ściana
   stoi między trybem testowym a produkcyjnym, gdzie oba wyglądają jak `cus_…`.
   `BillingProfile` ma teraz `external_customer_provider` i
   `external_customer_livemode` (migracja `organizations.0023`), a Billing
   odmawia użycia identyfikatora spoza bieżącej przestrzeni i tworzy nowego
   klienta. Wiersz bez stempla (sprzed tej reguły) jest uznawany za swój —
   odwrotne założenie tworzyłoby drugą tożsamość firmie, która już ją ma.

4. **Każde zdarzenie odbijało się z 400 przez wersję API.** Kod przypinał
   `2026-07-29.dahlia`, a konto ma domyślnie `2026-08-26.dahlia` — i to wersja
   konta decyduje o kształcie zdarzenia, gdy endpoint webhooka nie przypina
   własnej. `stripe listen` zawsze używa domyślnej wersji konta, więc nie da się
   tego obejść po stronie CLI. Przypięcie przesunięte na wersję konta; sprawdzenie
   zgodności zostaje, bo payload w wersji, której nie czytaliśmy, nie powinien
   być parsowany jak nasz. **Konsekwencja dla produkcji: endpoint webhooka trzeba
   utworzyć z jawnym `api_version` równym tej stałej**, inaczej podniesienie
   domyślnej wersji konta przez Stripe wyłączy przyjmowanie zdarzeń — głośno
   (400), ale łatwo to pomylić z błędem podpisu.

Po tych czterech: `POST /api/v1/billing/checkout/` zwraca 201 z adresem
`https://checkout.stripe.com/c/pay/cs_test_…`, a `stripe listen` pokazuje 202
na zdarzeniach z tej sesji.

### Dane do faktury: brakujący ekran, przez który nikt nie mógł kupić

Po przełączeniu na Stripe checkout odmawiał `billing_profile_incomplete`, bo
organizacja nie miała adresu — a **nie było żadnego API ani ekranu, żeby go
podać**. Profil billingowy powstawał wyłącznie w onboardingu z tym, co ten serwis
akurat miał. Bez adresu Stripe Tax nie policzy stawki (ADR-040), więc w trybie
Stripe żadna organizacja nie mogła kupić niczego.

Doszło: `PUT /api/v1/billing/details/` (właściciel, CSRF, audyt
`billing.profile.updated`), `billing_details` w `overview` razem z listą
`missing`, oraz karta „Dane do faktury" w panelu — React Hook Form + Zod,
combobox krajów z nazwami z `Intl.DisplayNames` (ADR-020: zbiór filtrowalny),
PL/EN. Przyciski planów są wyłączone, dopóki dane są niekompletne, z etykietą
„Najpierw uzupełnij dane do faktury" — panel mówi to przed kliknięciem, zamiast
pokazywać 409 po nim.

### Pierwsza prawdziwa płatność i to, co przy niej pękło (2026-09-04)

Właściciel przeszedł Checkout kartą testową na planie `starter`. Stripe zebrał
metodę płatności, `checkout.session.completed` wróciło i zostało przetworzone —
a w panelu nie pojawiło się nic. Trzy powody, jeden pod drugim:

1. **Panel pominął aktywację.** Warunek pokazania karty powrotnej i wywołania
   `trial-activation` brzmiał `!subscription`, a `subscription` jest budowane
   też ze snapshotu — anulowany plan nadal ma payload. Ta sama pomyłka co przy
   przyciskach planów, tylko w drugim miejscu, którego wtedy nie zmieniłem.
   Teraz oba pytają `has_active_subscription`.
2. **Realizacja zamówienia zależała od powrotu przeglądarki.** Plan aktywował
   się wyłącznie przez wywołanie panelu po redirectcie; kto zapłacił i zamknął
   kartę, zostawał z pobraną metodą płatności i bez subskrypcji. Regułę
   „powrót przeglądarki niczego nie dowodzi" mieliśmy już dla pakietów
   kredytów — teraz obowiązuje też plany: `checkout.session.completed` sam
   uruchamia plan, a wywołanie panelu tylko odświeża ekran (stąd 200 zamiast
   201 w teście pomostowym). Odmowa aktywacji nie jest błędem webhooka, ale
   niedostępny dostawca dalej jest — wtedy Stripe dostarczy ponownie.
3. **Organizacja może aktywować plan tylko raz w życiu.**
   `BillingTrialActivation` ma unikat na organizacji i wiąże się 1:1 z jednym
   Checkoutem. Konto właściciela miało aktywację z sierpnia (z symulatora), więc
   nowa sesja i tak by odbiła się o `TrialActivationConflict`. To znaczy, że
   **klient, któremu skończył się plan, nie może kupić ponownie** — a to nie
   jest przypadek brzegowy, tylko normalny cykl życia. Wymaga zmiany modelu
   (aktywacja per Checkout zamiast per organizacja) i ścieżki dostawcy dla
   subskrypcji bez triala, bo trial należy się raz. Pozycja planu, nie łatka.

Lokalnie usunąłem wiersz aktywacji z symulatora i uruchomiłem aktywację dla
prawdziwej sesji: subskrypcja `sub_1UBt5a…` istnieje w Stripe, panel pokazuje
plan Witryna, dostęp pełny, trial do 7 września.

Obserwacja przy okazji: rekonsyliacja dobija się do Stripe po pozostawioną
symulowaną subskrypcję (`sim_subscription_…`) i zapisuje kolejne porażki —
identyfikator subskrypcji też należy do przestrzeni, która go wydała, tak samo
jak identyfikator klienta. Do domknięcia razem z punktem 3.

### Drzwi RLS: pierwsze dwie tabele zamknięte (2026-09-05)

ADR-041 wdrożony w krokach 1 i 2, a z kroku 3 dwie tabele niosące dane osobowe.

**Druga tożsamość bazodanowa** (`saas_core_identity`) powstaje w bootstrapie
razem z rolą aplikacyjną, ma własny sekret i **nie ma BYPASSRLS** — jej zasięg
to wyłącznie polityki, które ją wymieniają. W Django jest to alias
`pre_tenant` wskazujący tę samą bazę; router nie kieruje tam nic samoczynnie i
nie pozwala na migracje, więc trafia tam tylko to, co jawnie napisze `.using()`.

**Pięć miejsc** czyta przez te drzwi, każde z powodem, i pilnuje tego
`tests/test_pre_tenant_door.py`: skanuje źródła i porównuje z zadeklarowaną
listą, więc szóste miejsce psuje test, dopóki ktoś go nie dopisze. To jest cała
wartość tego rozwiązania — bez tego testu drzwi są tylko wygodniejszym
obejściem.

**Migracja `organizations.0025`** zamyka `organizations_billingprofile` i
`organizations_invitation`: polityka po tenancie dla wszystkich plus polityka
przepuszczająca rolę drzwi. Migracja **odmawia startu**, gdy roli nie ma —
wdrożenie bez drzwi to wdrożenie, w którym procesor Stripe nie znajdzie tenanta
i nikt nie przyjmie zaproszenia, więc lepiej zatrzymać się z nazwą brakującej
roli niż dowiedzieć się przy pierwszym webhooku.

Sprawdzone na żywo, czyli tam, gdzie RLS w ogóle działa (testowa baza łączy się
właścicielem i polityki jej nie dotyczą): odczyt profili billingowych **bez
tenanta zwraca 0**, przez drzwi 1, z ustawionym tenantem 1. Po migracji panel
działa w całości — logowanie, lista organizacji, plan, kredyty, skrzynka,
witryny — a webhook Stripe odpowiada 202 na świeżym zdarzeniu.

Zmiany w ścieżkach, które to umożliwiły: middleware szuka członkostwa przez
drzwi w krótkiej transakcji (blokada trwa tyle, co odczyt), `create_organization`
ustawia tenanta **przed** zapisem organizacji — identyfikator istnieje przed
wierszem — a `accept_invitation` ustawia go zaraz po odnalezieniu zaproszenia,
więc wszystko, co potem pisze, idzie już pod polityką.

Zostały cztery tabele: `membership`, `organization`, `role`, `organizationauditentry`.
Każda dotyka ścieżki logowania, więc idą pojedynczo, w osobnym przejściu.

### Drzwi RLS: pozostałe cztery tabele zamknięte (2026-09-05)

Krok 3 ADR-041 domknięty. `organizations.0026` zamyka członkostwo i wpisy
audytowe, `0027` role, `0028` sam rejestr organizacji. Lista długu w
`tests/test_tenant_isolation_regimes.py` jest pusta pierwszy raz od jej
powstania.

Trzy rzeczy wyszły dopiero przy pisaniu ścieżek i są ważniejsze niż same
migracje.

**Renderer publiczny nie dostał drzwi.** Cztery ścieżki publiczne — strona,
sitemap i feed, obrazek, autoryzacja TLS dla Caddy — sprawdzały status
organizacji **złączeniem** `organization__status=ACTIVE`, czyli odczytem
rejestru bez tenanta. Najprostszym rozwiązaniem byłoby puścić je drzwiami i to
byłoby cofnięcie się: renderer jest najbardziej wystawioną powierzchnią
produktu, a drzwi to połączenie czytające ponad politykami — jeden błąd w
rendererze sięgałby wtedy członkostw i zaproszeń każdego tenanta. Zamiast tego
`tenant_is_servable(organization_id)` w `publication_routing.py` ustawia
tenanta, którego **nazwał host**, i czyta status od środka. Zapytań jest dwa
zamiast jednego złączenia; test `test_the_public_renderer_never_reads_through_the_door`
pilnuje, żeby to się nie odwróciło.

**Wpisy audytowe nie dostały drzwi.** ADR-041 zakładał je dla wszystkich sześciu
tabel, ale każda ścieżka, która pisze audyt, ustawia dziś tenanta wcześniej
(tworzenie organizacji, workspace platformy, przyjęcie zaproszenia). Otwarcie
wejścia, którego nikt nie używa, byłoby dziurą bez powodu.

**Role mają politykę asymetryczną.** Odczyt dopuszcza `organization IS NULL`, bo
`owner`, `admin` i reszta szablonów to katalog wspólny dla wszystkich. Zapis już
nie: żaden tenant nie dopisze sobie roli globalnej. Katalog zakłada migracja,
która biegnie właścicielem tabeli i politykom nie podlega.

Ścieżki przepisane bez drzwi, bo tenant był znany wcześniej, niż go ustawiano:
middleware kluczy API (czytał organizację **przed** `SET LOCAL` — po zamknięciu
rejestru każde żądanie SCR dostawałoby 403), kontekst zadania Celery, obie
komendy grantów i provisioning workspace'u platformy. Drzwi przybyły tam, gdzie
pytanie naprawdę dotyczy całego rejestru: wybór jedynej organizacji przy
logowaniu, workspace platformy, purge kont testowych, fixture E2E. Razem 16
użyć w ośmiu modułach, każde z powodem na liście.

Sprawdzone na żywo, na bazie, w której rola aplikacyjna podlega politykom:
`bez tenanta 0 organizacji i 0 członkostw / przez drzwi 3 i 4 / z tenantem 1 i
1`, a role globalne widoczne zawsze (5). Pełne przejście przez HTTP: rejestracja
→ potwierdzenie maila → logowanie → założenie firmy (201) → lista, bieżąca
firma, członkowie, zaproszenia, plan, kredyty, skrzynka → wysłanie zaproszenia
→ rejestracja drugiego konta → **przyjęcie zaproszenia (200)** → drugie konto
widzi dokładnie jedną firmę. Strona publiczna `/start` i `/oferta` 200,
sitemap 200, obrazek publiczny 200, przemiatania w tle bez błędów.

### Profil składa produkt, a nie tylko go opisuje (2026-09-05)

`deployment.json` był dotąd walidowany i ignorowany: każdy obraz instalował
wszystkie moduły, a profil decydował o kilku flagach. „Dwa produkty z jednego
repozytorium" było więc prawdą na papierze i nieprawdą przy starcie — `core-only`
wiózł tabele Billingu, adresy Sites i zadania cykliczne Bookingu.

Nowy `config/composition.py` czyta katalog modułów z dysku i buduje
`ACTIVE_MODULES` — te same reguły, które sprawdza `deployment-check.mjs` w CI,
tyle że w miejscu, gdzie coś rozstrzygają. Z tej krotki biorą się cztery rzeczy:
`INSTALLED_APPS`, middleware należące do modułu (dziś klucze API z
Notifications), routing (`urlpatterns_for`) i `CELERY_BEAT_SCHEDULE`. Każdy mount
routingu powstaje **wewnątrz funkcji**, żeby widoki wyłączonego modułu nigdy się
nie importowały — import by przeszedł, a wywalił się dopiero na modelu bez
zarejestrowanej aplikacji.

Zależności **nie** domykają się same. Profil, który bierze Billing bez
`core.organizations`, jest odrzucany, a nie po cichu uzupełniany: lista modułów
jest decyzją, którą ktoś podejmuje, a kompozycja rosnąca sama to kompozycja,
której nikt nie przejrzał.

Dwa produkty, zmierzone:

| profil      | aplikacje | ścieżki | zadania cykliczne |
| ----------- | --------: | ------: | ----------------: |
| `core-only` |         3 |       9 |                 0 |
| `business`  |         8 |      21 |                12 |

Obraz `core-only` **zbudowany i uruchomiony**, nie tylko policzony w teście.
Przy okazji wyszło, że deployment bez Billingu żądał kompletu sekretów Stripe —
teraz warunek pyta najpierw, czy Billing w ogóle jest w kompozycji.

Dwie rzeczy do zapamiętania. **Testy jadą na profilu `business`**, ustawionym w
`settings/test.py` przed importem `base` (profil czyta się przy imporcie, więc
`conftest.py` jest za późno — pytest-django konfiguruje Django wcześniej). Do tej
pory suite biegł nominalnie jako `core-only`, testując Billing, Sites i Booking.
**Schemat OpenAPI jest per produkt**: nazwa ciasteczka sesji zawiera nazwę
deploymentu, więc `pnpm api:schema` generuje teraz tym samym profilem, którym
sprawdza dryf — opublikowany kontrakt mówi `saas_core_business_session`, czyli
to, czego naprawdę używa działający deployment.

Zostaje w P1: artefakt modułów z hashem profilu, którym backend, frontend,
worker i scheduler odmawiają startu przy niezgodnym obrazie; macierz
`deployment → wersja/digest → migracje → rollback`; udokumentowanie osobnej bazy,
storage i sekretów per deployment. Frontend filtruje menu i kafle po
`deployment.modules` od dawna, ale obraz frontendu dla `core-only` nie był
jeszcze zbudowany ani przedymiony.

### Odcisk palca kompozycji (2026-09-05)

Backend, worker, scheduler i frontend to osobne obrazy budowane z osobnych
drzew. Nic nie stało na przeszkodzie, żeby frontend zbudowany z jednego spotkał
backend zbudowany z drugiego — i nic by nie wybuchło: panel pokazałby menu
modułu, którego adresy odpowiadają 404, co czyta się jak zepsuta funkcja, a nie
jak pomylony deploy.

`pnpm deployment:artifact` zapisuje `deployments/<profil>/module-artifact.json`:
profil, jego moduły w kolejności kompozycji wraz z deskryptorami i jeden
`sha256` nad całością. Artefakt jest **commitowany**, bo zmiana kontraktu
dowolnego modułu ma być widoczna jako diff w każdym profilu, który go używa —
czego nie daje hash liczony przy budowaniu i wyrzucany. `deployment:artifact:check`
wchodzi w `pnpm lint` obok walidacji profili.

Hash liczy **jeden** generator, po stronie JS. Python go **nie przelicza** —
dwie kanonizacje JSON-a w dwóch językach musiałyby zgadzać się w nieskończoność.
Backend sprawdza to, za co ten hash stoi: czy artefakt w obrazie opisuje tę samą
kompozycję, którą proces złożył z profilu i katalogu (ten sam deployment, te
same moduły, te same aplikacje Django). Jeśli nie — `ImproperlyConfigured` przy
starcie, z nazwą różnicy.

Frontend niesie ten sam hash w `generated/deployment.ts`, a `/healthz`
porównuje go z `/api/v1/health/`. Rozróżnienie, które warto zapamiętać:
**trwała niezgodność** to błąd budowania, więc jest zapamiętywana i kontener
zostaje niezdrowy; **brak odpowiedzi** backendu nie mówi nic o tym obrazie, więc
nie przewraca liveness — jedna awaria nie ma robić dwóch.

Dowód na żywo: obraz `business` uruchomiony z podmontowanym artefaktem
`core-only` odmawia startu („Artefakt opisuje deployment 'core-only', a proces
startuje jako 'business'"), a z artefaktem starszego drzewa wypisuje, którego
modułu brakuje.

### Macierz release'ów i rozdzielenie deploymentów (2026-09-05)

Trzy rzeczy, które razem domykają P1 poza jedną bramką.

**Obraz należy do produktu, nie do commita.** CI budowało backend **bez**
argumentu `DEPLOYMENT`, czyli jako `core-only`, i publikowało go obok frontendu
zbudowanego jako `business`. Nikt tego nie zgłaszał, bo backend i tak instalował
wszystkie moduły — po zmianie kompozycji taka para w ogóle by nie wstała. Teraz
matryca buduje po jednym obrazie na profil, z tagiem `sha-<commit>-<profil>`;
Caddy i Redis zostają bez profilu.

**Rollback jest faktem, nie nadzieją.** `manage.py deployment_release` wypisuje
wiersz macierzy: profil, hash, wersja, digesty (podaje je wdrażający — proces
nie zna własnego), migracje w obrazie i w bazie, lista nieodwracalnych. Dziś ta
lista jest pusta: **wszystkie 90 migracji jest odwracalnych**, a
`tests/test_deployment_release.py` pilnuje, żeby pierwsza nieodwracalna wymagała
wpisu z powodem — bo odbiera rollback każdemu deploymentowi za sobą, i to po
cichu, dopóki ktoś nie spróbuje.

**Rozdzielenie jest opisane i sprawdzane.** `docs/operations/deployment-matrix.md`
§4 wymienia 16 zasobów wraz ze zmienną, którą się je rozdziela, a
`tests/test_deployment_isolation.py` porównuje tę tabelę z `compose.yaml` w obie
strony. Granicą jest projekt Compose — osobne kontenery, sieć i wolumeny, czyli
osobny PostgreSQL, Redis i storage; zmienne są potrzebne dopiero wtedy, gdy dwa
deploymenty dzielą infrastrukturę.

Dowody: cztery obrazy zbudowane lokalnie. Frontend `core-only` odpowiada
`{"status":"ok","deployment":"core-only"}`, a podpięty pod backend `business`
zwraca **503 `profile_mismatch`** z obydwoma hashami — dwa prawdziwe kontenery,
nie mock. Różnicę w menu pilnuje `app-sidebar.test.tsx`: przy `core-only` nie ma
pozycji Kalendarz, Strona, Wiadomości ani Plan i płatności.

Otwarte w P1 zostaje jedno: **dwa środowiska testowe na osobnych danych i
sekretach**. Wiadomo, jak to zrobić (§4 dokumentu), ale nikt nie postawił drugiego
stacku, więc bramka zostaje niezaznaczona. Backup i `deploy staging` też są
opisane dla jednego stacku — to jest zapisane w §5 dokumentu, nie przemilczane.

### Katalog skills: mechanizm i pięć pierwszych instrukcji (2026-09-06)

P2 ruszyło od strony, która daje się sprawdzić maszynowo. Kanoniczne skills żyją
w `.agents/skills/<nazwa>/SKILL.md`; w `.claude/skills/` stoją **cienkie
adaptery** (limit 1200 bajtów) powtarzające `name` i `description` co do znaku i
wskazujące plik kanoniczny. Powód jest praktyczny: klient routuje po
`description` adaptera, więc kopia treści rozjeżdża się po cichu, a sam link bez
frontmatteru wyłącza routing — skill istnieje i nigdy nie zostaje wybrany.
Mirrory memexa są wyjątkiem i walidator porównuje je bajt po bajcie.

`pnpm ai:validate` (w `pnpm lint`, czyli i w CI) sprawdza frontmatter, `name`
równy katalogowi, unikalność nazw i opisów, rozmiary, **istnienie każdej ścieżki
repozytorium i każdej komendy `pnpm` wymienionej w treści**, zgodność adaptera z
kanonicznym, adaptery osierocone, ślady sekretów oraz to, że każdy skill ma
wiersz w mapie ścieżek w `AGENTS.md`. Sprawdzone negatywnie — zły link,
zduplikowany `description`, sekret w treści i rozjechany adapter dają exit 1, a
po przywróceniu exit 0.

Napisane pięć: `change-tenant-data`, `develop-saas-core-module`,
`prepare-product-deployment`, `change-api-and-events` i meta-skill
`maintain-saas-core-skills`. Wszystkie niosą kolejność pracy, komendy i pułapki,
które już kosztowały dzień — nie streszczenie ADR-u, bo ADR jest obok.

**Zostają trzy**: `develop-sites`, `develop-booking`, `verify-saas-core-release`.
Świadomie nienapisane w tym przejściu: ich źródła wymagają uważnej lektury, a
skill napisany z pobieżnej byłby wykonywany z przekonaniem. Do tego czasu w tych
obszarach obowiązują ADR-y i `docs/architecture/`.

`AGENTS.md` dostał przy okazji porządki: wskazuje plan 13 jako nadrzędny (baza
P0-P3 przed falami produktowymi), niesie mapę ścieżek do skills i pięć nowych
niezmiennych zasad wyciągniętych z ostatnich trzech sesji — w tym tę
najważniejszą, że **baza testowa omija RLS**, więc zielony test nie dowodzi
izolacji. Plik trafił do `.prettierignore`, bo blok `memex:*` pisze narzędzie i
formatter przepisywałby te same linie w kółko; dzięki temu `pnpm format:check`
jest po raz pierwszy czysty.

### Pierwszy katalog skills kompletny (2026-09-06)

Doszły trzy brakujące instrukcje, więc katalog P2 ma komplet ośmiu:
`develop-sites`, `develop-booking` i `verify-saas-core-release` obok pięciu
z poprzedniego przejścia. `pnpm ai:validate`: 11 kanonicznych (osiem naszych i
trzy memexa), 10 adapterów.

Każdy z trzech nowych stoi na przeczytanym źródle, nie na streszczeniu:

- **`develop-sites`** niesie cztery kształty, z których wynika reszta modułu:
  wersje są append-only (dlatego kontrakt adresuje bloki **pozycyjnie** wobec
  `base.version`, a nie po id), publikacja jest snapshotem (edycja jest widoczna
  po następnej publikacji), wpisy publikują się samodzielnie, a host jest
  deklaracją tenanta. Do tego sześć operacji zarezerwowanych dla człowieka i
  różnica między `person_required` a `page_automation_forbidden`, którą
  connector traktuje inaczej;
- **`develop-booking`** rozdziela to, co w tym module myli się najczęściej:
  instants w UTC, reguły tygodniowe w czasie lokalnym organizacji, DST jako
  zwykła niedziela (czas nieistniejący pomijany, dwuznaczny dający dwa
  instants), a rozstrzygnięcie wyścigu należy do `EXCLUDE USING gist`, nie do
  Pythona. Plus zasada, że klient końcowy nie jest membershipem i nigdy nim nie
  będzie, a self-service to token przypięty do jednej wizyty;
- **`verify-saas-core-release`** to lista bramek w kolejności, która najszybciej
  pada, i — ważniejsze — lista **pięciu pytań, na które zielony suite nie
  odpowiada**: izolacja tenantów, cokolwiek za Caddy, czy kompozycja jest realna,
  czy kontrakt czytany z dysku jest w obrazie, czy front i backend to ten sam
  produkt.

Bramka P2 w większości zamknięta. Zostają dwie rzeczy i obie są nazwane wprost:
evale (§6.4) oraz „przekroczenie uprawnień" jako trzeci przypadek negatywny —
tego nie da się złapać regexem, potrzebny jest scenariusz. Zły link, zduplikowany
`description`, sekret w treści i rozjechany adapter są sprawdzone i dają exit 1.

### Evale routingu i trzeci przypadek negatywny (2026-09-06)

Katalog skills dostał drugą bramkę. `pnpm ai:validate` pyta, czy skill jest
**dobrze zbudowany**; nowy `pnpm ai:eval` pyta o to, co ważniejsze później: czy
katalog **routuje** i czy **pokrywa** produkt.

**Routing.** Dziewięć scenariuszy w `.agents/evals/routing.json` — nowy endpoint,
migracja tenantowa, zmiana Booking, publikacja strony, webhook płatnościowy,
nowy moduł, nowy deployment, odbiór release'u i naprawa nieaktualnej instrukcji.
Każdy niesie terminy, a bramka sprawdza, czy oczekiwany skill **wygrywa nimi z
każdym innym**. Uczciwie o zakresie: to nie dowodzi, że model wybierze właściwy
skill — tego nie da się sprawdzić deterministycznie. Dowodzi, że **opisy
rozróżniają**, czyli tej połowy, którą kontrolujemy i która się psuje: nowy skill
z opisem zachodzącym na istniejący zamienia routing w rzut monetą, i to po cichu.

**Pokrycie.** Sekcja `coverage` przypisuje skill każdemu z ośmiu modułów katalogu
**wraz z powodem**. Trzy korzystają świadomie ze skill ogólnego i mówią dlaczego:
`shared.billing` i `shared.notifications` (kontrakt API i zdarzenia) oraz
`core.identity` — dedykowany skill tożsamości powstanie w P3 razem z profilami i
kontem klienta. Moduł bez wpisu albo z powodem krótszym niż zdanie psuje bramkę.

**Trzeci przypadek negatywny** wreszcie ma sprawdzalną formę. „Przekroczenia
uprawnień" nie da się złapać regexem w ogólności, ale da się złapać to, co
najgroźniejsze: **polecenie nieodwracalne podane do wykonania**. Walidator
przeszukuje wyłącznie bloki kodu pod kątem `git push`, `--force`, `--apply`,
`rm -rf`, `DROP`/`TRUNCATE`. Rozróżnienie jest celowe i działa:
`verify-saas-core-release` pisze w prozie, że `git push` idzie tylko na prośbę
właściciela — to zdanie jest przeciwieństwem autoryzacji i przechodzi; to samo
polecenie wstawione do bloku daje exit 1.

Bramka P2 zamknięta poza dwiema rzeczami, obiema nazwanymi: cykliczny przegląd
katalogu (dziś reagujemy na zmianę, nie mamy harmonogramu) i metryki procesu
poza samym doborem skill — nie ma ich gdzie zbierać, dopóki nad repozytorium nie
pracuje więcej niż jedna sesja naraz.

### P3 ruszyło: moduł `shared.profiles` (2026-09-06)

Pierwsza pozycja P3 zamknięta. `User` zostaje kontem uwierzytelniającym, a
wszystko, co ma zobaczyć odwiedzający, mieszka teraz w osobnym module — dziewiąty
moduł katalogu, pierwszy dodany od czasu, gdy profil naprawdę składa produkt.

**Dlaczego osobny moduł, a nie pole w `Organization`.** Booking musi wskazać
profil specjalisty, a Booking nie ma prawa zależeć od Sites; Core z kolei nie
może wskazać `MediaAsset`, bo to Shared. Zostaje moduł Shared zależny od
`core.organizations` i `shared.media` — dokładnie to, co ADR-036 §3 przewidział,
i to samo, co potwierdził import-linter (1 kept, 0 broken).

**Kształt danych.** Profil trzyma nazwę, nagłówek, opis, zdjęcie z biblioteki
mediów, **jawne pola kontaktu** (telefon, e-mail publiczny, adres — nie blob, bo
renderer i eksport muszą wiedzieć, co jest czym), linki, języki i specjalizacje.
Tłumaczenia to osobne wiersze per locale z flagami fallbacku, czyli ten sam
mechanizm co przy stronach. Organizacja ma **dokładnie jeden** profil, wymuszony
indeksem częściowym; osób może mieć dowolnie wiele, a **profil osoby nie wymaga
konta** — wskazanie członkostwa jest opcjonalne, bo specjalista przyjmujący raz w
tygodniu też ma być na stronie.

Opis i nagłówek odrzucają znaki `<`. To pole idzie na stronę publiczną, więc pole
przyjmujące HTML jest przechowywanym XSS-em, a nie wygodą.

**Dwie warstwy izolacji.** Migracja `profiles.0002` wymusza RLS na obu tabelach i
zakłada wyzwalacz relacji: zdjęcie, członkostwo i profil nadrzędny muszą należeć
do tej samej organizacji co wiersz, który je wskazuje. Serwis sprawdza to dla
dobrego komunikatu; baza — żeby to była prawda.

Sprawdzone na żywo, bo zielony suite tego nie dowodzi: obie tabele mają
`ENABLE`+`FORCE` i po jednej polityce oraz wyzwalaczu, odczyt **bez tenanta
zwraca 0**, z tenantem 1, a próba wstawienia obcego pliku kończy się
`profile relation belongs to another organization`.

**Bramka kompozycji zadziałała po drodze dwa razy** i warto to zapamiętać:
`makemigrations` odmówił startu, dopóki nie przegenerowałem artefaktu modułów
(profil wymieniał `shared.profiles`, artefakt jeszcze nie), a `pnpm ai:eval`
odmówił, dopóki nowy moduł nie dostał wpisu w sekcji pokrycia. Obie odmowy są
tym, po co te bramki powstały.

Zostaje w P3: powiązanie profilu z Site (blok `core.profile`, zrzut w snapshocie,
`StaffMember.profile` — dokłada zależność Booking → Profiles), konto klienta
(`Customer.user`, principal `customer`, panel „moje wizyty"), role
`specialist`/`reception`, `PolicyAcknowledgement` i **decyzja o usuwaniu
tenanta**, która wymaga ADR-u i Twojego zdania.

### Usunięcie tenanta jest usunięciem (ADR-042, 2026-09-06)

Twoja decyzja, zapisana jako ADR: **usuwamy dane, nie anonimizujemy**. Powód
jest jednocześnie prawny i praktyczny — w rezerwacjach, powiadomieniach i
zrzutach publikacji leżą dane osobowe **klientów naszych klientów**, a o
anonimizacji tekstu swobodnego i JSON-a nie da się udowodnić, że nikogo już nie
identyfikuje. Usunięcie wiersza udowadnia się policzeniem wierszy.

Stan przed: dziesięć wyzwalaczy odmawiało `DELETE` bezwarunkowo, osiem na
tabelach tenantowych. Organizacja, która kiedykolwiek załączyła plik albo
zapisała wpis audytowy — czyli każda prawdziwa — **była nieusuwalna**.
Inwentaryzacja na żywo: 77 tabel z `organization_id`, dane osobowe w co najmniej
dwudziestu, w tym w `snapshot`, `payload` i `metadata`.

**Furtka jest jedna i nazwana.** Wyzwalacze przepuszczają `DELETE` wierszy
organizacji wskazanej w `app.erasing_organization_id`. To **identyfikator, nie
flaga** — flaga włączona przez pomyłkę otwierałaby historię wszystkich tenantów
naraz, identyfikator otwiera dokładnie tę firmę, którą ktoś nazwał. Ustawia go
jedno miejsce w kodzie, a liczy je test, tak samo jak drzwi z ADR-041. Piszę
wprost, czego to nie daje: kto ma poświadczenia bazy aplikacyjnej, ustawi tę
zmienną sam — żadna warstwa w bazie tego nie zmieni. To broni przed błędem w
kodzie i czyni zamiar widocznym.

**Kolejność jest rozstrzygnięciem.** PostgreSQL nie cofnie usunięcia z object
storage, więc: wiersze w transakcji → commit → dopiero potem pliki, a klucze
czekających obiektów siedzą w **pokwitowaniu**, które przemiatanie mediów opróżnia
co pięć minut. Odwrotna kolejność kasowałaby pliki także wtedy, gdy transakcja
padnie.

**Pokwitowanie** zostaje poza usuniętym tenantem: identyfikator organizacji, kto
zlecił, powód, liczby wierszy per tabela, klucze obiektów. **Nic z treści** — ani
nazwy, ani adresu, ani e-maila. Dowód, że usunięcie się odbyło, nie kopia tego,
co usunięto.

Komenda operatorska wymaga `is_staff` z MFA, powodu dłuższego niż słowo,
przepisanego sluga i `--apply`; domyślnie tylko wypisuje plan.
`purge_test_tenants` przestał być osobną implementacją i jest nakładką na ten sam
serwis — więc konta testowe też dają się wreszcie usunąć.

Sprawdzone na uruchomionym stacku: bez furtki audyt nadal odmawia
(„organization audit entries are append-only"), po usunięciu **0 wierszy, 0
organizacji**, rejestr jej nie zna (sprawdzone przez drzwi, więc to nie artefakt
RLS), pokwitowanie jest. Jeden test zmienił wymowę na przeciwną i tak miało być:
`test_a_tenant_with_media_cannot_be_purged_and_says_so` opisywał defekt jako
regułę.

**Jedna rzecz do zapamiętania na przyszłość**: nie przechowujemy dokumentów
księgowych — `BillingInvoiceDocument` jest rekordem zadania, faktury żyją w
Stripe i u wystawcy. Dlatego nasze usunięcie może być kompletne. Gdybyśmy
kiedykolwiek zaczęli trzymać dokument księgowy u siebie, ADR-042 wymaga rewizji,
bo zniszczenie dokumentacji księgowej jest osobnym naruszeniem.

### Kredyty w panelu (2026-09-05)

Domena kredytów była kompletna od kilku dni i całkowicie niewidoczna: księga,
dwie pule, rezerwacje, checkout pakietu — i żaden sposób, żeby klient dowiedział
się, ile ich ma. Doszedł ekran **Kredyty** w panelu wraz z API.

Decyzje właściciela, które ukształtowały zakres:

- **saldo widzi każdy członek, kupuje tylko właściciel.** Kredyty zużywa osoba,
  która wykonuje pracę, i to ona musi wiedzieć, kiedy skończą się w połowie
  operacji; płatność zostaje przy właścicielu jak przy planach. Odczyt wymaga
  więc tylko `organization.read`, a zakup nadal `organization.billing.manage`
  i roli właściciela;
- **historia zakupów tak, historia zużycia nie** — dopóki nic kredytów nie
  pochłania, lista zużycia byłaby pusta. Wróci razem z operacjami AI (W9.5.7).

Dwie rzeczy wyszły przy okazji. Kredyty są **dodatkiem do aktywnego planu**
(`start_credit_purchase` odmawia bez pełnego dostępu), więc overview zwraca
`plan_required` i panel tłumaczy powód zamiast oferować przycisk kończący się
403. A adres powrotu z Checkoutu pakietu wskazywał na `/settings/credits`, czyli
stronę, której nigdy nie było — poprawione na `/panel/settings/credits`.

Sprawdzone na żywo: organizacja właściciela ma 200 kredytów z planu Witryna,
odnawiają się 1 października, trzy pakiety (49/199/699 zł netto) są kupowalne
przez prawdziwego Stripe'a.

### Powiadomienia: e-mail i skrzynka w aplikacji (2026-09-05)

Mapa cyklu życia wskazała, że ostrzeżenie o końcu triala powstaje w bazie i nie
dociera do nikogo. `BillingNotice` miał od początku kolumnę `delivered_at`,
której nic nie ustawiało — czyli dostarczenie było przewidziane i nigdy nie
powstało.

E-mail nie wymagał budowania: `shared.notifications` ma szablony z wersjami i
lokalizacją, kolejkę, ponowienia, wygaszanie adresów i idempotencję. Doszły dwa
szablony (`billing.trial_ending`, `billing.grace_ending`) i wiązanie.

**Kierunek zależności wymusił kształt.** `shared.notifications` już zależy od
`shared.billing`, więc billing nie może zawołać notifications — powstałby cykl,
który `deployment-check` odrzuca. Dostarczanie jest więc **ciągnięciem**:
`notifications/billing_notices.py` co minutę zabiera nierozesłane notice i
zamienia każdy na wiadomość w produkcie oraz e-mail, po czym stempluje
`delivered_at`.

**Skrzynka w aplikacji powstała od zera.** Nowy model `AppNotification`
(RLS wymuszone, migracja `notifications.0005`), `GET /api/v1/notifications/inbox/`
i `POST .../inbox/read/`, a w panelu dzwonek z licznikiem nieprzeczytanych w
nagłówku — otwiera listę, pozwala oznaczyć wszystko jako przeczytane, odświeża
się co dwie minuty.

Dwie decyzje warte zapamiętania. Odbiorcą jest **osoba z uprawnieniem do
zarządzania płatnościami**, a nie adres z faktury — tam siedzi księgowość, która
planu nie zmieni. I treść **nie jest zapisywana w bazie**: wiersz niesie `kind`
oraz fakty, a zdanie składa panel w języku czytelnika, więc jedna wiadomość jest
polska dla jednej osoby i angielska dla drugiej, a poprawka tłumaczenia nie
wymaga migracji danych.

### Mapa cyklu życia płatności (2026-09-05)

Usterki z 3–4 września siedziały wszystkie na **szwach między kawałkami**, z
których każdy miał własne zielone testy. Odpowiedzią jest
[docs/architecture/billing-lifecycle.md](../architecture/billing-lifecycle.md):
lista wszystkich stanów i przejść, a przy każdym przejściu co je wyzwala, kto je
wykonuje, co widzi klient i **czy ktokolwiek to udowodnił**. Status ⚠️ wolno
podnieść wyłącznie razem z testem; nowe przejście dopisuje się w tym samym
commicie, w którym powstaje kod.

Mapa od razu wskazała dwie dziury, obie zamknięte tego samego dnia:

- **zmiana planu nie miała ani jednego testu**, mimo że to najczęstsza operacja
  płacącego klienta. Doszły dwa: procesor przenosi plan i limity po zdarzeniu z
  inną ceną, a panel z aktywną subskrypcją kieruje do portalu zamiast próbować
  drugiego zakupu;
- **koniec triala był nieprzetestowany i niewidoczny lokalnie**.
  `tests/test_billing_lifecycle_walk.py` przechodzi teraz całą drogę w
  kolejności: wybór planu → opłacony Checkout → trial → pierwsza płatność →
  nieudana płatność → karencja → tylko odczyt → ponowna płatność → zmiana planu
  → anulowanie → koniec okresu → powrót bez drugiego triala, sprawdzając po
  każdym kroku stan, tryb dostępu i limity planu.

Doszedł też **zegar symulatora** (`simulated_clock.py`, zadanie beat co 5 minut):
w trybie Stripe czasu pilnuje rekonsyliacja, w symulowanym nie pilnował nikt i
lokalny trial trwał w nieskończoność. Każda z tych dwóch funkcji milczy w trybie
tej drugiej.

Co mapa zostawia otwarte: ostrzeżenie o końcu triala powstaje w bazie i **nikt
go nie dostaje** (ani e-mail, ani panel), 3DS przy zakupie bez triala nie jest
obsługiwane, kredyty nie mają interfejsu, a `SubscriptionState.SUSPENDED` jest
martwą wartością w enumie.

### Cykl życia planu: ponowny zakup (2026-09-04)

Do tej pory organizacja mogła aktywować plan **dokładnie raz w życiu**, bo
`BillingTrialActivation` miała unikat na organizacji i wiązała się 1:1 z jednym
Checkoutem. Klient po anulowaniu albo po wygasłym trialu przechodził Checkout,
zostawiał kartę i dostawał `TrialActivationConflict`. To nie jest przypadek
brzegowy, tylko zwykły cykl życia, więc zostało domknięte:

- aktywacja należy do Checkoutu, który za nią zapłacił (`billing.0020` zdejmuje
  unikat na organizacji). Niezmiennik „jedna żywa subskrypcja na organizację"
  nie zniknął — jest egzekwowany tam, gdzie powstają subskrypcje;
- **darmowy okres przysługuje raz**. Jeżeli organizacja miała już jakąkolwiek
  subskrypcję, druga startuje z `trial_days=0`, czyli od razu płatna: Stripe
  obciąża kartę zebraną w sesji setup i zwraca subskrypcję `active`, a nie
  `trialing`. `create_trial_subscription` nazywa się teraz `create_subscription`,
  bo trial przestał być jedyną możliwością;
- oba strażniki — „jedna żywa subskrypcja" i „nie ma innej aktywacji w toku" —
  siedzą pod tą samą blokadą `BillingProfile`. Wcześniej pierwszy z nich stał za
  blokadą, a wołanie dostawcy dzieje się poza transakcją: dwa równoległe powroty
  z Checkoutu poprosiłyby Stripe o dwie subskrypcje dla tej samej firmy;
- `StripePriceMapping` niesie `provider` (`billing.0021`, wiersze symulatora
  rozpoznane po prefiksie `sim_price_`). Rekonsyliacja pomija subskrypcje z
  cudzej przestrzeni — wcześniej co pięć minut pytała Stripe o
  `sim_subscription_…` i zapisywała kolejną porażkę — a checkout wybiera cenę
  tylko z katalogu aktywnego dostawcy.

Czego świadomie nie ma: zakup bez triala może wrócić ze Stripe jako
`incomplete`, jeśli karta zażąda uwierzytelnienia (3DS). Adapter odmawia wtedy
z jawnym komunikatem — ścieżki dokończenia płatności przez klienta jeszcze nie
mamy i jest to osobna pozycja planu.

### Konta lokalne, panel admina i sprzatanie po testach

Django admin jest pod `http://localhost:8080/internal/admin/` — Caddy przepuszcza
`/internal/*` do backendu (blokuje tylko `/internal/metrics/` i
`/internal/caddy/*`), a `collectstatic` biegnie w obrazie, więc arkusze się
wczytują. Zarejestrowane są dokładnie dwa modele: `identity.User` (pełna
edycja) i `sites.Domain` (tylko odczyt). Sprawdzone 2026-09-03 przez HTTP:
logowanie, lista kont i lista domen odpowiadają 200 i pokazują wiersze.

Do panelu potrzebne jest konto `is_staff`. Nie nadawaj go koncie panelowemu
właściciela: `sessions.py` wymaga od konta operatorskiego MFA i przy logowaniu
do panelu rzuci `MfaSetupRequired`. Operator jest osobnym kontem:
`manage.py createsuperuser --noinput --email operator@saas-core.localhost`
z hasłem w `DJANGO_SUPERUSER_PASSWORD`. Hasła nie zapisujemy w repozytorium.

Panel admina nie usunie konta, które ma członkostwo albo wpisy audytowe —
`on_delete=PROTECT` sprawi, że Django pokaże listę blokujących wierszy. Do tego
jest komenda `purge_test_tenants`:

- `--email` (można wielokrotnie) albo `--all` dla wszystkich kont na
  zastrzeżonych domenach testowych (`example.com/net/org`, `.test`, `.invalid`,
  `.example`);
- domyślnie wypisuje plan (ile wierszy w jakich modelach); usuwa dopiero z
  `--apply`;
- odmawia dla adresu poza zastrzeżoną domeną i pomija organizację, w której
  jest choć jeden prawdziwy członek — konto właściciela nie może zniknąć jako
  skutek uboczny sprzątania po teście;
- nie ma listy modułów: idzie za odmowami `ProtectedError`, które zgłasza
  Django, więc nowa tabela w dowolnym module jest objęta bez zmian w komendzie,
  a Core nie zaczyna wiedzieć o Shared.

Inwentaryzacja 2026-09-03 i sprzątanie: baza deweloperska miała 15 kont — 10 resztek
`identity-smoke-*` po smoke testach identity, cztery fixture'y
(`w6-e2e-manual-w9`, `w6-e2e-maciek`, `blog-smoke`, `w6-e2e-podglad`) i jedno
prawdziwe konto właściciela. Konto właściciela jest właścicielem organizacji
`airedale-terrier` („Test") z pełnym stanem: witryna ze stroną, domena,
subskrypcja z trialem, snapshot entitlementów, saldo kredytów — czyli można się
nim logować i widzieć produkt bez fixture'ów.

### Koniec triala nie wypuszczał nikogo z powrotem (2026-09-03)

Właściciel zgłosił, że jego konto ma trial do 24 sierpnia i nie da się nic
zrobić — nawet wybrać planu. Diagnoza pokazała dwie różne rzeczy.

**Pierwsza, naprawiona: panel mylił „jest co pokazać" z „ma aktywny plan".**
`customer_billing_overview` buduje `subscription` z subskrypcji, a gdy tej nie
ma — ze snapshotu entitlementów, żeby po zakończeniu było widać, jaki plan był i
że się skończył. Panel czytał samą obecność tego obiektu jako „już subskrybuje" i
w trybie symulowanym wyłączał wszystkie trzy przyciski planów. Backend był przy
tym łagodniejszy niż interfejs: `create_setup_checkout` odrzuca tylko
subskrypcję inną niż `canceled`, więc API przyjęłoby wybór planu, którego panel
nie pozwalał kliknąć. Overview ma teraz `has_active_subscription` liczone
dokładnie tym samym warunkiem, którego używa `create_setup_checkout`, a panel
opiera się na nim w trzech miejscach: blokadzie wyboru planu, kierowaniu do
portalu Stripe i stanie przycisków. Testy: `test_billing_simulator.py`
(anulowana subskrypcja nie blokuje nowego checkoutu) i test panelu
(po zakończonym trialu przyciski są aktywne).

**Druga, nienaprawiona: nic nie kończy triala.** `sync_subscription_lifecycle`
planuje wyłącznie `TRIAL_ENDING_NOTICE` — ostrzeżenie *przed* końcem. Samo
przejście stanu po `trial_end` ma przyjść od dostawcy, czyli webhookiem Stripe.
Symulator nigdy takiego zdarzenia nie tworzy, więc lokalnie subskrypcja zostaje
w `trialing` na zawsze, z pełnym dostępem i bez ścieżki zakupu. W trybie Stripe
transformacja przyjdzie, ale nie mamy własnej siatki bezpieczeństwa na wypadek
niedostarczonego webhooka. Do rozstrzygnięcia razem z W9.5.2S: dodać akcję
lifecycle „trial wygasł" działającą bez dostawcy, czy uznać rekonsyliację za
wystarczającą.

Lokalnie subskrypcja właściciela została zamknięta ręcznie (`canceled`,
`ended_at` = koniec triala), żeby dało się znowu wybierać plany.

### Czego nie da się usunąć

Sprzątanie tenantów testowych zatrzymało się na wyzwalaczach bazy: `DELETE` na
`media_mediareference` i na `organizations_organizationauditentry` jest odrzucany
bezwarunkowo. To znaczy, że **nie ma dziś sposobu usunięcia tenanta** — każda
organizacja, która załączyła plik albo zapisała wpis audytowy, jest trwała.
Komenda `purge_test_tenants` raportuje taką odmowę i przechodzi do następnej
organizacji zamiast przerywać przebieg; test `test_purge_test_tenants.py`
przypina to zachowanie. Decyzja (anonimizacja czy furtka operatorska w
wyzwalaczu) jest pozycją P3 planu 13 i wymaga ADR-u.

W bazie deweloperskiej zostały z tego powodu dwie organizacje testowe
(`w6-e2e-manual-w9`, `w6-e2e-maciek`) i trzy powiązane konta.

Uruchomienie komendy katalogu poza kontenerem wymaga kompletu zmiennych:
`DJANGO_SETTINGS_MODULE=saas_core.config.settings.local`, `APP_ENV=local`,
`DEPLOYMENT=business`, `BILLING_PROVIDER=stripe`, `STRIPE_LIVEMODE=false`,
`STRIPE_SECRET_KEY_FILE`, `STRIPE_WEBHOOK_SECRET_FILE`,
`STRIPE_PORTAL_CONFIGURATION_ID`, `DJANGO_SECRET_KEY_FILE` oraz `POSTGRES_*`
(lokalna baza to `saas_core_w3`, użytkownik migracyjny `saas_core`).

## Stan produktu

- W9.5.1 dostarczyło customer-facing shell panelu, nawigację mobilną, switcher
  organizacji, status planu i checklistę Start.
- W9.5.2 dostarczyło dokładnie trzy plany `profile`/`starter`/`pro`, jawny
  simulator wyboru planu i triala oraz egzekwowanie entitlementów. W local i
  staging nie ma formularza karty ani realnego obciążenia.
- W9.5.3 zastąpiło techniczny formularz strony trzyetapowym kreatorem
  adres → dane → podsumowanie. Kreator działa po polsku i angielsku, utrwala
  wersjonowany postęp i pozwala go bezpiecznie wznowić.
- W9.5.4 dostarczyło trzy wersjonowane recepty, pełny katalog dziewięciu
  kategorii sekcji, bezpieczny import do draftu oraz lokalizowany wybór z
  dynamiczną miniaturą i pełnym podglądem.

## Kontrakt W9.5.3

- `GET /api/v1/sites/subdomain-availability/` normalizuje etykietę, blokuje
  reserved names, uwzględnia globalne claimy i siedmiodniową kwarantannę oraz
  nie ujawnia właściciela zajętego adresu. Endpoint ma limit 30 zapytań/minutę.
- `GET/PUT /api/v1/sites/onboarding/` przechowuje tenantowy draft z optimistic
  lockiem, idempotencją, CSRF, permission, entitlementem i audytem.
- `POST /api/v1/sites/onboarding/complete/` atomowo tworzy stronę i claimuje
  preferowaną subdomenę. Wyścig nie przejmuje cudzego adresu: przegrany dostaje
  stabilny sufiks.
- Zmiana subdomeny platformy zachowuje stary hostname jako alias zwracający 308
  do nowego adresu. Faktycznie zwolniona etykieta trafia na 7 dni do
  kwarantanny.
- PostgreSQL pilnuje zgodności tenantów draftu, mutacji, domeny i zmiany domeny;
  dziennik mutacji onboardingu jest append-only.
- OpenAPI i generowany klient TypeScript zawierają onboarding, dostępność
  subdomeny i zmianę domeny platformowej.
- Własna domena jest w kreatorze wyłącznie opcjonalnym późniejszym upgrade'em;
  strona jest w pełni tworzona na subdomenie platformy.

## Dowody walidacji

- 2026-09-03 (konta lokalne, panel admina, luka RLS, koniec triala): pełna
  suita **498 passed** (drugi przebieg; w pierwszym jedyną porażką był
  `test_two_concurrent_transactions_create_only_one_appointment` — zielony w
  izolacji i w powtórce, niestabilny pod obciążeniem przez zakleszczenie
  zamiast konfliktu, osobna pozycja w P4). Nowe
  `tests/test_purge_test_tenants.py` (6, w tym ściana append-only) i szersza
  reguła wykrycia w `tests/test_tenant_isolation_regimes.py`. Frontend
  **95 passed**. Ruff czysty, import-linter 1 kept / 0 broken, Mypy 0 błędów w
  271 plikach, `pnpm api:check` bez dryfu, `pnpm lint` i `pnpm typecheck`
  zielone. Panel admina sprawdzony przez HTTP: logowanie 302, lista kont 200,
  lista domen 200, `/static/admin/css/base.css` 200. RLS na `organizations_*`
  sprawdzone wprost w `pg_class`/`pg_policies`: `relrowsecurity=false`, 0
  polityk na sześciu tabelach. Wybór planu po zakończonym trialu sprawdzony w
  przeglądarce na koncie właściciela: trzy przyciski aktywne.
  Uwaga: `pnpm format:check` jest czerwony na `AGENTS.md` i
  `.github/workflows/images.yml` — oba nietknięte dzisiaj, więc gate był
  czerwony już wcześniej;
- 2026-09-03 (W9.5.2S, kredyty w Stripe): sześć produktów i cen na koncie
  testowym (trzy plany + trzy pakiety), komenda nadal idempotentna; pełna suita
  **491 passed** w tym nowe `tests/test_billing_credit_checkout.py` (7); Mypy 0
  błędów w 270 plikach; `makemigrations --check` bez zmian;
- 2026-09-03 (W9.5.2S, katalog): `provision_stripe_catalog` utworzyła trzy
  produkty i ceny na koncie testowym i jest idempotentna (drugi przebieg
  „bez zmian"); `tax.calculations` potwierdziło 23% dla PL, 0% dla firmy z UE
  z NIP-em i 23% dla konsumenta z DE; migracje zastosowane na `saas_core_w3`;
  pełna suita **484 passed**; Mypy 0 błędów w 268 plikach;
- 2026-09-03 (W9.5.2S, krok 1): pełna suita **484 passed**; Mypy 0 błędów w
  266 plikach; Ruff czysty; `docker compose config` poprawny; sondy Stripe na
  koncie testowym potwierdziły parametry i zostały posprzątane (0 obiektów);
- 2026-09-03 (kredyty): pełna suita backendu **484 passed** na świeżej bazie,
  w tym `tests/test_billing_credits.py` (21) i zaktualizowany
  `test_billing_catalog`; `makemigrations --check` bez zmian; Mypy 0 błędów w
  266 plikach; import-linter 1 kept, 0 broken; Ruff czysty;
- 2026-09-03 (P1, ADR-039 w billing): pełna suita backendu **463 passed** na
  lokalnym PostgreSQL, w tym nowe `tests/test_billing_isolation.py` (6);
  `makemigrations --check` bez zmian po `billing.0013`; import-linter 1 kept,
  0 broken; Mypy 0 błędów w 261 plikach; Ruff czysty;
- 2026-09-02 (P1, ADR-039): `tests/test_tenant_isolation_regimes.py` 3/3,
  `tests/test_module_catalog.py` 3/3 i `tests/test_platform_workspace.py`
  4/4 na prawdziwym PostgreSQL (Windows venv, Docker Desktop) — dowód dla
  przeniesionej komendy jest tym samym uzupełniony; `makemigrations --check`
  bez zmian po `sites.0024`; kontrakty JS **20/20** (test cudzej tabeli
  publicznej i test aplikacji-ducha); Ruff czysty;
- 2026-09-02 (P1, katalog): `pnpm deployment:check:all` zielony dla
  `core-only` i `business`; testy kontraktów JS **18/18** (w tym nowy test
  odrzucający deskryptor aplikacji bez kodu); `tests/test_module_catalog.py`
  **3/3** (WSL, bez bazy); frontend **94/94** po regeneracji
  `generated/deployment.ts`; Ruff i format czyste; prettier na zmienionych
  plikach zielony;
- 2026-09-02: import-linter był czerwony od `6a6a30a` (W9.6.1) przez import
  Core → Shared w `provision_platform_workspace`; po przeniesieniu komendy do
  `shared.billing` kontrakt warstw jest zielony (`lint-imports`: 1 kept,
  0 broken), Ruff i Mypy (258 plików) przeszły. Testy `test_platform_workspace`
  nie zostały uruchomione — lokalny Docker Desktop był wyłączony, a testy
  wymagają PostgreSQL; komenda zmieniła lokalizację, nie zachowanie, ale ten
  dowód jest do uzupełnienia przy pierwszym uruchomieniu stacku;
- pełna bramka backendu: Ruff, import-linter, brak dryfu migracji, Mypy 0 błędów
  w 231 plikach i **360 testów**;
- import szablonu: **4 testy** obejmujące optimistic lock, idempotentne
  ponowienie, konflikt zmienionego replaya, exact-tenant, brak recepty, audit,
  odmowę przy brakującym entitlementcie oraz materializację zatwierdzonego
  medium z checksum, skanowaniem, quota, reuse między aktorami i kompensacją
  storage po rollbacku draftu;
- pełne testy workspace'u JS: contracts **12**, UI **8**, site-blocks **13**,
  frontend **73**; lint, typecheck, build Next.js i `api:check` przeszły;
- skrypt `api:check` uruchamia teraz izolowane środowisko backendu również na
  Windows zamiast próbować wykonać linuksowy `.venv/bin/python`;
- Playwright **1/1** dokumentuje pełną ścieżkę onboarding → domena opcjonalna →
  mobilny wybór i podgląd szablonu → import klawiaturą → edycja → preview →
  publikacja → rollback; test sprawdza także Escape i powrót fokusu;
- axe dla otwartego dialogu podglądu przechodzi bez naruszeń w obu wersjach
  językowych, a testy jednostkowe potwierdzają lokalizację PL/EN;
- `git diff --check` jest zielone.

Lokalny host ma Node.js 22 i emituje ostrzeżenie `engines`; właściwy runtime
Node.js 24 został potwierdzony buildem obrazu frontendowego. Testy backendu
wymagają zdrowego PostgreSQL i Redis. Pełny pytest może przy zamykaniu zgłosić
ostrzeżenie o dwóch sesjach testowej bazy pozostawionych chwilowo przez testy
wielowątkowych wyścigów; wynik pozostaje 360/360.

## Następny cel wykonawczy

P1 w toku — patrz punkt wznowienia. Poniżej stan W9.5.4 dla kontekstu.
W9.5.4 ma trzy kanoniczne
recepty, katalog sekcji, backendowy import oraz gotowy wybór z podglądem.
`PageTemplate` jest niemutowalnym modelem domenowym ładowanym z
`packages/contracts/page-templates`, nie drugą tabelą z kopią recept. Endpoint
`POST /api/v1/sites/pages/{page_id}/template-import/` tworzy zwykłą
`PageVersion` przez `save_draft`; panel używa endpointu bezpośrednio, więc
`requiredEntitlements` nie da się ominąć ścieżką UI.

Kontrakt recepty obsługuje już opcjonalne, zatwierdzone media z lokalnym źródłem,
MIME i SHA-256. Import materializuje je jako tenantowe `MediaAsset` przez ten sam
pipeline co upload użytkownika: skan malware, normalizacja, warianty, storage
quota i audyt. Deterministyczna tożsamość daje jeden rekord na organizację także
przy imporcie przez różnych managerów, a kompensacja usuwa obiekty z storage,
jeśli późniejszy optimistic lock lub zapis draftu cofnie transakcję. Dzisiejsze
trzy recepty v1 pozostają bez mediów; obrazy wejdą jako nowe wersje recept.
Miniatury i dialog podglądu nie są osobnymi screenshotami: panel renderuje je z
kanonicznej recepty przez ten sam rejestr bloków. Lokalizowane są metadane i
kontrolki interfejsu; przykładowa treść obecnych recept v1 pozostaje polska,
ponieważ zmiana seed copy wymaga nowej wersji recepty, a nie mutacji v1.

Biblioteka sekcji ma już 9 z 9 kategorii ADR-031. `core.testimonials`,
`core.pricing`, `core.booking` i `core.footer` mają kanoniczne JSON Schema,
deklaratywne pola edytora PL/EN i kontrolowane renderery. Rezerwacja pozostaje
bezpiecznym CTA — blok nie osadza skryptu ani zewnętrznego widgetu. Kontrakty
mają **12/12**, site-blocks **13/13**, frontend **73/73**; lint, typecheck i
build Next.js przeszły.

Znane długi frontendu, nietknięte przez te commity:

- publiczny renderer ma `<html>` bez `lang` (`app/site-renderer/layout.tsx`) —
  narusza WCAG 2.2 AA, które ADR-031 stawia jako bramkę odbioru;
- paleta `.dark` istnieje, ale nic nie ustawia klasy `dark`: przełącznik motywu
  wymaga decyzji, gdzie żyje kontrolka i jak wybór przeżywa SSR;
- lokalny Node to 22, projekt wymaga 24 — każda komenda pnpm ostrzega;
- `AGENTS.md` nie przechodzi `format:check` (sekcja memeksa).

W9.6 — stan po 2026-08-28. ADR-035 jest zatwierdzony, migracje odblokowane.
Zbudowane i działające na lokalnym stacku:

- **kolekcje treści i blog** (`27f3076`, `e4a22fc`): `ContentCollection`,
  `ContentEntry`, niemutowalna `ContentEntryVersion`, append-only
  `ContentEntryPublication`. Wpis publikuje się sam — test dowodzi, że rozmiar
  snapshotu nie rośnie z archiwum. Wpis jest osiągalny publicznie pod
  `/<kolekcja>/<slug>/` i renderuje się tym samym payloadem co strona;
- **polityka edycji** (`4de0558`): `automation_policy` na stronie i na kolekcji,
  plus chwilowa blokada ręcznej edycji; egzekwowane w `save_draft`, więc każdy
  kanał ją dziedziczy;
- **ręczny panel bloga i polityki** (`98076be` oraz kolejny przyrost): operator
  tworzy kolekcje i wpisy, a trzystanowa polityka `manual` / `proposed` /
  `automated` rozdziela ręczną redakcję, szkice do akceptacji i pełne prowadzenie
  przez automatyzację. Panel oznacza szkice napisane przez integrację, żeby
  publikacja propozycji była świadomą akceptacją;
- **klucz API dla SeoContentRank** (`cee17e2`): scope `content:read`,
  `content:draft`, `content:publish`; middleware w `shared.notifications`
  ustawia `TenantContext` z `principal_kind="api_key"`. Wymagany scope wynika z
  samego żądania, a aktorem audytu jest operator, który klucz wydał. Odczyt
  chronionego RLS rekordu klucza następuje dopiero po `SET LOCAL
  app.organization_id`; smoke na lokalnym stacku potwierdził odpowiedź `200`;
- **zakresowy grant automatyzacji** (`a1f4fe3`): brak grantu odcina dostęp, a
  grant zawęża klucz do site'u albo kolekcji oraz uwzględnia TTL i emergency
  revoke.

Dowody ostatniego przyrostu: Ruff, import-linter, brak dryfu migracji i Mypy
przeszły; pełny backend ma **358/358 testów**, pełny workspace JS jest zielony
(frontend **71/71**), a świeżo wygenerowane OpenAPI i klient TypeScript są
identyczne z wersjami kanonicznymi. Lokalny Node 22 nadal emituje znane
ostrzeżenie `engines`; wymagany runtime projektu to Node 24.

Słownik grantu jest zamrożony w obu projektach: jedyna nazwa czwartego trybu to
`autonomous`; historyczne `auto_publish_limited` nie jest aliasem i ma być
odrzucane fail-closed. Ograniczenie autonomii wynika z obowiązkowych limitów
grantu, a niezależna polityka treści `manual` / `proposed` / `automated` może
wyłącznie zawężać grant. SaaS Core utrwalił to w `73e9df5`, a SeoContentRank w
`97f1ab2`.

Stan W9.6 na 2026-09-02: wszystkie pakiety programistyczne W9.6.0–W9.6.8 są
odhaczone w checkliście (53 z 66 pozycji). Otwarte pozostają wyłącznie cztery
rolloutowe pozycje W9.6.8 i dziewięć pozycji bramki wyjścia — wszystkie
wymagają stagingu i connectora SeoContentRank po drugiej stronie i są
zaplanowane w P8 planu poaudytowego. Lista „do zrobienia" z 2026-08-28 była
nieaktualna i została usunięta.

Znany rozjazd do rozstrzygnięcia: ADR-022 wymaga RLS na prywatnych rekordach
tenantowych i `shared.media` go ma, ale `shared.sites` nie — izolacja opiera się
tam na warstwie serwisu i wyzwalaczach cross-tenant. Migracja `0009` wyrównała
tabele kolekcji do konwencji modułu, bo wymuszony RLS blokował publiczny
renderer (żądanie odwiedzającego nie ma kontekstu tenanta). Ktoś powinien
zdecydować, która strona ma rację.

## Niezmienne ograniczenia

- tenantowe operacje wymagają jawnego `TenantContext`;
- API osobno egzekwuje permission i entitlement;
- mutacje uwzględniają audyt, idempotencję i transakcję/outbox;
- typy API pochodzą z OpenAPI;
- UI korzysta wyłącznie z publicznego `@saas-core/ui`;
- nie zapisuj sekretów ani danych osobowych w repozytorium, fixture'ach i logach;
- stage'uj wyłącznie jawne ścieżki; `.codex/` jest lokalne i nie należy do
  przyrostu.

Po kolejnym znaczącym przyroście zaktualizuj checklistę właściwej fali i Memex, uruchom
odpowiednie bramki, a następnie wykonaj osobny commit.
