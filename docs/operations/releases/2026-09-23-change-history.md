# Historia zmian w ustawieniach firmy — wydanie 2026-09-23

Zakres: faza 3 planu memex
`saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`. Właściciel i
administrator widzą w Ustawieniach → Historia zmian, kto, kiedy, którym kanałem
i co zmienił, a przy edycjach — wartość przed i po. Tym samym wydaniem rdzeń z
Site Studio (bogata treść, raport `2026-09-23-rich-content.md`) trafił do
HoofCare i MedPlano — decyzja właściciela z 23.09 wieczorem („niech leci do
produktów core”), która zastąpiła wcześniejsze „tylko saas”.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `d9012de` | `7b41eb6` |
| HoofCare | `5262dcc` (rdzeń `d9012de`) | `d5f66e3` (rdzeń `7b41eb6`) |
| MedPlano | `dbb8f42` (rdzeń `d9012de`) | `3a22086` (rdzeń `7b41eb6`) |

## Co się zmieniło

- `GET /api/v1/organizations/current/history/` — od najnowszych, stronicowane
  (do 100 na stronę), filtr rodzaju zmiany, uprawnienie
  `organization.settings.manage`.
- Każdy wpis historii zapisuje kanał (`channel`, `credential_id`) z kontekstu
  żądania: panel, klucz API albo system. Migracja `organizations 0046` dodaje
  dwie kolumny z wartością domyślną; starsze wpisy nie mają kanału.
- „Było → jest” w edycjach: firma, wizytówka, rola, gospodarstwo, zwierzę,
  pozycja magazynu, dane do faktury. Dane osobowe (kontakt osoby, dane
  hodowcy, dane do faktury) — tylko „zmieniono”, bez wartości.
- Ekran na `DataTable` w trybie serwerowym; na telefonie karty. HoofCare nazywa
  swoje akcje (wizyty, raporty) przez slot produktu.
- Tłumaczenia produktu scalają się na każdej głębokości — wcześniej produkt,
  który dodał jedną etykietę w `History.actions`, skasowałby wszystkie z rdzenia.

## Wdrożenie

- Backend po kolei w trzech stackach: kopia bazy (`pg_dump`), migracje
  (`organizations 0046`; w produktach także `sites 0032` z Site Studio),
  `check_database_role`, skaner `CLEAN`, zero zaległych migracji, `/healthz` 200.
- Drugie wydanie tylko frontendu: poprawka szerokości pola filtra (strzałka
  wychodziła poza pole). 25 pozostałych kontenerów produktów bez zmian.
- Obrazy do wycofania: `<projekt>-{backend,frontend}:rollback-history-20260923`,
  `<projekt>-frontend:rollback-history-filter-20260923`.

## Odbiór

- [x] backend rdzenia **941 PASS, 2 SKIP** (po scaleniu z Site Studio);
  HoofCare **980/980**; frontend rdzenia **400** (1 niestabilny test Site
  Studio pod obciążeniem hosta przeszedł osobno 12/12), HoofCare **495** (jeden
  niestabilny test edytora osobno 7/7), MedPlano **403/403**; UI **60/60**;
  lint z `core:check`, `ai:validate`, `ai:eval`; typecheck; mypy (433 pliki);
  Ruff, granice importów, kontrola migracji, zgodność API, prettier;
- [x] zalogowany panel `saas.goldenstar.cloud` (Chromium 1.62.1): zakładka
  „Historia zmian”, zmiana nazwy firmy pokazana jako „Nazwa: stara → nowa” z
  kanałem „Panel”, na 390 px wiersze jako karty, bez poziomego przewijania i
  błędów JS;
- [x] trzy aplikacje: `/panel/settings/history` bez logowania → 307, API → 403;
- [x] konto i organizacja testowa usunięte.

Dowody (prywatne): `.runtime/releases/20260923-history/` i
`.runtime/releases/20260923-history-filter/`.
