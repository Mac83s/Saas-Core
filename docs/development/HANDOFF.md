# Handoff następnej sesji

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

Czego jeszcze nie ma: **nikt nie przeszedł jeszcze płatności kartą testową**,
więc `checkout.session.completed` nie został odebrany na żywo, a
`activate_customer_trial` nie zadziałał na prawdziwej sesji.

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
