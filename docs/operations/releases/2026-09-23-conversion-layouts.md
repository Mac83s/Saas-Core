# Układy redakcyjne pod konwersję (faza 3a) — wydanie 2026-09-23

Zakres: faza 3a planu memex `saas-core-site-studio-rich-content-and-full-width`
(kontrakt: [site-rich-content.md](../../architecture/site-rich-content.md),
lista kontrolna: [site-section-catalog.md](../../architecture/site-section-catalog.md)).
`core.rich_text` v3, 16 nowych układów (razem 20 redakcyjnych), katalog v6
(120 recept) z metadanymi konwersji, ostrzeżenie o miejscach `[Uzupełnij: …]`
w edytorze. Wdrożono **tylko** `saas.goldenstar.cloud`; HoofCare i MedPlano
dostaną to przez `core:update`.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `e0b9566` | `e0b9566` |

## Wdrożenie

- Obrazy z `git archive e0b9566`; poprzednie jako
  `saas-core-{backend,frontend}:rollback-conversion-layouts-20260923`.
- Kopia bazy przed startem, brak nowych migracji (nowe są tylko pliki
  kontraktów), start czterech usług — 112 s, `check_database_role`, skaner
  `CLEAN`, obrazy zgodne z buildem, zero zaległych migracji, `/healthz` 200.

## Odbiór

- [x] bramki na drzewie po scaleniu `main`: frontend **403/403**, renderer
  **175/175**, kontrakty **33/33**, UI **60/60**, backend
  `test_site_rich_content` **39**, `test_sites_api` **32** (wcześniej także
  blueprints 27, content operations 8), Ruff, mypy (436), brak nowych migracji,
  zgodność API, lint, typecheck, prettier;
- [x] przegląd wizualny 20 układów z seedów katalogu (Chromium 1440/390/320,
  bez poziomego przewijania, bez błędów JS) — strona przeglądu dla właściciela;
- [x] zalogowany panel na koncie syntetycznym: zapis 5 sekcji v3 z seedów
  (lead_statement, side_photo z zdjęciem z katalogu, problem_solution,
  expert_note, howto), zdjęcie w referencjach, publikacja; edytor pokazuje
  ostrzeżenie o miejscach do uzupełnienia i wszystkie układy; telefon 390 px
  bez poziomego przewijania; zero błędów JS;
- [x] strona publiczna przez Caddy z hostem witryny: 200, pięć układów,
  rzędy przycisków, etykiety, zdjęcie 200 `image/png`;
- [x] konto, organizacja i 1 obiekt magazynu testu usunięte.

## Uwagi

- Miejsca `[Uzupełnij: …]` publikują się, jeśli właściciel ich nie zastąpi —
  edytor tylko ostrzega (decyzja: wskazówka, nie blokada).
- Zdjęcia nadal jako oryginały PNG bez wariantów responsywnych.

Dowody (prywatne): `.runtime/releases/20260923-conversion-layouts/`.
