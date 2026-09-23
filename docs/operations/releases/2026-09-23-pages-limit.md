# Limit podstron na stronę (`pages.max`) — wydanie 2026-09-23

Zakres: faza 4 planu memex
`saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`. Decyzja
właściciela z 23.09: limit z ADR-032 jest egzekwowany, liczby tymczasowe —
**Profil 5, Witryna 15, Pro 50** podstron na jednej stronie. Tym samym `core:update`
produkty dostały nowe układy redakcyjne Site Studio (raport
`2026-09-23-conversion-layouts.md`).

| Aplikacja | Kod (backend i frontend) |
| --- | --- |
| Saas-Core / vps-dev | `e239f40` |
| HoofCare | `b2f8fe1` (rdzeń `e239f40`) |
| MedPlano | `9a45645` (rdzeń `e239f40`) |

## Co się zmieniło

- `billing 0024`: definicja limitu `pages.max` i nowe wersje planów profile,
  starter, pro z limitem (wersje planów są niezmienne; ceny, cechy, pozostałe
  limity i okresy próbne bez zmian). Plany gospodarstw bez zmian — nie mają stron.
- `create_page` (jedyne miejsce tworzenia podstron, także z kreatorów) odmawia
  podstrony ponad limit: 409 `page_limit_reached`. Istniejące podstrony zostają.
  Migawka bez `pages.max` (starsza wersja planu, konto testowe) nie ma limitu.
- Edytor pokazuje: „Plan nie pozwala na więcej podstron na tej stronie. Usuń
  nieużywaną podstronę albo wybierz wyższy plan.” (PL/EN).
- Możliwości treści dla integracji raportują `pages.max`.

## Wdrożenie

- Trzy stacki po kolei: kopia bazy, migracje (w tym `billing 0024`; ceny symulatora
  dla nowych wersji ustawia usługa `migrate`), `check_database_role`, skaner
  `CLEAN`, zero zaległych migracji, `/healthz` 200.
- Istniejące abonamenty przeniesione na nowe wersje planów (spis → próba z
  wycofaniem → zastosowanie), jak 21.09: Saas-Core 1 (Witryna v4 → v5, limit 15),
  HoofCare 2 (Profil v7 → v8, limit 5), MedPlano 0. Stan, terminy i ceny bez
  zmian; wpis `billing.reconciled` w historii każdej organizacji.
- Żadna istniejąca strona nie przekracza limitu (najwięcej 2 podstrony).
- Obrazy do wycofania: `<projekt>-{backend,frontend}:rollback-pages-limit-20260923`.

## Odbiór

- [x] backend rdzenia **945 PASS, 2 SKIP** (w tym testy limitu i planów);
  HoofCare **984/984**; frontend rdzenia **404** (1 niestabilny test Site Studio
  pod obciążeniem przeszedł osobno), HoofCare **499** (2 niestabilne testy Site
  Studio osobno 39/39), MedPlano **407/407**; lint, typecheck, mypy, zgodność
  API, prettier;
- [x] na żywo `saas.goldenstar.cloud` (konto testowe z limitem 1): pierwsza
  podstrona 201, druga 409 `page_limit_reached`, w edytorze komunikat, formularz
  zachowuje wpisane dane; konto usunięte;
- [x] plany na żywo: pro 50, profile 5, starter 15.

Uwaga: treść błędu API („Plan pozwala na N podstron…”) ma poprawną odmianę dla
5, 15 i 50; dla limitów 1–4 brzmiałaby niegramatycznie — do wygładzenia przy
następnej zmianie backendu, jeśli pojawią się takie plany.

Dowody (prywatne): `.runtime/releases/20260923-pages-limit/`.
