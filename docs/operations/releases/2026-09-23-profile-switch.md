# Przełącznik wizytówki, gospodarstwa w katalogu i strona wizytówki — wydanie 2026-09-23

Zakres: decyzja właściciela z 23.09 (ADR-053 §10, zaakceptowany). Wizytówka jest
w każdym planie i dla każdego typu organizacji, któremu produkt da
`shared.profiles`; obecność w katalogu to przełącznik, domyślnie wyłączony;
włączenie i wyłączenie mają własne wpisy historii zmian. HoofCare daje
wizytówkę także gospodarstwom (kategoria „Gospodarstwo rolne”). Przy okazji:
gunicorn trzyma bezczynne połączenie 10 s oraz naprawiona publiczna strona
wizytówki w katalogu, która od 21.09 zawsze odpowiadała 500.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `e0816cb` | `3c8760f` |
| HoofCare | `51f80a6` (rdzeń `e0816cb`, profil z gospodarstwami) | `a0368fe` (rdzeń `3c8760f`) |
| MedPlano | `b4ff9f2` (rdzeń `e0816cb`) | `3b1ffff` (rdzeń `3c8760f`) |

## Wdrożenie

- Backend po kolei w trzech stackach: zatrzymanie zapisujących usług, kopia
  bazy (`pg_dump`), migracja `organizations 0045` (zmiana listy akcji historii,
  bez zmian w danych), start backendu, workera, schedulera i frontendu,
  `check_database_role`, skaner plików `CLEAN`, zero zaległych migracji,
  `/healthz` 200 przez HTTPS. W HoofCare migracja zsynchronizowała role
  systemowe: właściciel i administrator gospodarstwa mają `profiles.manage`.
- Drugie wydanie tylko frontendu (poprawka strony katalogu): trzy obrazy z
  `git archive`, odtworzona wyłącznie usługa `frontend`; 25 pozostałych
  kontenerów produktów bez zmian ID, obrazów i startu.
- Obrazy do wycofania: `<projekt>-{backend,frontend}:rollback-profile-switch-20260923`
  i `<projekt>-frontend:rollback-catalog-page-20260923`.

## Odbiór

- [x] bramki: backend rdzenia **899 PASS, 2 SKIP**; HoofCare **938/938**; frontend
  rdzenia **336/336**, HoofCare **431/431**, MedPlano **339/339**; UI **60/60**;
  lint z `core:check`, `ai:validate`, `ai:eval`; typecheck; Ruff, granice
  importów, kontrola migracji, zgodność API, prettier;
- [x] zalogowany panel `saas.goldenstar.cloud` (Chromium 1.62.1): przełącznik
  domyślnie wyłączony → włączenie → publiczna strona
  `/katalog/<miasto>/<firma>/` 200 z treścią wizytówki → wyłączenie → API
  katalogu 404; telefon 390 px bez poziomego przewijania, bez błędów JS;
- [x] historia zmian w bazie: `profile.published` i `profile.withdrawn` z
  autorem dla każdego przełączenia;
- [x] HoofCare na żywo: typ `farm` składa `shared.profiles`, role
  `owner`/`admin` gospodarstwa mają `profiles.manage`, 2 z 3 gospodarstw mają
  cechę `profiles.enabled` w planie (trzecie nie ma abonamentu);
- [x] konto i organizacja testowa usunięte (`purge_test_tenants`).

## Uwagi

- Fixture odbioru `sites_e2e_fixture` nadaje tylko cechy witryny; kontrolne
  konto dostało `profiles.enabled` ręcznie w bazie na czas testu. Pierwsza
  próba pokazała poprawną odmowę serwera („Plan organizacji nie pozwala na tę
  operację”).
- Strona wizytówki czytała rekord przez klienta API ze względnym adresem, czego
  `fetch` w Node nie rozwiązuje. Katalog był pusty do 23.09, więc błąd nie
  wyszedł wcześniej; czyta teraz backend bezpośrednio, jak strona cennika.

Dowody (prywatne): `.runtime/releases/20260923-profile-switch/` i
`.runtime/releases/20260923-catalog-page/`.
