# ADR-064 — wyszukiwarka katalogu na Meilisearch, z wyszukiwaniem po znaczeniu

**Status:** Accepted — decyzja właściciela 2026-09-23 (osobny silnik, od razu po
znaczeniu), odpowiedzi 1–4 z 2026-09-29; plan memex
`saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`, faza 5.
**Data:** 2026-09-29

**Zastępuje ADR-053 §8** („Wyszukiwarka to Postgres”). Reszta ADR-053 obowiązuje
bez zmian — w szczególności `profiles_catalogentry` jako jedyna publiczna tabela
katalogu i wiersz katalogu jako deklaracja tenanta (§4).

## Kontekst

ADR-053 §8 zostawił wyszukiwanie w PostgreSQL: `tsvector simple` i prefiks nad
nazwą, nagłówkiem i kategorią. Nie znajduje literówek („fryzer”), odmiany ani
wyrazów bez polskich znaków, nie zna usług firmy i nie liczy odległości.
PostgreSQL bez zewnętrznych słowników nie ma polskiego stemmera. Właściciel
23.09 wybrał osobny silnik („potrzeba czegoś mocnego, to nie tylko PL wersja
będzie”) i wyszukiwanie po znaczeniu od razu.

Pomiar Meilisearch 1.54.1 z 29.09 (kontener jednorazowy, 16 polskich wpisów i 10
tys. wpisów testowych) ustalił trzy rzeczy, które kształtują tę decyzję:

- literówki i ogonki działają („fryzer”, „stomatlog”, „weterynaz”, „zlobek”),
  ale silnik nie zamienia „ł” na „l”, więc „lodz” nie znajduje Łodzi;
- pozostawiony sam sobie silnik dobiera budżet indeksowania do RAM hosta:
  kontener z limitem 512 MB padł (OOM) przy indeksowaniu; z limitem 128 MB
  indeksowania i dwoma wątkami 10 tys. wpisów z wektorami to szczyt 220 MB;
- lokalny model w silniku to +0,9 GB RAM na instancję i słaba jakość po polsku,
  a w jednej wspólnej liście wyniki po znaczeniu wypychały trafienia słowne.

## Decyzja

1. **Silnik w stacku każdej aplikacji.** Usługa `search` (Meilisearch Community
   Edition, MIT, obraz przypięty) w `compose.yaml` rdzenia: tylko sieć `data`
   (bez internetu, bez nowej sieci — pule adresowe Dockera na dev VPS są
   wyczerpane), bez portu na hoście, `MEILI_MAX_INDEXING_MEMORY=128Mb`, dwa wątki,
   limit 384 MB. Produkty dostają ją przez `core:update`. Wspólny silnik na
   dzisiejszym dev VPS to nakładka produktu: kopia za profilem `own-search`, sekret
   `search_api_key` wskazuje klucz ograniczony do indeksu tego wdrożenia; kod
   aplikacji się nie zmienia.
2. **Baza zostaje źródłem prawdy.** Silnik trzyma projekcję: jeden dokument na
   wiersz `profiles_catalogentry`, w indeksie `<DEPLOYMENT>-catalog`. Wyszukiwanie
   zwraca identyfikatory organizacji; wiersze czyta baza, więc wpis wycofany przed
   sekundą nie pokaże się, nawet jeśli silnik go jeszcze ma.
3. **Dokument to tylko pola publiczne**: nazwa, nagłówek, początek opisu,
   tłumaczenia, kategoria z etykietami i słowami kluczowymi ze słownika, miasto i
   województwo, nazwy aktywnych usług (rejestr `register_catalog_terms`, który
   wypełnia Booking — Profiles nie może importować Bookingu), pole `folded`
   (tekst bez znaków, których silnik nie składa: ł, ø, ß). Bez kontaktów i bez
   osób. Dokument powstaje **wewnątrz tenanta** z wiersza katalogu: najpierw
   `SET LOCAL`, potem odczyt profilu, tłumaczeń i usług rolą aplikacji pod RLS.
4. **Synchronizacja trzema drogami.** Sygnały zapisu i usunięcia wiersza
   katalogu (w tym kaskada przy usunięciu firmy) oraz `catalog_changed` (zmiana
   usług, tłumaczenia) kolejkują po commicie zadanie `index_catalog_organization`;
   `catalog_changed` przesuwa też `updated_at` wiersza. Co 10 minut
   `reconcile_catalog_search` porównuje indeks z tabelą (`source_updated_at`) i
   naprawia różnice. `manage.py reindex_catalog` wypełnia świeży indeks i podmienia
   go atomowo — przy pierwszym wdrożeniu i po zmianie ustawień indeksu.
5. **Edycja opublikowanej wizytówki odświeża wiersz katalogu.** Do tej pory
   katalog pokazywał starą nazwę do ponownego włączenia przełącznika. Wyczyszczenie
   nazwy, miasta albo kategorii opublikowanej wizytówki jest odrzucane (409) —
   obecność w katalogu to przełącznik właściciela (ADR-053 §10), nie skutek
   uboczny pustego pola.
6. **Awaria silnika to wyszukiwanie w bazie.** Błąd albo brak odpowiedzi w
   `SEARCH_TIMEOUT_SECONDS` (1,5 s) kieruje zapytanie na dotychczasowe
   wyszukiwanie PostgreSQL; metryka `saas_core_catalog_searches_total{engine}` i
   log **bez treści zapytania** (w części produktów zapytanie mówi coś o zdrowiu).
   Lista bez słów zawsze idzie do bazy. Po nieudanym zapytaniu kolejne przez 30 s
   omijają silnik: gdy jego nazwa przestaje się rozwiązywać, jedno czekanie trwało
   ok. 4 s, dłużej niż sam limit czasu (pomiar na lokalnym stacku 29.09).
7. **Odległość: środek miasta do środka miasta.** Słownik miast dostał
   współrzędne; promień od wybranego miasta albo od punktu „Blisko mnie” zamienia
   się w listę miast słownika, po której filtrują obie drogi — silnik i baza
   zgadzają się co do „w promieniu 25 km”. Punkt odwiedzającego służy tylko tej
   odpowiedzi: nie jest zapisywany ani logowany.
8. **Wyniki po znaczeniu osobno** (odpowiedź 2: a + c): `items` to trafienia
   słowne, `similar` to wyniki po znaczeniu bez powtórzeń — „Podobne” (do 20),
   gdy trafień nie ma, „Może też” (do 6) pod nimi, gdy są; tylko na pierwszej
   stronie. Wektory liczy backend przez OpenRouter (odpowiedź 1,
   `qwen/qwen3-embedding-8b`, $0,01 / 1 mln tokenów, najlepszy wynik PL-MTEB
   retrieval wśród sprawdzonych), skraca do 1024 wymiarów (model trenowany pod
   skracanie) i normalizuje; zapytanie dostaje instrukcję zadania zalecaną dla
   Qwen3, dokument nie. Silnik dostaje wektory jako `userProvided` — nie ma
   internetu ani klucza. Wyszukiwanie po znaczeniu używa samych wektorów z progiem
   `CATALOG_SIMILAR_MIN_SCORE` (silnik liczy (1 + cos) / 2: niepowiązane ~0,5,
   dokument bez wektora 0), więc nie zwraca „kogokolwiek”. Wektor zapytania trafia
   na 30 dni do cache (klucz to skrót zapytania, nie jego treść). Dokument pamięta
   `meaning_model`; bez klucza albo przy awarii dostawcy dokument idzie bez wektora,
   a `reconcile_catalog_search` dokłada go, gdy dostawca wróci albo zmieni się
   model. Bez klucza działa samo wyszukiwanie słowami, bez błędu.
9. **Limit zapytań** `catalog_search` (120/min na adres) przed płatnym API.

## Konsekwencje

- Drugi system do utrzymania — świadomie. Silnik nie ma kopii zapasowej: po
  utracie wolumenu `reindex_catalog` odtwarza go z bazy.
- Wdrożenie wymaga sekretu `search_master_key` (`scripts/runtime-secrets.mjs`) i
  jednorazowego `reindex_catalog`; bez tego katalog działa, tylko na bazie.
- Zmiana `INDEX_SETTINGS` wymaga `reindex_catalog` (kolejka `memex ops`).
- Słowa kluczowe kategorii żyją w słowniku rdzenia; produkt dopisuje swoje w
  `organizationTypes[].catalogCategories[].keywords`.
- Testy w CI używają atrapy silnika; jakość wyszukiwania po polsku sprawdza
  skrypt odbioru na działającym stacku.
- Odrzucone: rozbudowa PostgreSQL (brak polskiego stemmera i literówek w
  standardzie), Elasticsearch i OpenSearch (1–2 GB RAM na instancję), Typesense
  (cały indeks w RAM, GPL), lokalny model w silniku (+0,9 GB, słaba jakość po
  polsku), przeglądarka rozmawiająca z silnikiem wprost (bez powrotu do bazy,
  klucz po stronie klienta, brak limitu zapytań).
