# OpenAPI

`v1.yaml` jest generowany z backendu komendą `pnpm api:schema`. Nie edytuj
schematu ręcznie; CI porównuje go z aktualnym kodem DRF.

## Podłoga jakości (ADR-076 §7)

`pnpm api:check` po kontroli dryfu uruchamia `pnpm api:quality`
(`apps/backend/tests/test_openapi_quality.py`). Każda nowa i każda zmieniona
operacja ma:

- jawne `operationId` w snake_case (nie automatyczne `api_v1_…` drf-spectacular);
- `summary` i `description`;
- wymagany nagłówek `Idempotency-Key` przy `POST`, `PUT`, `PATCH`, `DELETE` —
  poza podglądem bez skutków, który deklaruje `extensions={"x-dry-run": True}`;
- odpowiedź 400 → `ProblemDetails`, gdy przyjmuje dane (ciało, parametr zapytania,
  wymagany nagłówek), a każda zadeklarowana 400 i 422 wskazuje `ProblemDetails`.

Wyjątek tylko dla `idempotency-key` i `error-400`, z powodem:
`extend_schema(extensions={"x-quality-exempt": {"error-400": "powód"}})`.
Nigdy nie przechodzi `operationId` z numerem dopisanym przez generator przy
kolizji (`nazwa_2`).

Dzisiejsze operacje stoją w `quality-baseline.json` (odcisk kształtu i
uchylone reguły). Operacja traci uchylenia, gdy zmieni się jej odcisk:
parametry, pola wejściowe ciała (schemat rozwinięty o jeden poziom, bez pól
`readOnly`) albo odpowiedzi 1xx–3xx. Zmiany dokumentacji i odpowiedzi błędów
odcisku nie zmieniają. Plik pisze tylko `pnpm api:quality --write-baseline` i
po utworzeniu tylko go zmniejsza; konflikt przy scalaniu rozwiązuje się
wzięciem dowolnej strony i ponownym `--write-baseline`. Repozytorium produktu
(`.saas-core-upstream`) prowadzi własne `quality-baseline.product.json` dla
operacji wertykałów.
