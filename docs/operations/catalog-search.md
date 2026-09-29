# Wyszukiwarka katalogu — silnik, indeks, awaria

Decyzja: [ADR-064](../adr/ADR-064-Wyszukiwarka-Katalogu-Na-Meilisearch.md).

## Co działa gdzie

- `search` — Meilisearch w stacku, sieć `data`, bez portu na hoście, limit
  384 MB, indeksowanie ograniczone do 128 MB i dwóch wątków. Trzyma kopię:
  kasowanie wolumenu `search-data` niczego nie gubi.
- `backend` szuka (`GET /api/v1/public/catalog/?q=…`), `worker` indeksuje
  (`index_catalog_organization` po każdej zmianie wiersza katalogu, usług albo
  tłumaczeń), `scheduler` co 10 minut uruchamia `reconcile_catalog_search`.
- Indeks: `<DEPLOYMENT>-catalog`, jeden dokument na firmę w katalogu.
- Sekrety: `search_master_key` (silnik) i `search_api_key` (procesy backendu; na
  własnym silniku to ten sam plik).
- Wyszukiwanie po znaczeniu: sekret `catalog_embedding_api_key` (klucz OpenRouter;
  pusty = tylko słowa). Model i wymiar: `CATALOG_EMBEDDING_MODEL`
  (`qwen/qwen3-embedding-8b`), `CATALOG_EMBEDDING_DIMENSIONS` (1024), próg
  `CATALOG_SIMILAR_MIN_SCORE`.

## Pierwsze wdrożenie

```
node scripts/runtime-secrets.mjs            # dopisuje search_master_key, nie rusza istniejących
docker compose up -d search backend worker scheduler
docker compose exec backend python manage.py reindex_catalog
```

Bez `reindex_catalog` katalog działa (wyszukiwanie w bazie), a indeks wypełnia
się sam przy pierwszym przebiegu `reconcile_catalog_search`.

## Klucz OpenRouter

Plik wkłada właściciel, bez pokazywania klucza na ekranie:

```
read -rs -p "Klucz OpenRouter: " KEY && printf '%s\n' "$KEY" > "$SAAS_CORE_SECRETS_DIR/catalog_embedding_api_key" \
  && chmod 0644 "$SAAS_CORE_SECRETS_DIR/catalog_embedding_api_key" && unset KEY
docker compose restart backend worker scheduler
```

Restart wystarczy: w ciągu 10 minut `reconcile_catalog_search` dokłada wektory
wszystkim dokumentom, które ich nie mają. Klucz z limitem wydatków w panelu
OpenRouter; koszt zaindeksowania 10 tys. wpisów to ok. 3 centy.

## Kiedy `reindex_catalog`

Po zmianie `INDEX_SETTINGS` w `modules/shared/profiles/search_index.py`, po
utracie wolumenu i po zmianie modelu wektorów. Komenda buduje indeks obok i
podmienia go atomowo — wyszukiwanie działa przez cały czas.

## Silnik nie działa

Katalog sam przechodzi na wyszukiwanie w PostgreSQL (bez literówek i usług).
Widać to w metryce `saas_core_catalog_searches_total{engine="database"}` i w
logu `catalog_search_fallback` (bez treści zapytania). Pierwsze zapytanie po awarii
czeka na limit czasu, kolejne przez 30 s omijają silnik od razu. Po powrocie silnika
`reconcile_catalog_search` w ciągu 10 minut dogania zmiany z czasu przerwy.

## Wspólny silnik na jednym hoście

Na dev VPS trzy stacki mogą używać jednego silnika (nakładka produktu, profil
`own-search` dla jego własnej kopii). Silnik stacku `saas-core` dołącza do sieci
`<produkt>_data` z aliasem `search`, a produkt dostaje klucz ograniczony do
swojego indeksu, zapisany w pliku, na który jego nakładka mapuje sekret
`search_api_key`:

```
docker network connect --alias search <produkt>_data saas-core-search-1
curl -s -X POST http://127.0.0.1:7700/keys -H "Authorization: Bearer $MASTER" \
  -H 'Content-Type: application/json' \
  -d '{"description":"<produkt>","actions":["search","documents.*","indexes.*","settings.*","tasks.get"],"indexes":["<deployment>-catalog*"],"expiresAt":null}'
```

Bez `keys.*` i bez `*`: klucz produktu nie może tworzyć kluczy ani sięgać do
indeksów innego wdrożenia. `indexes.*` obejmuje zamianę indeksów, której używa
`reindex_catalog` (`<deployment>-catalog-next` pasuje do wzorca).

(`curl` z wnętrza kontenera silnika, np. `docker exec saas-core-search-1 …`.)
Podpięcie ginie przy odtworzeniu kontenera silnika — jak przy ClamAV.
