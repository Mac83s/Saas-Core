# Bogata treść, pełna szerokość i lokalny wygląd strony

Status: faza 1–2 planu `saas-core-site-studio-rich-content-and-full-width`
(memex), implementacja w Saas-Core od 2026-09-23. Rozszerza ADR-027/031 bez
wykonywania kodu z danych. Wdrożenie stosu i aktualizacja produktów to osobne
bramki.

## Mapowanie rodzin katalogu na typy bloków

Nowy typ rejestru powstaje tylko przy odrębnym znaczeniu danych, nie dla każdej
karty biblioteki.

| Rodzina katalogu | Typ i wersja | Uzasadnienie |
|---|---|---|
| Treści redakcyjne | `core.rich_text` v2 | ten sam tekst redakcyjny, teraz strukturalny |
| Listy i objaśniane kroki | `core.feature_list` v4 | lista pozycji z objaśnieniem; v4 dodaje wstęp, panel uwag i dłuższe opisy |
| Cytaty redakcyjne | `core.quote` v1 | cytowana wypowiedź z autorem i źródłem; nie jest opinią klienta, nie ma oceny |
| Prezentacje produktu | `core.product` v1 | produkt z fotografiami, parametrami i zastosowaniami; bez ceny, stanu i koszyka |

Historie obrazem i galerie dostaną własny typ w kolejnej fazie. Wszystkie
poprzednie wersje schematów pozostają bez zmian i nadal są przyjmowane.

## `core.rich_text` v2 — struktura zamiast napisu

`data.content` to lista węzłów JSON: `paragraph`, `heading` (H2–H4),
`list` (punktowana/numerowana, najwyżej dwa poziomy), `quote` (autor, źródło,
opcjonalny link), `note` (ton info/tip/warning, tytuł) i `figure` (obraz, alt,
podpis, szerokość kolumny lub szeroka). Akapit, element listy, cytat i uwaga
składają się z przebiegów `{text, bold?, italic?, href?}`. `href` dopuszcza
wyłącznie `/ścieżkę`, `https://`, `mailto:`, `tel:` oraz `#kotwicę`; `//host`
i `javascript:` są odrzucane przez wzorzec. Opcjonalne pola sekcji: `layout`,
`title` (H2 sekcji), `lead` i `aside` (panel faktów/podsumowania: akapity
i listy). Nie zapisujemy HTML ani Markdown.

Limity techniczne (po teście dokumentu XL): do 160 węzłów, 64 przebiegi na
akapit, 4000 znaków przebiegu, 40 pozycji listy i 20 podpozycji. Miękkie
wskazówki długości należą do katalogu, nie do walidacji.

**Migracja v1 → v2** zamienia `{text}` na jeden akapit z jednym przebiegiem,
bez zmiany żadnego znaku. Blok v2, który ma tylko taki akapit i nie ma
`layout`, `title`, `lead` ani `aside`, renderuje się bajt w bajt jak v1
(`<section class="site-block site-block--rich-text" …><p>…</p></section>`),
więc stare publikacje, renderowane zawsze przez najnowszy komponent, nie
zmieniają wyglądu. Podział na akapity jest jawną akcją w edytorze.

**Kotwice** śródtytułów są zapisane w dokumencie (`anchor`,
`^[a-z][a-z0-9-]{0,63}$`). Edytor tworzy je z tekstu przy dodaniu śródtytułu i
nie zmienia ich przy późniejszej edycji tekstu. Kotwice są unikalne w obrębie
strony: wstawienie sekcji, duplikacja i import szablonu naprawiają kolizje
(sufiks `-2`, `-3`…) razem z linkami `#kotwica` tej sekcji. Backend odrzuca
zapis z powtórzoną kotwicą (400 `duplicate_rich_text_anchor`). Identyfikator
`id` nagłówka pojawia się tylko w publikacji; podglądy w panelu go nie emitują,
żeby wiele podglądów na jednym ekranie nie dublowało identyfikatorów.

### Układy redakcyjne pierwszego przekroju

| Układ | Kompozycja |
|---|---|
| `column` | klasyczna kolumna czytania z tytułem i wstępem |
| `split_intro` | tytuł i krótki wstęp obok obszernego wyjaśnienia |
| `facts_panel` | tekst z panelem najważniejszych faktów (`aside`) |
| `chapters` | rozdziały z indeksem tematów zbudowanym z kotwic H2 |

Każdy układ renderuje wszystkie pola; zmiana układu niczego nie ukrywa. Panel
`aside` w kolumnie i rozdziałach pojawia się po treści. Na telefonie kolejność
DOM jest kolejnością czytania.

## Pełna szerokość z czytelną treścią

Trzy poziomy, każdy jako zamknięta lista wartości:

1. **Strona** — `PagePresentation` v1 (`page-presentation.v1.schema.json`):
   `width: contained | full`, `headingFont`, `bodyFont` (te same fonty co
   wygląd witryny). Zapisany w `PageVersion.presentation`, w API jako
   `page_presentation`.
2. **Sekcja** — koperta `presentation` v1 obok `decoration`
   (`section-presentation.v1.schema.json`): `inner: narrow | standard | wide |
   full` i `surface: default | muted | accent | inverse`.
3. **Tekst** — kolumna czytania `.site-prose` ma własną miarę ok. 68 znaków,
   niezależną od szerokości tła. To cel projektowy, nie limit danych.

Mechanika CSS: szerokość witryny trafia do zmiennej `--site-content-width`
(56/72/96 rem). Strona `full` zdejmuje limit z `.site-theme`, a każda sekcja
centruje zawartość paddingiem `max(odstęp, (100cqw − szerokość wnętrza) / 2)`.
`cqw` odnosi się do kontenera `.site-theme`, czyli do obszaru strony — także w
canvasie telefonu na monitorze 3440 px — nigdy do okna (`100vw` jest zakazane).
Na stronie `contained` ten sam wzór daje dotychczasowy odstęp, więc stare
strony się nie zmieniają. Header i stopka strony `full` mają tło przez całą
szerokość, a linki w szerokości witryny.

Powierzchnia sekcji (`surface`) to jej schemat kolorów z palety witryny.
Dekoracja pozostaje warstwą ornamentu nad nią; nie ma dwóch pól o tej samej
funkcji. Klasy koperty trafiają na najbardziej zewnętrzny element sekcji
(opakowanie dekoracji, a bez niej korzeń bloku). Brak koperty to brak klas.

### Własność wyglądu strony

`page_presentation` należy do jednej wersji strony: ten sam optimistic lock,
wersjonowanie, hash treści i snapshot publikacji. Nie zmienia headera, stopki,
nawigacji, domeny ani innych podstron. Zasady zapisu:

- brak pola w żądaniu zachowuje wartość z bieżącego draftu (starsi klienci,
  change sets i blueprinty niczego nie resetują);
- jawne `null` przywraca dziedziczenie wyglądu witryny;
- hash treści i żądania zawiera klucz tylko, gdy wartość nie jest pusta, więc
  hashe istniejących wersji się nie zmieniają;
- odrzucenie propozycji przywraca wygląd poprzedniej wersji;
- import recepty v4 z `pagePresentation` ustawia go na nowym drafcie, recepta
  bez niego zachowuje obecny;
- snapshot publikacji niesie kopię (`pages[].page_presentation`), rollback
  kopiuje ją z całym snapshotem, publiczne API zwraca ją obok `appearance`.

Wpisy kolekcji nie mają jeszcze wyglądu strony (osobny kontrakt
`ContentEntryVersion`); kopertę `presentation` sekcji zachowują jak dekorację.

## Wiele zdjęć w bloku

Identyfikatory mediów zbiera jeden przechodzący po danych walker (klucz
`asset_id` w dowolnym obiekcie danych bloku): `blockAssetIds` w
`@saas-core/site-blocks` dla panelu i odpowiednik w backendzie. `save_draft`
i `save_entry_draft` łączą listę klienta z identyfikatorami znalezionymi w
blokach, więc ilustracje w tekście, galerie produktu i bloki wstawione przez
change set trafiają do referencji wersji i publikacji. Nieistniejący lub
niegotowy asset nadal kończy zapis 409 `site_media_reference_unavailable`.

Recepta v4 (`page-template.v4.schema.json`, nadzbiór v3) przyjmuje
`mediaBindings[].path`: ścieżkę obiektu obrazu w danych bloku. Ostatni
segment to klucz istniejącego obiektu albo indeks istniejącej tablicy nie
większy niż jej długość (równy — dopisuje). Brak ścieżki oznacza `["image"]`.
Para (pozycja bloku, ścieżka) jest unikalna, więc blok może mieć kilka zdjęć.
Blok recepty jest walidowany po podpięciu zdjęć zastępczym identyfikatorem —
w pliku recepty nie ma żadnego `asset_id`. Recepta v4 może też nieść
`decoration` i `presentation` bloku oraz `pagePresentation`. Limity 20 bloków
i 10 zdjęć recepty pozostają bez zmian.

Katalog sekcji v5 (`section-templates.v5.json`) zachowuje wszystkie 96 recept
v4 bez zmian i dodaje opcjonalne `sampleMedia.path` oraz metadane dopasowania:
`contentProfiles` (S/M/L/XL), `readingPattern`, `styleAffinities` (osiem
kierunków wizualnych), `supportedWidths`, `targetSurface`. Ziarno sekcji musi
być poprawne bez zdjęcia.

## Edytor

Pole katalogu `kind: "richText"` wskazuje całą tablicę `content`. Inspektor
pokazuje panel pisania: pasek wstawiania (akapit, śródtytuł, lista, lista
numerowana, cytat, uwaga, ilustracja), spis śródtytułów prowadzący do pola,
przesuwanie i usuwanie węzłów. Przebiegi akapitu edytuje się w zwykłym polu
tekstowym przez minimalny zapis `**pogrubienie**`, `*kursywa*`,
`[etykieta](adres)` z ucieczką `\`; przyciski B/I/link i skróty Ctrl/Cmd+B/I
opakowują zaznaczenie. To reprezentacja w polu edycji — zapisywany jest JSON
przebiegów. Lista to jedno pole: wiersz to pozycja, wcięcie to podpozycja.
Wklejenie z dokumentu normalizuje HTML (p, h1–h6, ul/ol/li, blockquote,
strong/b, em/i, a z dozwolonym adresem) do dozwolonych węzłów; zwykły tekst
dzieli po pustych liniach. Obrazy z schowka nie są importowane.

Płótno edytuje w miejscu teksty przebiegów, śródtytułów i podpisów tym samym
`InlineText` i tą samą historią RHF. Normalizacja zapisu nie przycina spacji
wewnątrz przebiegów.

Etap 2b zastępuje panel ze składnią `**` edytorem WYSIWYG (TipTap) na tym
samym kontrakcie — [ADR-056](../adr/ADR-056-Edytor-Tekstu-WYSIWYG-Na-Kontrakcie-Rich-Text.md):
schemat edytora = węzły `core.rich_text`, zapis wyłącznie JSON, jedna
historia cofania, pisanie w panelu bocznym i na pełnym ekranie. Do czasu
objęcia wszystkich węzłów panel działa jak wyżej.

## Automatyzacja treści

Content Operations v1 bez zmian: connector może wstawić `core.rich_text` v1
albo v2 (obie wersje są w `block_schemas`). Zastąpienie bloku zachowuje jego
`presentation` jak dekorację; jawne ustawianie wyglądu wymaga v2 kontraktu.
Zapis przez change set dziedziczy `page_presentation`. Blueprint (ADR-046) nie
tworzy slotów z przebiegów samych spacji, z cytatów (`core.quote` i węzłów
`quote`) ani z podpisów; nowe pola `lead` i `tagline` są slotami tekstu.
Automat nie wypełnia cytatów, cen, kwalifikacji ani wyników.

## Stan wdrożenia w kodzie — 2026-09-23

Gałąź `feat/site-studio-rich-content`. Zrealizowane fazy 1–2 planu; brak
wdrożenia stosu i `core:update` produktów.

- **Kontrakty:** `core.rich_text` v2, `core.feature_list` v4, `core.quote` v1,
  `core.product` v1, koperty `section-presentation.v1` i
  `page-presentation.v1`, recepta `page-template.v4` (manifest wskazuje v4 dla
  wszystkich recept), katalog `section-templates.v5` (104 recepty: 96 z v4 bez
  zmian i 8 nowych). Galeria produktu dopuszcza pustą tablicę, żeby powiązanie
  zdjęcia mogło ją uzupełnić.
- **Backend:** migracja `sites/0032_page_presentation` (dwa odwracalne
  `AddField`), kontrole `sites.E007` i `sites.E008`, pola
  `page_presentation_before/after` w szczegółach propozycji (tylko gdy
  niepuste). Treść śródtytułu rich text jest slotem blueprintu o limicie 200.
- **Adresy `#kotwica`** przyjmują wyłącznie przebiegi rich text. Przycisk
  produktu, hero i `link_list` nadal dopuszczają tylko `/`, `https://`,
  `mailto:` i `tel:`, dlatego recepty kierują zapytania na `mailto:` albo
  formularz, a spis treści usługi jest sekcją rich text.
- **Szerokość `wide`** to szerokość witryny + 20 rem (najwyżej cała strona).
  Na stronie `contained` równa się `standard`. Recepty używają jej tylko dla
  sekcji prowadzonych zdjęciem; sekcje tekstowe trzymają krawędź witryny.
  Hero `banner` z `inner: full` na stronie pełnej szerokości ma zdjęcie od
  krawędzi do krawędzi i tekst w linii headera.
- **Walidacja w panelu** zawęża błędy unii węzłów do gałęzi wskazanej przez
  `type` węzła, więc fokus trafia w istniejące pole.
- **Dowód zgodności wstecznej:** osiem dotychczasowych recept renderuje się
  bajt w bajt tak samo jak na `bf1a014`, a ich zrzuty 1440/390/3440 px są
  identyczne co do piksela (Chromium, 24/24).

## Faza 3 — układy redakcyjne pod konwersję (od 2026-09-23)

Decyzja właściciela: szablony powstają pod konwersję (lista kontrolna w
[site-section-catalog.md](site-section-catalog.md)). `core.rich_text` v3 =
v2 + opcjonalne `eyebrow` (etykieta nad tytułem), `image` (zdjęcie z
podpisem), `author` (imię, rola, portret), `action` i `secondaryAction`
(główne i ciche działanie; `href` jak w linkach bloków plus `#kotwica`).
Migracja v2 → v3 kopiuje dane. Katalog v6 dodaje `conversion`: etap ścieżki
(`attention`, `interest`, `proof`, `objection`, `action`) i to, czy sekcja
niesie główne działanie; pole jest wymagane dla każdej recepty dodanej od v6.

**Działanie w sekcji.** Gdy jest `action`, sekcja kończy się rzędem
`.site-section__actions`: przycisk główny i opcjonalnie ciche działanie
(obrys/link). Jedno główne działanie na sekcję. Układy niżej mówią, gdzie
rząd stoi, jeśli nie na końcu. W edytorze przyciski są tekstem do edycji,
bez nawigacji.

**Rozdziały.** Kilka układów dzieli `content` na grupy zaczynające się od
śródtytułu H2 (treść przed pierwszym H2 to wstęp). Kolejność DOM zawsze
odpowiada kolejności czytania; układ zmienia tylko rozmieszczenie.

| Układ | Kompozycja | Etap |
|---|---|---|
| `lead_statement` | `lead` w skali nagłówka jako teza, pod nim rozwinięcie w kolumnie czytania, działanie pod tekstem | attention |
| `two_parts` | dwie pierwsze grupy H2 obok siebie jako równoległe części (np. „dla kogo / dla kogo nie”), kolejne pod spodem | interest |
| `side_photo` | tekst obok `image` z podpisem; na telefonie zdjęcie po tytule | interest |
| `panorama` | `image` od krawędzi do krawędzi sekcji nad tytułem, potem wstęp, tekst i działanie | attention |
| `illustrated` | kolumna artykułu; `image` stoi w toku czytania po pierwszym akapicie i wychodzi poza kolumnę do szerokości sekcji, tak samo ilustracje `width: wide` | interest |
| `margin_quote` | pierwszy węzeł `quote` jako duży cytat na marginesie obok tekstu (na telefonie w toku) | proof |
| `summary_box` | panel `aside` jako „w skrócie” przed tekstem, wyróżniony | interest |
| `expert_note` | karta `author` (portret lub inicjały, imię, rola) obok objaśnienia; działanie pod kartą | proof |
| `alternating_chapters` | grupy H2 jako rzędy: śródtytuł po jednej stronie, treść po drugiej, strony zamieniają się co rozdział; ilustracja grupy dołącza do strony śródtytułu | interest |
| `timeline` | grupy H2 jako punkty osi czasu z pionową linią | interest |
| `numbered_sections` | grupy H2 z dużymi numerami 01, 02… jako kolejne argumenty | objection |
| `manifesto` | pozycje list jako duże zasady, akapity jako krótkie rozwinięcia, działanie po zasadach | attention |
| `problem_solution` | trzy pierwsze grupy H2 jako panele problem → analiza → rozwiązanie; działanie w panelu rozwiązania | action |
| `howto` | listy numerowane jako duże kroki, lista punktowana jako lista kontrolna, uwagi jako objaśnienia z boku | objection |
| `resources` | pozycje list zawierające link jako karty materiałów, wstęp nad nimi | proof |
| `essay_cta` | kolumna eseju, `aside` jako ramka „wnioski”, na końcu pas z głównym i cichym działaniem | action |

Jedyny wyjątek od kolejności danych: w `alternating_chapters` ilustracje
rozdziału stoją w DOM przy śródtytule (czytanie: śródtytuł → ilustracja →
tekst, tak jak na ekranie). Karta autora i cytat pokazują inicjały tylko z
prawdziwego imienia; imię z miejscem `[Uzupełnij: …]` daje neutralny znak.

Razem z `column`, `split_intro`, `facts_panel` i `chapters` to 20 układów
rodziny redakcyjnej. Seedy katalogu mówią językiem korzyści klienta; dowody
(opinie, liczby, realizacje) są miejscami `[Uzupełnij: …]` (EN `[Fill in: …]`),
nigdy wymyśloną treścią. Edytor strony pokazuje, które sekcje mają jeszcze
takie miejsca (`unfilledPlaceholders` w `@saas-core/site-blocks`), zanim
właściciel zapisze i opublikuje stronę.

## Faza 3b — style stron, kotwice sekcji, recepty pod konwersję

### Kotwice sekcji i przyciski „do formularza”

Koperta `presentation` v2 (`section-presentation.v2.schema.json`) dodaje
`anchor`. Najbardziej zewnętrzny element sekcji dostaje `id` równy kotwicy,
tylko w publikacji (jak `id` śródtytułów). Kotwice sekcji i śródtytułów to
jedna przestrzeń nazw, unikalna na stronie; backend odrzuca powtórzenie
(400 `duplicate_rich_text_anchor`), edytor naprawia kolizje przy wstawianiu i
duplikacji. `core.hero` v6 i `core.product` v2 pozwalają przyciskom
prowadzić pod `#kotwica`; hero v6 ma też cichsze `secondaryAction`. Recepty
nadają formularzowi kontaktu kotwicę `kontakt`, a główne przyciski strony
prowadzą do `#kontakt`. Przewijanie zostawia margines na przyklejoną
nawigację (`scroll-margin-top`).

### Osiem kierunków wizualnych (`page_presentation.style`, v2)

Styl strony to zestaw decyzji typograficznych i kompozycyjnych dla sekcji tej
strony. Kolor akcentu pozostaje z palety witryny; header, stopka i menu się
nie zmieniają. Jawnie wybrany font nagłówków lub tekstu wygrywa ze stylem.
Brak stylu = dotychczasowy wygląd (piksel w piksel), z trzema poprawkami,
które dotyczą każdej strony:

- blok opinii `core.testimonials` ma własny wygląd — wcześniej cytat, imię i
  rola zlewały się w jeden wiersz;
- w siatkach dwukolumnowych (kafle, bento, chipy, FAQ w kartach) pozycja bez
  pary zajmuje cały ostatni wiersz, a cztery karty `cards` układają się 2 × 2;
- sekcje kontaktu v2 stosują tło i szerokość z koperty prezentacji (wcześniej
  były po cichu pomijane).

| Styl | Typografia | Rytm i kształty | Charakter |
|---|---|---|---|
| `editorial` | nagłówki Lora 600, tekst Inter | przestronnie, cienka linia nad sekcją, promień 2 px | etykiety kapitalikami z rozstrzeleniem, wstęp większą czcionką |
| `product` | nagłówki Manrope 800, ciasne odstępy liter, skala ×1,1 | promień 14 px, zdjęcia z miękkim cieniem | duże przyciski w kształcie pigułki, mocne pasy ciemnej powierzchni |
| `studio` | nagłówki Manrope 800, skala ×1,3, bardzo ciasno | kąty proste, gruba linia pod tytułem sekcji | wysoki kontrast, przyciski prostokątne z grubym obrysem |
| `mosaic` | nagłówki DM Sans 700 | promień 18 px, pozycje list i paneli jako karty z cieniem | lekkie stonowane tła, większe odstępy siatki |
| `premium` | nagłówki Playfair Display 500, tekst Inter | bardzo przestronnie, kąty proste | etykiety z szerokim rozstrzeleniem; przyciski kwadratowe, wersaliki — główny wypełniony, drugi jako podkreślony link |
| `expert` | nagłówki DM Sans 600, tekst Inter | spokojny rytm, promień 10 px | uwagi i panele faktów w miękkim tle, czytelna hierarchia |
| `organic` | nagłówki i tekst Nunito | promień 24 px, zdjęcia mocno zaokrąglone | ciepłe stonowane tło, przyciski-pigułki |
| `technical` | nagłówki Inter 700, liczby tabelaryczne | promień 4 px, delikatna siatka na stonowanym tle | etykiety czcionką o stałej szerokości, parametry jak tabela |

Style działają przez klasę `site-style--{styl}` na `.site-theme` i reguły
ograniczone do wnętrza sekcji (`.site-block`), więc nie dotykają headera i
stopki. Wymagania: kontrast WCAG AA na wszystkich powierzchniach, cele dotyku
44 px, telefon 320 px bez przewijania w bok, bez nowego ruchu.

### Recepty stron v5 i wycofanie słabych szablonów

`page-template.v5.schema.json` (nadzbiór v4) dodaje `conversion`: cel strony
(`inquiry`, `call`, `booking`, `email`, `visit`) i etap ścieżki każdego bloku
(ta sama długość i kolejność co `blocks`). Każda najnowsza recepta, która nie
jest wycofana, ma `conversion`, zaczyna się etapem `attention`, ma co
najmniej jeden blok `action` i przechodzi listę kontrolną konwersji. W
manifeście szablonów `retired: true` ukrywa osiem dawnych szablonów w galerii
i w katalogu blueprintów; ich pliki zostają, strony już z nich zbudowane się
nie zmieniają, a import przez API po identyfikatorze nadal działa.
