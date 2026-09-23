# Bogata treść, pełna szerokość i wygląd strony — wydanie 2026-09-23

Zakres: fazy 1–2 planu memex `saas-core-site-studio-rich-content-and-full-width`
(kontrakt: [site-rich-content.md](../../architecture/site-rich-content.md)).
Wdrożono **tylko** `saas.goldenstar.cloud` (decyzja właściciela 1a);
HoofCare i MedPlano pozostają na poprzednim rdzeniu do osobnego `core:update`.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `2b137e5` | `2b137e5` |

## Wdrożenie

- Obrazy zbudowane z `git archive 2b137e5`; wcześniejsze obrazy oznaczone
  `saas-core-{backend,frontend}:rollback-rich-content-20260923`.
- Zatrzymanie zapisujących usług, kopia bazy (`pg_dump`), migracja
  `sites 0032_page_presentation` (dwa odwracalne pola, bez zmian w danych),
  start backendu, workera, schedulera i frontendu — 94 s. `check_database_role`,
  skaner `CLEAN` z backendu i workera, obrazy zgodne z buildem, zero
  zaległych migracji, `/healthz` 200 przez HTTPS.

## Odbiór

- [x] bramki przed wdrożeniem (drzewo po scaleniu `main`): frontend
  **395/395**, renderer **132/132**, kontrakty **33/33**, UI **60/60**;
  backend `test_site_rich_content` **37**, `test_sites_api` **32**,
  `test_site_blueprints` **27**, `test_profiles_catalog` **11**,
  `test_deployment_release` **4** (wcześniej także decoration, connections,
  operations, collections, content operations, proposal review); Ruff, mypy
  (434), granice importów, brak nowych migracji, zgodność API, lint,
  typecheck, prettier;
- [x] zgodność wsteczna: osiem dotychczasowych recept renderuje się bajt w
  bajt jak na `bf1a014`, zrzuty 1440/390/3440 px identyczne co do piksela
  (24/24, Chromium);
- [x] zalogowany panel (Chromium 1.62.1, konto syntetyczne): import recept
  `core.product_first_impression` i `core.expert_knowledge` — wygląd strony
  (pełna szerokość, Manrope) zapisany w wersji, zdjęcie galerii produktu i
  ilustracja w artykule w referencjach mediów, 5 kopert sekcji; publikacja;
  płótno z klasą pełnej szerokości i fontu, panel „Wygląd tej strony” z
  wartością z recepty; telefon 390 px bez poziomego przewijania; zero błędów JS;
- [x] strona publiczna przez Caddy z hostem witryny: `/` 200 (pełna
  szerokość, prezentacja produktu, ciemna sekcja), `/poradnik` 200 (rozdziały
  ze spisem, nagłówki Lora, ilustracje, cytat, uwagi, 6 unikalnych kotwic
  H2), oba zdjęcia 200 `image/png`, sitemap z obiema stronami;
- [x] konto, organizacja i 2 obiekty magazynu testu usunięte
  (`purge_test_tenants` + pokwitowanie usunięcia).

## Uwagi

- Pierwsza próba importu zakończyła się 500: skaner ClamAV nie odpowiedział w
  30 s na zdjęcie 2,2 MB przy obciążeniu hosta ~30. Ponowienie z tym samym
  kluczem idempotencji przeszło. Błąd niedostępności skanera trafia do
  użytkownika jako 500 zamiast odpowiedzi „spróbuj ponownie” — do poprawy
  osobno (niezależne od tego wydania).
- Publiczne zdjęcia są serwowane jako oryginały PNG (2–2,4 MB), bez wariantów
  responsywnych — wymaganie wydajności planu (LCP) pozostaje otwarte.
- Sprawdzenie strony publicznej wykonano `curl` przez port Caddy z nagłówkiem
  hosta; skrypt uruchamiający Pythona w kontenerze zablokował filtr uprawnień.
  Nie potwierdza to certyfikatu On-Demand dla subdomeny witryny.

Dowody (prywatne): `.runtime/releases/20260923-rich-content/`.
