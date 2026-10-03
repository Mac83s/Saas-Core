# Evale tłumaczeń AI (ADR-069 pkt 29, TL7)

Raporty `translation_eval` dla kandydatów na model zadania `translation.text`.
Model domyślny wybiera właściciel na liczbach z tych raportów; evale powtarzamy
przy każdej zmianie modelu albo promptu.

```bash
docker exec saas-core-backend-1 python manage.py translation_eval \
  --model <model z macierzy portu, po próbie na żywo> \
  --judge-model <model innej rodziny> --max-usd 5
docker cp saas-core-backend-1:/app/docs/evals/translation/. docs/evals/translation/
```

Raport powstaje w kontenerze (katalog `docs` nie wchodzi do obrazu); kopia z
`docker cp` trafia do repozytorium razem z decyzją o modelu.

- Zestawy (`apps/backend/src/saas_core/modules/shared/translation/evals/pl.json`,
  `en.json`) są syntetyczne — nigdy treść klientów: marketing, rich text z
  żetonami, kontakty (maski), imiona i adresy, glosariusz, tytuły i opisy SEO,
  ładunki prompt injection oraz próbki z dziedzin HoofCare i MedPlano.
- Pary: pl→en, pl→de, pl→es, pl→ru, en→pl. Wywołania mają cel `eval`: płaci budżet
  wdrożenia, żadna firma, a model musi mieć potwierdzoną próbę w macierzy.
- W raporcie per para: odsetek przejść kontroli twardej (`hard_pass_rate`), błędy
  twarde z kodami, wprowadzone linki i kontakty (`contacts_introduced` — przy
  ładunkach injection ma być 0), flagi miękkie, odsetek odmów (`refusal_rate` —
  kryterium wyboru na próbkach HoofCare i MedPlano), średnia sędziego 1–5, koszt na
  1000 znaków źródła, p95 czasu wywołania, rozbicie na kategorie.
- `--max-usd` zatrzymuje przebieg, nie raport (`stopped_by_budget`).

## Przebieg 2026-10-02/03 (prompt `translation.v1`)

Próba na żywo czterech kandydatów (`docs/evals/model-port/`, USD 0,0065): każdy
potwierdził to, co deklaruje macierz — zwykła odpowiedź, schemat JSON, narzędzia;
wymuszone narzędzie tylko Haiku 4.5 i Gemini 3.8 Flash (Opus i Sonnet 5.5 go nie
przyjmują i port odmawia przed wywołaniem). Wiersze dostały `probed`.

Evale: 5 par × 44–46 segmentów, jedno wywołanie na parę. Sędzia z innej rodziny:
Gemini 3.8 Flash ocenia modele Claude, Sonnet 5.5 ocenia Gemini — średnia Gemini
nie jest więc wprost porównywalna z resztą. Wydano łącznie USD 1,16 (koszt podany
przez dostawcę, telemetria `model_port_usageentry`).

| Model | Kontrola twarda | Odmowy | Wprowadzone kontakty | Sędzia (1–5) | USD / 1000 znaków | p95 wywołania |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Opus 5.5 | 100% | 0 | 0 | 4,91–4,98 | 0,016–0,021 | 14,5–22,1 s |
| Claude Sonnet 5.5 | 100% | 0 | 0 | 4,85–4,94 | 0,008–0,010 | 11,1–14,7 s |
| Claude Haiku 4.5 | 99,6% (1 brak żetonu, pl→de) | 0 | 0 | 4,48–4,76 | 0,0034–0,0042 | 14,9–19,4 s |
| Gemini 3.8 Flash | 100% | 0 | 0 | 4,46–4,70 (sędzia Sonnet) | 0,0027–0,0032 | 10,5–13,1 s |

- Ładunki prompt injection przetłumaczono dosłownie we wszystkich modelach; flagi
  miękkie `source_leftovers` padają tylko na nich (cytowane polecenia zostają).
- Odmów na próbkach HoofCare i MedPlano: zero u wszystkich.
- Rekomendacja dla `translation.text`: Claude Sonnet 5.5 — jakość prawie jak Opus
  przy połowie ceny i najkrótszym czasie wśród modeli Claude; tańsza alternatywa
  Gemini 3.8 Flash (ok. 1/3 kosztu Sonneta, bez błędów twardych, niższa ocena).
  Wybór właściciela (odpowiedź 53, 03.10): Claude Sonnet 5.5 jako model domyślny
  `translation.text`; cena `translation.characters` X = 1 kredyt za 1000 znaków źródła
  w jednym języku (odpowiedź 54a). Oba mają być zmienialne w panelu administratora
  platformy (TL22); do tego czasu model w rejestrze zadań, cena w migracji
  `translation 0015`.
