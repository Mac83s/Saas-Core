# Handoff następnej sesji

**Aktualizacja:** 2026-09-02

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
relacji rodzic–dziecko. `KNOWN_OPEN_PRIVATE_TABLES` w teście izolacji jest
puste — wpis wolno tam dodać wyłącznie razem z pozycją planu, która go usuwa.

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

## Realny Stripe (W9.5.2S) — gdy właściciel dostarczy konto

Właściciel zapowiedział konto Stripe na 2026-09-03. Zakres i bramka odbioru
pozostają w W9.5.2S i ADR-034; ten wpis mówi tylko, czego potrzeba na start.

Od właściciela:

1. dostęp do konta Stripe w trybie **test** (live dopiero po odbiorze):
   `STRIPE_SECRET_KEY` (`sk_test_…`) i `STRIPE_WEBHOOK_SECRET` (`whsec_…`)
   dostarczone przez secret store albo plik poza repo (`*_FILE`) — nigdy w
   czacie ani w commicie; klucz wklejony do czatu trzeba zrotować;
2. potwierdzenie waluty (PLN) i czy Stripe Tax ma liczyć VAT;
3. włączony Customer Portal w dashboardzie (metoda płatności, faktury,
   anulowanie, zmiana planu w obsługiwanym zakresie) i dane firmy do faktur;
4. gdzie odbieramy webhooki: lokalnie przez `stripe listen --forward-to`
   (Stripe CLI — wystarcza do testów) czy na stagingu (wymagane do zaliczenia
   bramki ADR-034, bo dowodem jest staging smoke).

Po stronie repo: `BILLING_PROVIDER=stripe` z fail-closed startem przy
niekompletnej konfiguracji, dokładnie trzy Product/Price zmapowane komendą
`configure_stripe_prices --mapping <plan>=<prod_…>,<price_…>` (komenda
istnieje), ścieżka Setup Checkout → webhook → lokalny snapshot entitlementów,
testy podpisu, kolejności, retry, idempotencji i exact-tenant, SCA/3DS,
grace/read-only, runbook aktywacji i rollbacku.

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
