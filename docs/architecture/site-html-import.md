# Tabela w treści i konwerter HTML → bloki

Status: plan memex `saas-core-wielojezycznosc-i-tlumaczenia-ai`, faza PB2
(2026-10-07); reguły dla podkreślenia, pogrubionych etykiet, słów poza
miejscem na słowa i linku w śródtytule ustalone po pierwszym przebiegu na
prawdziwych treściach (PB2c, 2026-10-08). Rozszerza ADR-027 (treść jako bloki) i ADR-056 (edytor na
kontrakcie) bez zmiany istniejących schematów. Powód: treści pisane poza
rdzeniem (wpisy i opisy w HTML) mają trafić do stron i wpisów, a 86 tabel w
przenoszonych wpisach nie miało w rdzeniu odpowiednika.

## `core.table` v1

`packages/contracts/site-blocks/core.table.v1.schema.json`. Wiersze komórek,
nigdy HTML:

| Pole | Znaczenie |
|---|---|
| `rows[].cells[]` | 1–120 wierszy, 1–12 komórek; komórka to `{content}` — jeden przebieg tekstu jak w `core.rich_text` (pogrubienie, kursywa, link z listy dozwolonych adresów i `rel`, ADR-061) — albo `{}`, gdy jest pusta |
| `caption` | podpis tabeli, do 300 znaków, zwykły tekst |
| `header` | które komórki nazywają pozostałe: `row` (pierwszy wiersz, domyślnie), `column`, `both`, `none` |
| `layout` | `lines` (linie między wierszami, domyślnie) albo `striped` (co drugi wiersz na tle) |

Nie ma scalonych komórek ani akapitów czy list w komórce. Każdy wiersz ma mieć
tyle komórek co najdłuższy; renderer dopełnia krótszy pustymi, edytor i
konwerter zawsze zapisują prostokąt.

**Dlaczego blok, a nie węzeł `core.rich_text` v5.** Blok jest czystym
dodatkiem: żaden zapisany tekst nie migruje, model dokumentu edytora WYSIWYG —
który ADR-056 czyni kontraktem — zostaje bez zmian, dwadzieścia układów
tekstu nie musi umieć rysować tabeli, a treść wpisu i tak jest listą bloków,
więc konwerter niczego przez to nie traci. Tabela dostaje też za darmo to, co
ma każda sekcja: kotwicę, dekorację i pozycję w `ContentChangeSet`. Koszt:
tabela jest osobną sekcją — tekst przed nią i po niej to dwa bloki, a w
komórce nie ma akapitów ani list.

**Renderer** (`packages/site-blocks/src/table-block.ts`, style
`packages/ui/src/styles/site-table.css`): prawdziwe `<table>` z `<caption>`,
`<th scope="col|row">` i `<thead>/<tbody>`; pusta komórka nagłówkowa jest
zwykłą komórką. Tabela szersza niż miejsce przewija się w bok we własnym
polu (`role="region"`, nazwa z podpisu albo „Tabela” w języku strony,
`tabindex="0"`) — strona na telefonie nigdy nie przewija się w bok. Blok ma
własne krótkie odstępy zamiast rytmu sekcji, bo stoi między dwoma tekstami.

**Edytor** (`table-editor.tsx`, `table-doc.ts`): pole katalogu rodzaju
`table` — cała siatka w jednym edytorze TipTap; komórki pisze się w miejscu,
znaczniki i link jak w tekście (ten sam `LinkDialog`). Wiersze i kolumny
zmieniają tylko przyciski, a wtyczka `tableGuard` odrzuca każdą edycję, która
zmieniłaby kształt siatki (usunięcie zaznaczenia przez dwie komórki, upuszczony
fragment). Tab przechodzi po komórkach i wychodzi po ostatniej, Enter schodzi
w dół kolumny. Zapis do formularza strony po pauzie i przy wyjściu z pola;
Ctrl+Z to „Cofnij” strony, jak w edytorze tekstu. Wklejany tekst trafia do
komórki jako zwykły tekst. Pusta komórka zapisuje się jako `{}` i formularz
jej nie przycina (`blockPayload`).

**Tłumaczenia.** Jednostki wynikają ze schematu
(`localized_bodies.text_fields`): `caption` to jednostka tekstowa, każda
niepusta komórka to jednostka `inline` z tokenami znaczników
(`<pozycja>/rows/2/cells/1/content`). Pusta komórka nie jest jednostką, więc
wersja językowa nie jest przez nią niekompletna; `header` i `layout` to
struktura. Strony i wpisy dostają to bez własnego kodu.

**Katalog sekcji** (v7): `core.table_lines` i `core.table_striped`, dla stron
i wpisów. Zalążek to siatka miejsc `[Uzupełnij: …]` — tabela nie niesie
przykładowych liczb, cen ani parametrów.

## Konwerter HTML → bloki

`saas_core.modules.shared.sites.api.convert_html` (kod:
`shared/sites/html_blocks.py`). Czysta funkcja: napis HTML na wejściu, lista
bloków i raport strat na wyjściu. Niczego nie zapisuje i czyta tylko kontrakty
bloków, więc import woła ją dla każdego dokumentu, a próba na sucho nic nie
kosztuje. Parser to `html.parser` z biblioteki standardowej z domykaniem
znaczników tak, jak robi to przeglądarka (`<p>`, `<li>`, części tabeli) — bez
nowej zależności.

```python
conversion = convert_html(
    html,
    image_assets={"https://stary.example/a.jpg": "<id zasobu mediów>"},
    default_image_alt="Tytuł wpisu",
    rewrite_link=lambda href: nowy_adres(href),
)
conversion.blocks   # [{"block_type", "schema_version", "data"}], gotowe do save_draft / save_entry_draft
conversion.losses   # (HtmlLoss(severity, kind, detail, count, sample), …)
conversion.images   # każdy <img src> dokumentu — co import ma wgrać najpierw
conversion.stats    # characters_in, characters_out, bloki według typu
```

Każdy blok jest przed zwróceniem sprawdzany swoim schematem
(`HtmlConversionError` oznacza błąd konwertera, nie dokumentu), a kotwice
śródtytułów są unikalne.

### Co się w co zamienia

| HTML | Wynik |
|---|---|
| tekst, `p`, `div` i inne kontenery | akapity `core.rich_text` v4 |
| `b`/`strong`, `i`/`em`, `font-weight`/`font-style` w `style` | znaczniki przebiegu; krótki akapit pogrubiony w całości — śródtytuł (reguła etykiety, niżej) |
| `u`/`ins`, `text-decoration: underline` | na części tekstu pogrubienie; krótki akapit podkreślony w całości — śródtytuł (reguła etykiety, niżej) |
| `a href` | link, gdy kontrakt przyjmuje adres (`/ścieżka`, `https://`, `mailto:`, `tel:`, `#kotwica` śródtytułu tego dokumentu); `http://` i `//host` zapisane jako `https://`; `rel` `sponsored`/`ugc`/`nofollow` zachowany |
| `h1`–`h6` | śródtytuł 2–4 (`h1` → 2, `h5`/`h6` → 4); `id` zgodne z kontraktem zostaje kotwicą, a linki `#stare-id` idą za śródtytułem |
| `ul`/`ol` | lista do dwóch poziomów; głębsze poziomy spłaszczone do drugiego |
| `blockquote` | węzeł `quote`; `cite`/`footer` jako źródło |
| `hr` | `core.separator` (`line`) |
| `table` | `core.table`: `caption`, `thead` albo pierwszy wiersz z samych `th` → nagłówek, pierwsza kolumna `th` → nagłówki wierszy |
| ciąg `div.question_answer` (`h3` + akapity) | jeden `core.faq` v3; śródtytuł `h2` tuż nad nim zostaje tytułem bloku |
| `img` (także w `figure` z `figcaption`) | węzeł `figure`, gdy `image_assets` zna `src` i jest tekst alternatywny |
| `br` w akapicie | granica akapitu |

### Rozstrzygnięcia

- **`<u>`.** Tekst ma pogrubienie, kursywę i link; podkreślenie w sieci czyta
  się jak link, więc kontrakt go nie ma i nie dostaje. Zostaje to, co
  podkreślenie znaczyło. Reguły są ustalone na prawdziwym korpusie (PB2c:
  16 996 dokumentów w pięciu językach, podkreślenie w 49 829 akapitach i
  pozycjach list):
  - **Podkreślona część tekstu to wyróżnienie i zostaje pogrubieniem**
    (`underline_as_bold`): fraza w zdaniu, początek pozycji listy, cała
    pozycja, komórka, cytat. Pogrubienie stojące tuż obok łączy się z nim w
    jeden przebieg. Na słowach już pogrubionych i na linku podkreślenie
    niczego nie dodaje i znika (`underline_dropped`, szczegół „on bold
    words” albo „on a link”); znika też tam, gdzie jest miejsce tylko na
    zwykły tekst — w śródtytule, podpisie, pytaniu i odpowiedzi FAQ
    (`underline_dropped`, „in a heading” itd.).
  - **Krótki akapit podkreślony w całości nazywa to, co po nim następuje, i
    zostaje śródtytułem** (`underline_as_heading`) — reguła etykiety, niżej.
  - Pozostałe 46 351 podkreśleń w korpusie to wyróżnienia (40 537 akapitów,
    5 814 pozycji list).
- **Etykieta: krótki akapit podkreślony albo pogrubiony w całości.** W
  przenoszonych tekstach to jeden zapis na dwa sposoby: 54 z 374 ras ma
  etykiety podkreślone, około 150 innych — takie same pogrubione. Obie stają
  się śródtytułem tą samą regułą (`underline_as_heading`, `bold_as_heading`;
  decyzja 2026-10-08, właściciel może ją cofnąć, a ponowny import ją
  odwraca). Warunki, wszystkie naraz:
  - podkreślona albo pogrubiona jest każda litera i cyfra akapitu albo
    wiersza między `<br>` (interpunkcja może stać poza znacznikiem —
    `<b>Narzędzia</b>:`);
  - ma najwyżej 100 znaków (`LABEL_MAX_LENGTH`);
  - nie kończy się kropką ani wykrzyknikiem — zdanie i okrzyk to wyróżnienie,
    nie nazwa;
  - nie ma linku ani kursywy;
  - po nim stoi tekst, lista, tabela albo pytania. Akapit tuż przed
    śródtytułem `h1`–`h6` albo tuż przed następną etykietą zapowiada rozdziały
    albo serię („Rodzaje hamulców:” nad „1. Szczękowe:”) i sam niczego nie
    nazywa; linia `hr` zamyka to, co przed nią; po ostatnim akapicie dokumentu
    nie ma już nic;
  - jest poziom, na którym może stanąć: o jeden niżej niż ostatni śródtytuł
    `h1`–`h6` nad nim (pod `h2` → `h3`, pod `h3` → `h4`); pod `h4` poziomu już
    nie ma. Tekst bez własnych śródtytułów stoi pod `h2` swojej strony albo
    sekcji, więc etykieta dostaje w nim `h3`. Etykiety nie wchodzą jedna pod
    drugą.

  Akapit, który któregoś warunku nie spełnia, zostaje tym, czym był:
  pogrubienie pogrubieniem (bez pozycji w raporcie), podkreślenie
  wyróżnieniem. Pogrubienie części akapitu, pozycji listy, komórki i cytatu
  nie jest etykietą; nie jest nią też pogrubienie, które dał sam konwerter
  (termin `dt`, wiersz nagłówka tabeli zbyt szerokiej na blok).
  - **Skąd progi.** W korpusie śródtytułem zostaje 26 469 takich akapitów:
    3 473 podkreślone (tylko w opisach ras) i 22 996 pogrubionych (opisy ras
    i 834 we wpisach). Mediana 26 znaków, co setny dłuższy niż 63, najdłuższy
    96; 87% kończy się dwukropkiem, 10% literą albo cyfrą (numer, temat), po
    1% nawiasem i pytajnikiem. Próg 100 obejmuje wszystkie i zostawia zapas
    na dłuższe tłumaczenie.
  - **Co reguła zostawia akapitem** (cały korpus, pięć języków). Pogrubione
    w całości — 1 258: 1 077 tuż przed następną etykietą, 80 okrzyków
    („…!”), 57 zdań z kropką, 18 dłuższych niż 100 znaków, 16 tuż przed
    śródtytułem, 10 pod `h4`. Podkreślone w całości — 199 (zostają
    wyróżnieniem): 194 tuż przed następną etykietą, 5 okrzyków.
  - **Czego reguła nie rozróżnia** (ocena z próbek, nie pomiar; razem około
    330 z 26 469, czyli 1,2%). Zapowiedź listy napisana jak zdanie („Koło
    trzeba wycentrować wtedy, gdy:”) ma kształt etykiety i zostaje
    śródtytułem — około 30 w polskich tekstach, 150 w pięciu językach;
    odróżnia ją tylko gramatyka danego języka, której konwerter nie zna.
    Pogrubiona odpowiedź w kształcie „hasło: wartość” — do 150. Trzy etykiety
    z rzędu — 15: dwie pierwsze zostają pogrubione, trzecia jest śródtytułem.
    Pojedyncze słowo-uwaga z dwukropkiem („Uwaga:”) — 10.
- **Słowa poza miejscem na słowa.** Lista trzyma tylko pozycje, tabela tylko
  komórki, a słowa nie przepadają przez znaczniki wokół nich. Słowa wpisane
  w `ul`/`ol` poza `li` (na przykład po `</li>` zamkniętym za wcześnie)
  zostają własną pozycją w tym samym miejscu, razem z elementami, między
  którymi stoją (`list_text_as_item`); pojedynczy element w miejscu pozycji
  jest czytany jako pozycja (`tag_unwrapped`). Słowa w `table`, `tbody` albo
  `tr` poza komórką stają akapitem przed tabelą, tak jak pokazuje je
  przeglądarka (`table_text_as_paragraph`).
- **Znacznik otwierający bez `>`.** `<b<Rozmiar:</b>`, `<b sztywna rama</b>`,
  `<liRozmiar: 54 cm</li>`: bez `>` znacznik ciągnie się do końca następnego i
  przeglądarka nie pokazuje żadnego ze słów między nimi (parser widzi znacznik
  `b<rozmiar:<` z atrybutami). Nazwa znacznika ani atrybutu nie zawiera `<`,
  więc taki znacznik jest czytany jako ten, którym był, a reszta jako słowa
  (`opening_tag_repaired`; szczegół to odczytany znacznik, próbka to surowy
  zapis). Nazwę wyznaczają kolejno: litery tej samej wielkości przed słowem
  (`<liRozmiar` → `li`), znacznik, który go zamyka (`<bsztywna rama</b>` →
  `b`), na końcu najkrótszy znany znacznik, od którego zaczynają się litery.
  Jeden znak `/`, `.`, `,`, `;`, `:` albo `-` stojący w miejscu `>` jest
  pomijany; `<` także, chyba że stoi za nim znacznik (`<li<b>Rozmiar</b>` —
  tu brakuje samego `>`). Znacznik z prawdziwymi atrybutami (`=`), który
  dopiero po nich wpada na następny, zostaje, jak czyta go przeglądarka: nie
  ma w nim słów. Znacznik, którego nie da się odczytać, jest stratą
  `text_dropped` („inside a broken tag”) z surowym zapisem w próbce. W
  korpusie: 75 dokumentów, same tłumaczenia (de 45, en 26, ru 3, es 1), około
  1 800 znaków — wszystkie odczytane.
- **Dokument urwany w środku znacznika.** Koniec `…</li> </`, `…</p><p` albo
  `…<a href="/x` to początek znacznika, nie słowa: jest odcinany
  (`unfinished_tag_dropped`, próbka to urwany fragment). Taka pozycja raportu
  znaczy, że treść została ucięta u źródła i warto ją tam sprawdzić — w
  korpusie 3 dokumenty. Urwany koniec, w którym po nazwie znacznika stoją
  słowa bez `=` (`…<pI ostatnie zdanie`), to zepsuty znacznik otwierający,
  którego słów nie da się odróżnić od atrybutów: strata `text_dropped`.
- **Link w śródtytule.** Śródtytuł to zwykły tekst, więc link w nim przepada,
  a słowa zostają. Strata `heading_link_dropped` ma w szczególe cały adres
  (po `rewrite_link`, nieskrócony), a w próbce tekst śródtytułu — o tym, co z
  linkiem zrobić, decyduje import. W korpusie 7 wpisów.
- **`div.question_answer`.** Odpowiedź w `core.faq` to zwykły napis. Grupa
  zostaje blokiem FAQ tylko wtedy, gdy każda odpowiedź to zwykłe akapity w
  granicach bloku (pytanie do 200, odpowiedź do 2000 znaków). Grupa z linkiem,
  listą, tabelą albo obrazem w odpowiedzi zostaje tekstem (śródtytuł i jego
  akapity, `faq_kept_as_text`) — inaczej przepadłby adres albo struktura.
  Ceną jest brak danych strukturalnych FAQ dla takiej grupy.
- **Linki.** Konwerter nie zgaduje celu: adres, którego kontrakt nie przyjmuje
  (względny, `javascript:`, kotwica bez śródtytułu), traci link, a słowa
  zostają (`link_dropped`). Import przepisuje stare adresy przez
  `rewrite_link`, zanim konwerter je oceni.
- **Obrazy.** Blok wskazuje zasób mediów, nie adres. Pierwszy przebieg bez
  `image_assets` wymienia wszystkie `src` (`images`); po wgraniu mediów drugi
  przebieg wstawia ilustracje. Obraz w komórce, pozycji listy, cytacie albo
  śródtytule nie ma gdzie stanąć i jest stratą.

### Raport strat

Każda różnica między wejściem a wyjściem to jeden `HtmlLoss` — rodzaj, szczegół,
liczba wystąpień w dokumencie i próbka (pierwsze słowa albo wartość).

| Waga | Znaczenie | Rodzaje |
|---|---|---|
| `lost` | treść przepadła | `tag_dropped` (element usunięty z zawartością: `script`, `iframe`, `form`…), `link_dropped`, `heading_link_dropped`, `image_dropped`, `text_dropped`, `text_mismatch` |
| `changed` | wszystko zostało, powiedziane inaczej | `underline_as_bold`, `underline_as_heading`, `bold_as_heading`, `underline_dropped`, `list_text_as_item`, `table_text_as_paragraph`, `opening_tag_repaired`, `unfinished_tag_dropped`, `strikethrough_dropped`, `superscript_flattened`, `subscript_flattened`, `code_mark_dropped`, `tag_unwrapped`, `heading_level_changed`, `heading_marks_dropped`, `heading_too_long`, `line_break_as_paragraph`, `line_break_as_space`, `blocks_flattened`, `blocks_joined`, `list_nesting_flattened`, `list_numbering_dropped`, `list_item_without_text`, `sublists_merged`, `sublist_overflow_promoted`, `table_span_flattened`, `table_column_widths_dropped`, `table_footer_as_rows`, `table_extra_header_rows`, `table_header_cell_as_data`, `table_too_wide`, `table_caption_as_paragraph`, `caption_marks_dropped`, `faq_kept_as_text`, `faq_marks_dropped`, `faq_paragraphs_joined`, `faq_heading_as_title`, `link_upgraded_to_https`, `link_target_dropped`, `link_rel_dropped`, `image_moved_after_paragraph`, `image_alt_shortened`, `preformatted_flattened`, `definition_list_flattened`, `marks_dropped_over_run_limit`, `class_dropped`, `style_dropped`, `attribute_dropped`, `comment_dropped`, `declaration_dropped`, `quote_source_marks_dropped`, `empty_block_dropped`, `stray_end_tag` |
| `split` | jedno stało się kilkoma przez limit | `rich_text_split` (ponad 160 węzłów: cięcie przed ostatnim `h2`, potem `h3`, `h4`, na końcu na limicie), `list_split` (ponad 40 pozycji), `table_split` (ponad 120 wierszy; podpis i wiersz nagłówka powtórzone), `faq_split` (ponad 30 pytań), `paragraph_split` (ponad 64 przebiegi) |

Dwa rachunki zamykają raport. Każdy węzeł tekstu wejścia trafia do bloku albo
jest nazwany w stracie, a liczba znaków przeczytanych (bez białych znaków)
musi równać się liczbie zapisanych; różnica sama jest stratą (`text_dropped`,
`text_mismatch`). Luka w konwerterze wychodzi więc jako pozycja raportu, a nie
jako brakujące słowa. Znaki dopisane przez konwerter (powtórzony nagłówek
dzielonej tabeli, myślnik pozycji listy bez słów) są odliczane.

`text_dropped` nie jest już wynikiem żadnej reguły: zostaje dla luki w
konwerterze i dla zepsutego znacznika, którego słów nie da się odczytać. Na
korpusie PB2c (16 996 dokumentów) obie liczby, `text_dropped` i
`text_mismatch`, wynoszą 0.

### Próba na sucho

```
python manage.py sites_convert_html wpis.html
python manage.py sites_convert_html wpis.html --json > wpis.json
python manage.py sites_convert_html wpis.html --image https://stary.example/a.jpg=<id zasobu>
```

Wypisuje bloki według typu, znaki przeczytane i zapisane oraz każdą stratę.
Nie tworzy strony, wpisu ani mediów.

### Poza zakresem

Sam import (tworzenie wpisów i stron, media, przepisywanie adresów,
pochodzenie tłumaczeń) należy do pakietu importu. Konwerter nie zna żadnego
produktu: jedyna konwencja źródła, jaką rozpoznaje, to klasa pytania z
odpowiedzią, podawana parametrem `faq_class` (domyślnie `question_answer`;
`None` wyłącza czytanie FAQ).
