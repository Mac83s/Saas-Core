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
`InlineText` i tą samą historią RHF. Nie dodajemy zależności edytora ani
`contentEditable`; wybór silnika bogatej edycji pozostaje otwarty i wymaga
osobnej decyzji. Normalizacja zapisu nie przycina spacji wewnątrz przebiegów.

## Automatyzacja treści

Content Operations v1 bez zmian: connector może wstawić `core.rich_text` v1
albo v2 (obie wersje są w `block_schemas`). Zastąpienie bloku zachowuje jego
`presentation` jak dekorację; jawne ustawianie wyglądu wymaga v2 kontraktu.
Zapis przez change set dziedziczy `page_presentation`. Blueprint (ADR-046) nie
tworzy slotów z przebiegów samych spacji, z cytatów (`core.quote` i węzłów
`quote`) ani z podpisów; nowe pola `lead` i `tagline` są slotami tekstu.
Automat nie wypełnia cytatów, cen, kwalifikacji ani wyników.
