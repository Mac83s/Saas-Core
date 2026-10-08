# ADR-079 — typy treści na stronach firm i treść własna platformy: typ to dział, taksonomie i pozycje, odczyt dla stron produktu

**Status:** Accepted — przyjęty przez właściciela 2026-10-08, punkt po punkcie (sekcja
„Odpowiedzi właściciela”). Zamówienie właściciela z 2026-10-08
(typy treści „jak custom posts w WordPressie”, taksonomie, kategorie, tagi,
wielojęzyczność, slugi; blog zawsze, typy niestandardowe per platforma i per plan) oraz
jego odpowiedź z tego samego dnia: blog własny produktu (91 wpisów Puppily, potem
HoofCare i MedPlano) żyje w tym samym systemie treści. Rozstrzygnięcia techniczne:
agent, pakiet CT0; plan memex `saas-core-typy-tresci`. Druga wersja dokumentu, po
przeglądzie projektu z kodem (14 uwag — sekcja „Po przeglądzie”) i po scaleniu pakietu
PC1 (`main` b97403ae). Zbudowana jest faza CT1 (sekcja „Stan budowy”); reszta czeka na
swoje pakiety.
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
| CT2–CT6 | czekają | — |

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
   `content_type_archived` — 409, każdy zapis do wyłączonego typu (wpis, publikacja,
   wycofanie, tagi, harmonogram, nazwa, adres, menu, polityka automatyzacji);
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
   zamówienia ich tłumaczenia. Wynik zlecenia rozpoczętego przed wyłączeniem zapisuje
   się normalnie — gość go nie zobaczy, dopóki typ jest wyłączony.
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

**Kto musi czytać `archived_at`** (lista dla następnych faz — nowy odczyt publiczny
dopisuje się tutaj): `published_entries`, `_find_entry`, `_find_index`,
`collections_with_entries`, `collection_links`, `moved_section`,
`_published_translations`, `site_host_company` (wszystkie w `publication_routing.py`),
pętla typów w sitemapie (`public_feeds.py`), lista źródła `sites.entry`, strażnik
zapisu `_assert_entry_writable`. Zawsze jako złączenie w tym samym zapytaniu
tenantowym, nigdy osobny odczyt przed nim. Nazwy typu wyłączonego zostają zajęte:
`_assert_section_names_free`, `page_slug_is_section` i `free_slug` czytają wszystkie
typy.

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
