# Wspólna lista panelu (DataTable) — wydanie 2026-09-23

Zakres: tylko frontend trzech aplikacji. Nowy komponent `DataTable` z ADR-054
i jego pierwsze użycie na liście zespołu. Backend, migracje, profile i
uprawnienia bez zmian.

| Aplikacja | Kod | Obraz frontendu |
| --- | --- | --- |
| Saas-Core / vps-dev | `7e6b784` | `saas-core-frontend:data-table-7e6b7845f5f5` |
| HoofCare | `66d12f3` (rdzeń `7e6b784`) | `hoofcare-frontend:data-table-66d12f30c737` |
| MedPlano | `f708b76` (rdzeń `7e6b784`) | `medplano-frontend:data-table-f708b76860f0` |

Obrazy zbudowano z dokładnego `git archive` każdego commita, po kolei (load
hosta 17–37 od obciążenia GoldenStar). Odtworzono wyłącznie usługę `frontend`
(`--no-deps --no-build`); każda odpowiedziała 200 na `/healthz` przez HTTPS, bez
zaległych migracji. Pozostałe **25** kontenerów produktów zachowało ID, obrazy i
czasy startu. Poprzednie obrazy: `<projekt>-frontend:rollback-data-table-20260923`.

## Odbiór

- [x] bramki przed wydaniem: UI **60/60**, frontend Saas-Core **335/335**,
  HoofCare **430/430**, MedPlano **338/338**; lint (z `core:check`,
  `ai:validate`, `ai:eval`), typecheck i prettier we wszystkich trzech;
- [x] zalogowana lista zespołu na `saas.goldenstar.cloud` (Chromium, Playwright
  1.62.1): sortowanie „Osoba” z `aria-sort`, na 1440 px wiersz tabeli, na 390 px
  karta z ramką, nagłówek ukryty wizualnie, rola `table` zachowana, brak
  poziomego przewijania i błędów JS;
- [x] konto i organizacja testowa usunięte (`purge_test_tenants`).

## Uwagi

- Pierwsze wejście na `/login` zwróciło 500: serwerowy `fetch` frontendu do
  backendu dostał `UND_ERR_SOCKET: other side closed`; ponowienie przeszło.
  Hipoteza: gunicorn (`gthread`) zamyka bezczynne połączenie po domyślnych 2 s,
  a klient `fetch` w Node trzyma je do 4 s i czasem wysyła na zamknięte. Do
  naprawy w następnym wydaniu backendu (`--keep-alive` powyżej 4 s) — plan
  memex `saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`.
- Karta „Konta pracowników kalendarza” pokazuje „Nie udało się wczytać” dla
  organizacji bez rezerwacji w planie (API odpowiada 403). Zachowanie sprzed
  tego wydania, osobna poprawka.

Dowody (prywatne): `/root/Saas-Core/.runtime/releases/20260923-data-table/`.
