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
