# Katalog publiczny: kategorie i miasta

Słownik, po którym katalog firm filtruje i adresuje (ADR-053 §7). Czyta go
backend (`shared.profiles.catalog_contract`), a obraz i każdy produkt dostają
cały ten katalog — kontrola startowa `profiles.E001` zatrzyma wdrożenie, w którym
brakuje któregoś z dwóch plików.

| Plik            | Co zawiera                                         | Kto pisze                                    |
| --------------- | -------------------------------------------------- | -------------------------------------------- |
| `manifest.json` | kategorie per typ organizacji, ze słowami kluczami | człowiek                                     |
| `cities.json`   | wszystkie miasta Polski                            | `../scripts/catalog-cities.py`, nikt ręcznie |

## Miasta

`cities.json` to **wszystkie miejscowości ze statusem miasta** — nic nie jest
pobierane w czasie działania produktu. Źródło i jego datę plik podaje sam, w
polu `source`:

- **PRNG** — Państwowy Rejestr Nazw Geograficznych (Główny Urząd Geodezji i
  Kartografii), eksport miejscowości
  `https://opendata.geoportal.gov.pl/prng/PRNG_MIEJSCOWOSCI_XLSX.zip`, obiekty
  rodzaju „miasto": nazwa urzędowa, województwo, identyfikator TERYT i punkt
  główny (szerokość i długość, WGS84) — z niego liczy się odległość w
  wyszukiwarce;
- **TERYT SIMC** (GUS, „SIMC urzędowy" z plików pełnych na
  `https://eteryt.stat.gov.pl`) — kontrola: te same miejscowości (`RM = 96`), te
  same nazwy i województwa. Gdy rejestry się różnią, skrypt niczego nie zapisuje.

Pozycja: `teryt` (identyfikator SIMC — po nim miasto jest rozpoznawane przy
następnym odświeżeniu), `slug`, `name`, `voivodeship`, `lat`, `lng`. Kolejność:
alfabet polski.

### Slug jest adresem i się nie zmienia

`/katalog/<slug>/<firma>` to opublikowany adres, więc slug raz nadany zostaje:

- miasto, które plik już zna (po `teryt`), zachowuje swój slug;
- nowe miasto dostaje nazwę bez polskich znaków (`Łomża` → `lomza`);
- nazwa, którą noszą dwa miasta, dostaje województwo (`jozefow-lubelskie`,
  `jozefow-mazowieckie`). Wyjątek z historii: `olsztyn` to Olsztyn
  warmińsko-mazurski, opublikowany przed pełną listą; Olsztyn pod Częstochową
  to `olsztyn-slaskie`;
- slug, którego miasto zniknęło z rejestru, zatrzymuje skrypt — o adresach
  opublikowanych wizytówek decyduje wtedy człowiek.

Pilnuje tego `../tests/catalog-contracts.test.mjs` (53 slugi sprzed pełnej listy
są tam wypisane z identyfikatorami).

### Odświeżenie (nowe miasta powstają 1 stycznia)

```bash
python3 packages/contracts/scripts/catalog-cities.py \
  PRNG_MIEJSCOWOSCI_XLSX.zip SIMC_Urzedowy_<data>.zip
pnpm --filter @saas-core/contracts test
```

Potem zwykła droga zmiany rdzenia: produkty dostają plik przy `core:update`,
a backend trzeba przebudować (lista jest w obrazie).

### Firma spoza miasta

Wsi na liście nie ma i nie będzie: miasto jest segmentem adresu i kubełkiem
filtra, a 43 tysiące wsi dałoby tyle samo pustych stron. Firma ze wsi wybiera
najbliższe miasto, a własny adres (ze wsią) wpisuje w polu „Adres" wizytówki;
wyszukiwarka i tak liczy odległość od punktu szukającego.
