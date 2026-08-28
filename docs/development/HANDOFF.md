# Handoff następnej sesji

**Aktualizacja:** 2026-08-28

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj falę W9.5 z
`Plan/Wdrozenie/10A-W9.5-Customer-Experience-Commerce-i-AI.md`. Pakiety
W9.5.1–W9.5.3 są ukończone lokalnie. Następny spójny przyrost to **W9.5.4 —
szablony i katalog sekcji**. Realny Stripe pozostaje świadomie odłożony do
W9.5.2S i blokuje płatny pilot, ale nie dalszą lokalną pracę nad W9.5.

Równolegle właściciel uruchomił planowanie osobnego systemu SeoContentRank.
SaaS Core przygotowuje dla niego falę **W9.6 — Publication Platform i gotowość
na SeoContentRank**. W9.6.0 (ADR i kontrakty graniczne) może rozpocząć się obok
W9.5.4; implementacja wymagająca nawigacji ma użyć rezultatu W9.5.5, a nie
tworzyć drugie drzewo stron.

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

- pełna bramka backendu: Ruff, import-linter, brak dryfu migracji, Mypy 0 błędów
  w 231 plikach i **358 testów**;
- import szablonu: **2 testy** obejmujące optimistic lock, idempotentne
  ponowienie, konflikt zmienionego replaya, exact-tenant, brak recepty, audit i
  odmowę przy brakującym entitlementcie;
- pełne testy workspace'u JS: contracts **10**, UI **8**, site-blocks **11**,
  frontend **71**; lint, typecheck, build Next.js i `api:check` przeszły;
- skrypt `api:check` uruchamia teraz izolowane środowisko backendu również na
  Windows zamiast próbować wykonać linuksowy `.venv/bin/python`;
- wcześniejszy Playwright **1/1** nadal dokumentuje pełną ścieżkę onboarding →
  domena opcjonalna → treść → preview → publikacja → rollback;
- `git diff --check` jest zielone.

Lokalny host ma Node.js 22 i emituje ostrzeżenie `engines`; właściwy runtime
Node.js 24 został potwierdzony buildem obrazu frontendowego. Testy backendu
wymagają zdrowego PostgreSQL i Redis. Pełny pytest może przy zamykaniu zgłosić
ostrzeżenie o dwóch sesjach testowej bazy pozostawionych chwilowo przez testy
wielowątkowych wyścigów; wynik pozostaje 358/358.

## Następny cel wykonawczy

W9.5.4 ma już trzy kanoniczne recepty, katalog sekcji oraz backendowy import.
`PageTemplate` jest niemutowalnym modelem domenowym ładowanym z
`packages/contracts/page-templates`, nie drugą tabelą z kopią recept. Endpoint
`POST /api/v1/sites/pages/{page_id}/template-import/` tworzy zwykłą
`PageVersion` przez `save_draft`; panel używa endpointu bezpośrednio, więc
`requiredEntitlements` nie da się ominąć ścieżką UI.

Do zamknięcia W9.5.4:

1. rozszerzyć kontrakt recepty o zatwierdzone media i wdrożyć ich idempotentną
   materializację jako tenantowych `MediaAsset`; dzisiejsze recepty celowo nie
   mają mediów;
2. przygotować lokalizowane miniatury i preview;
3. uzupełnić bibliotekę z 5 do 9 kategorii o Zaufanie, Cennik, Rezerwację i
   Stopkę;
4. wykonać dowody mobile, klawiatura i axe dla wyboru oraz importu szablonu.

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

Do zrobienia w W9.6, w kolejności zależności:

1. **semantyka czterech trybów grantu i limity** — model zna wszystkie tryby,
   ale serwisy muszą jeszcze odrębnie egzekwować `suggest_only`, `draft_write`,
   `publish_with_approval` i `autonomous`, limity zmian oraz allowed windows;
2. **indeks bloga, RSS i sitemap** — wpisy są osiągalne tylko po adresie
   bezpośrednim; czytelnik nie ma jak ich znaleźć;
3. **tłumaczenia i media wpisów** — wpis jest dziś jednojęzyczny;
4. **chroniony workspace platformowy (W9.6.1)** — dla waszych własnych stron
   marketingowych i bloga platformy;
5. **`ContentChangeSet` (§5, wstępny)** — do rewizji przy pierwszym realnym
   spięciu z SCR.

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
