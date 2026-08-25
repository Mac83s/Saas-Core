# Handoff następnej sesji

**Aktualizacja:** 2026-08-25

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
  w 221 plikach i **336 testów**;
- regresja Sites: **37 testów**, w tym claim race, reserved names, kwarantanna,
  rate limit, exact-tenant, permission/entitlement, CSRF, idempotencja, audyt,
  append-only i redirect 308;
- pełne testy workspace'u JS oraz `api:check` przeszły;
- testy komponentowe kreatora i panelu: **9 testów**, PL/EN, wznowienie,
  konflikt wersji, sugestia adresu i axe;
- produkcyjny build Next.js przeszedł w obrazie Node.js 24;
- Playwright: **1/1**, pełna ścieżka onboarding → domena opcjonalna → treść →
  preview → publikacja → rollback;
- `format:check`, pełny lint, typecheck i `git diff --check` są zielone.

Lokalny host ma Node.js 22 i emituje ostrzeżenie `engines`; właściwy runtime
Node.js 24 został potwierdzony buildem obrazu frontendowego. Testy backendu
wymagają zdrowego PostgreSQL i Redis. Pełny pytest może przy zamykaniu zgłosić
ostrzeżenie o dwóch sesjach testowej bazy pozostawionych chwilowo przez testy
wielowątkowych wyścigów; wynik pozostaje 336/336.

## Następny cel wykonawczy

Frontendowa część W9.5.4 jest dostarczona (commity `404fa60`, `e3eabd5`,
`dba53f3`): bloki opisują swoją kategorię ADR-031 i pola w manifeście,
`defineSiteBlockManifest` sprawdza każdą ścieżkę pola względem kanonicznego JSON
Schema, edytor renderuje formularz z tego katalogu, a pusta strona proponuje trzy
wersjonowane szablony (`core.profile`, `core.specialist_landing`,
`core.company`) z `packages/contracts/page-templates`. Dodanie sekcji to dziś
wpis w manifeście plus schemat; edytor nie zna żadnego bloku po nazwie.
Biblioteka ma 5 z 9 kategorii — brakuje Zaufanie, Cennik, Rezerwacja, Stopka.

**Backendu tej fali nie dało się dotknąć w tej sesji:** `.venv` jest linuksowe
(WSL), Windows nie ma Django, a kontenery SaaS Core nie działały. Praca po
stronie serwera wymaga sesji z działającym backendem. Do zrobienia:

1. model `PageTemplate` i endpoint importu recepty do draftu, bez obchodzenia
   istniejącego wersjonowania i optimistic locka — recepty i ich walidacja już
   są, backend ma je konsumować, nie definiować od nowa;
2. egzekwowanie `requiredEntitlements` recepty w API (frontend filtruje tylko
   po to, by nie proponować czegoś, co API odrzuci);
3. idempotentna materializacja mediów recepty jako tenantowych `MediaAsset`
   (ADR-031) — dzisiejsze szablony celowo nie zawierają mediów;
4. lokalizowane miniatury i preview;
5. dowody PL/EN, mobile, klawiatura, axe, exact-tenant i idempotentny import.

Znane długi frontendu, nietknięte przez te commity:

- publiczny renderer ma `<html>` bez `lang` (`app/site-renderer/layout.tsx`) —
  narusza WCAG 2.2 AA, które ADR-031 stawia jako bramkę odbioru;
- paleta `.dark` istnieje, ale nic nie ustawia klasy `dark`: przełącznik motywu
  wymaga decyzji, gdzie żyje kontrolka i jak wybór przeżywa SSR;
- lokalny Node to 22, projekt wymaga 24 — każda komenda pnpm ostrzega;
- `AGENTS.md` nie przechodzi `format:check` (sekcja memeksa).

Równoległy cel kontraktowy W9.6 — właściciel podjął cztery decyzje (ADR-035 §4,
§4a, §7): klucze i granty wydaje operator, nie klient; tryb `autonomous` jest
docelowy, a odpowiedzialność za jakość treści spoczywa na SeoContentRank;
polityka edycji jest ustawiana per strona (`manual` domyślnie), z chwilową
blokadą na czas ręcznej edycji; strony klientów muszą mieć podstrony, a blog
jest osobną powierzchnią publikującą wpis po wpisie. Polityka i blokada są już
zaimplementowane (commit `4de0558`). Dalej:

1. zatwierdzić ADR-035 w całości albo skorygować pozostałe sekcje;
2. zamrozić kontrakt `ContentChangeSet`, `ContentAutomationGrant` i dwa rodzaje
   publikacji: atomowy site oraz wpis kolekcji;
3. przygotować współdzielone fixture kontraktowe z connectorem SeoContentRank;
4. nie rozpoczynać migracji systemowego workspace'u przed akceptacją ADR-035.

## Niezmienne ograniczenia

- tenantowe operacje wymagają jawnego `TenantContext`;
- API osobno egzekwuje permission i entitlement;
- mutacje uwzględniają audyt, idempotencję i transakcję/outbox;
- typy API pochodzą z OpenAPI;
- UI korzysta wyłącznie z publicznego `@saas-core/ui`;
- nie zapisuj sekretów ani danych osobowych w repozytorium, fixture'ach i logach;
- stage'uj wyłącznie jawne ścieżki; `.codex/` jest lokalne i nie należy do
  przyrostu.

Po kolejnym znaczącym przyroście zaktualizuj checklistę W9.5 i Memex, uruchom
odpowiednie bramki, a następnie wykonaj osobny commit.
