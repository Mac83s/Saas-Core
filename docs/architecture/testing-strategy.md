# Strategia jakości i bezpieczeństwa

## 1. Poziomy testów

| Poziom | Odpowiedzialność | Narzędzia |
| --- | --- | --- |
| unit | reguły domenowe, parsery, komponenty UI | pytest, Vitest, Testing Library |
| integration | PostgreSQL, Redis, sesja, RLS, Celery eager | pytest-django |
| contract | OpenAPI, manifesty, zdarzenia, granice modułów | drf-spectacular, schema diff, import-linter, ESLint |
| end-to-end | krytyczne ścieżki w przeglądarce | Playwright |
| smoke | health, migracje, login, odczyt profilu po deployu | skrypt uruchamiany na stagingu |

Test jednostkowy nie zastępuje integracyjnego testu izolacji tenantów ani
rzeczywistej bazy PostgreSQL. SQLite nie jest wspieranym backendem testowym.

## 2. Obowiązkowa macierz autoryzacji

Każdy chroniony use case pokrywa co najmniej:

| Tenant | Permission | Entitlement | Wynik |
| --- | --- | --- | --- |
| właściwy | jest | jest | sukces |
| właściwy | brak | jest | `403 permission_denied` |
| właściwy | jest | brak | `403 entitlement_required` |
| obcy | dowolny | dowolny | `404` lub pusty zbiór |
| brak kontekstu | dowolny | dowolny | kontrolowany błąd, zero zapytań domenowych |
| zawieszony | jest | jest | blokada zgodna z polityką operacji |

Mutacje sprawdzają również CSRF, idempotency key, optimistic lock i wpis audytu.
Dla tabel z RLS macierz jest wykonywana raz przez ORM i raz przez bezpośrednie
SQL na roli aplikacyjnej.

## 3. Bramka pull requestu

PR nie może zostać połączony, dopóki nie przejdą:

1. formatowanie, lint i typecheck Python/TypeScript;
2. unit oraz integration z PostgreSQL i Redis;
3. test granic modułów i profili deploymentu;
4. generacja OpenAPI bez driftu i kontrola zmian łamiących;
5. `makemigrations --check --dry-run` oraz test migracji od pustej bazy;
6. test builda profilu `core-only` i głównego profilu z `product.json`;
7. testy komponentów UI, axe i krytyczne scenariusze klawiatury;
8. wybrany zestaw Playwright dla zmienionego obszaru.

Pełny E2E, backup/restore i skany obrazu mogą działać cyklicznie, ale wynik
blokuje wydanie.

## 4. Testy shadcn/ui

Komponenty w `packages/ui/components/ui` są własnym kodem produktu, lecz zachowują
semantykę i kontrakty shadcn/Base UI. Dla `Select`, `Combobox`, `Autocomplete`,
`Dialog`, `Popover` i menu testujemy:

- rolę, accessible name, opis oraz komunikat błędu;
- Tab, Shift+Tab, Enter, Escape i klawisze strzałek;
- focus po otwarciu i jego powrót po zamknięciu;
- wyszukiwanie, pusty wynik, loading, disabled i wartości z długą etykietą;
- integrację z React Hook Form oraz błąd z Problem Details;
- działanie w polskim i angielskim locale oraz przy powiększeniu 200%.

`Select` nie zastępuje natywnego pola bez uzasadnienia. `Combobox` jest wymagany
dla dużych lub filtrowalnych zbiorów, a `Autocomplete` dla wartości dopuszczającej
własny tekst. Reguły szczegółowe są w ADR-020.

## 5. Dane, logi i review bezpieczeństwa

Seedy używają wyłącznie danych syntetycznych i deterministycznych UUID. Fixture
nie może zawierać kopii danych produkcyjnych. Logi strukturalne dopuszczają
identyfikatory techniczne i `correlation_id`, ale maskują cookie, tokeny, hasła,
dane płatnicze, medyczne i treść wiadomości.

Review bezpieczeństwa wymaga sprawdzenia: scope tenanta, permissionu,
entitlementu, walidacji wejścia, danych w logach, SSRF/uploadu, CSRF/CORS,
idempotencji, audytu oraz migracji i rollbacku. Każdy wyjątek ma właściciela,
termin i zapis ryzyka.
