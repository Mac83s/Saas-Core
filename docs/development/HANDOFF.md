# Handoff następnej sesji

**Aktualizacja:** 2026-08-21

**Repozytorium:** `/mnt/a/DEVELOPMENT/Saas-Core` (`A:\DEVELOPMENT\Saas-Core`)

**Gałąź:** `main`

## Punkt wznowienia

Kontynuuj falę W9.5 z
`Plan/Wdrozenie/10A-W9.5-Customer-Experience-Commerce-i-AI.md`. Pakiety
W9.5.1–W9.5.3 są ukończone lokalnie. Następny spójny przyrost to **W9.5.4 —
szablony i katalog sekcji**. Realny Stripe pozostaje świadomie odłożony do
W9.5.2S i blokuje płatny pilot, ale nie dalszą lokalną pracę nad W9.5.

Równolegle właściciel uruchomił planowanie osobnego systemu Market Maker.
SaaS Core przygotowuje dla niego falę **W9.6 — Publication Platform i gotowość
na Market Makera**. W9.6.0 (ADR i kontrakty graniczne) może rozpocząć się obok
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

Zacznij W9.5.4 od kontraktu wersjonowanego `PageTemplate` i importu do draftu.
Przed zmianą architektury przeczytaj ADR-027 i ADR-031 oraz kontrakty
`docs/architecture/module-contract.md`, `api-and-events.md` i
`testing-strategy.md`. Następnie:

1. zdefiniuj wersjonowany kontrakt szablonu i granicę importu bez obchodzenia
   istniejącego wersjonowania draftów;
2. zaprojektuj lokalizowane metadata, kategorie, miniatury i preview;
3. dostarcz co najmniej profil, landing specjalisty i stronę firmy;
4. egzekwuj rodziny szablonów przez permission i entitlement w API;
5. dodaj dowody PL/EN, mobile, klawiatura, axe, exact-tenant i idempotentny
   import.

Równoległy cel kontraktowy W9.6:

1. przejrzeć i zatwierdzić lub skorygować proponowany ADR-035;
2. zamrozić kontrakt `ContentChangeSet`, `ContentAutomationGrant` i dwa rodzaje
   publikacji: atomowy site oraz wpis kolekcji;
3. przygotować współdzielone fixture kontraktowe z connectorem Market Makera;
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
