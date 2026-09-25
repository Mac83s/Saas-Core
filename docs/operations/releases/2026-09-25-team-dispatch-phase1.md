# Zespół i przydział wizyt, faza 1 (ADR-058) — wydanie 2026-09-25

Zakres: faza 1 planu memex `saas-core-zespol-pracownicy-i-przydzial-wizyt`
([ADR-058](../../adr/ADR-058-Zespoly-Przydzial-i-Dobor-Osob-w-Rezerwacjach.md)),
bez widocznych zmian w panelu poza formularzem publicznym. Decyzje
właściciela z 24.09: rezerwacja bez wyboru osoby potwierdza się od razu, a
osobę dobiera system; klient nie widzi danych pracowników. Wdrożono
**tylko** `saas.goldenstar.cloud`; HoofCare i MedPlano dostaną zmianę przez
`core:update`.

| Aplikacja | Backend, worker, scheduler i frontend |
| --- | --- |
| Saas-Core / vps-dev | `3e0f71b` |
| HoofCare | `df5ecfd` (rdzeń `a1fb1ea`) |
| MedPlano | `d9a71e0` (rdzeń `a1fb1ea`) — scalone, **niewdrożone** |

Produkty stoją na `a1fb1ea`: faza 1 plus poprawki testów pod profil produktu,
bez partii magazynu (`8fd0882`, inna sesja) i bez poprawki lintu okna
generatora obrazów (`08f5a01`) — obie wejdą z następnym `core:update`.

## Co się zmieniło

- **Przypomnienia** należą do organizacji, nie do osoby, która umówiła
  wizytę: kontrakt zadania podpisany jako usługa (`booking_reminder`), bez
  wygasania po `TENANT_TASK_CONTEXT_TTL_SECONDS`. Przełożenie wizyty uzbraja
  przypomnienie na nowy termin. Trasa, której nie da się otworzyć, jest
  logowana i zdejmowana z kolejki, zamiast blokować jej czoło.
- **Terminy** liczą się w trzech częściach: dni (bez globalnego limitu),
  godziny jednego dnia, walidacja konkretnego startu. Limit 250 wyników nie
  ucina już dnia w połowie i nie odrzuca wolnego terminu przy zapisie.
- **Dobór osoby robi serwer**, gdy nikt jej nie wskazał: najmniej minut
  zajętości tego dnia, potem tygodnia, potem id; przegrany wyścig o jedną
  osobę próbuje następnej. Wcześniej wizytę dostawała zawsze najdawniej
  dodana osoba, a wybierała ją przeglądarka.
- **Zakończenie wizyty** skraca zajętość osób i zasobu do faktycznego końca.
- **Lista wizyt** w API przyjmuje `from`, `to` i `staff_id`.
- **Klient** nie dostaje `staff_id`, nazwiska ani członkostwa pracownika — ani
  w odpowiedzi rezerwacji, ani w samoobsłudze, ani w katalogu i terminach.
  Formularz publiczny wybiera dzień, potem godzinę (w strefie firmy, ze
  strefą w etykiecie) i rezerwuje w języku strony.

## Wdrożenie

- Obrazy budowane po jednym, dopiero przy ≥ 3,5 GB wolnej pamięci i z
  przerwaniem poniżej 700 MB (host miał pełny swap, a 24.09 baza GoldenStara
  dwa razy dostała OOM przy równoległych buildach): backend 232 s (minimum
  wolnej pamięci 1660 MB), frontend 297 s (minimum 842 MB).
- `deploy.py` (199 s): kopia bazy, **zero migracji**, `check_database_role`,
  skaner `CLEAN` na backendzie i workerze, zero zaległych migracji,
  `/healthz` 200. Wszystkie migracje w obrazie odwracalne.
- Obrazy do wycofania: `saas-core-{backend,frontend}:rollback-team-dispatch-20260925`.
  Backend i frontend wracają **razem**: stary formularz publiczny nie działa
  z nowym API terminów.

## Odbiór

- [x] bramki na gałęzi (24.09, po scaleniu `main`): backend **1052 passed,
  2 skipped**; ruff, import-linter (1 kontrakt), brak zmian migracji, mypy
  446 plików; `api:check`; typecheck i lint całego workspace (w tym
  `ai:validate`); prettier; vitest frontendu **62 pliki, 543 testy**;
- [x] po drugim scaleniu `main` (25.09, 16 commitów generatora obrazów AI):
  testy rezerwacji, przypomnień, terminów, kontekstu organizacji i usuwania
  organizacji **85 passed**; tsc frontendu; ruff; `api:check`;
- [x] na żywo `saas.goldenstar.cloud`, konto syntetyczne, dwie osoby z tą
  samą usługą 30 min w sobotę 08:00–18:00:
  - katalog publiczny bez kluczy pracowników, strefa `Europe/Warsaw`;
  - dni: `2026-09-26`, `2026-10-03`; godziny soboty **115 z 115 unikalnych**,
    tylko `starts_at` i `ends_at`;
  - formularz w przeglądarce 390 px: Usługa → Lokalizacja → Pokaż terminy →
    Dzień → „08:00 CEST” → „Rezerwacja potwierdzona”, zero błędów strony;
  - trzech klientów na 10:00: pierwsza wizyta do osoby bez porannej wizyty,
    druga do drugiej osoby, trzecia **409**;
  - odpowiedź rezerwacji i samoobsługa bez kluczy pracowników;
  - lista wizyt z oknem: 3 w dniu, 0 w następnym; filtr `staff_id` działa;
  - po „zakończeniu” pierwszej wizyty 10:00 ta sama osoba dostaje kolejną
    rezerwację na 10:00 — zajętość została skrócona;
  - konto i organizacja usunięte (`purge_test_tenants`).

## Znalezione przy odbiorze

- Usunięcie organizacji zostawia wiersze tabel routingu rezerwacji
  (`booking_publicbookingroute`, `booking_selfserviceroute`,
  `booking_reminderroute`): mają `organization_id` jako zwykłe pole, nie klucz
  obcy, więc `erasure.py` ich nie odkrywa. Na saas po dotychczasowych kontach
  testowych: 9 / 14 / 14 osieroconych wierszy (same identyfikatory, bez
  danych osobowych). Skutek praktyczny: nowa organizacja z tym samym `slug`
  dostałaby publiczną trasę starej. Przypomnienia osieroconych tras są od tego
  wydania odrzucane i nie blokują kolejki. Poprawka `fc9c08b`: moduły
  rejestrują takie tabele (`register_erasure_rows`), a usunięcie organizacji
  je liczy, kasuje i sprawdza w dowodzie kompletności; to samo dotyczy tras
  powiadomień (wiadomości dostawcy, klucze API). Wchodzi z następnym
  wdrożeniem; istniejące sieroty na instancjach deweloperskich zostają
  (losowe slugi kont testowych, bez danych osobowych).

## Produkty (25.09)

- [x] HoofCare: backend **1122 passed** (7 testów generatora obrazów AI
  padało na kolekcji i poleceniu spoza profilu — poprawione w rdzeniu
  `3fe2f7a`, `a1fb1ea`), tsc, `core:check`, `deployment:check:all`,
  `ai:validate`, `ai:eval`, prettier, vitest **682** (2 testy stron
  niestabilne pod obciążeniem, osobno zielone); ESLint: 2 błędy w
  `generate-image-dialog.tsx` z rdzenia (naprawione w `08f5a01`);
- [x] HoofCare wdrożony: obrazy po jednym przez strażnika pamięci
  (backend 244 s, frontend 220 s), migracje zakończone kodem 0, ale Docker
  ~10 min usuwał kontener `migrate` (`--rm`), a skrypt czekał z zatrzymanym
  backendem — **~11 min przestoju**; usługi uruchomione ręcznie na nowych
  obrazach, dalej kontrole jak w `deploy.py`: rola bazy, skaner `CLEAN`, zero
  zaległych migracji, wszystkie odwracalne, `/healthz` 200. Kopia
  `deploy.py` już nie używa `--rm`;
- [x] HoofCare na żywo, ten sam odbiór co na saas: wyniki identyczne, konto
  usunięte;
- [x] MedPlano: backend **1053 passed, 28 skipped**, tsc, vitest **575**,
  prettier; ESLint jak w HoofCare; scalone do `main`, **niewdrożone**.

Dowody (prywatne): `.runtime/releases/20260925-team-dispatch/`.
