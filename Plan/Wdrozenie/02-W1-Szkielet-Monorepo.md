# W1 — szkielet monorepo

**Status:** complete  
**Szacunek:** 1 tydzień  
**Poprzednik:** W0  
**Rezultat:** uruchamialny szkielet aplikacji i automatyczne bramki jakości

## 1. Scenariusz demonstracyjny

Nowy programista klonuje repozytorium, uruchamia jedną udokumentowaną komendę i
otrzymuje frontend, API oraz zależności lokalne. Endpoint `/api/v1/health/`
odpowiada, frontend pokazuje stan API, a CI odtwarza te same kontrole.

## 2. Pakiety pracy

### W1.1 — repozytorium i narzędzia

- utworzyć strukturę zatwierdzoną w W0;
- dodać `.editorconfig`, reguły końców linii i wspólne komendy developerskie;
- skonfigurować workspace JavaScript i środowisko Python;
- dodać pre-commit albo równoważną komendę zbiorczą bez ukrytych modyfikacji;
- udokumentować wymagania Windows + WSL oraz Docker Desktop.

### W1.2 — backend

- utworzyć projekt Django i ustawienia podzielone na base/local/test/staging;
- utworzyć katalog modułów bez modeli domenowych przed zakończeniem W0;
- dodać DRF, generowanie OpenAPI, endpoint health i correlation ID;
- skonfigurować PostgreSQL, Redis i Celery na poziomie połączeń;
- dodać test startu Django i test health endpointu.

### W1.3 — frontend

- utworzyć aplikację Next.js z TypeScript i Tailwind;
- dodać layout panelu, stronę health oraz obsługę konfiguracji deploymentu;
- przygotować miejsce na generowany klient API, bez ręcznie pisanych duplikatów;
- skonfigurować lint, typecheck i test komponentu bazowego;
- dodać bezpieczny mechanizm publicznej konfiguracji bez sekretów.

### W1.4 — pakiety i kontrakty wspólne

- utworzyć pakiety UI, site-blocks i contracts zgodnie z W0;
- dodać minimalny manifest modułu i walidację zależności;
- przygotować profil `medplano` oraz profil testowy `core-only`;
- dodać test odrzucający niepoprawny profil;
- ustalić zasady wersjonowania pakietów wewnętrznych.

### W1.5 — CI i dokumentacja

- uruchamiać format-check, lint, typecheck, testy i build obu aplikacji;
- sprawdzać migracje Django i drift wygenerowanego klienta OpenAPI;
- dodać skan sekretów i zależności jako osobne, czytelne kroki;
- opisać komendy bootstrap, test, build i reset danych lokalnych;
- dodać szablon zmiany zawierający migracje, bezpieczeństwo i rollback.

## 3. Artefakty

- kompilowalne aplikacje backend i frontend;
- minimalne pakiety wspólne i dwa profile deploymentu;
- pierwsza specyfikacja OpenAPI i generowany klient;
- pipeline CI;
- dokumentacja lokalnego developmentu;
- diagram struktury repozytorium zgodny ze stanem rzeczywistym.

## 4. Testy obowiązkowe

- test importów i kierunków zależności modułów;
- test walidacji profilu deploymentu;
- test health API z bazą i bez bazy;
- test generowania OpenAPI oraz brak driftu klienta;
- build produkcyjny Django i Next.js;
- czysty bootstrap w nowym katalogu roboczym.

## 5. Bramka wyjścia

- [x] bootstrap działa na udokumentowanym środowisku Windows + WSL;
- [x] frontend komunikuje się z `/api/v1/health/` przez generowany klient;
- [x] oba profile deploymentu przechodzą walidację i build;
- [x] CI odtwarza wszystkie lokalne komendy jakości;
- [x] repozytorium nie zawiera sekretów ani przykładowych prawdziwych danych;
- [x] struktura jest gotowa na customowy model `User` w pierwszej migracji W3.

## 6. Stan wykonania — 2026-08-10

W1 jest ukończone. Aplikacja Django, aplikacja Next.js, wspólny pakiet
shadcn/ui, profile `core-only` i `medplano`, kontrakty modułów, OpenAPI,
generowany klient, testy i pipeline CI tworzą uruchamialny szkielet monorepo.

Dowody bramki:

- `pnpm bootstrap --profile core-only` wykonany pod Node.js 24.19.0 i pnpm 11;
- PostgreSQL 18 i Redis 8.2 uruchomione w Docker Desktop z integracją WSL;
- migracje wykonane od pustego wolumenu PostgreSQL;
- `/api/v1/health/` zwrócił `200` oraz `database: ok`, `cache: ok`;
- testy backendu przeszły `4/4` na prawdziwym PostgreSQL i Redis;
- pełne `pnpm quality` zakończyło się poprawnie, wraz z buildem Next.js,
  kontrolą granic importów, mypy oraz brakiem driftu OpenAPI.

Podczas odbioru dostosowano punkt montowania wolumenu do kontraktu obrazu
PostgreSQL 18 (`/var/lib/postgresql`) oraz ustawiono `pytest --capture=sys`, aby
test runner działał stabilnie na repozytorium montowanym z Windows pod WSL.
