# ADR-079 — typy treści na stronach firm i treść własna platformy: typ to dział, taksonomie i pozycje, odczyt dla stron produktu

**Status:** Proposed — do decyzji właściciela. Zamówienie właściciela z 2026-10-08
(typy treści „jak custom posts w WordPressie”, taksonomie, kategorie, tagi,
wielojęzyczność, slugi; blog zawsze, typy niestandardowe per platforma i per plan) oraz
jego odpowiedź z tego samego dnia: blog własny produktu (91 wpisów Puppily, potem
HoofCare i MedPlano) żyje w tym samym systemie treści. Rozstrzygnięcia techniczne:
agent, pakiet CT0; plan memex `saas-core-typy-tresci`. Nic z tego dokumentu nie jest
zbudowane — kod powstaje dopiero po odpowiedziach z sekcji „Pytania do właściciela”.
**Data:** 2026-10-08

**Zmienia częściowo** ADR-031 (blok listy wpisów w katalogu sekcji), ADR-071 pkt 14
(slugi tagów per język) i komentarz modelu `ContentTag` („jedna płaska taksonomia”);
**rozszerza** ADR-035 §1 i §7, ADR-070 pkt 18 i ADR-077 pkt 2. Fragmenty — w sekcji
„Zmiany wcześniejszych decyzji”.

## W skrócie dla właściciela

**Co zrobi klient w panelu.** W „Strona internetowa → Treści” widzi listę typów treści;
pierwszy to jego blog. Klika „Nowy typ treści”, wpisuje nazwę „Realizacje”, panel
proponuje adres `/realizacje/` i pozwala nazwać go w innych językach (`/en/projects/`,
`/de/referenzen/`). Zaznacza, czy typ ma kategorie i tagi. Potem dodaje wpisy tym samym
edytorem co wpisy bloga, przypisuje im kategorie („Łazienki”, „Kuchnie”) i tagi,
publikuje. Na stronie odpowiada indeks `/realizacje/`, wpis `/realizacje/<slug>/`,
archiwum kategorii `/realizacje/kategoria/lazienki/` — i to samo po angielsku i
niemiecku, z tłumaczeniami robionymi przez ten sam silnik i za te same kredyty co dziś.

**Na czym to stoi.** Dzisiejszy blog jest już „typem treści” — w bazie to dział
(kolekcja) z nazwą, adresem per język, indeksem i stroną wpisu. Nie powstaje nic obok:
typ to ten sam wiersz z kilkoma nowymi polami, pozycja taksonomii (kategoria, tag) to
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
4. **Dostęp: przełącznik platformy i cecha planu z limitem.** Blog nie wymaga niczego
   poza stroną. Limit liczy **włączone typy treści na jednej stronie poza pierwszym**.
   Liczby są Pana; mechanizm — w sekcji „Dostęp”.
5. **Wersja 1 ma stały wygląd strony wpisu i indeksu** (z kilkoma przełącznikami), bez
   pól własnych, bez szablonów strony wpisu i bez relacji między typami. Dla każdego z
   nich ADR wskazuje miejsce w modelu, tak żeby dodanie go nie wymagało migracji treści
   klientów.
6. **Treść własna platformy pisze się w tym samym panelu, a strony publiczne produktu
   rysuje produkt.** Rdzeń daje odczyt „opublikowane wpisy według typu, języka i sluga”;
   produkt ma własne trasy, nagłówek i stopkę.

## Kontekst

Stan kodu (`apps/backend/src/saas_core/modules/shared/sites/`, `main` 75c4bcb9):

- `ContentCollection` — dział strony: `key`, `name`, `kind` (blog | news | guide; sama
  etykieta, nic jej nie czyta poza inwentarzem), `base_path` i `locale_paths` (nazwa w
  adresach per język, ADR-071 „Uzupełnienie 2026-10-07”), `former_paths` (dawne nazwy,
  jedno 308), `show_in_navigation`, polityka automatyzacji.
- `ContentEntry` — wpis w jednym języku, w grupie tłumaczeń, z własnym slugiem,
  wersjami (`ContentEntryVersion`: lista bloków) i publikacją (`ContentEntryPublication`;
  każdy wpis publikuje się sam, ADR-035 §1). Migawka publikacji niesie adres, tytuł,
  bloki i tagi wpisu (`{slug, name}`).
- `ContentTag` i `ContentEntryTag` — płaskie tagi wspólne dla strony. Archiwum tagu jest
  projekcją liczoną z migawek, pod działem: `/blog/tag/<slug>/`; segment `tag` i slug są
  te same we wszystkich językach (dług z ADR-071 pkt 14). Nazwa tagu w innym języku to
  tekst strony (`SiteTextTranslation`, klucz `tag/<id>`), tak jak nazwa działu
  (`collection/<id>`).
- Indeks działu, archiwa, kanały RSS/Atom (`/rss.xml`, `/xx/rss.xml` — jeden kanał na
  stronę i język, wszystkie działy razem, 50 pozycji), sitemapa, hreflang i JSON-LD
  (`BlogPosting` dla każdego wpisu, bez względu na `kind`) liczą się przy żądaniu z
  jednej projekcji `published_entries`.
- Backend obsługuje wiele działów na stronie od dawna (testy `test_sites_collections.py`,
  `test_sites_section_addresses.py`); panel (`/panel/sites/blog`, `blog-panel.tsx`)
  pozwala założyć tylko pierwszy. Dział nie ma usuwania ani wyłączania.
- Slug wpisu podaje się przy utworzeniu (panel proponuje go z tytułu); potem **nie da
  się go zmienić wcale**, także w szkicu. Rodzeństwo z tłumaczenia AI dostaje slug
  liczony kodem z przetłumaczonego tytułu, do pierwszej publikacji.
- Kontrakt `content-change-set.v1` adresuje wpis parą `content_entry` + `collection_id`
  i nie ma komend dla tagów — SCR pisze do dowolnego działu, na który ma grant.
- Workspace platformy (ADR-077) ma stronę w `shared.sites` i panel wydawcy; jego cechy
  nadaje `provision_platform_workspace` audytowaną ścieżką override'ów, bez planu.

Pomiar danych na lokalnych stosach (08.10, tylko odczyt, w tenancie każdej firmy):

| Stos | Strony | Typy (działy) | Wpisy | Tagi / przypisania |
| --- | --- | --- | --- | --- |
| Saas-Core `:8080` | 9 | 3 (po jednym na stronę, wszystkie `kind=blog`; klucze `blog`, `blog`, `poradnik`) | 13 (pl 10, en 2, de 1; 10 opublikowanych, 3 szkice; 10 grup tłumaczeń) | 4 / 5 (żaden tag nie jest użyty w dwóch działach, 1 nieużywany; 1 przetłumaczona nazwa tagu) |
| HoofCare `:8081` | 1 | 0 | 0 | 0 |
| MedPlano `:8082` | 2 | 0 | 0 | 0 |

Dwa działy mają nazwy per język (`{"de": "ratgeber"}`, `{"de": "ratgeber", "en":
"guide"}`), jeden ma dawną nazwę. VPS nie był mierzony z tej maszyny; migracja jest
zaprojektowana tak, żeby kształt danych na VPS nie miał znaczenia (sekcja „Migracja”).

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

1. **Typ treści to wiersz `ContentCollection`.** Dochodzą cztery pola, każde z wartością
   domyślną równą dzisiejszemu zachowaniu:
   - `archived_at` (puste) — typ wyłączony (pkt 21);
   - `schema_type` (domyślnie `BlogPosting`) — czym wpis jest dla wyszukiwarek:
     `BlogPosting`, `NewsArticle`, `Article` albo `WebPage` (sama strona, bez węzła
     artykułu). Każdy istniejący dział zostaje przy `BlogPosting`;
   - `in_site_feed` (domyślnie tak) — czy wpisy typu trafiają do kanału RSS/Atom strony;
   - `presentation` (domyślnie puste = dzisiejszy wygląd) — mały, walidowany zestaw
     przełączników wyglądu (pkt 13).
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
   taksonomii), `position` (kolejność wśród rodzeństwa), `locale_slugs` i `former_slugs`
   (pkt 9). Tagi strony nie dostają wiersza taksonomii: ich reguły (płaskie, wspólne,
   segment `tag`) zostają jedną nazwaną stałą modułu — dzięki temu migracja nie dotyka
   żadnego istniejącego tagu.
4. **Przypisanie zostaje w `ContentEntryTag`**, bez zmian. Wpis ma najwyżej 10 pozycji
   w jednej taksonomii (dziś: 10 tagów). Nie ma „kategorii głównej”.
5. **`ContentTag.slug` staje się stałym kluczem pozycji i nigdy się nie zmienia.**
   Migawki opublikowanych wpisów są niezmienne i wskazują tag właśnie slugiem; archiwum
   dobiera wpisy po nim. Gdyby slug dało się zmienić, starsze wpisy wypadłyby z
   archiwum. Adres inny niż klucz zapisuje się obok (pkt 9). Nowe migawki niosą
   dodatkowo `terms` (identyfikator, taksonomia, klucz, nazwa) dla wszystkich
   taksonomii; pole `tags` zostaje, w dzisiejszym kształcie i tylko dla tagów.
6. **Unikalność.** Tag strony: jak dziś, klucz unikalny w stronie (ograniczenie
   zawężone do wierszy bez taksonomii). Pozycja taksonomii: klucz unikalny w
   taksonomii — kategoria „porady” i tag „porady” mogą istnieć obok siebie, bo mają
   różne adresy. Adres pozycji w danym języku jest unikalny w taksonomii (sprawdza
   serwis, jak przy nazwach działów).
7. **Wpis** dostaje jedno pole: `former_slugs` (pkt 11).

### Taksonomie

8. **Wersja 1 ma dwa rodzaje:** tagi (płaskie, wspólne dla strony — istnieją) i
   kategorie (hierarchiczne, osobne dla każdego typu, do trzech poziomów). Kategorie
   powstają, gdy klient je włączy dla typu — także dla bloga, bez żadnej cechy planu.
   Własnych taksonomii firmy („Lokalizacja”, „Marka”) wersja 1 nie pokazuje w panelu,
   choć tabela z pkt 2 już je mieści; to pytanie 3.
   - Archiwum kategorii nadrzędnej pokazuje też wpisy kategorii podrzędnych.
   - Usunięcie kategorii z podrzędnymi przenosi je poziom wyżej. Pozycję da się usunąć
     tylko wtedy, gdy nie nosi jej żaden wpis (łączenie pozycji — później).
   - Przełącznik „ten typ używa tagów” jest częścią `presentation`: chowa pole w
     edytorze i tagi na stronie, niczego nie kasuje.
9. **Nazwa i adres pozycji per język.**
   - Nazwa w innym języku: tekst strony, klucz `tag/<id>` — ten sam co dziś, więc
     istniejące tłumaczenia nazw zostają. Nazwa taksonomii: `taxonomy/<id>`.
   - Adres: w każdym języku domyślnie klucz pozycji — dokładnie tak, jak odpowiadają
     dzisiejsze tagi. `locale_slugs` (`{"de": "tipps"}`) nadaje adres w jednym języku,
     także w języku strony.
   - Kto liczy: kod, z nazwy (`slug_from_title`, ADR-070 pkt 18: ASCII, ä → ae,
     cyrylica według BGN/PCGN), nigdy model. Klucz — z nazwy przy utworzeniu. Adres w
     języku L — z przetłumaczonej nazwy, w chwili jej przyjęcia.
   - Kiedy się zamyka: gdy archiwum pozycji w języku L pierwszy raz odpowiada gościom
     (pierwszy opublikowany wpis w L z tą pozycją). Od tej chwili kod go nie rusza.
     Istniejące tagi z opublikowanymi wpisami są więc zamknięte na swoim kluczu — ich
     adresy nie zmienią się same w żadnym języku.
   - Zmiana po zamknięciu: tylko osoba, z powodem, z podglądem; poprzedni adres trafia
     do `former_slugs` i odpowiada **jednym 308** do dzisiejszego (cel liczony z tego,
     jak pozycja nazywa się teraz, nie z kolejnej pozycji w historii — jak
     `moved_section`). Działa od zapisu, bez ponownej publikacji wpisów.
   - Granica: pozycja, której nazwy nikt nie przetłumaczył, zanim jej archiwum w L
     pierwszy raz odpowiedziało, zostaje w L pod kluczem — jak dziś.
10. **Segment taksonomii w adresie.** Tagi: `tag` we wszystkich językach — bez zmiany
    (dług z ADR-071 pkt 14 zostaje; spłata to wiersz taksonomii dla tagów i jedno 308).
    Kategorie: słowo w języku czytelnika, zapisane w wierszu taksonomii przy jej
    utworzeniu ze słownika backendu (pl `kategoria`, en `category`, de `kategorie`,
    es `categoria`, ru `kategoriya`), zmieniane jak nazwa działu. Segment nie może być
    słowem `tag` ani segmentem paginacji żadnego języka.

### Adresy

Strona w języku polskim, typ „Realizacje” nazwany po angielsku `projects`. Żaden adres
oznaczony „jest” nie zmienia się ani o znak; pilnują tego testy złotych adresów
(`test_sites_section_addresses.py`) i ich odpowiednik dla archiwów tagów, napisany na
dzisiejszym kodzie, zanim cokolwiek się zmieni.

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

- Wpis ma dwa segmenty pod działem, archiwum trzy — dlatego wpis o slugu `kategoria`
  niczego nie zasłania (tak samo jest dziś z `tag`).
- Nazwa nowego typu przechodzi tę samą kontrolę co dziś nazwa działu: nie może być
  adresem podstrony, innego typu ani segmentem zarezerwowanym, w żadnym języku.
- Kanału per typ (`/realizacje/rss.xml`) wersja 1 nie ma; kształt adresu jest wolny, bo
  slug wpisu nie może zawierać kropki.

### Slugi wpisów

11. **Co jest, czego brakuje.** Jest: slug z tytułu przy utworzeniu, unikalny w (typ,
    język); adres zamrożony w migawce publikacji; 308 po zmianie nazwy działu. Brakuje
    zmiany sluga — dochodzi jedna operacja `change_entry_slug` z podglądem:
    - przed pierwszą publikacją: wolna, bez śladu;
    - po publikacji: tylko osoba, z powodem (integracja i asystent dostają
      `person_required`, jak przy adresie podstrony i działu). Wpis publikuje się
      ponownie z tą samą treścią pod nowym adresem, stary slug trafia do
      `ContentEntry.former_slugs` i odpowiada jednym 308;
    - nowy slug nie może być dawnym ani obecnym slugiem innego wpisu tego typu w tym
      języku.

### Wygląd w wersji 1

12. **Strona wpisu** ma stały skład: tytuł (nagłówek strony), wiersz z datą i autorem,
    treść z bloków kreatora, kategorie i tagi jako odnośniki do archiwów. **Indeks i
    archiwa** to lista wpisów (blok `core.entry_list` wypełniany przez serwer) z tytułem,
    datą i zajawką, stronicowana po 10.
13. **Przełączniki typu (`presentation`)**: układ indeksu — lista albo karty ze
    zdjęciem (pierwsze zdjęcie z treści wpisu); pokazuj datę; pokazuj autora; używaj
    tagów. Puste = jak dziś. Osobnego „obrazka wyróżniającego” wersja 1 nie ma — przyjdzie
    jako pole wbudowane razem z polami własnymi.
14. **Blok „Lista wpisów” na dowolnej podstronie.** `core.entry_list` dostaje wersję 2
    schematu: obok dzisiejszych pól zapytanie — typ, opcjonalnie pozycja taksonomii,
    liczba wpisów — i układ. Trafia do katalogu sekcji kreatora. Podstrona przechowuje
    zapytanie, nie wpisy: listę wypełnia backend przy żądaniu, tak jak bloki pokazujące
    żywe rekordy (`live` w odpowiedzi strony), a skrót odpowiedzi liczy się także z
    pokazanych wpisów, więc nowy wpis odświeża pamięć podręczną bez publikowania
    podstrony. Wersja 1 schematu zostaje dla indeksów i starszych migawek.

### Kanały, sitemapa, hreflang, dane strukturalne

15. **Kanał strony** niesie wpisy typów z `in_site_feed`. Istniejące działy mają „tak”,
    więc ich kanały się nie zmieniają. Nowy typ dostaje „tak”, gdy jest artykułowy
    (`BlogPosting`, `NewsArticle`, `Article`), i „nie”, gdy to `WebPage` — realizacje
    nie wpadają czytelnikom bloga do czytnika, dopóki klient tego nie zechce.
16. **Sitemapa** wymienia indeksy, wpisy i archiwa wszystkich włączonych typów;
    archiwum kategorii podlega tej samej regule co tagu: poniżej trzech wpisów
    (`TAG_INDEX_THRESHOLD`) odpowiada gościom, ale ma `noindex` i nie ma go w sitemapie.
17. **hreflang i x-default** — bez nowych reguł: wpis przez grupę tłumaczeń, pierwsza
    strona indeksu między językami, archiwum pozycji między językami, w których ma
    wpisy (teraz z adresem pozycji w każdym z nich).
18. **JSON-LD:** węzeł wpisu ma typ z `schema_type`; przy `WebPage` wpis jest samą
    stroną. Reszta grafu (firma, okruszki, znacznik tekstu AI) bez zmian.

### Dostęp: platforma, plan, limit

19. **Dwie bramki, obie sprawdzane w API.**
    - Przełącznik wdrożenia `features.contentTypes` w `deployment.json` (jak
      `publicBooking`; brak = wyłączone): czy platforma w ogóle oferuje firmom typy
      poza pierwszym.
    - Cecha planu `sites.content_types.enabled` (jak `custom_domain.enabled`: plan,
      który jej nie wymienia, jej nie ma) i limit `sites.content_types.max` (jak
      `pages.max`: plan bez wartości nie ma limitu).
    - **Co liczy limit:** włączone (niezarchiwizowane) typy treści na jednej stronie,
      **poza pierwszym**. Pierwszy typ — blog albo cokolwiek klient założy jako
      pierwsze — wymaga tylko `sites.enabled`, jak dziś.
    - Propozycja liczb, **do zmiany przez właściciela**: Profile — bez cechy; Site —
      cecha, limit 1; Pro — cecha, limit 10. Liczby wchodzą nowymi wersjami planów
      (migracja danych billing w każdym produkcie, wzór `0025`).
    - Subskrypcja trzyma wersję planu, którą kupiła, więc istniejący klient dostaje typy
      po przeniesieniu na nową wersję albo z nadania operatora.
20. **Strażnik działa tylko przy zakładaniu i przywracaniu typu.** Obniżenie planu,
    wyłączenie przełącznika platformy i wygaśnięcie subskrypcji niczego nie zdejmują:
    typy ponad limit dalej odpowiadają gościom i dają się edytować; nie da się tylko
    założyć kolejnego. To ta sama reguła co przy językach (ADR-071 pkt 7), podstronach
    i szablonach. Oddajemy: klient może zejść na tańszy plan i zachować typy, które już
    ma (pytanie 2).
21. **Wyłączenie i usunięcie typu.**
    - Usunąć można tylko typ bez żadnego wpisu (także szkicu).
    - Typ z wpisami się **wyłącza** (`archived_at`): to przełącznik dostępności liczony
      przy żądaniu, jak wyłączenie języka (ADR-071 pkt 9). Nic nie jest kasowane ani
      publikowane; adresy typu odpowiadają 404, typ znika z menu, kanału i sitemapy, a
      jego wpisów nie da się edytować ani publikować (zaplanowane publikacje są
      anulowane z powodem). Nazwy działu zostają zajęte, więc **włączenie przywraca
      wszystko pod tymi samymi adresami od razu**. Wyłączony typ nie liczy się do
      limitu; przywrócenie wymaga wolnego miejsca.
    - Wyłącza i przywraca tylko osoba; dla asystenta to polecenie wysokiego ryzyka.
22. **Uprawnienia:** bez nowych. Typy, taksonomie i pozycje zakłada i zmienia
    `site.content.edit`, publikuje `site.publish` — jak dziś dział i wpis. Zmiana
    adresu, który już odpowiada gościom, oraz wyłączenie typu wymagają osoby.

### Panel

23. **Jedna pozycja menu „Treści”** (`/panel/sites/content`) tam, gdzie platforma oferuje
    typy: lista typów w `DataTable` (nazwa, adres, liczba wpisów, języki, stan), akcja
    „Nowy typ treści”, filtr „Wyłączone” z przywracaniem. Podstrony to adresy, nie
    zakładki (ADR-057):
    - `/panel/sites/content/<typ>` — wpisy typu (dzisiejszy ekran bloga);
    - `/panel/sites/content/<typ>/categories` i `…/tags` — pozycje: drzewo kategorii z
      przenoszeniem, nazwa, adresy per język z podglądem przekierowań;
    - `/panel/sites/content/<typ>/settings` — nazwa, adresy działu per język (dzisiejszy
      `collection-paths`), przełączniki z pkt 1, 8 i 13, wyłączenie.
    Tam, gdzie platforma typów nie oferuje, pozycja menu nazywa się dalej „Blog” i
    prowadzi prosto do wpisów. Adres `/panel/sites/blog` działa nadal w obu przypadkach.
    Odrzucone: pozycja menu na każdy typ (jak w WordPressie) — menu panelu jest dziś
    statyczną listą sekcji; to pytanie 1.
24. **Edytor wpisu** dostaje obok pola tagów pole kategorii (drzewo z zaznaczaniem,
    dodanie nowej w miejscu). Tłumaczenie wpisu przenosi pozycje źródła we wszystkich
    taksonomiach (dziś: tagi).

### Treść własna platformy i odczyt dla stron produktu

Decyzja właściciela z 2026-10-08: blog produktu żyje w tym systemie, dzielonym między
platformy. Strona publiczna produktu to zakodowane widoki w aplikacji produktu, nigdy
renderer kreatora (memex `puppily-s-public-site-is-dedicated-coded-views-o`).

25. **Pisanie.** Treść własna platformy powstaje w panelu workspace'u platformy
    (ADR-077 pkt 2 i 9) — te same typy, wpisy, taksonomie, edytor, harmonogram,
    centrum tłumaczeń i publikacja co u klienta. Nie ma drugiej ścieżki zapisu.
26. **Jak workspace dostaje typy.** Nie ma planu, więc `provision_platform_workspace`
    nadaje mu cechę `sites.content_types.enabled` tą samą audytowaną ścieżką co
    pozostałe (bez limitu). Przełącznik `features.contentTypes` dotyczy oferty dla
    firm i workspace'u nie obejmuje — produkt może prowadzić własne typy, nie dając ich
    klientom. Istniejący workspace dostaje nadanie przez ponowne uruchomienie komendy.
27. **Odczyt po stronie serwera** — nowy moduł `shared/sites/content_reads.py`, czytający
    te same projekcje co publiczny router (jedna prawda o tym, co jest opublikowane i w
    jakim języku dostępne):
    - wpis według typu, języka i sluga: tytuł, zajawka, autor, daty, **treść jako bloki**
      w kontrakcie bloków rdzenia, pozycje z nazwami i adresami w języku czytelnika,
      opublikowane wersje w innych językach (do hreflang i przełącznika), `noindex`,
      znacznik tekstu AI i gotowy węzeł JSON-LD wpisu;
    - lista według typu, opcjonalnie kategorii albo tagu, stronicowana: pozycje listy,
      liczba stron, wersje językowe listy i znacznik `indexable` (reguła „poniżej trzech
      wpisów archiwum nie jest indeksowane” zostaje w rdzeniu, produkt ją tylko stosuje);
    - drzewo pozycji taksonomii z liczbą wpisów;
    - wykaz do sitemapy: wszystkie wpisy i archiwa z datą zmiany i wersjami językowymi;
    - dla sluga wpisu lub pozycji, który jest dawnym adresem: odpowiedź „przeniesione
      do…”, z której produkt robi jedno 308.
28. **Czy to także publiczne API HTTP: tak technicznie, nie jako produkt.** Strony
    produktu renderuje serwer Next.js, osobny proces, więc odczyt jest wystawiony jako
    `GET /api/v1/public/content/…` w OpenAPI (typy dla stron produktu generują się jak
    każde inne) i wołany po stronie serwera, tak jak renderer stron firm woła
    `/api/v1/public/site/`. Zwraca wyłącznie to, co opublikowane, więc nie potrzebuje
    logowania. Ale w wersji 1 odpowiada **tylko dla treści własnej platformy**
    (workspace odnajduje istniejąca, zadeklarowana ścieżka sprzed tenanta w
    `platform_workspace()`; nowe drzwi nie powstają), bez CORS, kluczy i obietnicy
    stabilności dla obcych. „Headless CMS” dla klientów byłby osobnym produktem (klucze,
    limity, cennik) — nikt o niego nie prosił; odczyt bierze stronę jako parametr, więc
    droga zostaje otwarta.
29. **Co produkt bierze z rdzenia, a co jest jego.**

    | Rdzeń (wspólne) | Produkt (własne) |
    | --- | --- |
    | edytor, wersje, publikacja wpisu, harmonogram | trasy i kształt adresów, strona główna |
    | typy, taksonomie, pozycje; slugi per język, ich zamykanie i dawne adresy (dane) | odpowiedź 308 na dawny adres (z danych rdzenia) |
    | nazwa działu per język (dana, edytowana w panelu) | to, czy i gdzie jej użyje we własnych trasach |
    | silnik i centrum tłumaczeń, kredyty, znacznik tekstu AI | nagłówek, stopka, szablony widoków |
    | kontrakt bloków i ich renderery (`@saas-core/site-blocks`) | układ strony wokół treści |
    | projekcja „co jest opublikowane”, dostępność języków, próg `noindex` | własna sitemapa i kanały (z wykazu rdzenia) |
    | węzeł JSON-LD wpisu | graf strony: własne `WebSite` i `Organization` |

    Trasy, stronę główną, sitemapę i przekierowania produktu daje osobny pakiet rdzenia;
    ten ADR ustala tylko, o co te trasy pytają. Renderer kreatora, jego menu i wygląd
    nie biorą udziału.
30. **Jedna różnica wobec strony firmy.** Nazwy typów i pozycji w innych językach
    wychodzą dziś z publikacją strony (`site_texts` w migawce). Strona workspace'u,
    której nie rysuje kreator, może nie mieć żadnej publikacji — odczyt bierze wtedy
    przyjęte tłumaczenia nazw wprost. To jedyne miejsce, w którym odczyt produktu
    różni się od publicznego routera, i ma własny test.

### SCR, asystent, centrum tłumaczeń

31. **Kontrakt `content-change-set.v1` się nie zmienia.** SCR pisze do każdego typu
    przez `collection_id`, jak dziś. Addytywnie, poza kontraktem: inwentarz dostaje przy
    typie `archived`, `schema_type` i listę taksonomii z pozycjami; zapis do wyłączonego
    typu odpowiada odmową z kodem `content_type_archived`. Przypisanie pozycji: dzisiejszy
    serwis tagów uogólniony o taksonomię (`set_entry_terms`); dotychczasowy adres API
    tagów zostaje jako jego szczególny przypadek.
32. **Asystent:** każda nowa operacja jest serwisem z typowanym wejściem, podglądem bez
    zapisu i audytem z rodzajem aktora; polecenia (`sites.content_type.*`,
    `sites.taxonomy_term.*`, `sites.entry.terms.set`) są adapterami w klasach ADR-076.
33. **Tłumaczenia — żadnej nowej ścieżki.** Wpisy każdego typu tłumaczy istniejące
    źródło `sites.entry`; nazwy typów, taksonomii i pozycji — istniejące źródło tekstów
    strony (nowe są tylko klucze `taxonomy/<id>` i pozycje kategorii pod `tag/<id>`).
    Koszty według dzisiejszych reguł kredytów. Nazwy działu i segmentu taksonomii w
    adresie wpisuje człowiek; adres pozycji liczy kod (pkt 9).

### Czego wersja 1 nie ma i gdzie to wejdzie

| Brak w wersji 1 | Miejsce w modelu | Dlaczego bez migracji treści klientów |
| --- | --- | --- |
| **Pola własne** (cena, data, miejsce, obrazek wyróżniający) | definicje: `ContentCollection.field_schema`; wartości: `ContentEntryVersion.fields` obok `blocks`, w migawce pod `fields` | wartości są wersjonowane, publikowane i cofane razem z treścią, tą samą drogą; pola tekstowe stają się jednostkami tłumaczenia (`field/<klucz>`), pozostałe są kopiowane ze źródła jak tagi. Wpis bez pól to puste `fields` |
| **Szablon strony wpisu i indeksu** | lista bloków kreatora przy typie, publikowana z migawką strony, z blokami „tytuł”, „treść”, „pole” | migawka wpisu dalej niesie tylko wpis, więc zmiana szablonu nie publikuje ponownie trzystu wpisów; przełączniki z pkt 13 przechodzą w szablon domyślny mechanicznie |
| **Relacje między typami** | rodzaj pola własnego: wartość to grupa tłumaczeń wpisu docelowego | dochodzi z polami, bez tabel łączących |
| **Własne taksonomie firmy** | wiersz `ContentTaxonomy` (pkt 2) | model jest od wersji 1; brakuje ekranu |
| **Kanał per typ, opis kategorii, łączenie pozycji** | adres `/<dział>/rss.xml`; tekst strony `tag/<id>/description`; operacja serwisu | same dodatki |

## Migracja

- **Sama zmiana schematu, bez przepisywania danych:** jedna nowa tabela i nowe kolumny
  z wartościami domyślnymi równymi dzisiejszemu zachowaniu. Żaden istniejący typ, wpis,
  tag, przypisanie, migawka ani tłumaczenie nie jest modyfikowane — kształt danych na
  VPS nie ma więc znaczenia dla bezpieczeństwa migracji. Każda migracja jest odwracalna.
- Jedyna zmiana ograniczenia: unikalność klucza tagu w stronie zostaje zawężona do
  wierszy bez taksonomii (dla istniejących danych to to samo ograniczenie).
- Przed migracją na VPS faza uruchamia tam ten sam odczyt liczący, którym zmierzono
  stosy lokalne (typy, wpisy, tagi, tagi użyte w dwóch typach, strony z więcej niż
  jednym typem), i zapisuje wynik w `memex ops` — dla porównania po wdrożeniu, nie
  jako warunek.
- Zmiana zachowania API, jedyna: założenie drugiego typu na stronie wymaga odtąd
  przełącznika platformy i cechy planu (dziś integracja mogła je założyć bez limitu).
  Typy już istniejące zostają.

## Zmiany wcześniejszych decyzji

- **ADR-031** (katalog dziewięciu sekcji; `core.entry_list` poza katalogiem): blok w
  wersji 2 wchodzi do katalogu jako „Lista wpisów” (pkt 14).
- **ADR-071 pkt 14** i „Uzupełnienie 2026-10-07”: slug tagu przestaje być wspólny dla
  języków (pkt 9); długiem zostają segment `tag` i kotwice nagłówków.
- **Komentarz `ContentTag`** („celowo jedna płaska taksonomia”): zmieniony zamówieniem
  właściciela z 2026-10-08 — dochodzą kategorie per typ; tagi zostają, jakie były.
- **ADR-035 §1, §7:** bez zmiany zasady (wpis publikuje się sam, indeks jest projekcją);
  kolekcja dostaje nazwę „typ treści” i może być wyłączona.
- **ADR-070 pkt 18:** reguła „slug liczy kod, zamyka pierwsza publikacja” obejmuje
  adresy pozycji taksonomii.
- **ADR-077 pkt 2:** `provision_platform_workspace` nadaje dodatkowo
  `sites.content_types.enabled`. Strony publiczne produktu jako zakodowane widoki
  (zamiast kreatora) rozstrzyga decyzja właściciela i pakiet tras produktu, nie ten ADR.

## Fazy

Szczegóły, zależności i odbiór każdej fazy: plan memex `saas-core-typy-tresci`. Dzień
znaczy tu dzień roboczy pakietu z pełną bramką, przebudową stosu i przejściem w
przeglądarce.

| Faza | Zakres | Szacunek | Co właściciel kliknie |
| --- | --- | --- | --- |
| CT1 | Typy treści: bramki i limit, „Treści” w panelu, nowy typ, wyłączenie, `schema_type`, kanał | 2–3 dni | zakłada „Realizacje”, dodaje wpis, otwiera `/realizacje/` i `/en/projects/` |
| CT2 | Odczyt dla stron produktu (wpis, lista, wersje, sitemapa), nadanie workspace'owi, strona wzorcowa | 2–3 dni | pisze wpis w panelu platformy i widzi go na zakodowanej stronie hosta platformy |
| CT3 | Kategorie i tagi: taksonomia, drzewo, przypisanie, archiwa, adresy per język z 308, filtry w odczycie | 3–4 dni | kategorie w blogu i „Realizacjach”, archiwa w trzech językach |
| CT4 | Zmiana sluga wpisu, przełączniki wyglądu i karty, blok „Lista wpisów” | 2–3 dni | „Ostatnie realizacje” na stronie głównej; zmiana adresu wpisu z przekierowaniem |
| CT5 | Polecenia asystenta, inwentarz SCR, `core:update` produktów, wersje planów, kolejka VPS | 2 dni | to samo w HoofCare i MedPlano; odmowa ponad limit planu |

Razem 11–15 dni. Poza wersją 1 (osobne decyzje): pola własne 4–6 dni, szablony strony
wpisu 5–8 dni, własne taksonomie 1–2 dni, relacje 2–3 dni.

## Ryzyka

- **Klucz a adres pozycji** (pkt 5): pomylenie ich w jednym miejscu kodu gubi wpisy z
  archiwum. Zabezpieczenie: testy złotych adresów archiwów napisane przed zmianą i
  jedna funkcja, która mówi, gdzie odpowiada archiwum.
- **Projekcja czyta wszystkie opublikowane wpisy strony przy każdym żądaniu** indeksu,
  archiwum i sitemapy. Przy kilku typach i tysiącach wpisów to będzie za wolne; CT3
  mierzy to na 1 000 wpisów i w razie potrzeby zawęża zapytanie do typu.
- **Baza testowa omija RLS:** izolację nowej tabeli dowodzi uruchomiony stos, nie test.
- **Kanał strony zmienia skład**, gdy klient założy drugi typ artykułowy — z jego woli,
  odwracalnie jednym przełącznikiem (pkt 15).
- **Zależności:** CT2 zależy od pakietu tras produktu (gdzie stoją zakodowane widoki)
  i od porządków PC1 w `main`; strona wzorcowa CT2 jest odbiorem, nie docelową trasą.
  Pkt 30 trzeba potwierdzić z tym pakietem.
- **Subskrypcje na starych wersjach planów** nie dostają cechy same (pkt 19).

## Rozważane alternatywy

- **Tabela „typ treści” nad kolekcjami** — drugi byt o tych samych polach, migracja
  każdego bloga i zmiana kontraktu SCR za nazwę.
- **Meta wpisu jako tabela klucz–wartość (jak `postmeta`)** — wartości poza wersją,
  publikacją i cofnięciem; każda lista to dodatkowe zapytania; tłumaczenie nie wie, co
  jest tekstem.
- **Hierarchia szablonów jak w WordPressie** — kreator ma własny sposób: listę bloków.
- **Taksonomie zawsze wspólne dla strony, z tabelą łączącą typ i taksonomię** — druga
  nowa tabela dla przypadku, o który nikt nie prosił.
- **Wiersz taksonomii także dla tagów już teraz** — wymaga dopisania danych każdej
  stronie z tagami; odłożone do spłaty długu segmentu `tag`.
- **Zagnieżdżony adres kategorii** — przeniesienie kategorii ruszałoby adresy
  wszystkich podrzędnych.
- **Sam limit bez cechy planu („brak liczby = zero”)** — odwraca regułę wszystkich
  pozostałych limitów (brak = bez limitu) w jednym miejscu.
- **Zamrożenie typów ponad limit po obniżeniu planu** — pytanie 2.
- **Osobne tabele produktu na jego blog** — własny edytor, tłumaczenia, harmonogram i
  SEO w każdym produkcie; właściciel wybrał system wspólny.
- **Odczyt jako publiczne API dla wszystkich stron firm** — produkt, nie mechanizm.

## Pytania do właściciela

1. **Gdzie typy w menu panelu.** (a) jedna pozycja „Treści” z listą typów (blog
   pierwszy); (b) osobna pozycja menu na każdy typ, jak w WordPressie. Rekomendacja: (a)
   — menu panelu jest statyczne, a (b) wymaga nowego mechanizmu w powłoce panelu.
2. **Obniżenie planu.** (a) typy ponad limit działają dalej, nie da się tylko dodać
   kolejnego — jak języki i podstrony; (b) typy ponad limit przestają przyjmować nowe
   wpisy do czasu wyłączenia któregoś albo powrotu na wyższy plan. Rekomendacja: (a).
   Przy okazji — liczby z pkt 19 (Site 1, Pro 10) są do zmiany.
3. **Własne taksonomie firmy.** (a) wersja 1: kategorie i tagi, własne później (model
   gotowy, 1–2 dni); (b) własne taksonomie już w wersji 1. Rekomendacja: (a).
4. **Kolejność.** (a) po typach najpierw odczyt dla stron produktu (CT2), bo czeka na
   niego 91 wpisów Puppily, potem kategorie; (b) najpierw kategorie i tagi dla klientów.
   Rekomendacja: (a).
5. **Kanał RSS a nowe typy.** (a) typy artykułowe wchodzą do kanału strony, pozostałe
   nie, klient może przełączyć; (b) do kanału wchodzi tylko pierwszy typ. Rekomendacja:
   (a).

## Relacje

- **ADR-027, ADR-031** — bloki i katalog sekcji; **ADR-035** — dwa rodzaje powierzchni,
  granty, kontrakt zmian; **ADR-054, ADR-057** — listy i strony panelu.
- **ADR-032, ADR-033** — cechy i limity planów; **ADR-049** — `features` profilu.
- **ADR-039, ADR-041** — RLS nowej tabeli; ścieżka sprzed tenanta bez nowych drzwi.
- **ADR-069, ADR-070, ADR-071** — tłumaczenia, slugi, języki, adresy i SEO;
  `docs/architecture/translation-sources.md` — źródła `sites.entry` i tekstów strony.
- **ADR-076, ADR-078** — polecenia asystenta; ustawienia firmy (cechy typu są polami
  typu, nie ustawieniami firmy).
- **ADR-048, ADR-077** — strony produktu i workspace platformy jako wydawca.
