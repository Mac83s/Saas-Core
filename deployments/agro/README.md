# Profil `agro`

Profil wzorcowy produktu rolniczego (ADR-051): Business z rejestrem gospodarstw
(`shared.farms`). Istnieje tylko po to, żeby Saas-Core walidował i testował
rejestr u siebie — żaden profil rdzenia go nie składa. Nie ma obrazu
(`product.json` go nie wymienia) ani instancji. Testy rejestru:

```
DEPLOYMENT=agro uv run --project apps/backend pytest apps/backend/tests/test_farms.py
```
