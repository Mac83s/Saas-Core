# Import treści — dokument `content-import.v1` i komenda operatora

Kontrakt dla tego, kto przygotowuje dokument z istniejącą treścią (wpisy starego
serwisu, eksport z innego systemu) i uruchamia import. Decyzja: ADR-079 pkt 34
i „Uzupełnienie CT4”. Kod: `shared/sites/content_import.py`, schemat
`shared/sites/content_import_schema.py`; jego opublikowana kopia to
[`content-import.v1.schema.json`](content-import.v1.schema.json) (test trzyma je
razem), a pełny przykład — `apps/backend/tests/fixtures/content_import/document.json`.

## 1. Komenda

```
python manage.py sites_import_content dokument.json \
    --organization <uuid organizacji> --operator <e-mail>             # przebieg próbny
python manage.py sites_import_content dokument.json \
    --organization <uuid> --operator <e-mail> --apply                  # import
    [--site <uuid>] [--report raport.json] [--overwrite-edits <id wpisu> …]
python manage.py sites_import_content --schema                         # schemat JSON
```

- **Bez `--apply` komenda niczego nie zapisuje**: nie tworzy wierszy, nie wysyła
  zdjęć, nie pyta skanera. Wypisuje raport tego, co by zrobiła.
- **Organizację nazywa się dwa razy**: operator podaje jej identyfikator, dokument —
  jej slug (`organization`). Gdy to nie ta sama organizacja, komenda kończy się
  przed jakimkolwiek odczytem treści. Stronę bierze, gdy organizacja ma dokładnie
  jedną; przy kilku wymaga `--site`. Język dokumentu (`default_locale`) musi być
  językiem strony.
- **Operator** to konto operatorskie (`is_staff`, potwierdzone logowanie dwuetapowe —
  jak przy komendach grantów) z aktywnym członkostwem tej organizacji i prawami
  `site.content.edit` oraz `site.publish` (do zdjęć także `media.manage`). Wszystko jest
  zapisywane **jako ta osoba, przez serwisy panelu** — historia firmy ją nazywa,
  a każda blokada, którą spotyka człowiek, działa: limit typów w planie, typ wyłączony,
  kontrakty bloków, przestrzeń nazw kategorii i tagów, biblioteka mediów ze skanerem.
  Konto właściciela firmy, który nie jest operatorem platformy, nie wystarczy: historia
  nie może nazwać kogoś, kto importu nie uruchomił.
- Zdjęcia komenda czyta z plików obok dokumentu (ścieżki względne; nic spoza
  katalogu dokumentu).
- Kod wyjścia: `0` — nic nie odrzucono; `1` — część obiektów odrzucona (raport mówi
  które i dlaczego; pozostałe weszły); `2` — zły dokument albo cel, nic nie zrobiono.

Na VPS komendę uruchamia się w osobnym kontenerze (nie przez `docker exec` w żywym
backendzie), z katalogiem dokumentu podmontowanym do odczytu.

## 2. Dokument w dziesięciu liniach

```json
{ "schema": "content-import.v1", "source": "stary-blog", "organization": "moja-firma", "default_locale": "pl",
  "types": [{ "key": "poradnik", "name": "Poradnik", "base_path": "poradnik", "locale_paths": { "en": "guide" } }],
  "categories": [{ "id": "c1", "type": "poradnik", "names": { "pl": "Pielęgnacja", "en": "Care" }, "slugs": { "pl": "pielegnacja" } }],
  "tags": [{ "id": "t1", "names": { "pl": "Szczenięta", "en": "Puppies" } }],
  "entries": [{ "id": "post-17", "type": "poradnik", "categories": ["c1"], "tags": ["t1"], "author_name": "Anna Nowak",
    "versions": [
      { "locale": "pl", "title": "Jak czesać psa", "slug": "jak-czesac-psa", "former_slugs": ["czesanie"], "origin": "human",
        "body": { "html": "<p>…</p>" }, "cover": { "file": "img/a.jpg", "alt": "Pies" },
        "fields": { "title": { "sha256": "…" }, "body": { "sha256": "…" } },
        "status": "published", "published_at": "2023-03-14T08:30:00+01:00", "changed_at": "2025-02-01T10:00:00+01:00" },
      { "locale": "en", "title": "How to brush a dog", "body": { "html": "<p>…</p>" }, "status": "published",
        "published_at": "2023-03-14T08:30:00+01:00", "origin": "ai", "model": "…",
        "fields": { "title": { "source_sha256": "…" }, "body": { "source_sha256": "…" } } }] }] }
```

Trzy rzeczy, o które pierwszy prawdziwy dokument potknie się najczęściej:

- **Odciski.** Jeśli `source_sha256` tłumaczeń liczono inaczej niż „SHA-256 z bajtów
  UTF-8 pola dokładnie tak, jak stoi w dokumencie”, wersja źródłowa **musi** nieść własne
  `fields.<pole>.sha256` policzone tą samą metodą co odciski tłumaczeń — inaczej każde
  tłumaczenie zostanie zgłoszone jako nieaktualne, choć nim nie jest.
- **Zdjęcia w HTML.** Każdy `<img>` potrzebuje pliku w `images` (klucz = jego `src`)
  i opisu (`alt` w HTML albo w `images`); bez tego konwerter zgłasza stratę
  `image_dropped`, a wersja wchodzi jako szkic.
- **Odnośnik w nagłówku** jest przez konwerter gubiony (słowa zostają):
  `heading_link_dropped`. Bez tego rodzaju w `accept_losses` wersja wchodzi jako szkic.
- **Tabela szersza niż 12 kolumn** jest zapisywana jako linie tekstu (`table_too_wide`):
  słowa zostają, ale czytelnik nie widzi już tabeli, więc wersja też wchodzi jako szkic,
  dopóki dokument tego nie przyjmie. Tabela dłuższa niż 120 wierszy jest dzielona
  (`table_split`): publikowana, ale zawsze wypisana w „NEEDS A LOOK”.
- **Tytuł i zajawka to czysty tekst.** HTML w nich (znacznik albo encja, np. `<p>`,
  `&amp;`) odrzuca wersję (`markup_in_title`, `markup_in_excerpt`) — pokazałby się
  czytelnikowi litera po literze na karcie i w wyniku wyszukiwania. To samo dotyczy nazw
  kategorii i tagów (`markup_in_name`). Sam znak `<` albo `&` w zdaniu jest w porządku.

Najważniejsze reguły (pełny opis każdego pola jest w schemacie):

| Co | Reguła |
| --- | --- |
| `source`, `id` | `source` to przestrzeń nazw identyfikatorów. Ten sam `source` i `id` w kolejnym dokumencie znaczy „ten sam obiekt” — także gdy uruchamia go inna osoba. |
| typ | Istniejący znajdowany jest po `key` i nie jest zmieniany. Brakujący powstaje (potrzebne `name` i `base_path`); działa oferta wdrożenia i limit planu. |
| kategoria, tag | Nazwy per język wchodzą jako **tekst człowieka** (silnik tłumaczeń ich nie nadpisze). `slugs` wolno podać tylko w części języków — w pozostałych adres liczy się z nazwy. Rodzic przed dzieckiem, najwyżej trzy poziomy. `fields` niesie to, na co rdzeń nie ma pola, per język (`{"description": {"pl": "…"}}`) — trafia do księgi. |
| ta sama nazwa | **Pozycja, którą strona już ma** (tag o tej nazwie, kategoria o tej nazwie w tym samym miejscu drzewa), jest przejmowana, nie dublowana — jawnie: `term_adopted` w „NEEDS A LOOK” mówi, co się w niej zmieni. Import dopisuje jej tylko brakujące nazwy w innych językach i dawne adresy; istniejących nazw i adresów nie rusza (`name_kept`, `address_kept`). **Dwie pozycje dokumentu o tej samej nazwie w języku strony** to na stronie jedna pozycja (`term_merged`): drugi identyfikator wskazuje pierwszą, a jego własne nazwy i adresy nie są stosowane. **Ta sama nazwa tylko w innym języku** (`name_shared`): obie pozycje zostają, druga dostaje w tym języku adres z numerem (`tips-2`). |
| wersje językowe | Jeden wpis dokumentu to jedna grupa tłumaczeń; każda wersja jest własnym wpisem. Kategorie i tagi wpisu dostaje każda wersja. Wersja w języku, którego strona nie ma, jest odrzucana (pozostałe wchodzą). **Tłumaczenia wchodzą razem ze źródłem, nie przed nim:** gdy wersja źródłowa (`source_locale`, domyślnie język strony) jest odrzucona i nie ma jej jeszcze na stronie, pozostałe nowe wersje wpisu czekają (`source_refused`). Wersji w języku, którą wpis już ma, a której import nie zrobił (ręczna, z silnika tłumaczeń), import nie rusza (`version_exists`). |
| `slug` | Pominięty — liczony z tytułu funkcją rdzenia (cyrylica zapisana alfabetem łacińskim), unikalny w typie i języku; kolejny wpis o tym samym tytule dostaje `-2`. |
| `former_slugs` | Same końcówki dawnych adresów (nie całe ścieżki — te należą do tabeli starych adresów produktu). Każda odpowiada jednym 308. Końcówka, pod którą dziś odpowiada inny wpis, jest pomijana z ostrzeżeniem: żywy adres zawsze wygrywa. |
| `body` | `{"html": …}` — przechodzi przez konwerter rdzenia (`site-html-import.md`), raport wymienia każdą stratę; albo `{"blocks": […]}` — gotowe bloki, zdjęcie jako `"asset_id": "file:<ścieżka>"`. |
| zdjęcia | `cover` — zdjęcie pokazywane jako pierwsze w treści (karta na liście, podgląd linku); `images` — plik dla każdego `<img src>` z HTML, kluczem jest dokładnie ten `src`. JPEG, PNG, WebP. |
| `status` | Import publikuje tylko to, co ma `published` — i nigdy niczego nie wycofuje. |
| `published_at`, `changed_at` | Patrz §5. Zawsze ze strefą; `published_at` nie może być w przyszłości. |
| `origin`, `fields` | Patrz §4. Pole, którego rdzeń nie ma (`seo_title`, `seo_description`), niesie swój tekst w `fields.<nazwa>.text` — księga trzyma go razem z pochodzeniem i odciskami. |
| `accept_losses` | Rodzaje strat konwertera, które w tej wersji nie wstrzymują publikacji (patrz §3). |

## 3. Raport

Raport (tekst na wyjściu, pełny JSON przez `--report`) zaczyna się od tego, **do której
organizacji i strony** trafia import i kto go wykonuje, potem liczby, potem to, co
wymaga wzroku człowieka, na końcu jedna linia na każdy obiekt. Każdy obiekt ma jedno
z działań:

| Działanie | Znaczenie |
| --- | --- |
| `create`, `update` | powstanie / zmieni się (lista zmienionych pól obok) |
| `unchanged` | jest takie, jak mówi dokument |
| `kept` | **człowiek zmienił to po imporcie — zostaje, jak zostawił** (raport mówi, które pole i czy dokument niósł nowszą wartość) |
| `held` | treść wchodzi jako szkic i **nie jest publikowana**: konwerter zgubił treść, data publikacji jest ewidentnie błędna albo publikacja się nie udała |
| `refused` | nic nie zapisano; powód w raporcie |

Nad listami raport ma sekcję „BEFORE YOU RUN” — to, co nie dotyczy jednego obiektu.
Dziś jedna rzecz: gdy silnik tłumaczeń jest dla firmy włączony, publikacja oryginałów
może zamówić płatne tłumaczenia maszynowe na języki, których dokument nie ma (raport
liczy je per język). Czy firma włączyła automatyczne tłumaczenie zmian, to ustawienie
silnika, którego moduł stron nie czyta — sprawdź je przed `--apply`.

Odrzucenia, które raport nazywa kodem: `locale_not_enabled`, `type_unknown`,
`content_type_archived`, `content_types_not_offered` / `quota_exceeded` /
`plan_access_denied` (limit typów), `slug_taken`, `slug_former`, `slug_missing`,
`picture_missing`, `picture_outside`, `picture_unsupported`, `picture_too_large`,
`picture_refused`, `library_unavailable` (rola operatora bez `media.manage` albo plan
bez biblioteki mediów — wiadomo już w przebiegu próbnym), `source_refused`,
`version_exists`, `markup_in_title`, `markup_in_excerpt`, `markup_in_name`,
`body_unreadable`, `body_invalid`, `body_empty`, `term_unknown`,
`parent_unknown`, `published_at_missing`, `published_at_future`, `date_invalid`,
`write_failed`. Ostrzeżenia: `term_adopted`, `term_merged`, `name_shared`, `made_again`,
`translation_stale`, `held_for_losses`,
`published_at_implausible`, `former_slug_live`, `former_slug_claimed`, `*_kept`,
`withdrawn_in_panel`, `removed_in_panel`, `not_republished`, `source_edited_in_panel`.

**Straty konwertera.** Każda różnica między HTML a blokami jest w raporcie przy swojej
wersji: rodzaj, liczba, przykład (np. `body lost: heading_link_dropped ×1
(https://…) — e.g. „Jak wybrać szczotkę”`). Strata rodzaju `lost` (zgubiona treść:
odnośnik w nagłówku, zdjęcie bez pliku albo opisu, usunięty znacznik) **wstrzymuje
publikację tej wersji** — wchodzi jako szkic — chyba że dokument wymieni ten rodzaj w
`accept_losses`; tak samo `table_too_wide`. Pozostałe zmiany zapisu (`changed`:
podkreślenie jako pogrubienie, `h1` jako `h2`, scalone komórki tabeli) i podziały
(`split`) publikacji nie wstrzymują; `table_split` jest mimo to w „NEEDS A LOOK”.

**Czego przebieg próbny nie wie:** werdyktu skanera i tego, czy plik da się przetworzyć
jako zdjęcie (sprawdza istnienie, typ po nagłówku pliku i rozmiar), czy zdjęcia zmieszczą
się w limicie magazynu planu, oraz odmów, które
zależą od stanu z chwili zapisu (ktoś zmienił wpis między planem a zapisem — wpis jest
wtedy odrzucany z `write_failed` i wchodzi przy kolejnym uruchomieniu).

## 4. Skąd tekst: `origin` i odciski źródła

- `origin` wersji (`human`, `ai`, `import` — nikt nie ręczy; domyślnie `import`) obejmuje
  jej pola; `fields.<pole>.origin` zmienia je dla jednego pola (tytuł człowieka na
  tekście modelu). Pola rdzenia to `title`, `excerpt`, `body`.
- Wersja z choć jednym polem `ai` jest **oznaczona dla wyszukiwarek jako tekst
  maszynowy** (ADR-071 pkt 17) i nie ma akceptacji człowieka, dopóki ktoś sam jej nie
  opublikuje w panelu. Poprawka człowieka w takim tekście nie zdejmuje znacznika
  (wersja staje się „mieszana”).
- `fields.<pole>.source_sha256` — odcisk tekstu źródłowego, z którego powstało
  tłumaczenie pola. Rdzeń przechowuje go **dosłownie** (księga importu,
  `ContentImportRecord.fields`), także dla pól, których sam nie ma (np.
  `meta_description`). `fields.<pole>.sha256` na wersji źródłowej to odcisk tego tekstu
  policzony przez autora dokumentu; gdy go brak, import liczy SHA-256 z bajtów UTF-8
  pola dokładnie tak, jak stoi w dokumencie (`body`: napis `html`, a dla bloków JSON
  z posortowanymi kluczami bez spacji).
- Pole bez słów (wersja bez zajawki) nie mówi nic o pochodzeniu tekstu: jego `origin`
  nie wchodzi do znacznika wersji.
- Gdy `source_sha256` tłumaczenia różni się od odcisku źródła, raport oznacza pole jako
  `translation_stale` („do ponownego tłumaczenia”), a księga zapisuje `stale`. Gdy
  człowiek zmienił w panelu tekst źródłowy po imporcie, każde tłumaczenie tej grupy
  dostaje `source_edited_in_panel`.
- Zaimportowanymi tłumaczeniami **nie zarządza centrum tłumaczeń** (są wersjami
  językowymi bez wskazania źródła): silnik ich nie nadpisze ani nie zaproponuje
  poprawek; kolejną wersję przynosi nowszy dokument.

## 5. Daty

| Data | Skąd | Gdzie ją widać |
| --- | --- | --- |
| `published_at` | dokument (data pierwszej publikacji w starym serwisie) | strona wpisu i listy, RSS `pubDate`, Atom `published`, JSON-LD `datePublished`, kolejność na listach |
| `changed_at` | dokument (kiedy tekst ostatnio zmienił się u źródła; brak = `published_at`) | „zaktualizowano” na stronie, `lastmod` sitemapy, JSON-LD `dateModified`, Atom `updated` |

Noc importu nie pojawia się w żadnej z nich. `published_at` sprzed 1995 r. jest
traktowana jako ewidentna pomyłka: wersja wchodzi jako szkic (`held`), a po poprawieniu
daty w dokumencie kolejne uruchomienie ją publikuje. Późniejsza edycja w panelu ustawia
`changed_at` zwykłą drogą — na chwilę zapisu tekstu.

## 6. Drugie uruchomienie

- **Ten sam dokument drugi raz niczego nie zmienia** (poza jedną linią historii, że
  import się odbył).
- **Zmieniony dokument zmienia tylko to, co się zmieniło — i tylko tam, gdzie wartość
  jest nadal tą, którą zapisał import.** Księga pamięta skrót każdego pola, które import
  zapisał, i numer wersji tekstu. Tytuł, zajawka, autor, tekst, zestaw kategorii i tagów,
  adres albo wycofanie wpisu, które po imporcie zmienił człowiek, zostają; raport mówi to
  wprost (`kept`). Operator może świadomie oddać pierwszeństwo dokumentowi:
  `--overwrite-edits <id wpisu>`.
- Wpis, w którym jest cokolwiek od człowieka, **nie jest publikowany przez import**:
  zmiany importu czekają w szkicu razem z jego zmianami (`not_republished`).
- Wpis usunięty w panelu nie powstaje ponownie. Wpis, który był publiczny, a nie jest,
  **zostaje wycofany — ktokolwiek go wcześniej opublikował** (import nigdy nie wycofuje,
  więc „był, nie ma” to zawsze decyzja człowieka): `withdrawn_in_panel`.
- **Czego już nie ma, powstaje ponownie — i raport mówi to wprost** (`made_again` w
  „NEEDS A LOOK”): pozycja, którą ktoś usunął w panelu, jest zakładana od nowa; wersja
  wpisu skasowana razem ze swoim typem treści powstaje od nowa i jest publikowana, jeśli
  dokument tak mówi. Kto tego nie chce, usuwa obiekt z dokumentu.
- `changed_at` z przyszłości jest zastępowane datą publikacji (`changed_at_future`) —
  nie „teraz”, bo wtedy każde uruchomienie publikowałoby wpis ponownie.

## 7. Transakcje, błędy, skala

- Każda transakcja importu zaczyna się od nazwania tenanta (`SET LOCAL`), więc pod rolą
  aplikacji niczego nie czyta ani nie zapisuje poza organizacją operatora.
- Tekst jednego wpisu dokumentu (wszystkie jego wersje) to jedna transakcja: wchodzi
  cały albo wcale. Publikacja każdej wersji to osobna transakcja (publikacja blokuje
  pozycje, które niesie — po jednym wpisie naraz, w kolejności, w jakiej robi to każdy
  inny zapis). Zakleszczenie z równoczesną zmianą słownika jest ponawiane do trzech
  razy i policzone w raporcie; nieudana publikacja zostawia tekst jako szkic.
- Zdjęcie jest zapisywane przed swoim wpisem, we własnej transakcji, i rozpoznawane po
  zawartości — drugi raz nie jest wysyłane. Zdjęcie odrzucone przez bibliotekę (skaner,
  uszkodzony plik) odrzuca wersje, które je pokazują; reszta wchodzi. Gdy skaner nie
  odpowiada trzy razy z rzędu, import przestaje go pytać: wpisy czekające na zdjęcia są
  w raporcie i wejdą przy kolejnym uruchomieniu.
- Liczba zapytań planu nie rośnie z liczbą wpisów ani pozycji (księga, wpisy, slugi
  i przypisania są czytane po jednym zapytaniu na cały dokument).
