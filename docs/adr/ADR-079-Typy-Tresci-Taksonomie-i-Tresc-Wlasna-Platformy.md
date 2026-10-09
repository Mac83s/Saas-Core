# ADR-079 — typy treści na stronach firm i treść własna platformy: typ to dział, taksonomie i pozycje, odczyt dla stron produktu

**Status:** Accepted — przyjęty przez właściciela 2026-10-08, punkt po punkcie (sekcja
„Odpowiedzi właściciela”). Zamówienie właściciela z 2026-10-08
(typy treści „jak custom posts w WordPressie”, taksonomie, kategorie, tagi,
wielojęzyczność, slugi; blog zawsze, typy niestandardowe per platforma i per plan) oraz
jego odpowiedź z tego samego dnia: blog własny produktu (91 wpisów Puppily, potem
HoofCare i MedPlano) żyje w tym samym systemie treści. Rozstrzygnięcia techniczne:
agent, pakiet CT0; plan memex `saas-core-typy-tresci`. Druga wersja dokumentu, po
przeglądzie projektu z kodem (14 uwag — sekcja „Po przeglądzie”) i po scaleniu pakietu
PC1 (`main` b97403ae). Zbudowane są fazy CT1, CT2 i CT3 (sekcja „Stan budowy”); reszta
czeka na swoje pakiety.
**Data:** 2026-10-08

**Zmienia częściowo** ADR-071 pkt 14 i „Uzupełnienie 2026-10-07” (adresy pozycji per
język; dawna nazwa działu), komentarz modelu `ContentTag` („jedna płaska taksonomia”)
i — dopiero z dodatkiem CT6 — ADR-031; **rozszerza** ADR-035 §1 i §7 oraz ADR-070
pkt 18; limit planu idzie wzorem ADR-071 pkt 7; **wprowadza jeden jawny wyjątek** od
zasady „publiczny odczyt nie używa drzwi sprzed tenanta” (pkt 31). Fragmenty — w sekcji
„Zmiany wcześniejszych decyzji”.

## W skrócie dla właściciela

**Co zrobi klient w panelu.** W „Strona internetowa → Treści” widzi listę typów treści;
pierwszy to jego blog. Klika „Nowy typ treści”, wpisuje nazwę „Realizacje”, panel
proponuje adres `/realizacje/` i pozwala nazwać go w innych językach (`/en/projects/`,
`/de/referenzen/`). Potem dodaje wpisy tym samym edytorem co wpisy bloga, przypisuje im
kategorie („Łazienki”, „Kuchnie”) i tagi, publikuje. Na stronie odpowiada indeks
`/realizacje/`, wpis `/realizacje/<slug>/`, archiwum kategorii
`/realizacje/kategoria/lazienki/` — i to samo po angielsku i niemiecku, z tłumaczeniami
robionymi przez ten sam silnik i za te same kredyty co dziś.

**Na czym to stoi.** Dzisiejszy blog jest już „typem treści” — w bazie to dział
(kolekcja) z nazwą, adresem per język, indeksem i stroną wpisu. Nie powstaje nic obok:
typ to ten sam wiersz z trzema nowymi polami, pozycja taksonomii (kategoria, tag) to
dzisiejszy wiersz tagu z kilkoma nowymi polami, a jedyną nową tabelą jest taksonomia.
Żaden istniejący adres, wpis ani tag się nie zmienia i żaden wiersz nie jest
przepisywany.

**Sześć wyborów, które warto zobaczyć przed budową** (każdy z tym, co oddaje):

1. **Typ treści to dział, nie nowy byt nad działami.** Zyskujemy: publikację, harmonogram,
   tłumaczenia, SCR i adresy od pierwszego dnia, bez migracji. Oddajemy: dwa typy nie
   mogą dzielić jednego adresu działu, a wpis nie zmienia typu po utworzeniu.
2. **Kategorie należą do typu, tagi są wspólne dla całej strony** — jak dziś. Kategorie
   „Realizacji” i bloga to dwa osobne zbiory. Oddajemy: jedna kategoria nie obejmuje
   wpisów dwóch typów (od tego są tagi).
3. **Adres kategorii jest płaski:** `/realizacje/kategoria/lazienki/`, także gdy
   „Łazienki” leżą pod „Wnętrzami”. Zyskujemy: przeniesienie kategorii pod inną nie
   rusza żadnego adresu. Oddajemy: hierarchii nie widać w adresie (widać ją w okruszkach
   i w tym, że archiwum nadrzędnej pokazuje też wpisy podrzędnych).
4. **Dostęp: przełącznik platformy i limit w planie.** Blog nie wymaga niczego poza
   stroną. Limit liczy **włączone typy treści na jednej stronie poza pierwszym** i działa
   jak limit języków: plan z liczbą ma limit, plan bez liczby go nie ma. Oddajemy: plan,
   któremu nikt nie wpisał liczby, daje typy bez ograniczeń — dlatego liczby wchodzą do
   planów, zanim platforma włączy przełącznik. Liczby są Pana.
5. **Wersja 1 wygląda jak dzisiejszy blog.** Strona wpisu i indeks każdego typu mają
   dzisiejszy, stały skład. Układ kart, przełączniki wyglądu i blok „Lista wpisów” do
   wstawienia na dowolną podstronę to pierwszy dodatek po wersji 1 (pytanie 4). Pól
   własnych, szablonów strony wpisu i relacji między typami wersja 1 nie ma — dla
   każdego z nich ADR wskazuje miejsce w modelu, tak żeby dodanie go nie wymagało
   migracji treści klientów.
6. **Treść własna platformy pisze się w tym samym panelu, a strony publiczne produktu
   rysuje produkt.** Rdzeń daje odczyt „opublikowane wpisy według typu, języka i sluga”;
   produkt ma własne trasy, nagłówek i stopkę. Strona workspace'u platformy przestaje
   odpowiadać przez renderer kreatora, żeby te same wpisy nie miały drugiego adresu.

## Kontekst

Stan kodu (`apps/backend/src/saas_core/modules/shared/sites/`, `main` b97403ae):

- `ContentCollection` — dział strony: `key`, `name`, `kind` (blog | news | guide; sama
  etykieta, nic jej nie czyta poza inwentarzem), `base_path` i `locale_paths` (nazwa w
  adresach per język, ADR-071 „Uzupełnienie 2026-10-07”), `former_paths` (dawne nazwy,
  jedno 308), `show_in_navigation`, polityka automatyzacji.
- `ContentEntry` — wpis w jednym języku, w grupie tłumaczeń, z własnym slugiem,
  wersjami (`ContentEntryVersion`: lista bloków) i publikacją (`ContentEntryPublication`;
  każdy wpis publikuje się sam, ADR-035 §1). Migawka publikacji jest niezmienna i niesie
  adres, tytuł, bloki i tagi wpisu (`{slug, name}`).
- `ContentTag` i `ContentEntryTag` — płaskie tagi wspólne dla strony, slug unikalny w
  stronie. `ContentEntryTag` mówi o szkicu; to, w którym archiwum wpis jest widoczny,
  mówi migawka. Archiwum tagu jest projekcją liczoną z migawek, pod działem:
  `/blog/tag/<slug>/`; segment `tag` i slug są te same we wszystkich językach (dług z
  ADR-071 pkt 14). Nazwa tagu w innym języku to tekst strony (`SiteTextTranslation`,
  klucz `tag/<id>`), oferowany do tłumaczenia dopiero, gdy tag nosi opublikowany wpis.
- Indeks działu, archiwa, kanały RSS/Atom (`/rss.xml`, `/xx/rss.xml` — jeden kanał na
  stronę i język, wszystkie działy razem, 50 pozycji), sitemapa, hreflang i JSON-LD
  (`BlogPosting` dla każdego wpisu, bez względu na `kind`) liczą się przy żądaniu z
  jednej projekcji `published_entries`.
- Backend obsługuje wiele działów na stronie od dawna (testy `test_sites_collections.py`,
  `test_sites_section_addresses.py`); panel (`/panel/sites/blog`, `blog-panel.tsx`)
  pozwala założyć tylko pierwszy, ale ma wybór działu, gdy jest ich więcej. Dział nie ma
  usuwania ani wyłączania.
- Slug wpisu podaje się przy utworzeniu; potem **nie da się go zmienić wcale**, także w
  szkicu. Przekierowanie po zmianie nazwy działu (`moved_section`) liczy cel pod
  dzisiejszą nazwą i rezygnuje, gdy dokładnie ten adres nie odpowiada.
- Podstrony są dopasowywane przed działami, a zapis sluga podstrony nie sprawdza nazw
  działów (sprawdza tylko segmenty zarezerwowane) — podstrona `/realizacje/` zasłoniłaby
  indeks typu.
- Kontrakt `content-change-set.v1` adresuje wpis parą `content_entry` + `collection_id`
  i nie ma komend dla tagów — SCR pisze do dowolnego działu, na który ma grant.
- Workspace platformy (ADR-077 pkt 2 i 9, obowiązują) ma stronę w `shared.sites` i panel
  wydawcy. Każda strona dostaje przy utworzeniu zweryfikowaną subdomenę platformy, a
  publiczny renderer obsługuje każdą stronę, która ma opublikowany wpis. Sam
  `platformDomain` nie może być domeną żadnej strony; zakodowane widoki produktu stoją
  właśnie na nim. Opublikowane zdjęcia są serwowane tylko na hoście strony.

Pomiar danych na lokalnych stosach (08.10, tylko odczyt, w tenancie każdej z 24
organizacji stosu Saas-Core, policzone dwukrotnie):

| Stos | Strony | Typy (działy) | Wpisy | Tagi / przypisania |
| --- | --- | --- | --- | --- |
| Saas-Core `:8080` | 9 | 3 — trzy strony mają po jednym, sześć nie ma żadnego; wszystkie `kind=blog` | 13 (pl 10, en 2, de 1; 10 opublikowanych, 3 szkice; 10 grup tłumaczeń) | 4 / 5 (żaden tag nie jest użyty w dwóch działach, 1 nieużywany; 1 przetłumaczona nazwa tagu) |
| Puppily `:8083` | 1 | 1 (`poradnik`, `kind=guide`, nazwy w czterech językach) | 0 | 0 |
| HoofCare `:8081`, MedPlano `:8082` | 1 i 2 | 0 | 0 | 0 |

Żadna strona nie ma dziś więcej niż jednego działu. VPS nie był mierzony z tej maszyny;
migracja jest zaprojektowana tak, żeby kształt danych na VPS nie miał znaczenia.
Fakty o treści Puppily do przeniesienia (z eksportu, podane przez koordynatora; pakiet
CT0 eksportu nie czytał): 91 wpisów, wszystkie opublikowane; 20 ma wersję en i de, 19 —
es i ru, 71 jest tylko po polsku; 19 kategorii z nazwami w pięciu językach, 164
przypisania wpis–kategoria; slugi tłumaczeń per język; tagi jako pole wpisu.

## Decyzja

### Słownik

| W panelu i dokumentach | W kodzie | Uwagi |
| --- | --- | --- |
| **typ treści** | `ContentCollection` | w adresach nadal „dział” („adres działu”), jak w dzisiejszych komunikatach |
| **wpis** | `ContentEntry` | bez zmiany |
| **taksonomia** | `ContentTaxonomy` (nowa) | w wersji 1 klient widzi tylko jej dwa rodzaje: „Kategorie” i „Tagi” |
| **pozycja** (taksonomii) | `ContentTag` | słowo ogólne; w panelu zawsze konkretnie „kategoria” albo „tag”. Nie „termin”, bo w tej platformie termin to termin wizyty |
| **kategoria**, **tag** | pozycja taksonomii hierarchicznej / płaskiej | |

### Model danych

1. **Typ treści to wiersz `ContentCollection`.** Dochodzą trzy pola, każde z wartością
   domyślną równą dzisiejszemu zachowaniu:
   - `archived_at` (puste) — typ wyłączony (pkt 23);
   - `schema_type` (domyślnie `BlogPosting`) — czym wpis jest dla wyszukiwarek:
     `BlogPosting`, `NewsArticle`, `Article` albo `WebPage` (sama strona, bez węzła
     artykułu). Każdy istniejący dział zostaje przy `BlogPosting`;
   - `in_site_feed` (domyślnie tak) — czy wpisy typu trafiają do kanału RSS/Atom strony.
   `kind` zostaje nietknięty i dalej jest etykietą; nie dostaje nowych wartości, bo
   wystawiają go inwentarz i `collection_kinds` czytane przez SCR. Typ nie ma osobnej
   nazwy w liczbie pojedynczej — panel mówi „Nowy wpis” w każdym typie.
2. **Taksonomia to jedyna nowa tabela, `ContentTaxonomy`** (z wymuszonym RLS): strona,
   `key`, `name`, `hierarchical`, segment adresu (`segment`, `locale_segments`,
   `former_segments` — ten sam wzór co nazwa działu) oraz `collection`: ustawione —
   taksonomia należy do jednego typu (kategorie), puste — jest wspólna dla wszystkich
   typów strony (miejsce na własne taksonomie firmy).
3. **Pozycja to wiersz `ContentTag`.** Dochodzą: `taxonomy` (puste = tag strony, czyli
   to, czym jest każdy dzisiejszy wiersz), `parent` (kategoria nadrzędna w tej samej
   taksonomii), `position` (kolejność wśród rodzeństwa) oraz trzy pola adresu:
   `locale_slugs`, `slug_locked_at` i `former_slugs` (pkt 11). Tagi strony nie dostają
   wiersza taksonomii: ich reguły (płaskie, wspólne, segment `tag`) zostają jedną
   nazwaną stałą modułu — dzięki temu migracja nie dotyka żadnego istniejącego tagu.
4. **Przypisanie zostaje w `ContentEntryTag`**, bez zmian. Wpis ma najwyżej 10 pozycji
   w jednej taksonomii (dziś: 10 tagów). Nie ma „kategorii głównej”.
5. **`ContentTag.slug` staje się stałym kluczem pozycji: nigdy się nie zmienia i zostaje
   unikalny w stronie — ograniczenie bazy się nie zmienia.** Migawki wskazują tag
   właśnie nim; gdyby dało się go zmienić, starsze wpisy wypadłyby z archiwum. Kategoria,
   której naturalny klucz jest zajęty (przez tag albo kategorię innego typu), dostaje
   klucz z przyrostkiem (`porady-2`) — klucza nikt nie ogląda, bo adres bierze się z
   nazwy (pkt 11). Adres pod samym kluczem zawsze prowadzi do pozycji: odpowiada, gdy
   jest jej adresem, a inaczej daje jedno 308.
6. **Adresy pozycji to jedna przestrzeń nazw taksonomii, wspólna dla języków.** Klucz,
   adresy we wszystkich językach i dawne adresy jednej pozycji nie mogą być kluczem,
   adresem ani dawnym adresem innej pozycji tej samej taksonomii (tagi strony są pod tym
   względem jedną taksonomią). Sprawdza serwis, pod blokadą wiersza strony — tak jak
   nazwy działów. Oddajemy: to samo słowo nie będzie adresem dwóch różnych pozycji w
   dwóch językach; druga dostaje przyrostek.
   - **Jak rozstrzyga się wpisana nazwa** (pole tagów przy wpisie w dowolnym języku):
     ze sluga nazwy szukamy pozycji, której klucz albo adres w którymkolwiek języku jest
     mu równy — „Wood” przy angielskim wpisie trafia w tag `drewno`, jeśli ten ma
     angielski adres `wood`. Dopiero gdy takiej nie ma, powstaje nowa pozycja.
     Przestrzeń jest jedna, więc wynik nie zależy od języka wpisu.
7. **Wpis** dostaje jedno pole: `former_slugs` (pkt 16).
8. **Migawka wpisu** zachowuje pole `tags` w dzisiejszym kształcie i tylko dla tagów, a
   dodatkowo niesie `terms` (identyfikator, taksonomia, klucz, nazwa) dla wszystkich
   taksonomii. Starsze migawki zostają nietknięte i dalej się liczą.

### Taksonomie

9. **Wersja 1 ma dwa rodzaje:** tagi (płaskie, wspólne dla strony — istnieją) i
   kategorie (hierarchiczne, osobne dla każdego typu, do trzech poziomów). Kategorie
   powstają, gdy klient je włączy dla typu — także dla bloga, bez żadnego limitu planu.
   Własnych taksonomii firmy („Lokalizacja”, „Marka”) wersja 1 nie pokazuje w panelu,
   choć tabela z pkt 2 już je mieści; to pytanie 3.
10. **Co czyta się z migawek, a co na żywo — powiedziane wprost.**
    - To, **które wpisy są w archiwum**, mówi migawka każdego wpisu (pozycje z chwili
      publikacji). Zmiana kategorii wpisu jest widoczna po jego publikacji.
    - **Drzewo i nazwy** czyta się na żywo: archiwum kategorii nadrzędnej pokazuje wpisy
      kategorii, które są pod nią teraz. **Przeniesienie kategorii zmienia więc
      opublikowane archiwa od razu, bez żadnej publikacji** — tak samo jak zmiana nazwy
      działu działa od zapisu.
    - **Usunąć** można tylko pozycję, której nie nosi żaden wpis ani w szkicu
      (`ContentEntryTag`), ani w bieżącej publikacji (migawka) — inaczej odpowiadające
      archiwum zamieniłoby się w 404. Usunięcie kategorii z podrzędnymi przenosi je
      poziom wyżej. Łączenie pozycji — później.
11. **Nazwa i adres pozycji per język.**
    - Nazwa w innym języku: tekst strony, klucz `tag/<id>` — ten sam co dziś, z jego
      ochroną tekstu wpisanego przez człowieka. Nazwa taksonomii: `taxonomy/<id>`.
    - Adres w języku L: `locale_slugs[L]`; gdy go nie ma — adres w języku strony; gdy i
      tego nie ma — klucz. Dzisiejszy tag nie ma żadnego wpisu w `locale_slugs`, więc
      odpowiada pod kluczem we wszystkich językach, dokładnie jak dziś.
    - Kto liczy: kod, z nazwy (`slug_from_title`, ADR-070 pkt 18), nigdy model.
    - **Zamknięcie adresu jest zapisane** (`slug_locked_at[L]`, wzorem
      `PageTranslation.slug_locked_at`), a nie wyliczane przy żądaniu — wycofanie
      ostatniego wpisu niczego nie otwiera. Zamyka się tylko adres policzony z nazwy:
      - **dzisiejsze tagi** dostają przy dodaniu kolumny znacznik „zamknięte we
        wszystkich językach, na kluczu” (wartość domyślna dla istniejących wierszy), więc
        żaden ich adres nie zmieni się sam, także gdy ktoś później przetłumaczy nazwę;
      - **nowa pozycja w języku strony** ma nazwę od początku: adres liczy się z niej i
        zamyka przy pierwszej publikacji wpisu, który ją nosi (`publish_entry`);
      - **nowa pozycja w innym języku L**: dopóki nie ma przyjętej nazwy w L, archiwum
        odpowiada pod adresem zastępczym (język strony albo klucz), niezamkniętym. Gdy
        nazwa w L zostaje przyjęta, adres liczy się z niej i zamyka — przy pierwszej
        publikacji wpisu w L albo od razu, jeśli archiwum w L już odpowiada; w tym drugim
        przypadku adres zastępczy trafia do `former_slugs` i daje jedno 308.
    - Reguła nie zależy od kolejności prac w zleceniu tłumaczenia (nazwę pozycji i wpis
      tłumaczą dwa źródła, a nazwa jest oferowana dopiero po publikacji wpisu
      źródłowego). Oddajemy: archiwum nowej pozycji w innym języku może **raz, samo**
      zmienić adres — z zastępczego na właściwy, z przekierowaniem — jeśli pierwszy wpis
      w tym języku wyszedł przed tłumaczeniem nazwy. Import ustawia nazwy i adresy przed
      publikacją (pkt 34), więc jego to nie dotyczy.
    - Zmiana po zamknięciu: tylko osoba, z powodem, z podglądem; poprzedni adres trafia
      do `former_slugs` i odpowiada jednym 308 (pkt 13). Działa od zapisu.
12. **Segment taksonomii w adresie.** Tagi: `tag` we wszystkich językach — bez zmiany
    (dług z ADR-071 pkt 14 zostaje; spłata to wiersz taksonomii dla tagów i jedno 308).
    Kategorie: słowo w języku czytelnika, zapisane w wierszu taksonomii przy jej
    utworzeniu ze słownika backendu (pl `kategoria`, en `category`, de `kategorie`,
    es `categoria`, ru `kategoriya`), zmieniane jak nazwa działu. Segment nie może być
    słowem `tag` ani segmentem paginacji żadnego języka.

### Adresy

Strona w języku polskim, typ „Realizacje” nazwany po angielsku `projects`. Żaden adres
oznaczony „jest” nie zmienia się ani o znak; pilnują tego testy złotych adresów
(`test_sites_section_addresses.py`) i ich odpowiednik dla archiwów tagów, napisany w
CT1 na dzisiejszym kodzie, zanim cokolwiek się zmieni.

| Co | Język strony (pl) | Inny język (en) | Stan |
| --- | --- | --- | --- |
| indeks typu | `/realizacje/` | `/en/projects/` | jest |
| dalsza strona indeksu | `/realizacje/strona/2/` | `/en/projects/page/2/` | jest |
| wpis | `/realizacje/dom-w-gdyni/` | `/en/projects/house-in-gdynia/` | jest |
| archiwum tagu | `/realizacje/tag/drewno/` | `/en/projects/tag/drewno/` albo, gdy pozycja ma adres angielski, `/en/projects/tag/wood/` | jest; adres per język — nowe |
| archiwum kategorii | `/realizacje/kategoria/lazienki/` | `/en/projects/category/bathrooms/` | nowe |
| dalsza strona archiwum | `…/kategoria/lazienki/strona/2/` | `…/category/bathrooms/page/2/` | jak dla tagu |
| kanał strony | `/rss.xml`, `/atom.xml` | `/en/rss.xml`, `/en/atom.xml` | jest |
| sitemapa, llms.txt | `/sitemap.xml`, `/llms.txt` | `/en/llms.txt` | jest |

Wpis ma dwa segmenty pod działem, archiwum trzy — dlatego wpis o slugu `kategoria`
niczego nie zasłania (tak samo jest dziś z `tag`). Kanału per typ wersja 1 nie ma.

13. **Jedno 308 liczy jeden resolver, w jednym przejściu.** Dzisiejsze przekierowanie
    zna tylko dawną nazwę działu; po zmianie nazwy działu **i** sluga wpisu albo pozycji
    adres `/dawny-dzial/dawny-slug/` dałby 404. Jedna funkcja rozkłada żądany adres na
    język, nazwę działu, segment taksonomii i slug, każdą część zamienia na dzisiejszą
    (dawna nazwa działu, dawny segment, dawny slug wpisu, dawny adres albo klucz
    pozycji), składa adres kanoniczny i — jeśli różni się od żądanego, a pod nim coś
    odpowiada — daje jedno 308. Zastępuje `moved_section`; ma test z kombinacjami zmian.
14. **Dawny adres jest zajęty dla automatu, a osoba przejmuje go świadomie.** Slug wpisu
    liczony kodem (`free_entry_slug`), wpis zakładany przez integrację lub asystenta i
    adres pozycji liczony przy publikacji omijają dawne adresy innych obiektów. Osoba
    może dawny adres zająć — wpisem, pozycją albo typem — ale podgląd mówi, które
    przekierowanie przestanie działać, a przejęty adres przestaje być dawnym u
    poprzedniego właściciela. Dla nazw działów to doprecyzowanie ADR-071 („żywy adres
    wygrywa”): reguła zostaje, znika tylko przejęcie po cichu.
15. **Podstrona nie zasłoni typu.** Nazwa nowego typu przechodzi dzisiejszą kontrolę
    (nie może być adresem podstrony, innego typu ani segmentem zarezerwowanym). Dochodzi
    kontrola w drugą stronę, której dziś nie ma: slug podstrony — w języku strony i w
    wersji językowej — nie może być nazwą typu w tym języku, także typu wyłączonego.

### Slugi wpisów

16. **Co jest, czego brakuje.** Jest: slug z tytułu przy utworzeniu, unikalny w (typ,
    język); adres zamrożony w migawce publikacji; 308 po zmianie nazwy działu. Brakuje
    zmiany sluga — dochodzi jedna operacja `change_entry_slug` z podglądem:
    - przed pierwszą publikacją: wolna, bez śladu;
    - po publikacji: tylko osoba, z powodem (integracja i asystent dostają
      `person_required`). Wpis publikuje się ponownie pod nowym adresem **z treścią
      bieżącej publikacji, nie szkicu** — niewydane poprawki nie wychodzą przy okazji;
      stary slug trafia do `ContentEntry.former_slugs` i odpowiada jednym 308 (pkt 13);
    - nowe wpisy i slugi liczone kodem omijają dawne slugi tego typu i języka (pkt 14).

### Wygląd, kanały, sitemapa, dane strukturalne

17. **Wersja 1 wygląda jak dzisiejszy blog.** Strona wpisu: tytuł, wiersz z datą i
    autorem, treść z bloków kreatora, a pod nią kategorie i tagi jako odnośniki do
    archiwów. Indeks i archiwa: lista wpisów (blok `core.entry_list` wypełniany przez
    serwer) z tytułem, datą i zajawką, po 10 na stronę. Przełączniki wyglądu, karty ze
    zdjęciem i blok „Lista wpisów” na dowolnej podstronie to dodatek CT6 (sekcja „Czego
    wersja 1 nie ma”).
18. **Kanał strony** niesie wpisy typów z `in_site_feed`. Istniejące działy mają „tak”,
    więc ich kanały się nie zmieniają. Nowy typ dostaje „tak”, gdy jest artykułowy
    (`BlogPosting`, `NewsArticle`, `Article`), i „nie”, gdy to `WebPage` — realizacje
    nie wpadają czytelnikom bloga do czytnika, dopóki klient tego nie zechce.
19. **Sitemapa, hreflang, x-default** — bez nowych reguł: wszystkie włączone typy;
    archiwum kategorii jak tagu — poniżej trzech wpisów (`TAG_INDEX_THRESHOLD`) odpowiada
    gościom, ale ma `noindex` i nie ma go w sitemapie; wpis łączy języki przez grupę
    tłumaczeń, archiwum pozycji — przez języki, w których ma wpisy.
20. **JSON-LD:** węzeł wpisu ma typ z `schema_type`; przy `WebPage` wpis jest samą
    stroną. Reszta grafu (firma, okruszki, znacznik tekstu AI) bez zmian.

### Dostęp: platforma, plan, limit

21. **Dwie bramki, obie sprawdzane w API.**
    - Przełącznik wdrożenia `features.contentTypes` w `deployment.json` (jak
      `publicBooking`; brak = wyłączone): czy platforma w ogóle oferuje firmom typy
      poza pierwszym.
    - Miękki limit planu `sites.content_types.additional.max` — ten sam wzór, który
      właściciel przyjął dla języków (`public_locales.additional.max`, ADR-071 pkt 7):
      plan z wartością ma limit, plan bez wartości nie ma żadnego. Typy nie są cechą
      planu.
    - **Co liczy limit:** włączone (niezarchiwizowane) typy treści na jednej stronie,
      **poza pierwszym**. Pierwszy typ — blog albo cokolwiek klient założy jako
      pierwsze — wymaga tylko `sites.enabled`, jak dziś. Wartość 0 znaczy „sam blog”.
    - Propozycja liczb, **do zmiany przez właściciela**: Profile 0, Site 1, Pro 10.
    - Subskrypcja trzyma wersję planu, którą kupiła. Subskrypcje na wersjach sprzed tej
      zmiany nie mają wartości, czyli nie mają limitu, dopóki operator ich nie przeniesie.
22. **Strażnik działa tylko przy zakładaniu i przywracaniu typu**, dokładnie jak strażnik
    języków: pyta `decide_quota` z `operation=WRITE`; brak wartości — bez limitu; limit
    wyczerpany — odmowa `quota_exceeded`; każdy inny powód (subskrypcja tylko do
    odczytu, brak migawki uprawnień, **brak definicji limitu w katalogu billing**) —
    odmowa `plan_access_denied` z powodem. Workspace platformy jest zwolniony jawnie, w
    samym strażniku, jak w limicie języków (`core/organizations/public_locales.py`).
    Obniżenie planu, wyłączenie przełącznika platformy i wygaśnięcie subskrypcji niczego
    nie zdejmują: typy ponad limit dalej odpowiadają gościom i dają się edytować; nie da
    się tylko założyć kolejnego (pytanie 2).
23. **Wyłączenie i usunięcie typu.**
    - Usunąć można tylko typ bez żadnego wpisu (także szkicu).
    - Typ z wpisami się **wyłącza** (`archived_at`): to przełącznik dostępności liczony
      przy żądaniu, jak wyłączenie języka (ADR-071 pkt 9). Nic nie jest kasowane ani
      publikowane; adresy typu odpowiadają 404, typ znika z menu, kanału i sitemapy, a
      jego wpisów nie da się edytować ani publikować (zaplanowane publikacje są
      anulowane z powodem). Nazwy działu zostają zajęte, więc **włączenie przywraca
      wszystko pod tymi samymi adresami od razu**.
    - **Dlaczego 404, a nie 410** (odpowiedź 2 właściciela, sprawdzone w kodzie
      2026-10-08). Stronę klienta rysuje strona Next.js za przepisaniem adresu w proxy;
      taka strona umie odpowiedzieć 404 (`notFound()`) i przekierowaniem, a kodu 410
      nie umie. 410 musiałoby więc paść w proxy, które — żeby wiedzieć, że adres leży
      pod wyłączonym typem — pytałoby backend przed **każdą** wizytą **każdej** strony
      klienta. Dokładnie takie pytanie zdjął pakiet PC1 razem z mapą starych adresów
      (ADR-077 pkt 5). Zostaje 404 i wszystko, co każe wyszukiwarce zapomnieć adres
      równie skutecznie: adresy typu znikają w tej samej chwili z sitemapy, z kanałów
      RSS/Atom, z `llms.txt`, z menu, z `hreflang` i `x-default` pozostałych stron, a
      żadne przekierowanie (dawna nazwa działu, adres z migawki) nie prowadzi pod
      wyłączony typ. Dla Google 404 i 410 kończą się tym samym — strona wypada z
      indeksu; 410 bywa szybsze o dni. Włączenie typu przywraca te same adresy, więc
      „nie ma na stałe” (410) byłoby też mniej prawdziwe niż „nie ma” (404).
    - Wyłączony typ nie liczy się do limitu, a przywrócenie wymaga wolnego miejsca —
      zwolnienie przywracania z limitu pozwalałoby obejść go na przemian wyłączając i
      zakładając typy. Dlatego **podgląd wyłączenia mówi, czy typ da się potem
      przywrócić** na obecnym planie; strona ponad limitem dostaje to ostrzeżenie zawsze.
    - Źródło tłumaczeń `sites.entry` i granty SCR pomijają wpisy wyłączonego typu.
    - Wyłącza i przywraca tylko osoba; dla asystenta to polecenie wysokiego ryzyka.
24. **Uprawnienia:** bez nowych. Typy, taksonomie i pozycje zakłada i zmienia
    `site.content.edit`, publikuje `site.publish` — jak dziś dział i wpis. Zmiana
    adresu, który już odpowiada gościom, oraz wyłączenie typu wymagają osoby.

### Panel

25. **Jedna pozycja menu „Treści”** (`/panel/sites/content`) tam, gdzie platforma oferuje
    typy: lista typów w `DataTable` (nazwa, adres, liczba wpisów, języki, stan), akcja
    „Nowy typ treści”, filtr „Wyłączone” z przywracaniem. Podstrony to adresy, nie
    zakładki (ADR-057):
    - `/panel/sites/content/<typ>` — wpisy typu (dzisiejszy ekran bloga);
    - `/panel/sites/content/<typ>/categories` i `…/tags` — pozycje: drzewo kategorii z
      przenoszeniem, nazwa, adresy per język z podglądem przekierowań;
    - `/panel/sites/content/<typ>/settings` — nazwa, adresy działu per język (dzisiejszy
      `collection-paths`), pola z pkt 1, wyłączenie.
    Tam, gdzie platforma typów nie oferuje, pozycja menu nazywa się dalej „Blog” i
    otwiera dzisiejszy ekran — razem z jego wyborem działu dla stron, które mają ich już
    kilka. Adres `/panel/sites/blog` działa w obu przypadkach. Odrzucone: pozycja menu
    na każdy typ (jak w WordPressie) — menu panelu jest dziś statyczną listą sekcji; to
    pytanie 1.
26. **Edytor wpisu** dostaje obok pola tagów pole kategorii (drzewo z zaznaczaniem,
    dodanie nowej w miejscu). Tłumaczenie wpisu przenosi pozycje źródła we wszystkich
    taksonomiach (dziś: tagi).

### Treść własna platformy i odczyt dla stron produktu

Decyzja właściciela z 2026-10-08: blog produktu żyje w tym systemie, dzielonym między
platformy. Strona publiczna produktu to zakodowane widoki w aplikacji produktu na hoście
platformy, nigdy renderer kreatora (memex `puppily-s-public-site-is-dedicated-coded-views-o`;
ADR-077 jest zapisem wycofanej drogi przez kreator). Trasy, stronę główną, języki,
przekierowania i sitemapę produktu daje osobny pakiet rdzenia (PR1); ten ADR ustala
tylko, o co te trasy pytają.

27. **Pisanie.** Treść własna platformy powstaje w panelu workspace'u platformy
    (ADR-077 pkt 2 i 9) — te same typy, wpisy, taksonomie, edytor, harmonogram,
    centrum tłumaczeń i publikacja co u klienta. Nie ma drugiej ścieżki zapisu.
28. **Jak workspace dostaje typy.** Nie ma planu i jest zwolniony z limitu typów (pkt
    22); przełącznik `features.contentTypes` dotyczy oferty dla firm i workspace'u nie
    obejmuje — produkt może prowadzić własne typy, nie dając ich klientom.
29. **Strona workspace'u platformy nie odpowiada przez publiczny renderer.** Każda
    strona ma zweryfikowaną subdomenę platformy, a renderer obsługuje każdą stronę z
    opublikowanym wpisem — bez tej reguły wpisy platformy miałyby drugi publiczny
    adres, z własnym canonical, sitemapą i kanałem RSS. Host strony workspace'u
    odpowiada więc 404 wszędzie: podstrony, wpisy, indeksy, kanały, sitemapa, media.
    (404, nie 308: rdzeń nie zna adresów produktu.) Panel wpisów nie ma dziś podglądu
    ani odnośnika do strony publicznej, więc operatorowi nic z panelu nie znika; ale
    między CT3 a stronami produktu opublikowany wpis platformy widać tylko w edytorze i w
    odczycie — dlatego reguła wchodzi razem z odczytem, nie wcześniej.

    **Panel bez ekranów kreatora, API otwarte (pakiet PW1, 2026-10-09).** Strony
    workspace'u nikt nie zobaczy, więc panel wydawcy nie ma ekranów, które ją budują:
    „Podstron” z edytorem (a z nim wyglądu, szablonów i biblioteki sekcji), „Menu”,
    „Publikacji” witryny, „Adresu i domen” ani „Wiadomości” (zapytań z formularza
    podstrony). Menu do nich nie prowadzi, a adres wpisany ręcznie odpowiada „Nie ma
    takiej strony” (ADR-077 pkt 9, uzupełniony). **API tych ekranów zostaje otwarte:**
    operacje na podstronach, menu, publikacji witryny i domenach odpowiadają
    workspace'owi platformy tak samo jak firmie. Odmowa oznaczałaby sprawdzanie rodzaju
    workspace'u w każdej z kilkudziesięciu operacji modułu po to, by zatrzymać coś,
    czego i tak nikt nie zobaczy — regułę „nie jest serwowane” trzyma jedno miejsce
    (`serving_locales`); osierociłaby wiersze, które workspace już ma, bez drogi do ich
    uporządkowania; a zewnętrzny automat dostawałby odmowy zależne od rodzaju
    workspace'u zamiast od swojego nadania. Skutek, który trzeba znać: kto woła API
    wprost, może w workspace platformy założyć i opublikować podstronę albo dodać domenę
    — nic z tego nie odpowie pod żadnym hostem (brama TLS nie wyda certyfikatu,
    „Uzupełnienie CT3” pkt 5). Z tego samego powodu zostaje nadanie
    `custom_domain.enabled` z `provision_platform_workspace` (ADR-077 pkt 2): jest
    martwe, a jego cofnięcie zmieniałoby odpowiedź API. Przypina to
    `tests/test_sites_publisher_builder_api.py`, z obu stron — operacje odpowiadają,
    host dalej 404. Usunięcie danych kreatora, które workspace już ma, jest osobną
    decyzją o danych, nie o panelu.

    **Czego treść potrzebuje od rekordu strony** (sprawdzone, zanim ekrany zniknęły):
    - samego rekordu — dokładnie jednego (odczyt nie zgaduje, „Uzupełnienie CT3” pkt
      3). Zakłada go ekran „Treści” przy pierwszym wejściu, pytając wyłącznie o język
      (`publisher-start.tsx`), bez subdomeny i nazwy; adres na platformie rekord dostaje
      od API sam;
    - jego `default_locale` — języka, w którym platforma pisze: od niego liczą się
      segmenty działów i grupy tłumaczeń. Ustawia się go raz, przy założeniu; żaden
      ekran go nie zmienia, także u firmy. API przyjmuje tu tylko `pl` albo `en`
      (`locale_not_seeded` — reguła szablonów kreatora), więc treść platformy też
      zaczyna w jednym z nich;
    - języków workspace'u (`Organization.public_locales`) — „Ustawienia → Języki”,
      ekran spoza „Strony internetowej”; zostaje i ma skrót na ekranie „Dziś”;
    - przyjętych tłumaczeń nazw typów, kategorii i tagów (pkt 33) — „Tłumaczenia”,
      rodzaj „Nazwy typów treści, kategorii i tagów”; zostaje.

    Publikacja wpisu nie zależy od publikacji witryny, menu, wyglądu, domeny ani
    przekierowań: `publish_entry` czyta z rekordu strony tylko `default_locale`.
30. **Odczyt po stronie serwera** — nowy moduł `shared/sites/content_reads.py`, czytający
    te same projekcje co publiczny router. **Zwraca części adresu, nigdy gotowe
    ścieżki:** adresy składa produkt, bo jego trasy mają własny kształt (na hoście
    platformy bez końcowego ukośnika, ADR-071 pkt 10).
    - wpis według typu, języka i sluga: tytuł, zajawka, autor, daty (`published_at` i
      data zmiany treści), **treść jako bloki** w kontrakcie bloków rdzenia, pozycje
      (nazwa i adres w języku czytelnika), opublikowane wersje w innych językach jako
      pary język–slug, `noindex`, znacznik tekstu AI;
    - lista według typu, opcjonalnie kategorii albo tagu, stronicowana: pozycje listy,
      liczba stron, języki, w których lista ma wpisy, i znacznik `indexable` (reguła
      „poniżej trzech wpisów” zostaje w rdzeniu, produkt ją tylko stosuje);
    - typ: nazwa i segment działu w każdym języku; drzewo pozycji taksonomii z liczbą
      wpisów. **Wyłącznie z opublikowanych migawek bez `noindex`:** pozycja, której nie
      nosi żaden taki wpis w danym języku, nie istnieje dla odczytu — ani w drzewie, ani
      z nazwą, ani w liczniku. Przypisań ze szkiców odczyt nie dotyka;
    - wykaz do sitemapy: wpisy i archiwa jako (typ, język, slug) z datą zmiany i
      wersjami językowymi;
    - węzeł JSON-LD wpisu budowany tą samą funkcją co na stronach firm, z adresu
      kanonicznego, który podaje produkt;
    - dla sluga wpisu, pozycji albo segmentu działu, który jest dawnym: odpowiedź
      „przeniesione” z dzisiejszymi częściami adresu (resolver z pkt 13) — produkt robi
      z niej jedno 308;
    - **media:** opublikowane zdjęcia są dziś serwowane tylko na hoście strony, którego
      workspace publicznie nie ma. Odczyt dostaje więc własną trasę zdjęć z tą samą
      kontrolą co dziś: zdjęcie jest dostępne tylko wtedy, gdy wymienia je bieżąca
      publikacja wpisu workspace'u. Renderery bloków budują adres zdjęcia jako
      `/media/<id>` względem hosta, więc ta trasa musi odpowiadać pod `/media/…` na
      hoście platformy — to reguła proxy po stronie pakietu tras produktu (PR1). Wpis
      niesie też fakty o zdjęciach, których renderer potrzebuje obok bloków (rozmiary,
      warianty, znacznik obrazu AI), jak odpowiedź strony firmy.
31. **Publiczne API HTTP: tak technicznie, nie jako produkt — i jeden jawny wyjątek.**
    Strony produktu renderuje serwer Next.js, osobny proces, więc odczyt jest wystawiony
    jako `GET /api/v1/public/content/…` w OpenAPI i wołany po stronie serwera. Zwraca
    wyłącznie to, co opublikowane; bez CORS, kluczy i obietnicy stabilności dla obcych.
    „Headless CMS” dla klientów byłby osobnym produktem — nikt o niego nie prosił.
    - **Punkt końcowy nie przyjmuje hosta, strony ani tenanta.** Zawsze czyta jedyny
      workspace platformy tego wdrożenia. Host nie może nazwać tenanta, bo zakodowane
      widoki stoją na `platformDomain`, który nie jest domeną żadnej strony.
    - Workspace odnajduje `platform_workspace()` — odczyt przez drzwi sprzed tenanta.
      To **wyjątek od zasady, że publiczny odczyt drzwi nie używa**, przyjmowany razem z
      tym ADR: zapytanie jest stałe (żadna dana od gościa do niego nie trafia), zwraca
      jeden identyfikator, a wszystko dalej czyta się już w tym tenancie, pod RLS.
    - Test listy drzwi liczy wiersze z `PRE_TENANT_DB` w plikach, więc nowego wywołania
      `platform_workspace()` by nie zauważył. Dochodzi test przypinający **wywołujących
      `platform_workspace()`**: lista z powodem, która pada, gdy pojawi się nowy.
32. **Co produkt bierze z rdzenia, a co jest jego.**

    | Rdzeń (wspólne) | Produkt (własne) |
    | --- | --- |
    | edytor, wersje, publikacja wpisu, harmonogram | trasy, strona główna |
    | części adresu: segment działu, slug wpisu i adres pozycji w każdym języku | złożenie adresu z tych części: prefiks języka, zagnieżdżenie, końcowy ukośnik |
    | typy, taksonomie, pozycje; zamykanie adresów i dawne adresy (dane) | odpowiedź 308 na dawny adres (z danych rdzenia) |
    | silnik i centrum tłumaczeń, kredyty, znacznik tekstu AI | nagłówek, stopka, szablony widoków |
    | kontrakt bloków i ich renderery (`@saas-core/site-blocks`), trasa zdjęć | układ strony wokół treści |
    | projekcja „co jest opublikowane”, dostępność języków, próg `noindex` | własna sitemapa i kanały (z wykazu rdzenia) |
    | węzeł JSON-LD wpisu (z adresu podanego przez produkt) | adres kanoniczny i graf strony: własne `WebSite` i `Organization` |

33. **Jedna różnica wobec strony firmy.** Wpis odpowiada także wtedy, gdy strona nie ma
    żadnej publikacji z kreatora, a dostępność jego języka liczy się z języków firmy —
    tak jest dziś. Inaczej jest z nazwami typów i pozycji w innych językach: te wychodzą
    dziś z publikacją strony (`site_texts` w migawce), której strona workspace'u może
    nie mieć. Odczyt bierze wtedy przyjęte tłumaczenia nazw wprost — tylko dla typów i
    pozycji widocznych według pkt 30. Ma własny test.
34. **Import treści — usługa operatora, nie API.** Przeniesienie gotowej treści (91
    wpisów Puppily) wymaga rzeczy, których zwykłe serwisy celowo nie dają. Powstaje
    `shared/sites/content_import.py` z komendą operatora: dokument wejściowy (typy,
    taksonomie, pozycje, wpisy per język w grupach tłumaczeń, przypisania; identyfikator
    zewnętrzny każdego obiektu), przebieg próbny z raportem, powtarzalność. Pisze przez
    te same serwisy, z trzema uprawnieniami, które ma tylko import:
    - nazwy pozycji we wszystkich językach jako **tekst od człowieka** (chroniony przed
      silnikiem) i ich adresy per język ustawione i **zamknięte przed pierwszą
      publikacją**;
    - dawne slugi wpisów i pozycji wpisane do `former_slugs` bez ponownej publikacji;
    - data zmiany treści (`changed_at`, czyli `lastmod` sitemapy) podana z zewnątrz,
      obok istniejącego już antydatowania `published_at`.
    Zamiana starego HTML na bloki zostaje po stronie produktu (rdzeń ma do tego
    `sites_convert_html`).

### SCR, asystent, centrum tłumaczeń

35. **Kontrakt `content-change-set.v1` się nie zmienia.** SCR pisze do każdego typu
    przez `collection_id`, jak dziś. Addytywnie, poza kontraktem: inwentarz dostaje przy
    typie `archived`, `schema_type` i listę taksonomii z pozycjami; zapis do wyłączonego
    typu odpowiada odmową z kodem `content_type_archived`. Przypisanie pozycji: dzisiejszy
    serwis tagów uogólniony o taksonomię (`set_entry_terms`); dotychczasowy adres API
    tagów zostaje jako jego szczególny przypadek.
36. **Asystent:** każda nowa operacja jest serwisem z typowanym wejściem, podglądem bez
    zapisu i audytem z rodzajem aktora; polecenia (`sites.content_type.*`,
    `sites.taxonomy_term.*`, `sites.entry.terms.set`) są adapterami w klasach ADR-076.
37. **Tłumaczenia — żadnej nowej ścieżki.** Wpisy każdego typu tłumaczy istniejące
    źródło `sites.entry`; nazwy typów, taksonomii i pozycji — istniejące źródło tekstów
    strony (nowe są tylko klucze `taxonomy/<id>` i pozycje kategorii pod `tag/<id>`).
    Koszty według dzisiejszych reguł kredytów. Nazwy działu i segmentu taksonomii w
    adresie wpisuje człowiek; adres pozycji liczy kod (pkt 11).

### Czego wersja 1 nie ma i gdzie to wejdzie

| Brak w wersji 1 | Miejsce w modelu | Dlaczego bez migracji treści klientów |
| --- | --- | --- |
| **Wygląd typu i blok „Lista wpisów”** (dodatek CT6): układ kart ze zdjęciem, przełączniki daty, autora i tagów; `core.entry_list` w wersji 2 z zapytaniem (typ, pozycja, liczba), wstawiany na podstronę i wypełniany przy żądaniu | `ContentCollection.presentation`; nowa wersja schematu bloku obok dzisiejszej | puste `presentation` = dzisiejszy wygląd; wersja 1 bloku zostaje dla indeksów i starszych migawek |
| **Pola własne** (cena, data, miejsce, obrazek wyróżniający) | definicje: `ContentCollection.field_schema`; wartości: `ContentEntryVersion.fields` obok `blocks`, w migawce pod `fields` | wartości są wersjonowane, publikowane i cofane razem z treścią, tą samą drogą; pola tekstowe stają się jednostkami tłumaczenia, pozostałe są kopiowane ze źródła jak tagi. Wpis bez pól to puste `fields` |
| **Szablon strony wpisu i indeksu** | lista bloków kreatora przy typie, publikowana z migawką strony | migawka wpisu dalej niesie tylko wpis, więc zmiana szablonu nie publikuje ponownie trzystu wpisów |
| **Relacje między typami** | rodzaj pola własnego: wartość to grupa tłumaczeń wpisu docelowego | dochodzi z polami, bez tabel łączących |
| **Własne taksonomie firmy** | wiersz `ContentTaxonomy` (pkt 2) | model jest od wersji 1; brakuje ekranu |
| **Kanał per typ, opis kategorii, łączenie pozycji** | adres `/<dział>/rss.xml`; tekst strony; operacja serwisu | same dodatki |

## Migracja

- **Migracje `shared.sites` zmieniają tylko schemat:** jedna nowa tabela i nowe kolumny
  z wartościami domyślnymi równymi dzisiejszemu zachowaniu. Żaden istniejący typ, wpis,
  tag, przypisanie, migawka ani tłumaczenie nie jest modyfikowane, a żadne ograniczenie
  bazy się nie zmienia (klucz pozycji zostaje unikalny w stronie, pkt 5) — kształt
  danych na VPS nie ma więc znaczenia dla bezpieczeństwa migracji. Istniejące tagi
  dostają znacznik zamknięcia adresów (pkt 11) jako wartość domyślną nowej kolumny, bez
  osobnego przejścia po danych.
- **Do tego dwie migracje danych w `shared.billing`** (wzór `0025`, odwracalne):
  definicja limitu `sites.content_types.additional.max` — bez niej strażnik odmawia
  każdemu (pkt 22), więc wchodzi w tym samym wydaniu co on — oraz nowe wersje planów z
  liczbami, w każdym produkcie, **przed** włączeniem przełącznika w profilu.
- **Odwracalność, uczciwie:** każda migracja ma drogę wstecz, ale cofnięcie migracji
  taksonomii po tym, jak klienci założyli kategorie, kasuje te kategorie i ich
  przypisania (inaczej zostałyby w tabeli jako tagi). Bezstratne jest tylko cofnięcie
  przed użyciem.
- Przed migracją na VPS faza zamykająca uruchamia tam ten sam odczyt liczący, którym
  zmierzono stosy lokalne, i zapisuje wynik w `memex ops` — dla porównania po wdrożeniu.
- Zmiany zachowania API: założenie drugiego typu na stronie wymaga odtąd przełącznika
  platformy i miejsca w limicie planu (dziś integracja mogła je założyć bez żadnej
  bramki); slug podstrony równy nazwie typu jest odrzucany (pkt 15); strona workspace'u
  platformy przestaje odpowiadać publicznie (pkt 29). Typy już istniejące zostają.

## Zmiany wcześniejszych decyzji

- **ADR-071 pkt 14** i „Uzupełnienie 2026-10-07”: adres pozycji przestaje być wspólny
  dla języków (pkt 11); długiem zostają segment `tag` i kotwice nagłówków. Jego
  „świadoma granica” o dawnej nazwie działu zostaje doprecyzowana pkt 14 (automat jej
  nie zajmie, osoba — po podglądzie), a `moved_section` zastępuje resolver z pkt 13.
- **Komentarz `ContentTag`** („celowo jedna płaska taksonomia”): zmieniony zamówieniem
  właściciela z 2026-10-08 — dochodzą kategorie per typ; tagi zostają, jakie były.
- **ADR-035 §1, §7:** bez zmiany zasady (wpis publikuje się sam, indeks jest projekcją);
  kolekcja dostaje nazwę „typ treści” i może być wyłączona.
- **ADR-070 pkt 18:** reguła „slug liczy kod, zamyka pierwsza publikacja” obejmuje
  adresy pozycji taksonomii, z zamknięciem zapisanym jak `slug_locked_at`.
- **ADR-071 pkt 7:** bez zmiany — limit typów jest drugim limitem tego samego wzoru.
- **ADR-039, ADR-041** (drzwi sprzed tenanta): jeden nowy, nazwany cel — publiczny
  odczyt treści własnej platformy (pkt 31).
- **ADR-077:** zapis wycofanej drogi; pkt 2 i 9 (workspace jako wydawca i jego panel)
  obowiązują i ten ADR na nich stoi. Dochodzi pkt 29: strona workspace'u nie jest
  serwowana przez renderer kreatora.
- **ADR-031** (katalog dziewięciu sekcji): zmieni go dopiero dodatek CT6 (blok „Lista
  wpisów”), jeśli właściciel go zamówi.

## Fazy

Szczegóły, zależności i odbiór każdej fazy: plan memex `saas-core-typy-tresci`. Dzień
znaczy tu dzień roboczy pakietu z pełną bramką, przebudową stosu i przejściem w
przeglądarce. Szacunki po przeglądzie są wyższe niż w pierwszej wersji.

| Faza | Zakres | Szacunek | Co właściciel kliknie |
| --- | --- | --- | --- |
| CT1 | Typy treści: testy złotych adresów archiwów tagów, bramki i limit (z migracją danych billing), „Treści” w panelu, nowy typ, wyłączenie, kontrola podstrona–typ (resolver jednego 308 — przeniesiony do CT2, „Uzupełnienie CT1”) | 3–5 dni | zakłada „Realizacje”, dodaje wpis, otwiera `/realizacje/` i `/en/projects/`, wyłącza i włącza typ |
| CT2 | Kategorie i tagi: taksonomia, drzewo, przypisanie, archiwa, adres per język z zapisanym zamknięciem, resolver jednego 308 (pkt 13) | 4–6 dni | kategorie w blogu i „Realizacjach”, archiwa w trzech językach, zmiana adresu kategorii z przekierowaniem |
| CT3 | Odczyt dla stron produktu: API z testami kontraktu, trasa zdjęć, strona workspace'u poza rendererem. Po pakiecie tras produktu (PR1) | 2–3 dni | nic w przeglądarce w samym rdzeniu — pierwszym kliknięciem jest strona produktu z pakietu Puppily |
| CT4 | Adres wpisu i import: `former_slugs`, zmiana sluga, usługa importu | 3–4 dni | zmienia adres opublikowanego wpisu i widzi jedno 308; przykładowy import widoczny w panelu platformy |
| CT5 | Polecenia asystenta, inwentarz SCR, `core:update` produktów, wersje planów, kolejka VPS | 2 dni | to samo w HoofCare i MedPlano; odmowa ponad limit planu |

Razem 14–20 dni (było 11–15). Po odpowiedzi 4 właściciela dochodzi do serii **CT6 —
wygląd typu i blok „Lista wpisów”** (2–3 dni, własny pakiet po CT2). Poza wersją 1:
pola własne 4–6 dni, szablony strony wpisu 5–8 dni, własne taksonomie 1–2 dni,
relacje 2–3 dni. Przeniesienie 91 wpisów Puppily i jej strony publiczne to pakiet
Puppily po CT2, CT3, CT4 i PR1.

## Stan budowy

| Faza | Stan | Gdzie |
| --- | --- | --- |
| CT1 | zbudowana 2026-10-08 | pakiet `pkg-ct1`; migracje `sites` 0053 (schemat) i `billing` 0029 (dane) |
| CT2 | zbudowana 2026-10-08 | pakiet `pkg-ct2`; migracja `sites` 0054 (schemat); sekcja „Uzupełnienie CT2” |
| CT3 | zbudowana 2026-10-08; kategorie w odczycie dołożył pakiet CT2 | pakiet `pkg-ct3`; bez migracji; kontrakt dla produktów: `docs/architecture/product-content-read.md` |
| CT4 | zbudowane 09.10 („Uzupełnienie CT4”) | migracja `sites` 0055 |
| CT5–CT6 | czekają | — |

### Uzupełnienie CT1 (2026-10-08): co kod pokazał inaczej niż projekt

Zbudowane zgodnie z punktami 1, 15, 18–25 i 28. Odstępstwa i doprecyzowania — żadne
nie zmienia tego, co firma widzi wbrew temu, co właścicielowi powiedziano:

1. **Resolver jednego 308 (pkt 13) przechodzi do CT2.** W CT1 nie powstaje żaden nowy
   rodzaj dawnego adresu (slug wpisu zmienia CT4, adres pozycji — CT2), a dzisiejszy
   `moved_section` odpowiada na każdą kombinację, która może dziś zaistnieć (dawna
   nazwa działu × adres z migawki × archiwum × dalsza strona × wyłączony język) i ma na
   to test (`test_a_renamed_section_answers_every_former_name_in_one_step`). Przepisanie
   publicznego routingu bez nowej potrzeby byłoby ryzykiem dla istniejących adresów bez
   żadnej korzyści. Jedyna zmiana: żadne przekierowanie nie prowadzi pod wyłączony typ.
2. **Kody odmów** (ADR nazywał tylko dwa pierwsze): `quota_exceeded` i
   `plan_access_denied` — 400 z listą `errors`, jak przy językach;
   `content_types_not_offered` — 400, przełącznik platformy wyłączony;
   `content_type_archived` — 409, każdy zapis do wyłączonego typu poza wycofaniem wpisu
   (wpis, publikacja, tagi, harmonogram, nazwa, adres, menu, polityka automatyzacji);
   `content_type_not_empty` — 409, usuwanie typu z wpisami; `slug_is_content_type` —
   400 z polem `slug`, podstrona pod nazwą typu.
3. **Kolejność w strażniku** (`content_type_limit.py`): workspace platformy → pierwszy
   typ strony → przełącznik → limit planu. „Pierwszy typ” znaczy „żaden inny nie jest
   włączony”, więc jedyny wyłączony typ strony zawsze da się przywrócić. Strażnik liczy
   pod blokadą wiersza strony, po sprawdzeniu powtórki idempotentnej.
4. **Kanał a `llms.txt`.** `in_site_feed` dotyczy RSS i Atom. `llms.txt` to spis tego, co
   strona mówi, nie subskrypcja — wymienia wpisy wszystkich włączonych typów.
5. **`schema_type = WebPage`:** wpis nie ma węzła artykułu; jego daty (`datePublished`,
   `dateModified`) trafiają do węzła strony. Typ czyta się przy żądaniu z wiersza typu,
   nigdy z migawki — zmiana niczego nie publikuje ponownie.
6. **Kontrola podstrona ↔ typ** (pkt 15) obejmuje wszystkie drogi, którymi osoba albo
   polecenie nadaje adres podstronie: zapis wersji językowej, zmianę adresu, szablon z
   blueprintu, polecenie asystenta i **przywrócenie usuniętej podstrony** (typ mógł
   zająć jej adres w międzyczasie — wtedy panel prosi o nowy adres). Adresy liczone
   kodem (`free_slug`) omijały nazwy działów już wcześniej.
7. **Menu.** Wpis menu wskazujący typ wyłączony albo usunięty jest pomijany przy żądaniu
   we wszystkich językach, bez publikacji strony; po włączeniu typu wraca sam.
8. **Tłumaczenia.** Źródło `sites.entry` nie wystawia wpisów wyłączonego typu i odmawia
   zamówienia ich tłumaczenia; element zlecenia, którego typ wyłączono, zanim poszedł
   do modelu, kończy się jako nieudany z kodem `content_type_archived` i nic nie
   kosztuje. To, co zlecenie już przetłumaczyło, zapisuje się normalnie, ale **nie jest
   publikowane**: krok publikacji pomija wpis wyłączonego typu (jak pomija wycofany),
   więc tłumaczenie zostaje szkicem wersji językowej, zlecenie rozlicza się i zamyka, a
   po włączeniu typu publikuje je osoba. Krok publikacji nigdy nie odmawia — działa w
   tej samej transakcji, która rozlicza kredyty zlecenia (uwaga z przeglądu:
   odmowa zatrzymywała całe zlecenie razem z jego tłumaczeniami dla innych typów).
9. **Workspace platformy** widzi w menu „Treści” zawsze (pkt 28), także na swojej
   stronie startowej panelu; jego menu nie zależy od przełącznika.
10. **API typu** (wszystko jako serwisy z podglądem i audytem; polecenia asystenta —
    CT5): `GET /sites/{site}/content-types/` (typy z licznikami, słowo bramek o
    kolejnym typie, dozwolone rodzaje treści z etykietami pl/en),
    `PUT /sites/collections/{id}/settings/` (+ `preview/`),
    `POST …/switch-off/` (+ `preview/`), `POST …/switch-on/`, `DELETE …/{id}/`.
    Zakładanie zostaje pod `POST /sites/{site}/collections/` z nowymi polami
    `schema_type` i `in_site_feed`. Typ założony w panelu „Treści” dostaje `kind=blog`
    — etykieta zostaje nietknięta (pkt 1).
11. **Przełącznik w profilach rdzenia:** `business` — włączony (lokalny stos `:8080`);
    `agro`, `core-only`, `vps-dev` — wyłączone. Włączenie na VPS i w produktach to
    faza CT5 i decyzja właściciela.

12. **Wpis wyłączonego typu można wycofać** (uwaga z przeglądu) — osoba, w panelu na
    ekranie wpisów typu albo przez API; edycja i publikacja zostają odmówione. Wycofany
    wpis nie wraca z typem. **Usuwania wpisu nie ma** — nie ma go dziś dla żadnego typu,
    włączonego ani wyłączonego — więc typu, który miał choć jeden wpis, nie da się
    opróżnić i usunąć, a jego nazwy w adresach zostają zajęte. Usuwanie wpisu to nowa,
    nieodwracalna operacja z własnymi pytaniami (historia publikacji, wersje językowe,
    adres po usunięciu) — do zaprojektowania w CT2 albo osobno.
13. **Automatyzacja nie widzi wyłączonego typu.** Inwentarz i lista działów czytane
    kluczem integracji pomijają typ wyłączony; po włączeniu wraca pod tym samym
    identyfikatorem, więc żaden identyfikator trzymany przez SeoContentRank się nie
    starzeje (dlatego pominięcie, a nie dodatkowe pole `archived`). Change set dla wpisu
    wyłączonego typu jest odmawiany już przy planowaniu (`content_type_archived`), nie
    dopiero przy zapisie. Kontrakt `content-change-set.v1` bez zmian. Panel osoby dalej
    pokazuje typ, oznaczony.
14. **Zdjęcia.** Zdjęcie wymienione przez opublikowany wpis wyłączonego typu przestaje
    odpowiadać razem z wpisem i wraca razem z nim.
15. **Nazwa typu a menu.** Zmiana nazwy działa od razu w nagłówku listy wpisów; menu
    strony nosi nazwę z ostatniej publikacji strony, więc nową pokaże po kolejnej
    publikacji — jak każda zmiana menu. Ekran ustawień i opis operacji mówią to wprost.

**Zmiany zachowania, które trzeba znać przed wdrożeniem** (przyjęte w przeglądzie):

- **Drugi dział przez API tam, gdzie przełącznik jest wyłączony** (`agro`, `core-only`,
  `vps-dev`, produkty do czasu CT5): `POST /sites/{site}/collections/` na stronie, która
  ma już włączony dział, odpowiada odtąd 400 `content_types_not_offered` — także kluczowi
  integracji z grantem na całą stronę; do dziś przechodziło. Drugie działy już założone
  działają bez zmian.
- **Przeniesienie subskrypcji na nową wersję planu** (`billing/plan_versions.py`, kod
  starszy): limit, którego stara wersja nie ma, a nowa ma, liczy się jako „podniesiony”,
  więc zbiorcze przeniesienie w tej samej cenie przeniosłoby firmę z „bez limitu” na
  Profile 0 bez kroku akceptacji obniżenia. Nic nie znika — typy działają dalej — ale
  typu wyłączonego potem nie dałoby się włączyć. To zadanie fazy CT5 (wersje planów):
  taki limit ma być traktowany jak obniżenie.
- **Wycofanie migracji `sites` 0053** kasuje `archived_at`, więc każdy wyłączony typ
  wróciłby na strony. Między migracją a restartem stary kod nie założy działu (nowe
  kolumny są `NOT NULL` bez wartości domyślnej w bazie) — backend i frontend
  restartują się razem z migracją; mówi o tym wpis w kolejce wdrożeń.

**Kto musi czytać `archived_at`** (lista dla następnych faz — nowy odczyt publiczny
dopisuje się tutaj): `published_entries`, `_find_entry`, `_find_index`,
`collections_with_entries`, `collection_links`, `moved_section`,
`_published_translations`, `site_host_company` (wszystkie w `publication_routing.py`),
pętla typów w sitemapie (`public_feeds.py`), opublikowane zdjęcia
(`public_media._published_asset_ids`), lista i krok publikacji źródła `sites.entry`,
inwentarz i lista działów dla klucza integracji, planowanie change setu, strażnik
zapisu `_assert_entry_writable`. Zawsze jako złączenie w tym samym zapytaniu
tenantowym, nigdy osobny odczyt przed nim. Nazwy typu wyłączonego zostają zajęte:
`_assert_section_names_free`, `page_slug_is_section` i `free_slug` czytają wszystkie
typy.

### Uzupełnienie CT2 (2026-10-08): co kod pokazał inaczej niż projekt

Zbudowane zgodnie z punktami 2–14, 19, 24–26 i 37, z poprawkami z przeglądu (uwagi 3–6,
10). Kod: `shared/sites/term_addresses.py` (adresy pozycji — jedyne miejsce, które je
składa; słownik strony czytany w tenancie), `taxonomies.py` (serwisy),
`public_archives.py` (archiwa, odnośniki kategorii pod wpisem, resolver),
`entry_removal.py`. Odstępstwa i doprecyzowania:

1. **Pkt 17 mylił się co do dzisiejszego bloga.** Strona wpisu nie pokazuje dziś tagów
   jako odnośników — tagi trafiają tylko do Open Graph i słów kluczowych JSON-LD. Każdy
   odnośnik zmieniałby więc istniejące strony wpisów. Odpowiedź właściciela (08.10,
   wariant a): pod wpisem są odnośniki do jego **kategorii**, a odpowiedź publiczna niesie
   `article.categories` tylko wtedy, gdy wpis ma kategorię — wpis bez kategorii odpowiada
   bajt w bajt jak dotąd. Odnośniki tagów przyjdą z przełącznikiem „pokaż tagi” w CT6.
   Wpis z `noindex` odnośników do kategorii nie pokazuje (nie ma go na listach archiwów,
   więc archiwum mogłoby nie odpowiadać).
2. **Kategorie nie mają przełącznika** (pkt 9 mówił „gdy klient je włączy”). Pierwsza
   kategoria typu zakłada jego wiersz taksonomii; nie ma stanu „kategorie włączone, żadnej
   nie ma”, którego ktoś musiałby pilnować.
3. **Nazwa taksonomii nie idzie do tłumaczenia** (pkt 11, 37 nazywały klucz
   `taxonomy/<id>`). W wersji 1 nazwy „Kategorie” gość nie widzi nigdzie, więc silnik nie
   dostaje jej do tłumaczenia i firma za nią nie płaci. Klucz zostaje zarezerwowany dla
   własnych taksonomii.
4. **Zamknięcie adresu (pkt 11) — pięć doprecyzowań.**
   - Adres w języku strony zamyka się przy pierwszej publikacji wpisu z pozycją **w
     dowolnym języku**: jest też adresem zastępczym w językach bez nazwy, więc wpis
     angielski wydany jako pierwszy inaczej pozwalałby zmianie polskiej nazwy przesunąć
     odpowiadające archiwum bez 308.
   - Razem z kategorią zamykają się adresy **kategorii nad nią**: ich archiwa pokazują
     jej wpisy, więc odpowiadają od tej samej chwili — przy publikacji wpisu i przy
     przeniesieniu kategorii, która ma opublikowane wpisy.
   - „Archiwum w L już odpowiada” czyta się z historii publikacji (także wycofanych i
     typów wyłączonych) pozycji i kategorii pod nią, nie z tego, co odpowiada w tej
     sekundzie.
   - Adres zastępczy nie jest dopisywany do `former_slugs`. Przestrzeń nazw jest jedna
     (pkt 6), więc klucz pozycji i jej adres w każdym języku prowadzą do niej jednym 308;
     `former_slugs` niesie tylko adresy, które przestały być jej adresem we wszystkich
     językach.
   - Publikacja niczego nie liczy: adres w L powstaje przy przyjęciu nazwy (pod blokadą
     wiersza strony, którą trzyma każdy zapis tekstów strony), a `publish_entry` tylko
     stempluje zamknięcie. Oba kroki nigdy nie odmawiają — zajęty adres dostaje
     przyrostek, a błąd jest logowany — bo działają w transakcji, w której zlecenie
     tłumaczenia rozlicza kredyty. Cofnięcie zlecenia po zamknięciu adresu zostawia adres.
5. **Co gość widzi, a co jest „na żywo” (pkt 10).** Istnienie pozycji dla gościa — archiwum,
   odnośnik, licznik, nazwa w publikacji strony — bierze się wyłącznie z bieżących
   publikacji wpisów (`carried_terms`); pozycji noszonej tylko przez szkic nie ma. Źródło
   tekstów strony oferuje do tłumaczenia pozycje **z migawek**, nie z przypisań szkicu
   (dotąd: z przypisań opublikowanego wpisu). Nazwa pozycji, którą publikacja niesie,
   jest czytana z wiersza także dla tagów — zmiana nazwy działa od zapisu, jak zmiana
   nazwy działu; nazwa z migawki zostaje tylko dla tagu, który nie ma wiersza. Dla
   istniejących danych obie nazwy są równe.
6. **Klucz tagu liczy dalej `tag_slug`** (składa tylko polskie litery), żeby wpisana nazwa
   znajdowała tagi sprzed tej fazy; adresy z nazw liczy `slug_from_title`. Wpisana nazwa
   jest szukana w obu zapisach. Klucz nowej pozycji omija także przestrzeń nazw swojej
   taksonomii, więc nigdy nie jest cudzym adresem ani dawnym adresem.
7. **Resolver (pkt 13)** zastępuje `moved_section` (nazwa funkcji została jako wejście, dla
   pakietu CT3). Rozkłada adres na język, nazwę typu, opcjonalnie slug wpisu albo segment
   i adres pozycji, opcjonalnie numer strony; rozpoznaje też typ pod **dzisiejszą** nazwą,
   bo dawna może być tylko dalsza część. Segment innego języka i nazwa typu z innego
   języka nie są dawnymi adresami — odpowiadają 404, jak dotąd. Kolumna
   `ContentEntry.former_slugs` powstała tutaj (resolver ją czyta); pisze ją dopiero
   zmiana adresu wpisu w CT4, razem z regułą pkt 14 dla slugów wpisów.
8. **Dawna nazwa typu (pkt 14).** Założenie albo przemianowanie typu na nazwę, która dziś
   tylko przekierowuje do innego typu, odpowiada `section_path_former`; integracja i
   asystent nie przejmą jej nigdy, osoba — po podglądzie (`takes_over`) polem
   `take_over_former`. Przejęta nazwa przestaje być dawną we wszystkich językach, którym
   służyła. Pierwszy adres wpisu zapisany w jego migawce prowadzi do wpisu dalej
   (ADR-071), dopóki nowy typ czegoś pod nim nie opublikuje.
9. **Kody odmów:** `term_name_invalid`, `term_name_taken` (ta sama nazwa obok),
   `term_kind_invalid`, `term_parent_invalid`, `term_too_deep`, `term_slug_invalid`,
   `term_slug_taken`, `term_slug_former`, `term_not_of_type`, `locale_not_enabled`,
   `redirect_reason_required`, `taxonomy_segment_invalid`, `taxonomy_segment_reserved`,
   `taxonomy_segment_source_locale`, `section_path_former`, `confirmation_required` — 400
   z polem; `entry_too_many_categories` — 400; `term_in_use` — 409;
   `taxonomy_term_not_found`, `taxonomy_not_found` — 404.
10. **API** (serwisy z podglądem i audytem; polecenia asystenta — CT5):
    `GET|POST /sites/collections/{typ}/terms/` (`kind=categories|tags`),
    `PATCH|DELETE …/terms/{id}/` (+ `preview/`, `removal/preview/`), `PUT …/terms/{id}/names/`,
    `PUT …/terms/{id}/address/` (+ `preview/`), `PUT …/category-segments/` (+ `preview/`),
    `GET|PUT /sites/entries/{id}/categories/`, `DELETE /sites/entries/{id}/`
    (+ `removal/preview/`), `POST /sites/collections/{typ}/removal/preview/`;
    `DELETE /sites/collections/{typ}/` przyjmuje `confirm_name`. Adres API tagów wpisu bez
    zmian. Słowo „kategoria” w adresach zmienia się przez API; panel wersji 1 tego nie
    pokazuje („tylko przydatne opcje”).
11. **Usuwanie wpisu** (zostawione przez CT1; odpowiedzi właściciela 2a i 3a z 08.10).
    Osoba usuwa wpis — jedną wersję językową — po potwierdzeniu. Wpis dostaje stan
    `removed` i znika w tej samej chwili z każdego odczytu: `ContentEntry.all_objects`
    pomija usunięte, a czyta nim publiczny router, panel, liczniki, źródła tłumaczeń i
    inwentarz integracji. Adres odpowiada 404 jak po wycofaniu. Wiersze zostają jako
    historia (wersje, publikacje, przypisania), jak po usuniętej podstronie; slug, miejsce
    w grupie tłumaczeń i klucz utworzenia są zwalniane. Przycisku „przywróć” nie ma:
    przywrócenie to zmiana stanu na szkic, nadanie wolnego sluga i dopięcie do grupy z
    wpisu audytu `sites.entry.removed`. Wersja zrobiona przez zlecenie tłumaczenia może
    przy kolejnym zleceniu powstać ponownie — potwierdzenie mówi o tym i radzi wycofanie.
    **Kasowanie:** typ, którego wszystkie wpisy są usunięte, da się usunąć; to kasuje na
    stałe te wpisy z wersjami, publikacjami i ich zdarzeniami. Tylko osoba (nigdy klucz
    ani asystent), po wpisaniu nazwy typu (`confirm_name`); wpis audytu
    `sites.content_type.deleted` niesie liczby i tytuły skasowanych wpisów.
12. **Zlecenie tłumaczenia a usunięcie.** Źródło `sites.entry` czyta wpis razem z
    usuniętymi: zapis zlecenia dla wpisu usuniętego po odczycie dostaje odmowę
    `withdrawn`, a krok publikacji go pomija — bez wyjątku w transakcji rozliczenia.
    Zamówienie tłumaczenia usuniętego wpisu odpowiada 404. Pozycja zmieniona albo
    usunięta między odczytem a zapisem zlecenia tekstów strony daje konflikt
    `source_changed` dla tej strony i języka i nie rusza żadnego adresu.
13. **Pomiar (ryzyko „projekcja czyta wszystkie wpisy”).** 1 001 wpisów w typie i 2 002 na
    stronie, baza testowa na tej maszynie: indeks typu 230 ms, archiwum kategorii 231 ms,
    archiwum tagu 234 ms, wpis 124 ms, sitemapa 157 ms. Indeks i archiwa czytają odtąd
    tylko swój typ (`published_entries(collection_id=…)`). Nie zmienione: każde żądanie
    spoza podstron przechodzi wszystkie opublikowane wpisy strony z pełnymi migawkami
    (`_find_entry`, ok. 110 ms na 2 000 wpisów) — do zawężenia po slugu z migawki w
    osobnej zmianie.
14. **Migracja `sites` 0054** — sam schemat: tabela `sites_contenttaxonomy` z wymuszonym
    RLS, kolumny pozycji i `ContentEntry.former_slugs`, każda z wartością domyślną **w
    bazie**, więc kod sprzed migracji zakłada tagi także między `migrate` a restartem
    (inaczej niż 0053). Dzisiejsze tagi i tagi zapisane starym kodem czytają się jako
    zamknięte na kluczu we wszystkich językach (`LEGACY_TERM_LOCK`). Wycofanie najpierw
    kasuje kategorie i ich przypisania (zostawione czytałyby się jako tagi), potem
    kolumny — bezstratne tylko przed pierwszą kategorią.
15. **Świadkowie.** `tests/golden/sites_blog.json` bez zmiany bajtu; drugi plik,
    `tests/golden/sites_sections.json`, napisany na kodzie sprzed tej fazy (dwa działy,
    nazwy per język, dawne nazwy i ich 308, wpis `noindex`, archiwa poniżej progu, adresy,
    które mają dalej odpowiadać 404). Oba testy tworzą tagi dzisiejszym kodem, więc ich
    przygotowanie oznacza je jako starsze od migracji (jedna linia) — to dokładnie stan
    każdego istniejącego tagu. Dwa testy `test_sites_blog_languages` mówią teraz, co robi
    tag założony dziś: angielskie archiwum pod angielską nazwą i jedno 308 ze starego adresu.
16. **Ręczne dodanie wersji językowej wpisu** nie kopiuje pozycji — jak dotąd; kopiuje je
    zlecenie tłumaczenia (wszystkie taksonomie, bez zmiany kodu).
17. **Nazwa pozycji wpisana w panelu jest publikowana od razu**, jeśli osoba ma prawo
    publikacji — inaczej niż w „Tekstach strony”, gdzie zapis i publikacja są osobne.
    Powód: adres z tej nazwy działa od zapisu (pkt 11), więc tytuł archiwum pod nowym
    adresem nie powinien czekać na osobny krok. Publikowany jest tylko ten jeden tekst i
    tylko dla pozycji, którą niesie jakaś publikacja; bez prawa publikacji nazwa wychodzi
    z następną publikacją strony.
18. **Kolejka przeglądu tłumaczeń po usunięciu wpisu.** Usunięcie wpisu zamyka w kolejce to,
    co na niego czekało do akceptacji (`review_decided`); pytanie „czy zdjąć też
    tłumaczenia” po usunięciu opublikowanego oryginału zostaje i działa — tłumaczenia są
    odnajdywane po `translation_of`, bo usunięty wpis opuścił grupę. Decyzja w sprawie
    wpisu skasowanego razem z typem dostaje odpowiedź „konflikt” i pozycja kolejki się
    zamyka; zapis zlecenia dla takiego wpisu dostaje odmowę, nie wyjątek.
19. **Nazwa „Blog” w menu a strony kategorii.** Tam, gdzie platforma nie oferuje typów
    poza pierwszym, „Kategorie” i „Tagi” bloga stoją pod `/panel/sites/content/<blog>/…`
    i należą do pozycji „Blog” (pole `under` w `PANEL_SECTIONS`) — kategorie ma każdy
    blog na każdej platformie (pkt 9).
20. **Kategorie w odczycie dla stron produktu** (zostawione przez CT3, dołożone tutaj, bo
    na nich stanie blog Puppily): `content_reads` nazywa i adresuje pozycje słownikiem
    strony (`site_vocabulary`) — taksonomia `category` w `read_terms` z drzewem przez
    `parent_slug` i licznikami razem z podrzędnymi, pozycje wpisu z `terms` migawki,
    lista po kategorii z wpisami podrzędnych, adres pozycji per język i `moved` dla
    każdej innej nazwy pozycji (klucz, adres z innego języka, dawny adres), listy
    kategorii w wykazie sitemapy. Istnienie, liczniki i nazwy — jak dla tagów — tylko z
    opublikowanych wpisów bez `noindex`. Kontrakt: `product-content-read.md` §4.2–4.3, §10.

Po przeglądzie przed scaleniem (2026-10-09):

21. **Słownikiem zarządza osoba.** Założenie, zmiana nazwy, przeniesienie, kolejność i
    nazwy pozycji w językach odmawiają kluczowi integracji (w każdym trybie grantu) i
    asystentowi (`person_required`, także w podglądzie): nazwa i miejsce w drzewie
    pokazują się gościom od razu, a klucz w trybie propozycji nie może zmieniać tego, co
    publiczne, bez osoby. Wejście dla asystenta i integracji z podglądem — CT5.
    Przypisanie wpisu do kategorii i tagów zostaje przy regule wpisu (jak tagi dotąd):
    goście widzą je dopiero z publikacją wpisu, bo archiwa czytają migawki, nie przypisania.
22. **Kasowanie z typem wymaga więcej niż edycji treści.** Usunięcie typu, które kasuje
    usunięte wpisy, wymaga prawa publikowania — tak jak zdjęcie opublikowanego wpisu — i
    niesie liczbę usuniętych wpisów pokazaną w podglądzie; gdy w transakcji jest ich
    inna liczba (ktoś usunął wpis między podglądem a potwierdzeniem), nic nie znika i
    osoba potwierdza jeszcze raz (`confirmation_stale`).
23. **Usunięcie wpisu zamyka czekające propozycje integracji** jako odrzucone, każdą z
    własnym wpisem w historii (`sites.proposal.closed`, powód `entry_removed`) — inaczej
    zostałyby w kolejce na zawsze, bo akceptacja i odrzucenie szukają wpisu.
24. **Jedna kolejność blokad pozycji.** Każda zmiana słownika blokuje cały słownik strony
    jednym zapytaniem w kolejności identyfikatorów; publikacja — to, co niesie, w tej
    samej kolejności; przypisanie wpisu nie blokuje pozycji. Zostaje (pierwszy następny
    krok w planie): transakcja, która publikuje **kilka** wpisów (publikacja oryginału
    z tłumaczeniami, zlecenie tłumaczenia), bierze pozycje partiami i druga partia może
    sięgnąć po starszą pozycję niż pierwsza — z równoczesną zmianą słownika albo drugą
    taką publikacją baza przerwie jedną z nich.
25. **Trzeci świadek.** Oba testy złotych plików mają wariant „publikacje bez `terms`” —
    tak wygląda każda publikacja starsza od tej fazy — i odpowiadają tymi samymi plikami.

**Kto musi o tym pamiętać** (lista dla następnych faz):

- Każdy publiczny odczyt `sites_contenttag` i `sites_contenttaxonomy` idzie przez
  `site_vocabulary` (ustawia tenanta z hosta w tej samej transakcji); test kolejności
  zapytań `test_a_visitors_reads_of_terms_set_the_tenant_the_host_named_first`.
- „Tagi” znaczą `site_tags()` (pozycje bez taksonomii): migawka `tags`, archiwum tagu,
  `article.tags`, słowa kluczowe, pole tagów wpisu.
- Wpisy czyta się przez `ContentEntry.all_objects`; `with_removed` tylko w usuwaniu,
  kasowaniu i w źródle tłumaczeń `sites.entry`. Złączenia przez relacje (`entry__…`) nie
  przechodzą przez menedżera — tam, gdzie liczą, wykluczają stan `removed` jawnie.
- Pozycje blokuje się zawsze w kolejności identyfikatorów, jednym zapytaniem i
  `FOR NO KEY UPDATE`: zmiana słownika — cały słownik strony (`lock_vocabulary`),
  publikacja — to, co niesie (`terms_to_close`); wiersz strony przed wpisem. Kod, który
  tylko przypisuje wpis, wierszy pozycji nie blokuje.
- Nowa operacja na słowniku zaczyna od `assert_person_required(…, TERM_MANAGE_GATE)`,
  dopóki CT5 nie da asystentowi i integracjom wejścia z podglądem.
- Adres archiwum składa tylko `term_archive_path`; odczyt dla stron produktu (CT3)
  bierze z niego części, a „przeniesione” z `moved_address`.

### Uzupełnienie CT3 (2026-10-08): odczyt dla stron produktu — co kod pokazał inaczej niż projekt

Zbudowane punkty 29–33 poza kategoriami (CT2 buduje je równolegle). Kontrakt, z którego
produkt przenosi swoje widoki: [`docs/architecture/product-content-read.md`](../architecture/product-content-read.md).
Odstępstwa i doprecyzowania:

1. **Typ pyta się po kluczu, nie po nazwie działu (zmiana pkt 30).** Tabela adresów
   produktu (ADR-080) nazywa sekcje sama, na sztywno, per język; nazwę działu typu da
   się zmienić w panelu. Odczyt pytany o segment zamieniałby strony produktu w 404 po
   takiej zmianie. Klucz typu jest stały. `segments` typu wracają jako informacja;
   **dawnego segmentu działu odczyt nie obsługuje** — zmiana nazwy sekcji u produktu
   to jego tabela i jego `old-addresses.ts`. „Przeniesione” dotyczy więc sluga wpisu
   i adresu pozycji.
2. **Co dziś daje „przeniesione”.** Jedno źródło: wpis w języku, który workspace
   wyłączył — odpowiedź wskazuje wersję w języku strony (albo pierwszą, jaką wpis ma),
   tak jak renderer strony firmy daje wtedy 308 (ADR-071 pkt 9). Dawny slug wpisu (CT4)
   i dawny adres pozycji (CT2) dojdą bez zmiany kształtu: wpis i lista odpowiadają
   kopertą `{ entry | list, moved }` już teraz.
3. **Drzwi: `platform_workspace_id()`, nie `platform_workspace()` (zawężenie pkt 31).**
   Nowa funkcja w `core/organizations/platform_workspace.py` wybiera **samą kolumnę
   `id`** i pyta po rodzaju workspace'u **oraz** po slugu wyliczonym z wdrożenia
   (`platform-<DEPLOYMENT>`): do ścieżki publicznej nie trafia żaden wiersz wczytany
   poza politykami, a workspace innego wdrożenia w tej samej bazie nie jest czytany.
   Bez pamięci w procesie. Dalej wszystko czyta się w tym tenancie. Workspace musi mieć
   dokładnie jedną stronę — przy żadnej albo kilku odczyt nie zgaduje, tylko nic nie
   oddaje.
4. **Test przypinający wywołujących (uwaga 12).** `test_pre_tenant_door.py` ma listę
   `DECLARED_WORKSPACE_LOOKUPS` (dziś: port modeli i `content_reads.py`, każdy z
   powodem). Wykrywa moduł, który nazwę odnalezienia **importuje** (także przez moduł
   pośredni), bierze cały moduł definiujący, sięga po nią jako atrybut albo zapisuje ją
   w napisie — osobny test trzyma wykrywacz przy tych sposobach. Pięć plików
   publicznego renderera nie może nazwać odnalezienia wcale. Liczba linii
   `PRE_TENANT_DB` w module definiującym wzrosła z 2 do 3, z powodem. Policzone są też
   moduły importujące sam odczyt (`content_reads`): tylko jego widoki i ich
   serializery — drugi wywołujący przeniósłby wyjątek tam, gdzie nikt go nie sprawdził.
   Czego wykrywacz nie zobaczy: nazwy złożonej dopiero w czasie działania.
   **Od PR1c** (ADR-080, „Uzupełnienie PR1c” pkt 2) ta sama lista liczy też blok
   `in_platform_workspace()`: moduł wertykału produktu woła go bez wpisu i nigdy nie
   nazywa odnalezienia, moduł rdzenia potrzebuje wpisu za jedno i za drugie.
5. **Reguła pkt 29 stoi w jednym miejscu: `serving_locales`.** Przez nią przechodzą
   wszystkie odczyty hosta — strony i wpisy, podpowiedź 404, kanały, sitemapa,
   `robots.txt`, `llms.txt`, media, formularz kontaktowy — więc host strony workspace'u
   odpowiada jak host nieznany. Dochodzą dwa skutki tej samej reguły: brama TLS nie
   wyda **nowego** certyfikatu dla takiego hosta (decyzja sprzed zmiany żyje do końca
   swojej pamięci podręcznej), a bramka hostów nie przepuści tam odczytów formularza
   rezerwacji. Panel wydawcy dalej podgląda swoje strony (`publisher=True` w podglądzie
   SEO) — reguła dotyczy hostów, nie panelu. `publisher=True` ma dwóch wywołujących
   (odczyt i ten podgląd), policzonych testem: trzeci serwowałby workspace gdzieś, gdzie
   nikt tego nie sprawdził.
6. **Strona workspace'u z opublikowanymi podstronami.** Wiersze zostają nietknięte
   (publikacje, podstrony, domeny); przestają być serwowane od wdrożenia. Lokalny stos
   Puppily ma taką stronę — jej adresy `<etykieta>.<platformDomain>` odpowiedzą 404.
   **Panel wydawcy nie pokazuje adresu tej witryny i nigdzie do niej nie prowadzi**
   (uwaga właściciela z 08.10, po wejściu do panelu na stosie Puppily): karta strony
   na ekranie startowym nie ma adresu ani „Otwórz opublikowaną stronę” i mówi, że
   wpisy pokazuje serwis pod hostem produktu (albo — gdy produkt nie ma własnych stron
   — że witryna nie ma własnego adresu); ekrany „Strona internetowa” nie piszą hosta
   przed adresem typu i nie linkują opublikowanych podstron ani wersji językowych
   (`usePublisher` w `sites-panel.tsx`); „Widoczność w wyszukiwarkach” nie dostaje od
   API żadnego adresu (`read_search_visibility`). Panel firmy bez zmian — pilnują tego
   jego dotychczasowe testy. Ekrany kreatora u wydawcy („Podstrony”, „Menu”,
   „Wygląd”, „Adres i domeny”, publikacja witryny) zdjął z panelu pakiet PW1
   (2026-10-09) — pkt 29, akapit „Panel bez ekranów kreatora, API otwarte”; ekrany,
   które zostały („Treści”, „Tłumaczenia”, „Integracje”), nie pokazują też linii ze
   stanem witryny, a „Tłumaczenia” nie wymieniają ani nie zamawiają podstron.
7. **Nazwy w innych językach zawsze wprost (rozszerzenie pkt 33).** Punkt mówił
   o stronie bez publikacji kreatora; po pkt 29 publikacja strony workspace'u niczego
   już nie wydaje, więc odczyt bierze przyjęte tłumaczenia nazw typów i pozycji wprost
   także wtedy, gdy taka publikacja istnieje — z tą samą regułą, co publikacja strony
   firmy (`shown_texts`), i tylko dla tego, co nosi wpis z listy.
8. **Co „istnieje dla odczytu”.** Typ — gdy ma wpis na liście (opublikowany, bez
   `noindex`, w języku workspace'u); pusty typ, typ wyłączony i typ, którego nie ma,
   odpowiadają tym samym 404. Pozycja — jak w pkt 30. Wpis z `noindex` odpowiada pod
   własnym adresem (jak na stronie firmy), ale nie ma go na liście, w liczniku
   ani w sitemapie i **nie użycza pozycji**: wśród jego `terms` są tylko te, które
   niesie także wpis z listy.
9. **JSON-LD: własne węzły wpisu, nie jeden węzeł.** `page_graph` (ta sama funkcja co
   na stronach firm, niezmieniona) liczy graf z adresu podanego przez produkt
   (`canonical_url`), a odczyt oddaje z niego węzły wpisu: `WebPage` (także `FAQPage`,
   gdy treść ma pytania — sam węzeł artykułu zgubiłby je) i artykuł. `WebSite`
   i `Organization` pisze produkt pod identyfikatorami, które te węzły wskazują.
   `canonical_url` przechodzi kontrolę kształtu (pełny `http(s)` **na hoście
   platformy**, bez danych logowania, zapytania, fragmentu i znaków zamykających
   cudzysłów albo znacznik; adres, którego parser nie czyta, to 400, nie 500) i służy
   tylko do złożenia identyfikatorów. Bez
   `translationOfWork` — rdzeń nie zna adresu wersji źródłowej u produktu.
10. **Zdjęcia.** `GET /api/v1/public/content/media/<id>/[<wariant>/]` oddaje zdjęcie
    tylko wtedy, gdy wymienia je bieżąca publikacja wpisu workspace'u we włączonym
    typie i w języku, który workspace ma włączony (zdjęcie odpowiada tam, gdzie jego
    wpis) — nie zdjęcia podstron kreatora workspace'u (nikt ich nie pokazuje) ani
    źródeł rekordów na żywo. Frontend odpowiada pod `/media/<id>` i dwoma kopiami WebP
    na hoście platformy (reguła w `proxy.ts`, trasa `app/media/…`); to origin panelu,
    więc trasa oddaje wyłącznie JPEG, PNG i WebP, z `nosniff` i CSP `default-src 'none';
    sandbox`, i odmawia hostom innym niż platformy. Strony firm i ich `/media/…` — bez
    zmian (`proxy.golden.json`, `metadata.golden.json` nietknięte).
    **Zmienione przez ADR-080, „Uzupełnienie PR1c” pkt 1:** kopię — nigdy oryginał —
    zdjęcia rekordu na żywo, które zadeklarowało źródło publiczne workspace'u, ta
    trasa oddaje (jak strona firmy od ADR-074).
11. **Punkt końcowy tylko na hostach platformy.** Trasy `/api/v1/public/content/…` nie
    ma na liście tras czytanych przez host strony firmy (`http/hosts.py`), więc pod
    hostem spoza `ALLOWED_HOSTS` — także strony firmy — odpowiada 400, jak API panelu.
12. **Listy bez treści.** Nazwy pozycji w innym języku pyta się raz na odpowiedź, nie
    raz na wpis: koszt strony listy nie rośnie z liczbą wpisów na niej (ma test).
    Lista, liczniki i sitemapa czytają z migawek same fakty
    (tytuł, slug, pozycje, daty) wszystkich opublikowanych wpisów strony; treść czyta
    się tylko dla wpisów bieżącej strony listy (pierwsze zdjęcie). Test trzyma tę
    projekcję przy projekcji routera (`published_entries`): te same wpisy, ta sama
    kolejność.
13. **Na frontendzie.** `#lib/product-site/content` (klient tylko dla serwera, wyniki
    `entry | moved | not-found`, `contentVersions` i `contentSitemapEntries` łączące
    części adresu z tabelą produktu) oraz `#components/site-entry-body` (bloki rdzenia
    bez strony wokół; `renderPublishedBody` w `@saas-core/site-blocks`, opakowanie
    `.site-theme--embedded`). Formularz kontaktowy i bloki rekordów na żywo są w treści
    pomijane. Odnośniki w treści wracają tak, jak je napisano.

**Czego testy nie dowodzą** (baza testowa łączy się właścicielem tabel i omija RLS):
że rola aplikacji widzi wiersze tagów (`sites_contenttag`), tekstów strony
(`sites_sitetexttranslation`), mediów (`media_mediaasset`) i organizacji
(`organizations_organization`) workspace'u — i tylko jego. Test trzyma to, co widać
mimo wszystko: każde zapytanie do tabel bez polityki (`sites_site`, `sites_contententry`,
`sites_contentcollection`, `sites_contententrypublication`) nazywa workspace, żadne nie
nazywa innej firmy, a `SET LOCAL` stoi przed każdym odczytem tabeli z polityką,
w tej samej transakcji. Resztę sprawdza się po scaleniu na uruchomionym stosie, pod
rolą aplikacji.

**Kategorie w odczycie** dołożył pakiet CT2 („Uzupełnienie CT2” pkt 20): taksonomia
`category` w `read_terms` (drzewo przez `parent_slug`), pozycje wpisu z `terms` migawki,
lista po kategorii z wpisami kategorii podrzędnych, adres pozycji per język i `moved`
dla każdej innej nazwy pozycji, listy kategorii w wykazie sitemapy.

### Uzupełnienie PW1 (2026-10-09): panel wydawcy bez ekranów kreatora

Decyzja i jej powody stoją w pkt 29; co panel wydawcy oferuje — w ADR-077 pkt 9. Tu to,
co wyszło dopiero przy przejściu panelu w przeglądarce, i to, co zostało świadomie:

1. **Ekrany, które zostały, nie prowadzą do tych, których nie ma.** Dwa miejsca wyszły
   dopiero w przeglądarce. „Historia zmian” linkowała każdy wiersz o podstronie, witrynie
   i domenie do ekranu kreatora (adres podaje API, `history_targets.py`): u wydawcy
   wiersz mówi, czego dotyczył, i nigdzie nie prowadzi (`goneForPublisher` w
   `panel-navigation.ts` — jedna lista adresów, których panel wydawcy nie ma).
   „Ustawienia typu treści” miały dwa przełączniki, które czyta wyłącznie strona
   kreatora — udział w kanale RSS strony (`in_site_feed`) i „Pokaż w menu strony”,
   czekające na publikację witryny, której wydawca nie ma jak zrobić: u wydawcy nie są
   rysowane (odczyt dla stron produktu żadnego z nich nie oddaje; menu i kanały
   produktu są jego własne, pkt 32). Typ dla wyszukiwarek (`schema_type`) zostaje.
2. **Słowa.** Wpis menu i nagłówki zachowanych ekranów mówią u wydawcy „Treści
   platformy”; „Dziś” mówi, co platforma napisała, nie w jakim stanie jest strona;
   „Języki” mówią o językach treści i o „języku źródłowym treści”; opublikowany wpis
   jest w „Tłumaczeniach” „Opublikowany”, nie „Na stronie”. Słowa wewnątrz ekranów
   treści wspólne z firmami („Wpisy bloga” jako rodzaj, „Otwórz blog”, „na stronie”
   w podpowiedziach edytora wpisu) zostają.
3. **Zostało świadomie.** Blok formularza kontaktowego i bloki rekordów na żywo są
   nadal w bibliotece sekcji wpisu, choć strony produktu je pomijają („Uzupełnienie
   CT3” pkt 13). „Zlecenia” i „Do akceptacji” mogą wymieniać podstronę kreatora,
   jeśli workspace takie ma i ktoś zamówił ich tłumaczenie wcześniej — pozycja nie
   prowadzi wtedy do edytora; „Przetłumacz brakujące” podstron nie zamawia. Adresy
   działu per język („Adres w każdym języku”) zostają: odczyt oddaje je jako
   informację, a wpis nadal nosi swój adres.

### Uzupełnienie CT4 (2026-10-09): adres wpisu i import — co kod pokazał inaczej niż projekt

Zbudowane punkty 13 (część wpisu), 14, 16 i 34. Kod: `shared/sites/entry_addresses.py`
(zmiana adresu, dawne slugi), `content_import.py` z `content_import_schema.py` i komendą
`sites_import_content`. Kontrakt importu: [`docs/architecture/content-import.md`](../architecture/content-import.md).

1. **Zmiana adresu wpisu (pkt 16).** `change_entry_slug` z podglądem (`dry_run`):
   - przed pierwszą publikacją — wolna, bez śladu, także dla klucza integracji w granicach
     grantu; po niej — tylko osoba (`person_required`, także w podglądzie), a gdy wpis
     dziś odpowiada — z powodem (`redirect_reason_required`) i z prawem publikowania;
   - wpis opublikowany wychodzi ponownie **z migawką bieżącej publikacji**, w której
     zmieniają się tylko slug i adres: treść, tytuł, pozycje, `version` i `changed_at`
     zostają, szkic nie jest dotykany. Silnik tłumaczeń nie dostaje powiadomienia (tekst
     się nie zmienił), a tłumaczenia nie są publikowane „za źródłem”;
   - podgląd mówi: nowy adres, co przekieruje (`moved`, `redirects`), czyje przekierowanie
     przestanie działać (`takes_over`) i czy w szkicu są niewydane zmiany
     (`unpublished_changes`);
   - wpis wycofany, który kiedyś odpowiadał, też zostawia dawny slug (może wrócić), ale
     powodu nie wymaga. Wpis pamięta najwyżej 50 dawnych slugów.
   API: `GET|PUT /sites/entries/{id}/address/`, `POST …/address/preview/` — tylko sesja.
   Kody: `entry_slug_invalid`, `entry_slug_taken`, `entry_slug_former`.
2. **Czyje dawne slugi się liczą (pkt 14).** Slug, pod którym wpis tego typu i języka
   kiedyś odpowiadał, jest zajęty dla kodu (`free_entry_slug`: tłumaczenia, import) i dla
   **każdego** nowego wpisu (`create_entry`, ręczna wersja językowa: `entry_slug_former`).
   Osoba przejmuje go zmianą adresu, po podglądzie, polem `take_over_former`; przejęty
   slug znika z dawnych u poprzedniego właściciela. Wpis **usunięty** niczego nie trzyma
   (jego wiersz jest przemianowany i nikt go nie czyta); wpis **wycofany** trzyma swoje.
3. **Resolver (pkt 13).** Bez nowej funkcji: `moved_address` czytał `former_slugs` od CT2.
   Doszła jedna reguła — **żywy adres wygrywa**: gdy pod slugiem odpowiada wpis typu
   i języka, slug znaczy ten wpis, cokolwiek mówi historia innego. Test kombinacji:
   dawna nazwa typu + dawny slug wpisu w `/en/…` i dawna nazwa typu + dawny segment
   + dawny adres kategorii — zawsze jedno 308; slug jednego języka nie jest adresem
   w drugim; język wyłączony prowadzi od razu do wersji w języku strony.
4. **Wpis szukany po slugu, nie przez wszystkie wpisy strony** (dług z CT2 pkt 13).
   Adres wpisu kończy się jego slugiem, a wiersz opublikowanego wpisu niesie slug
   swojej publikacji (zmienia go tylko `change_entry_slug`, który publikuje w tej samej
   transakcji), więc `_find_entry` pyta o `slug = <ostatni segment>` i dopiero kandydatów
   porównuje pełnym adresem. Pomiar na 2 002 opublikowanych wpisach strony (baza
   testowa tej maszyny, mediana z 20 prób): samo przejście po wpisach 121 ms → całe
   odnalezienie wpisu 5,8 ms; adres, który nie jest wpisem (indeks, archiwum, 404) na
   tym kroku 120 ms → 1,9 ms. Przed wdrożeniem trzeba sprawdzić, że żaden opublikowany
   wpis nie ma w wierszu innego sluga niż w migawce (zapytanie w `memex ops`); lokalne
   bazy czterech stosów (rdzeń, HoofCare, MedPlano, Puppily, 09.10): 0 takich wierszy
   na 15 opublikowanych wpisów.
5. **Odczyt dla stron produktu.** `read_entry` odpowiada `moved` z dzisiejszym slugiem
   dla dawnego sluga, tą samą regułą (żywy pierwszy; język wyłączony — jeden krok do
   wersji czytanej). Kontrakt §9.
6. **Ręczna wersja językowa kopiuje kategorie i tagi oryginału** (zostawione przez CT2
   pkt 16) — przy utworzeniu, jak wersja zlecenia tłumaczenia.
7. **Daty.** Atom `<updated>` podaje odtąd chwilę zmiany tekstu (`changed_at` migawki),
   jak `lastmod` sitemapy i `dateModified` — nie chwilę ostatniej publikacji: zmiana
   adresu i import publikują teksty, które tego dnia się nie zmieniły. Oba złote pliki
   bez zmiany bajtu.
8. **Import (pkt 34)** — reguły dla autora dokumentu są w kontrakcie; tu decyzje:
   - **Dwa kroki.** Plan czyta i niczego nie zapisuje (to jest przebieg próbny: żadnego
     `INSERT`/`UPDATE`, żadnego pliku w magazynie, żadnego pytania do skanera — test
     liczy wiersze wszystkich tabel przed i po); zapis wykonuje plan przez serwisy
     panelu, jako operator.
   - **Księga `ContentImportRecord`** (nowa tabela, wymuszone RLS, migracja `sites`
     0055): identyfikator zewnętrzny → obiekt, skrót każdego pola, które import
     zapisał, numer zapisanej wersji tekstu, pochodzenie pól i odciski źródeł dosłownie.
     Klucz idempotencji serwisów do tego nie służy: jest unikalny per autor, a jego
     skrót obejmuje tytuł.
   - **Edycja człowieka wygrywa.** Wartość, która nie jest już tym, co zapisał import,
     zostaje (`kept`); wpis z czymkolwiek od człowieka import przestaje publikować;
     `--overwrite-edits` odwraca to dla nazwanego wpisu.
   - **Pochodzenie tekstu** jest przy wersji: `ContentEntryVersion.units` niesie dla
     wersji z importu klucze `import/title|excerpt|body` (`origin`, `model`,
     `source_sha256`), z których `publish_entry` liczy znacznik tekstu maszynowego tak
     samo jak z jednostek tłumaczenia. Edycja człowieka dopisuje `import/edit` — tekst
     modelu poprawiony przez osobę zostaje oznaczony („mieszany”). Wersje importu nie
     mają `translation_of`: centrum tłumaczeń traktuje je jak wersje człowieka i ich
     nie nadpisuje. Wyrównanie do jednostek źródła (żeby zarządzał nimi silnik)
     odrzucone na teraz: `texts_against` wymaga tej samej struktury i tych samych
     znaczników, a tłumaczenia mają inne adresy odnośników; do tego silnik mógłby sam
     zamawiać płatne tłumaczenia zaimportowanej treści.
   - **Trzy uprawnienia importu** (pkt 34), każde w jednym miejscu:
     `record_former_entry_slugs` i `record_former_term_slugs` (dawne adresy bez
     publikacji), `publish_entry(changed_at=…)` i `save_entry_draft(imported=…)` —
     żaden widok ich nie przekazuje.
   - **Operator** to konto operatorskie (`is_staff`, MFA), jak przy komendach grantów,
     z aktywnym członkostwem organizacji: prawa daje rola, a historia nazywa tego, kto
     import uruchomił. Organizację podaje się identyfikatorem, a dokument nazywa ją
     slugiem — niezgodność kończy komendę przed odczytem treści.
   - **Tłumaczenia czekają na źródło.** Gdy wersja źródłowa wpisu jest odrzucona i nie
     ma jej jeszcze na stronie, pozostałe nowe wersje nie wchodzą: opublikowana sama,
     jedna z nich stałaby się oryginałem — dla czytelnika i dla silnika tłumaczeń,
     który uzupełnia brakujące języki. Publikacja oryginału zawiadamia silnik jak
     każda inna; plan mówi z góry, ile tłumaczeń mogłoby to zamówić (stan zgody na
     automatyczne tłumaczenie należy do modułu tłumaczeń i stąd nie jest czytany).
   - **Transakcje.** Jedna na tekst wpisu dokumentu (wszystkie wersje), jedna na
     publikację każdej wersji (uwaga 24 z CT2: publikacja jednego wpisu naraz), każda
     zaczyna się od `SET LOCAL` (test kolejności zapytań); zakleszczenie ponawiane.
   - **Zdjęcia** przez `materialize_approved_media_asset` z kluczem z zawartości
     pliku (`approved_media_asset_id` — identyfikator znany już w planie).
   - **Schemat w kodzie**, nie w `packages/contracts` (komenda działa w obrazie
     backendu); kopia w `docs/architecture/` trzymana testem.
9. **Moderacja.** Moduły stron i mediów nie mają pojęcia moderacji treści; „te same
   blokady co człowiek” znaczą: uprawnienia roli, typ wyłączony, oferta i limit planu,
   kontrakty bloków, sloty prawdziwych zdjęć, przestrzeń nazw słownika, skaner mediów
   i limit magazynu.

Po przeglądzie przed scaleniem (2026-10-09):

10. **„Był publiczny, nie jest” to zawsze decyzja człowieka.** Import nie publikuje
    ponownie wpisu, który ma `published_at` i nie jest publiczny — niezależnie od tego,
    kto go opublikował (księga tego nie rozstrzyga: człowiek mógł opublikować
    wstrzymaną wersję i ją wycofać).
11. **`changed_at` z przyszłości** jest zastępowane datą publikacji, nie chwilą
    uruchomienia — inaczej każde uruchomienie dawałoby nową publikację, wpis historii
    i zdarzenie. Ponowna publikacja oryginału bez zmiany tekstu nie zawiadamia silnika
    tłumaczeń (`notify_entry_published` porównuje bloki, tytuł i zajawkę), więc nie
    kosztuje kredytów; publikacja ze zmienionym tekstem zawiadamia go jak każda inna.
12. **Znacznik tekstu maszynowego przeżywa edycję asystenta** (`import/edit` z `ai`),
    a pole bez słów nie mówi nic o pochodzeniu (wersja bez zajawki nie staje się
    „mieszana” przez `fields.excerpt`).
13. **Pozycja, którą strona już ma, jest przejmowana jawnie.** Plan dopasowuje ją po
    nazwie tak, jak zrobiłby to serwis (`_find_named` dla tagów; nazwa i rodzic dla
    kategorii), mówi o tym w „NEEDS A LOOK” (`term_adopted`) i zmienia w niej tylko to,
    czego nie miała: nazwy w brakujących językach i dawne adresy. Dwie pozycje dokumentu
    o tej samej nazwie w języku strony to jedna pozycja (`term_merged`); ta sama nazwa
    tylko w innym języku — dwie, druga z numerem w adresie (`name_shared`).
14. **Tabela zapisana jako linie tekstu wstrzymuje wersję** jak strata treści
    (`table_too_wide`), a tabela podzielona jest zawsze pokazana (`table_split`).
15. **Slug wpisu nie ma słów zarezerwowanych** — sprawdzone testem, nie założeniem: wpis
    (i dawny slug) o nazwie segmentu taksonomii, słowa stronicowania albo kanału, w każdym
    języku, niczego nie zasłania i niczego nie przechwytuje (wpis ma dwa segmenty pod
    typem, archiwum i dalsza strona listy — trzy).
16. **Usunięty wpis nie trzyma slugów:** `former_slugs` zostają w wierszu jako historia
    (na dzień, gdy usunięty wpis da się przywrócić), ale każdy, kto pyta „czyj to slug”,
    czyta menedżerem `all_objects`, który usuniętych nie widzi. Czyszczenie przy usunięciu
    odrzucone: zabrałoby przywróceniu to, z czego ma odtworzyć przekierowania.
17. **To, czego już nie ma, powstaje ponownie i raport to mówi** (`made_again`):
    pozycja usunięta w panelu, wersja skasowana razem z typem.
18. **Wersja źródłowa jest zapisywana pierwsza** (`source_locale`, potem język strony):
    w grupie bez wersji w języku strony najstarszy wpis jest dla silnika źródłem.
    Zapis wznowiony po zakleszczeniu zaczyna od stanu z planu, nie od wierszy cofniętej
    próby.
19. **HTML w polu tekstowym odrzuca wersję** (`markup_in_title`, `markup_in_excerpt`;
    dla nazw pozycji `markup_in_name`) — serwis nie zapisuje po cichu znaczników, które
    karta i opis w wyszukiwarce pokazałyby dosłownie.
20. **Pola, których rdzeń nie ma, zostają w księdze razem z tekstem** (`fields.<nazwa>.text`
    wersji; `fields` pozycji per język): gdy rdzeń dostanie takie pole (tytuł i opis SEO,
    opis kategorii), wypełni je z księgi bez pierwotnego dokumentu.
21. **Odczyt dla stron produktu:** lista niesie `timezone` wydawcy jak wpis; klient
    (`#lib/product-site/content`) przyjmuje opcjonalne `revalidate`. Znacznik „treść
    zaczyna się od zdjęcia” i opcja pominięcia go w `SiteEntryBody` — do planu.

**Czego testy nie dowodzą** (baza testowa omija RLS): że rola aplikacji widzi i zapisuje
wiersze księgi, pozycji, mediów i audytu wyłącznie organizacji operatora. Test trzyma
kolejność: każda transakcja importu zaczyna się od `SET LOCAL` z tą organizacją, żadne
zapytanie nie nazywa innej, żaden wiersz drugiej firmy się nie zmienia. Resztę sprawdza
import fixture'u na uruchomionym stosie, pod rolą aplikacji.

### Uzupełnienie PR1d (2026-10-09): co znalazł pierwszy produkt na tych pakietach

Poprawki po pierwszym prawdziwym użyciu (panel wydawcy, strony bloga i import 91 wpisów
w pięciu językach w produkcie). Żadna nie zmienia decyzji wyżej; każda mówi, co kod
robił inaczej, niż mówił.

1. **Słowo przebiegu próbnego jest słowem importu** (uzupełnia pkt 13 z CT4). Na
   prawdziwym przebiegu plan powiedział „utwórz” o tagu, którego nazwa była angielskim
   adresem tagu założonego chwilę wcześniej w tym samym przebiegu; zapis przejął go
   (`create_term` szuka po adresach wszystkich języków, plan patrzył tylko na stan sprzed
   przebiegu). Plan trzyma odtąd **słownik taki, jakim zostawi go przebieg** — kopie
   wierszy strony i zastępniki pozycji, które przebieg założy, nigdy niezapisywane
   (`_Plan.shelves`) — i każdą decyzję o pozycji przenosi na nie w kolejności i według
   reguł serwisów, ich własnymi funkcjami (`_find_named`, `_free`, `_taken`,
   `_source_address`, `_assert_sibling_name_free`, `_depth`, `shown_texts`): klucz i adres
   nowej pozycji, adres idący za nazwą w każdym języku (`settle_term_addresses` — dla
   wszystkich otwartych pozycji, bo nazwa w innym języku jest tekstem strony znajdowanym
   po słowach nazwy źródłowej, więc dwie pozycje o tej samej nazwie ją dzielą), adres
   nadany wprost, dawne adresy. Co serwis odmówiłby przy zapisie, plan mówi z góry i nie
   przekazuje zapisowi: `term_merged` (pozycja, za którą stoi już inny identyfikator
   dokumentu), `term_name_taken`, `term_too_deep`, `name_invalid`, `address_refused`,
   `former_slug_refused`. **Zapis robi to, co robił** — te same serwisy, ta sama
   kolejność; zmienia się tylko to, że pozycja połączona w planie nie jest już wysyłana do
   `create_term` (jej własne nazwy w innych językach nie nadpisują nazw pozycji, z którą
   się łączy — tak jak przy `term_merged` od CT4), a adres, którego serwis by nie nadał,
   nie jest do niego wysyłany.
   Dowód: test losuje stan (pozycje z panelu, wcześniejszy przebieg innego dokumentu,
   jedno i drugie, nic) i dokument ze słów dobranych tak, żeby na siebie wpadały, po czym
   sprawdza dwie rzeczy: raport przebiegu próbnego i raport importu mówią o każdym
   obiekcie to samo (działanie, publikacja, kod każdej uwagi), a serwis zapytany mimo
   wszystko o to, co plan przewidział, odpowiada dokładnie tak, jak plan powiedział.
   Przed poprawką 40 losowań dało 144 rozbieżności w pięciu klasach (poza zgłoszoną:
   odmowa nazwy przy zmianie nazwy i przy nowej kategorii, kategoria za głęboko, adres
   zajęty albo dawny, dawny adres zajęty — i wpisy odrzucane dopiero przy zapisie, bo ich
   pozycja nie powstała); po niej 150 losowań — zero.
   Czego plan nadal nie wie — kontrakt importu §3.
2. **Apostrof w adresie jest pomijany, nie zamieniany na łącznik** (uzupełnia ADR-070
   pkt 18). Kategoria „Dog Owner's Guide” dostawała adres `dog-owner-s-guide`; odtąd
   `slug_from_title` (i jej bliźniak w panelu, `slugFromTitle` — wspólne przypadki
   w `packages/contracts/locales/slug-cases.json`) pomija apostrof prosty i drukarski:
   `dog-owners-guide`. **Tylko dla adresów wyliczanych od teraz — żaden zapisany adres
   się nie zmienia.** Reguła jest wołana w pięciu miejscach i każde zostało sprawdzone:
   - klucz i adres nowej pozycji (`_new_term`), adres po zmianie nazwy (`_source_address`
     — tylko gdy nazwa się zmienia), slug wpisu wyliczany przez import (tylko dla wersji,
     której jeszcze nie ma: istniejąca bierze slug z wiersza) — nowe wyliczenia, nowa
     reguła;
   - trzy miejsca, które **wyliczają adres ponownie z tej samej nazwy**, dopóki adres jest
     otwarty: `settle_term_addresses` (każdy zapis tekstów języka przelicza wszystkie
     otwarte adresy pozycji) oraz tytuł wersji językowej strony i wpisu zapisany przez
     zlecenie tłumaczenia przed publikacją (`_apply_meta` ×2, `_translation_changes`).
     Wszystkie idą przez `following_slug`: adres, który wersja albo pozycja ma, zostaje,
     jeśli jest tym, co dawna reguła dała z tej samej nazwy (także z numerem); nowa nazwa
     dostaje nową regułę;
   - nazwa tagu wpisana ponownie (`_find_named`) próbuje także dawnej pisowni, więc tag
     odpowiadający pod `nino-s-toys` jest nadal znajdowany po nazwie „Niño's toys”.
   Kotwice nagłówków z konwertera HTML zostają przy łączniku (`apostrophes="-"`): tak
   robi je edytor (`richTextAnchorSlug`), a nagłówek skonwertowany ponownie ma dostać
   kotwicę, do której już prowadzą odnośniki. Klucz tagu (`tag_slug`) zostaje, jak był —
   to osobna, starsza reguła, zamrożona celowo; tag nazwany z apostrofem w języku strony
   nadal dostaje klucz z łącznikiem. Oba złote pliki bez zmiany bajtu. Skutek uboczny,
   przyjęty: dwie nazwy różniące się tylko apostrofem („Dogs”, „Dog's”) czytają się
   odtąd tak samo — nowa kategoria o drugiej z nich obok pierwszej jest odmawiana jak
   „Porady” obok „porady”, a wpisana jako tag znajduje tag pierwszej.

## Ryzyka

- **Klucz a adres pozycji** (pkt 5, 11): pomylenie ich w jednym miejscu kodu gubi wpisy
  z archiwum. Zabezpieczenie: testy złotych adresów archiwów napisane przed zmianą i
  jeden resolver (pkt 13).
- **Kategorie w tabeli tagów:** każde miejsce, które dziś znaczy „tagi”, musi pytać
  wyłącznie o wiersze bez taksonomii: `set_entry_tags`, odnalezienie tagu w
  `_find_tag_archive` i `_localized_article`, lista `tags` w migawce z `publish_entry`,
  `entry_tags`, pętla tagów w sitemapie; `_copy_tags` i `site_text_units` obejmują
  odtąd wszystkie pozycje. Jedno nazwane zapytanie „tagi strony” i test, że kategoria
  nigdy nie trafia do `tags` ani do archiwum tagu.
- **Jednorazowa zmiana adresu archiwum** nowej pozycji w innym języku (pkt 11): jest
  zamierzona i daje 308, ale musi zdarzyć się najwyżej raz — test przebiegu „wpis przed
  nazwą” i „nazwa przed wpisem”.
- **Projekcja czyta wszystkie opublikowane wpisy strony przy każdym żądaniu.** CT2
  mierzy to na 1 000 wpisów i w razie potrzeby zawęża zapytanie do typu.
- **Baza testowa omija RLS:** izolację nowej tabeli dowodzi uruchomiony stos.
- **Drzwi sprzed tenanta na publicznej ścieżce** (pkt 31): wyjątek jest wąski i
  przypięty testem, ale jest wyjątkiem — przyjmuje go właściciel razem z ADR.
- **Zależności:** CT3 czeka na PR1; z PR1 trzeba uzgodnić pkt 29 (żeby reguła nie
  powstała dwa razy) i trasę `/media/…` na hoście platformy (pkt 30).
- **Subskrypcje na starych wersjach planów** nie mają limitu (pkt 21).
- **Treść Puppily:** 71 z 91 wpisów jest tylko po polsku, więc większość archiwów
  kategorii w innych językach zostanie poniżej progu trzech wpisów i dostanie `noindex`,
  dopóki wpisy nie zostaną przetłumaczone (to koszt kredytów treści platformy).

## Rozważane alternatywy

- **Tabela „typ treści” nad kolekcjami** — drugi byt o tych samych polach, migracja
  każdego bloga i zmiana kontraktu SCR za nazwę.
- **Meta wpisu jako tabela klucz–wartość (jak `postmeta`)** — wartości poza wersją,
  publikacją i cofnięciem; tłumaczenie nie wie, co jest tekstem.
- **Hierarchia szablonów jak w WordPressie** — kreator ma własny sposób: listę bloków.
- **Tabela łącząca typ z taksonomią; wiersz taksonomii także dla tagów już teraz** —
  druga tabela i dopisywanie danych każdej stronie z tagami za przypadek, o który nikt
  nie prosił.
- **Klucz pozycji unikalny tylko w taksonomii** — wymagał zawężenia ograniczenia bazy,
  którego nie da się cofnąć, gdy kategoria i tag dzielą klucz, i czynił każde dzisiejsze
  wyszukanie tagu po kluczu dwuznacznym.
- **Zamknięcie adresu pozycji wyliczane przy żądaniu** — zamykało wartość sprzed
  tłumaczenia nazwy i otwierało się po wycofaniu ostatniego wpisu.
- **Zamknięcie adresu pozycji na tym, co jest w chwili pierwszej publikacji, z kolejnością
  „najpierw nazwy” w zleceniu tłumaczenia** — nazwę i wpis tłumaczą dwa źródła, więc
  reguła zależałaby od planowania silnika; wybrano regułę, która kolejności nie potrzebuje.
- **Przestrzeń adresów pozycji osobna dla każdego języka** — reguła trudniejsza do
  sprawdzenia i wynik wpisanej nazwy zależny od języka wpisu.
- **Zagnieżdżony adres kategorii** — przeniesienie kategorii ruszałoby adresy
  wszystkich podrzędnych.
- **Cecha planu `sites.content_types.enabled` obok limitu** — wymaga nowych wersji
  wszystkich planów i przenoszenia subskrypcji; z tego powodu ADR-071 odrzucił
  `translation.enabled`. **Limit, w którym brak liczby znaczy zero** — odwraca regułę
  pozostałych limitów.
- **Przywrócenie typu poza limitem** — furtka do obejścia limitu.
- **Tenant odczytu z hosta (domena produktu jako domena strony workspace'u)** — nie
  działa: widoki stoją na `platformDomain`, którego strona mieć nie może.
- **Strona wzorcowa w rdzeniu jako odbiór odczytu** — powtarza wzór wycofany razem z
  drogą ADR-077; odbiorem są testy kontraktu i strona produktu.
- **Osobne tabele produktu na jego blog; odczyt jako publiczne API dla wszystkich stron
  firm** — właściciel wybrał system wspólny; drugie to produkt, nie mechanizm.

## Po przeglądzie (2026-10-08)

Przegląd projektu z kodem zgłosił 14 uwag. Przyjęte i wprowadzone:

| # | Uwaga | Co się zmieniło |
| --- | --- | --- |
| 1 | tenant odczytu z hosta nie działa | punkt końcowy bez hosta, strony i tenanta; jawny wyjątek drzwi (pkt 31) |
| 2 | wpisy workspace'u miałyby drugi publiczny adres | strona workspace'u poza rendererem (pkt 29) |
| 3 | adres pozycji zamykał się na złej wartości, bez zapisu | zamknięcie zapisane w `slug_locked_at`; zamyka się tylko adres z nazwy — przy publikacji albo przyjęciu nazwy (pkt 11) |
| 4 | niezdefiniowana unikalność adresów tagów | jedna przestrzeń nazw taksonomii, reguła wpisanej nazwy (pkt 6) |
| 5 | „jedno 308” się nie składało; dawny adres do przejęcia po cichu | jeden resolver (pkt 13); automat omija dawne adresy, osoba przejmuje po podglądzie (pkt 14) |
| 6 | usuwanie i drzewo czytały wiersze, archiwa — migawki | pkt 10 |
| 7 | brak zdjęć na hoście produktu | trasa zdjęć w odczycie (pkt 30) |
| 8 | odwracalność i migracje danych billing | klucz zostaje unikalny w stronie, ograniczenie bez zmian (pkt 5); sekcja „Migracja” |
| 9 | podstrona mogła zasłonić typ | kontrola w drugą stronę (pkt 15) |
| 10 | licznik i nazwy pokazałyby nieopublikowane kategorie | tylko z opublikowanych migawek bez `noindex` (pkt 30, 33) |
| 11 | strona ponad limitem nie przywróci typu | ostrzeżenie w podglądzie wyłączenia; przywrócenie zostaje pod limitem (pkt 23) |
| 12 | odbiór „test drzwi bez nowego wpisu” był pusty | test przypinający wywołujących `platform_workspace()` (pkt 31) |
| 13 | braki przy przenoszeniu treści Puppily | usługa importu (pkt 34), faza CT4 |
| 14 | fazy: strona wzorcowa, zaniżone szacunki, zakres do ścięcia | CT3 jako API po PR1; szacunki w górę; testy złotych adresów w CT1; wygląd i blok listy poza wersją 1 (CT6) |

Zostały w wersji 1 mimo sugestii ścięcia: `schema_type` i `in_site_feed` — dwa małe
pola, bez których każda „Realizacja” byłaby dla wyszukiwarek wpisem bloga i trafiała do
kanału RSS bloga. Jedna uwaga nie potwierdziła się w danych: żadna strona lokalnego
stosu nie ma trzech działów — trzy strony mają po jednym (policzone ponownie po
wszystkich 24 organizacjach).

## Odpowiedzi właściciela (2026-10-08)

Właściciel przeczytał projekt i odpowiedział na pytania z następnej sekcji:

1. **Menu panelu: (a)** — jedna pozycja „Treści” z listą typów, blog pierwszy.
2. **Obniżenie planu: (a)** — typy ponad limit działają dalej; odmowa dotyczy tylko
   założenia kolejnego i przywrócenia wyłączonego. Dodał: „jednocześnie opublikowane
   stają się nieopublikowane, a dla wyszukiwarek informacja jest usuwana (chyba kod
   410, o ile dobrze pamiętam)”. Odczytane jako zdanie o **typie wyłączonym**, nie o
   obniżeniu planu: wpisy wyłączonego typu przestają być publiczne, a wyszukiwarki mają
   się dowiedzieć, że treści nie ma. Jak to jest zbudowane i dlaczego odpowiedzią jest
   404, nie 410 — pkt 23.
3. **Własne taksonomie firmy: (a)** — po wersji 1; „na pierwsze miesiące powinno
   wystarczyć”.
4. **Wygląd typu i blok „Lista wpisów”: „zróbmy to od razu”** — dodatek CT6 jest częścią
   tej serii pakietów (własny, późniejszy pakiet), nie odłożoną opcją.
5. **RSS: (a)** — typy artykułowe wchodzą do kanału strony, firma może to przełączyć
   dla każdego typu.
6. **Liczby planów** (Profile 0, Site 1, Pro 10) zostają jako wartości domyślne; zmienia
   je właściciel.

Przyjęte razem z ADR, bez wariantów: wyjątek drzwi sprzed tenanta (pkt 31) i strona
workspace'u platformy poza rendererem kreatora (pkt 29).

**Zasada dla całej funkcji** (jego słowa): „zakoduj to tak, żeby użytkownik mógł zmieniać
ustawienia — z rozsądkiem, tylko przydatne opcje”. Czym typ **jest** — nazwa, adres w
każdym języku, czy trafia do kanału RSS, czym jest dla wyszukiwarek — firma ustawia w
panelu, z sensownymi wartościami domyślnymi; panel nie pokazuje niczego, czego właściciel
firmy by nie zrozumiał albo nie potrzebował.

## Pytania do właściciela

Stan sprzed odpowiedzi, zostawiony dla wariantów, które odpadły.

1. **Gdzie typy w menu panelu.** (a) jedna pozycja „Treści” z listą typów (blog
   pierwszy); (b) osobna pozycja menu na każdy typ, jak w WordPressie. Rekomendacja: (a)
   — menu panelu jest statyczne, a (b) wymaga nowego mechanizmu w powłoce panelu.
2. **Obniżenie planu.** (a) typy ponad limit działają dalej, nie da się tylko dodać
   kolejnego ani przywrócić wyłączonego — jak języki i podstrony; (b) typy ponad limit
   przestają przyjmować nowe wpisy do czasu wyłączenia któregoś albo powrotu na wyższy
   plan. Rekomendacja: (a). Liczby z pkt 21 (Profile 0, Site 1, Pro 10) są do zmiany.
3. **Własne taksonomie firmy.** (a) wersja 1: kategorie i tagi, własne później (model
   gotowy, 1–2 dni); (b) własne taksonomie już w wersji 1. Rekomendacja: (a).
4. **Wygląd typu i blok „Lista wpisów”** (karty ze zdjęciem, przełączniki, „Ostatnie
   realizacje” na stronie głównej). (a) pierwszy dodatek po wersji 1, 2–3 dni; (b) w
   wersji 1. Rekomendacja: (a). To pytanie zastępuje pytanie o kolejność z pierwszej
   wersji: kolejność rozstrzygnęły fakty — wpisy Puppily niosą kategorie (19 kategorii,
   164 przypisania), a odczyt czeka na pakiet tras produktu, więc kategorie idą przed
   odczytem i importem.
5. **Kanał RSS a nowe typy.** (a) typy artykułowe wchodzą do kanału strony, pozostałe
   nie, klient może przełączyć; (b) do kanału wchodzi tylko pierwszy typ. Rekomendacja:
   (a).

Do przyjęcia razem z ADR, bez wariantów: wyjątek drzwi sprzed tenanta dla publicznego
odczytu treści platformy (pkt 31) i to, że strona workspace'u platformy przestaje
odpowiadać przez renderer kreatora (pkt 29).

## Relacje

- **ADR-027, ADR-031** — bloki i katalog sekcji; **ADR-035** — dwa rodzaje powierzchni,
  granty, kontrakt zmian; **ADR-054, ADR-057** — listy i strony panelu.
- **ADR-032, ADR-033** — limity planów; **ADR-049** — `features` profilu.
- **ADR-039, ADR-041** — RLS nowej tabeli; drzwi sprzed tenanta (pkt 31).
- **ADR-069, ADR-070, ADR-071** — tłumaczenia, slugi, języki, adresy i SEO;
  `docs/architecture/translation-sources.md` — źródła `sites.entry` i tekstów strony.
- **ADR-076, ADR-078** — polecenia asystenta; ustawienia firmy (pola typu są polami
  typu, nie ustawieniami firmy).
- **ADR-048, ADR-077** — strony produktu jako zakodowane widoki; workspace platformy
  jako wydawca.
