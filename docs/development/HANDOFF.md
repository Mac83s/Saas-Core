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

P0 jest rozpoczęte: trzy ADR-y są zapisane jako `Proposed` — ADR-036
(tożsamość: `User`, `Organization`, `PublicProfile`, tenantowy `Customer`),
ADR-037 (Appointment Commerce i Stripe Connect) i ADR-038 (repozytoryjne Agent
Skills). Każdy ma sekcję „Decyzje wymagające właściciela"; P0 zamyka się, gdy
właściciel zatwierdzi albo zmieni te punkty i status przejdzie na `Accepted`.
Do tego czasu nie zmieniaj modeli `User` i `Customer` ani nie twórz
`shared.commerce`. Następnie P1 (kompozycja deploymentów) i P2 (kanoniczne
skills, `pnpm ai:validate`, CI). Skills mają być utrzymywane przez agentów;
właściciel produktu nie synchronizuje ani nie edytuje ich ręcznie.

Repozytoryjne skills deweloperskie i produktowe skills `shared.assistant` są
dwoma osobnymi systemami. Pierwsze pomagają zmieniać kod, drugie działają w
TenantContext przez wersjonowane komendy aplikacyjne. Żaden skill nie zmienia
zaakceptowanego ADR-u ani nie autoryzuje wdrożenia produkcyjnego.

Istniejące W9.5 i W9.6 pozostają planami szczegółowymi. Nie duplikuj ich modeli
ani kontraktów w planie poaudytowym.

W9.5 (`Plan/Wdrozenie/10A-W9.5-Customer-Experience-Commerce-i-AI.md`) ma
ukończone W9.5.1–W9.5.4; W9.5.5–W9.5.8 są zaplanowane w P6, a W9.5.2S w P5.
Nie zaczynaj W9.5.5 przed P0–P2, chyba że właściciel zmieni kolejność.

W9.6 — Publication Platform i gotowość na SeoContentRank — jest ukończone
lokalnie (kod, testy, panel). Zostały wyłącznie rolloutowe pozycje W9.6.8 i
bramka wyjścia, które wymagają stagingu i connectora po drugiej stronie; żyją w
P8. Model nawigacji jest jeden i powstał w W9.6.3.

Nie wracaj teraz do bramek wymagających prawdziwego stagingu/VPS. Są odłożone do
sesji z dostępem do hosta, domeny, GHCR i GitHub Environment.

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

Domknij P0: właściciel zatwierdza albo zmienia decyzje w ADR-036–038, potem
P1. Poniżej stan W9.5.4 dla kontekstu. W9.5.4 ma trzy kanoniczne
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
