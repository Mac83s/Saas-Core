# Generator obrazów AI (ADR-059) — wydanie 2026-09-24

Zakres: paczki IG-0, IG-1 i IG-2 z planu memex
`saas-core-site-studio-rich-content-and-full-width` (decyzja
`generator-obrazo-w-openai-gpt-image-2-5-bezpos-r`,
[ADR-059](../../adr/ADR-059-Generowanie-Obrazow-AI-i-Pochodzenie-Mediow.md),
runbook [image-generation.md](../image-generation.md)). Wdrożono **tylko**
`saas.goldenstar.cloud`, **bez klucza OpenAI** — generowanie dla klientów
jest niedostępne (`offer.available=false`) do czasu klucza i uruchomienia
`worker-ai` (profil compose `image-generation`). Wdrożone na decyzję
właściciela („na moją odpowiedzialność”) przy pełnym swapie hosta.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `a315812` | `184b1e9` (bez zmian frontu od `184b1e9`) |

## Wdrożenie

- `184b1e9` (269 s): migracje `media 0008` (ai_origin; zdjęcia szablonów
  oznaczone jako AI), `image_generation 0001–0004` (tabela z RLS, oferta:
  funkcja we wszystkich planach, 2 kredyty, limit prób profile 50 / starter
  200 / pro 1000, uprawnienia ról), `sites 0034` (przełącznik odznaki).
  Przed wdrożeniem pusty plik sekretu `image_generation_openai_api_key`
  (0644) na saas, w HoofCare i w MedPlano (bez niego compose nie tworzy
  backendu).
- Abonament przeniesiony na nową wersję planu (spis → próba z wycofaniem →
  zastosowanie → weryfikacja): 1 organizacja, starter v6 → v8, dodane
  `image_generation.enabled` i `image_generation.monthly` = 200; cena, stan i
  terminy bez zmian; wpis `billing.reconciled`.
- `a315812` (213 s, tylko backend): poprawka z odbioru — lista mediów nie
  wysyłała `ai_origin`.

## Odbiór

- [x] bramki na gałęzi po scaleniu `main`: testy generatora (worker 20, API
  20, RLS 5), `media_ai_origin` 6, `sites_ai_badge` 6, sloty dowodowe 7,
  tenant context 16, kompozycja wdrożeń 25; ruff, mypy, migracje,
  importy, `api:check`, `deployment:check:all`, tsc, vitest dialogu 18;
- [x] na żywo, konto syntetyczne: oferta `available=false`, koszt 2,
  proporcje 16:9 / 4:3 / 3:2, `badge_visible=true`; import recepty premium
  zapisuje zdjęcie z `ai_origin=generated`; strona publiczna przez Caddy z
  hostem witryny ma odznakę `.site-ai-badge` i alt „… — obraz wygenerowany
  przez AI”; plik `/media/<id>` (200) zawiera XMP `trainedAlgorithmicMedia`;
  zero błędów JS; usunięcie organizacji skasowało 4 obiekty (w tym zachowany
  oryginał), 0 oczekujących;
- [ ] przełącznik operatora `set_ai_badge --off/--on`: jedyne konto
  operatora nie ma potwierdzonego MFA, więc komenda poprawnie odmawia; test
  wyłączenia czeka na włączenie MFA na koncie administratora;
- [ ] generowanie obrazu — czeka na klucz, Tier ≥ 2, limit wydatków i pilot
  SynthID (follow-up memex `goldentrdcom-20260924-28`).

## Znalezione przy odbiorze i poprawione

- Lista mediów (`GET /api/v1/media/`) składała odpowiedź ręcznie i pomijała
  `ai_origin`, choć deklarowały go serializer i OpenAPI, a panel na nim
  filtrował — wybór mediów traktował obrazy AI jak prawdziwe zdjęcia (także w
  slotach tylko na prawdziwe zdjęcia; serwer i tak odrzucał zapis).
  Poprawka `a315812` z testem.

## Uwagi

- HoofCare i MedPlano: mają już pusty plik sekretu; reszta kroków po
  `core:update` — follow-up `goldentrdcom-20260924-29`.
- Przegląd prawnika (szkic ToS/AUP/DPA w memeksie, gałąź
  `proposals/saas-core-image-generation-plan`) przed udostępnieniem klientom.

Dowody (prywatne): `.runtime/releases/20260924-image-generation/`.
