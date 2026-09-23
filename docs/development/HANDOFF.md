# Stan bieżący Saas-Core

Ten plik opisuje **stan na dziś** i jest aktualizowany w miejscu: zmieniasz
sekcję, której dotyczy Twoja praca, zamiast dopisywać nowy wpis na górze.
Plany, fazy i odpowiedzi właściciela żyją w memeksie (`desk/plans`, projekt
`saas-core`); historia sesji — w git i w worklogach memeksu. Ostatnia wersja
dawnego dziennika (59 sekcji, do 2026-09-23):
`git show cd66b20:docs/development/HANDOFF.md`.

Stan na: **2026-09-23**. Punkty „otwarte” niżej sprawdzono tego dnia w kodzie
i git; zamknięte pozycje z dawnego dziennika zostały pominięte.

## Żywe plany (memex)

| Plan | O czym | Gdzie jesteśmy |
| --- | --- | --- |
| `saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka` | standard list panelu, wizytówka, historia zmian, limit podstron, wyszukiwarka katalogu | fazy 1–4 zrobione (DataTable, przełącznik wizytówki, historia zmian, limit podstron); dalej magazyn v2, potem Meilisearch |
| `magazyn-materia-o-w-od-pakietu-korektora-do-kare` | uniwersalny magazyn firm (`shared.inventory` v2): dokumenty, miejsca, rezerwacje, rezerwacje stanu przy wizytach, przyszły sklep | projekt v2 przyjęty 23.09; implementacja po fazach 2–4 planu panelu |
| `saas-core-site-studio-templates`, `saas-core-site-studio-rich-content-and-full-width` | Site Studio: szablony, warianty, bogata treść | bogata treść, pełna szerokość, wygląd strony i 3 strony demonstracyjne scalone i wdrożone 23.09 (saas, a wieczorem też HoofCare i MedPlano) (`docs/architecture/site-rich-content.md`, raport `2026-09-23-rich-content`); faza 3a (20 układów redakcyjnych pod konwersję, `core.rich_text` v3, katalog v6, ostrzeżenie o miejscach `[Uzupełnij: …]`) i 3b (8 stylów strony, kotwice sekcji i przyciski „do formularza”, 9 recept stron v5 z celem i ścieżką konwersji, 8 dawnych szablonów wycofanych z galerii) scalone 23.09; dalej edytor WYSIWYG (etap 2b) |
| `domkna-c-saas-core-po-audycie-realna-kompozycja-` | baza P0–P3 po audycie | treść w `Plan/Wdrozenie/13-…` |

Kolejność przyjęta 23.09: faza panelu 3 → 4 → magazyn 4–8 → wyszukiwarka →
magazyn 9–10 → pozostałe listy na DataTable.

## Wdrożenie (dev VPS goldentrd, instancje to development do ok. połowy października)

- `saas.goldenstar.cloud` (profil `vps-dev`), `hoofcare.goldenstar.cloud`,
  `medplano.goldenstar.cloud` — osobne stacki compose; produkty przez
  `--env-file .env.<produkt>` i `compose.<produkt>.yaml`.
- Kod działający na VPS i raporty wydań: `docs/operations/releases/`
  (ostatnie z 23.09: DataTable, przełącznik wizytówki i strona wizytówki w
  katalogu, bogata treść Site Studio, historia zmian). Od 23.09 wieczorem
  HoofCare i MedPlano stoją na tym samym rdzeniu co Saas-Core (`e239f40`,
  decyzja właściciela „niech leci do produktów core”).
- Płatności we wszystkich trzech: `BILLING_PROVIDER=simulated`.
- E-mail: Saas-Core wysyła przez Resend SMTP; HoofCare i MedPlano zapisują
  pocztę do plików (`.runtime-<produkt>/emails`) — raporty dla rolników i
  potwierdzenia nie wychodzą.
- Skrypty wydań (build z `git archive`, rollback tagami, kopia bazy przed
  migracją): `.runtime/releases/<data>-<nazwa>/`.

## Otwarte — rdzeń

- **Infrastruktura** (memex follow-up, termin 30.09): staging i rollback przez
  GHCR, odbiór alertu poza VPS, szyfrowany backup offsite z odtworzeniem, test
  On-Demand TLS dla domeny klienta. Obejmuje też „dwa środowiska testowe na
  osobnych danych” (plan 13, P1).
- **Realny Stripe (W9.5.2S):** runbook aktywacji i wycofania
  (`docs/operations/billing.md:41-52`), ceny brutto dla konsumentów (ADR-040 §2),
  ścieżka 3DS/`incomplete` (`shared/billing/provider.py:398`), konto live i
  webhook z przypiętą wersją API; po stronie właściciela OSS, księgowość,
  dokumenty sprzedaży. `SubscriptionState.SUSPENDED` jest martwą wartością.
- **Kredyty:** operacje content-ops zasiane jako nieaktywne do kontraktu SCR
  (`shared/billing/migrations/0016_seed_credit_catalog.py:89-100`); brak
  `shared.assistant` (zużycie przez AI, historia).
- **P3 (plan 13:406-442):** powiązanie profilu osoby z witryną, konto klienta
  (`Customer.user`, „moje wizyty”), role specjalista/recepcja,
  `PolicyAcknowledgement`, skill tożsamości.
- **Wizytówka (ADR-053):** plan `profile` nadal ma `sites.enabled`
  (`shared/billing/migrations/0012_seed_profile_plan.py:26`) — decyzja cenowa
  właściciela; wyszukiwarka to jeszcze `tsvector simple`.
- **Limit podstron** działa od 23.09 (Profil 5, Witryna 15, Pro 50; liczby
  tymczasowe, do ustalenia przez właściciela). Migawka bez `pages.max` nie ma
  limitu — zmiana planu dociera do organizacji dopiero po przeniesieniu jej
  abonamentu na nową wersję (skrypt w `.runtime/releases/20260923-pages-limit/`).
- **Historia zmian:** „było → jest” zapisują główne edycje (firma, wizytówka,
  rola, gospodarstwo, zwierzę, pozycja magazynu, dane do faktury); pozostałe
  akcje pokazują listę pól albo nic. Wpisy sprzed 23.09 nie mają kanału.
- **Fixture odbioru** `sites_e2e_fixture` nadaje tylko cechy witryny; do odbioru
  wizytówki trzeba dopisać `profiles.enabled` (23.09 zrobione ręcznie na koncie
  testowym). Wszystkie prawdziwe plany tę cechę mają.
- **Rezerwacje:** wizyta bez rezerwacji obsługuje jeden wymagany zasób
  (`shared/booking/services.py:340`); karta „Konta pracowników kalendarza”
  pokazuje błąd zamiast się ukryć, gdy plan nie ma rezerwacji (403).
- **Rejestr gospodarstw (backlog z przebudowy panelu):** brak slotu sekcji
  gospodarstwa dla produktu; brak GET pojedynczego zwierzęcia i filtra statusu
  (`shared/farms/views.py:139-176`); brak importu CSV; brak telefonu/miasta
  na `Organization`; płatny okres próbny wymaga Checkout; „Wiadomości”
  wymagają `notifications.manage` albo `site.content.edit`
  (`apps/frontend/src/lib/panel-navigation.ts:197-200`).
- **Workspace platformy** dostaje `sites.enabled` bez `sites.max`, więc
  założenie witryny kończy się `QuotaUnavailable`
  (`provision_platform_workspace.py:45`).
- **Strony marketingowe:** brak bloga i stron prawnych; formularz kontaktowy
  czeka na klucze (`contact/page.tsx:21`); SCR dla stron marketingowych
  (plan 14:133).
- **Site Studio:** edytor WYSIWYG na strukturze `core.rich_text` (etap 2b);
  prawdziwe zdjęcia produktu i portretów (dziś 4 ilustracje AI, recepty
  używają ich wielokrotnie); `core:update` produktów o fazy 3a i 3b; własne
  szablony (faza 4), AI (faza 8), Content Ops v2. Formularz kontaktu nie ma
  konfiguracji pól — telefon jest zawsze opcjonalny, więc prośba o
  oddzwonienie nie wymusi numeru. Styl `studio`/`product` chce nagłówków 800,
  a dołączony Manrope kończy się na 700. Realne doręczenie zapytań ze strony przez SMTP nieudowodnione. Import
  szablonu ze zdjęciem zwraca 500, gdy ClamAV nie zdąży w 30 s (obciążony host)
  — powinien być błąd „spróbuj ponownie”; publiczne zdjęcia bez wariantów
  responsywnych (oryginały PNG ~2 MB).
- **Listy na DataTable:** tylko zespół; własne tabele nadal w `farms-panel`,
  `animals-panel`, `farm-detail`, `inventory-panel`, `seo/audits-panel`,
  `seo/gsc-panel`.
- **Wyszukiwarka panelu** z makiety — brak API i UI; **warianty kolorów
  produktów** (5 od właściciela) — brak.
- **Integracja SEO na instancjach (plan 14:74-91, 205):** osiem przepływów na
  żywych instancjach, realne GSC OAuth, płatny audyt i generacja, manifest
  wydania; W9.6.8 wymaga stagingu i konektora SCR.
- **Testy** `navigation-editor`/`page-editor` bywają niestabilne pod
  obciążeniem hosta; czekają na `findByText("Start")`, co nie dowodzi
  wczytania menu.
- **Nieaktualne dokumenty:** `docs/architecture/site-studio-editor.md:116-119`
  i `:209` (zamknięte 21.09); plan 13:468 (mapowanie zakleszczenia — zrobione).

## Otwarte — produkty

- HoofCare: `docs/product/HANDOFF.md` w repo HoofCare (etap 5 sprzedaży
  zwierząt, magazyn v2, tryb offline, publikacja rezerwacji publicznej do
  kartoteki rolnika — decyzja właściciela).
- MedPlano: bez własnych rozszerzeń — dostaje wyłącznie aktualizacje rdzenia
  (decyzja właściciela 23.09).

## Nierozstrzygnięte

- Obraz SCR na VPS (I6, plan 14:74) — działa od 12 dni, brak zapisanego
  digestu i SHA w planie 14.
- Plany firmowe są wspólne dla wszystkich produktów — do potwierdzenia przez
  właściciela, czy tak zostaje.
- ADR-050, 051 i 052 mają status „proponowana”, choć są wdrożone.

## Praca na tym VPS

- `pnpm` przez corepack: `export PATH="/usr/lib/node_modules/corepack/shims:$PATH"`;
  host ma Node 22, repo wymaga 24 — ostrzeżenie jest nieszkodliwe, obrazy
  budują się na Node 24.
- Testy backendu: kontener `saas-core-testdb` na `127.0.0.1:55432`
  (`POSTGRES_HOST`/`POSTGRES_PORT` wskazują go przy `uv run … pytest`); pełny
  backend rdzenia ~11 min, pojedynczy plik 1–3 min.
- Kilka sesji pracuje równolegle: własny worktree, commity jawnymi ścieżkami,
  a zmiany rdzenia do produktów tylko przez `pnpm core:update`.
