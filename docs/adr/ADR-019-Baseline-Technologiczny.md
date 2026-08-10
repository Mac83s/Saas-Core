# ADR-019 — baseline technologiczny

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core  
**Przegląd:** przed W2 oraz przy końcu wsparcia którejkolwiek linii

## Kontekst

Projekt potrzebuje stabilnego, wspieranego zestawu wersji dla lokalnego Windows
+ WSL, kontenerów i produkcji na VPS. Priorytetem jest długa ścieżka poprawek
bezpieczeństwa, zgodność generatora OpenAPI oraz jeden lockfile na ekosystem.

## Decyzja

### Backend

| Obszar | Linia przyjęta na start | Polityka |
| --- | --- | --- |
| Python | `3.14.x` | najnowszy patch; standard CPython, bez free-threaded build |
| Django | `5.2.x LTS` | najnowszy patch, `<5.3`; wsparcie bezpieczeństwa do 2028-04 |
| Django REST Framework | `3.17.x` | start od `3.17.2`, `<3.18` |
| drf-spectacular | `0.30.x` | dokładnie pinowany; schema diff przy aktualizacji |
| Celery | `5.6.x` | najnowszy patch w lockfile |
| PostgreSQL | `18.x` | najnowszy wspierany patch |
| Redis | `8.2.x` | broker/cache; najnowszy patch, bez modułów Redis Stack w Core |

DRF 3.18 nie jest przyjmowany w pierwszym bootstrapie, ponieważ obecna
dokumentacja drf-spectacular deklaruje zgodność do DRF 3.17. Aktualizacja wymaga
zielonego schema diff, testów auth i testów walidacji serializerów.

Zależności Python są zarządzane przez `uv` w `pyproject.toml` i `uv.lock`.
Kontenery instalują wyłącznie zależności z lockfile przez `uv sync --locked`.

### Frontend

| Obszar | Linia przyjęta na start | Polityka |
| --- | --- | --- |
| Node.js | `24.x LTS` | najnowszy patch linii Krypton |
| pnpm | `11.x` | dokładna wersja w `packageManager` |
| Next.js | `16.2.x` | App Router, Turbopack; najnowszy patch |
| React | `19.2.x` | wersja zgodna z wybranym Next.js |
| TypeScript | `5.x` | najwyższa wersja wspierana przez Next.js i narzędzia |
| Tailwind CSS | `4.x` | tokeny przez CSS variables |

Zależności JavaScript są zarządzane przez pnpm workspace i jeden
`pnpm-lock.yaml`. Nie używamy Turborepo na starcie: przy jednej aplikacji
Next.js pnpm filters i jawne skrypty są wystarczające. Dodanie task runnera
wymaga zmierzonego problemu z czasem buildów lub grafem zadań.

### Narzędzia jakości

- Python: Ruff (format + lint), mypy z django-stubs, pytest, pytest-django,
  pytest-xdist i Hypothesis dla krytycznych niezmienników;
- TypeScript: ESLint Flat Config, Prettier, `tsc --noEmit`, Vitest,
  Testing Library i Playwright;
- repozytorium: Docker Compose Specification, skan sekretów, skan zależności i
  obrazów, deterministyczne generowanie OpenAPI.

Dokładne patche zapisuje lockfile w W1. Pliki konfiguracyjne podają dozwolony
zakres minor, a CI blokuje niekontrolowaną zmianę lockfile.

## Konsekwencje

- Django LTS daje dłuższą stabilność niż najnowsze Django 6.1;
- Python 3.14 jest oficjalnie wspierany przez Django 5.2 i DRF 3.17;
- PostgreSQL 18 zapewnia natywne `uuidv7()` i długą ścieżkę rozwoju;
- ograniczenie DRF do 3.17 zmniejsza ryzyko niespójnego OpenAPI;
- brak Turborepo upraszcza bootstrap, lecz może wymagać rewizji przy wielu appkach.

## Alternatywy odrzucone

- Django 6.1 — krótsze wsparcie i brak potrzeby jego nowych funkcji;
- Python 3.13 — stabilny, ale Django rekomenduje najnowszą wspieraną linię;
- npm — pnpm lepiej obsługuje workspace i współdzielony pakiet UI;
- DRF 3.18 od pierwszego dnia — generator schematu nie deklaruje jeszcze wsparcia;
- SQLite w testach — nie odwzorowuje constraintów, RLS i blokad PostgreSQL.

## Źródła

- https://www.djangoproject.com/download/
- https://docs.djangoproject.com/en/5.2/faq/install/
- https://www.django-rest-framework.org/community/release-notes/
- https://drf-spectacular.readthedocs.io/en/latest/changelog.html
- https://nodejs.org/en/about/previous-releases
- https://www.python.org/downloads/
- https://www.postgresql.org/docs/18/release-18.html
- https://pnpm.io/installation
- https://docs.astral.sh/uv/guides/integration/docker/

