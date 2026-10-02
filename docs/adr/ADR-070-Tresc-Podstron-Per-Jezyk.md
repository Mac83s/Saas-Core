# ADR-070 — treść podstron per język: wersje związane ze strukturą źródła, publikacja pochodna

**Status:** Accepted — decyzja właściciela 1b z 2026-10-02 (pełna treść podstron w
każdym języku) i odpowiedź 5a z tego samego dnia (memex
`a-language-version-whose-source-changed-a-fact-i`); plan memex
`saas-core-wielojezycznosc-i-tlumaczenia-ai`, decyzje TL-T7–TL-T15, fazy TL8, TL9,
TL11 i TL13.
**Data:** 2026-10-02

**Zmienia częściowo** ADR-027, ADR-044 i ADR-065 oraz decyzję memex
`wpisy-kolekcji-t-umaczy-sie-przez-grupe-strony-p` — fragmenty w sekcji „Zmiany
wcześniejszych decyzji”. Bez zmian zostaje
`contentchangeset-adresuje-bloki-pozycyjnie-wobec`: blok adresuje pozycja wobec
wersji bazowej, a ten ADR trzyma te same pozycje w każdym języku. Języki firmy,
dostępność, adresy i SEO rozstrzyga ADR-071; silnik tłumaczeń, tryby, granice
automatu i to, kiedy zadanie publikuje — ADR-069.

## Kontekst

Podstrona ma jedną listę bloków dla wszystkich języków; per język są tylko metadane
`PageTranslation`, a wersja liczy się jako kompletna także z polami pożyczonymi z
języka bazowego (`shared/sites/localization.py:144-212`). Migawka niesie jedne
`blocks` na podstronę (`shared/sites/services.py:2713-2755`), więc `/en/<slug>/`
serwuje polski tekst z `lang="en"` i hreflang `en`.

Publikacja ma dwie drogi: `publish_site` osoby, ze szkiców całej witryny, i
publikację pochodną z ADR-065 — opublikowany stan z jedną zmianą. Ta druga rejestruje
od nowa zdjęcia wszystkich podstron ze sprawdzeniem `READY`
(`shared/sites/page_deletion.py:255-271`), więc jedno usunięte zdjęcie zatrzymałoby
każdą publikację tłumaczeń. Zestawy zmian SCR adresują bloki pozycją wobec
`Page.version` i dziś zmieniają wspólną treść niezależnie od języka
(`shared/sites/change_sets.py:444-473`).

## Decyzja

### Treść i zapis

1. **Źródło zostaje, inne języki mają wersje związane z jedną wersją źródła.**
   Język źródłowy żyje w `PageVersion` i `PageBlock` jak dotąd. Każdy inny język ma
   niezmienne `PageLocaleVersion` (FORCE RLS, append-only z furtką ADR-042):
   wiązanie z jedną `PageVersion`, podpis jej struktury i fragmenty tekstu
   `{klucz: {text, provenance}}` — bez bloków. Bloki składa serwer ze źródła i
   fragmentów, więc wersja językowa ma te same bloki, zdjęcia, linki i układ, a
   różni się tylko tekstem i opisami zdjęć. Klucz fragmentu to pozycja bloku i
   ścieżka JSON — stały, bo wersja jest związana z jedną wersją źródła.
   `PageTranslation` dostaje `body_current` (robocza treść), `body_pending`
   (wynik czekający na przegląd) z `pending_reason` i własną blokadę
   `body_version`; zapis języka nigdy nie podnosi `Page.version`. — Zachowuje
   niezmienność i rollback z ADR-027, trzyma pozycje bloków jednakowe dla SCR i
   formularzy, nie wymaga stałych identyfikatorów bloków, a zapis DE nie
   unieważnia oczekującego zestawu zmian PL.
2. **Zapis wyłącznie fragmentami.** Panel i silnik wysyłają fragmenty; serwer
   składa bloki i sprawdza schemat. Wszystkie wadliwe fragmenty wracają naraz:
   `400 locale_unit_invalid` z błędem pola `units.<klucz>` i kodem (format
   błędów pól z ADR-076 §5);
   nieaktualna blokada — `409 locale_body_version_conflict`; inna wersja źródła —
   `409 source_version_mismatch`; język źródłowy — `400 locale_is_source`. Całe
   bloki przyjmujemy tylko od SCR (pkt 17). Podpis struktury to bloki bez tekstu,
   ale ze znacznikami biegów rich text (pogrubienie, kursywa, `href`, `rel`) —
   tłumaczenie nie zmieni celu linku.
3. **Co jest tekstem — schematy bloków plus krótka tabela w kodzie.** Napis bez
   `enum`, `pattern`, `const` i `format` to tekst, reszta to struktura. Tabela
   wyjątków: imiona i nazwiska (opinie, cytaty, karta autora) i adres w
   `core.contact` są kopiowane do każdego języka i nigdy nie idą do modelu
   (cyrylicę dostaje transliteracja kodem); pola danych (data w `core.entry_list`)
   to struktura; opinie, cytaty i rola autora mają klasę danych `public_personal`
   (ADR-069 decyduje, co trafia do dostawcy). Bieg rich text v2–v4 to jeden
   fragment z numerowanymi żetonami znaczników. Gramatyka żetonów, maski,
   `Provenance`, `unit_hash` i fakty mają jedną implementację w
   `saas_core/content_protocol` — czysty Python bez importów z `saas_core.modules`
   (kontrakt `.importlinter`), wspólny z silnikiem (ADR-069). Znacznik
   „[Uzupełnij: …]” zostaje dosłownie i nigdy nie idzie do modelu; wersja czeka,
   aż właściciel uzupełni źródło. Test przechodzi po każdej wersji każdego
   schematu z manifestu; nowa wersja schematu musi go przejść.
4. **Pamięć tłumaczeń bez własnej tabeli.** To fragmenty bieżących treści
   (`body_current`) wszystkich podstron witryny w danym języku, według skrótu
   tekstu źródłowego (rodzaj fragmentu i tekst po NFC); tekst człowieka i
   integracji wygrywa z tekstem AI. Treści oczekujące nie wchodzą — nieprzejrzany
   tekst nie może trafić za darmo na inną podstronę.
5. **Przeniesienie na nową wersję źródła po skrócie tekstu, nigdy po pozycji.**
   Niezmieniony fragment zachowuje tłumaczenie, gdziekolwiek się przesunął, a
   zdanie przetłumaczone na innej podstronie bierze się z pamięci. Zmieniony
   fragment zaczyna nieprzetłumaczony; jeśli w tym samym miejscu (pozycja, rodzaj
   bloku, pole) był tekst człowieka albo integracji, zostaje obok jako propozycja —
   nigdy nie znika po cichu i nie wychodzi jako tłumaczenie słów, których nie
   tłumaczył; wynik AI dla takiego fragmentu idzie do przeglądu
   (`overwrites_human`, ADR-069). Przywrócenie starszej wersji przywraca też jej
   wiązanie; wersja związana ze starszym źródłem przed publikacją wymaga
   przeniesienia.

### Publikowalność i migawka

6. **Jedna reguła „publikowalne” dla `publish_site` i publikacji pochodnej.**
   Wersja innego języka jest publikowalna, gdy ma własny slug, tytuł i opis
   (pola zastępcze nie czynią jej kompletną), zero nieprzetłumaczonych fragmentów
   (kopia źródła się liczy, kopiowane nazwiska i adresy nie), źródło bez znaczników
   do uzupełnienia, gotową stronę główną języka (pkt 7), dostępne zdjęcia i
   wiązanie z wersją źródła zapisaną w tej samej migawce. Inaczej jest pomijana z
   powodem — `metadata_incomplete`, `untranslated_units`, `source_placeholder`,
   `locale_home_missing`, `media_unavailable`, `source_unpublished` (związana z
   nowszym, nieopublikowanym szkicem) albo `source_outdated` (ze starszą wersją) —
   w odpowiedzi i audycie, a publikacja nie pada.
7. **Strona główna otwiera język.** Język wchodzi na witrynę (`live_locales`
   migawki) tylko razem z wersją swojej strony głównej; zadania tłumaczą ją
   najpierw. Strony główne odpowiadają pod `/` i `/xx/` (ADR-071). Wstrzymana
   strona główna daje `/xx/` 307 do `/` jak każda wstrzymana wersja (pkt 10), a
   język zostaje; schodzi z witryny tylko przez wyłączenie (ADR-071) albo zdjęcie
   wersji strony głównej (pkt 12).
8. **Migawka v2 jest ściśle dodatkowa.** `pages[].blocks` zostaje treścią źródłową,
   a każdy wpis `locales[]` innego języka dostaje `blocks`, `locale_version_id`,
   `source_version_id`, `content_hash`, `changed_at`, skrót pochodzenia (`ai`,
   `human`, `mixed`, `template` i czy przejrzane — dla znacznika AI z ADR-071) oraz
   `withheld` po zmianie faktów; migawka dostaje `live_locales`. Czytnik v1 nadal
   poprawnie serwuje język źródłowy. Reguła odczytu starszych migawek (TL2): wpis
   innego języka bez własnych `blocks` nie jest publiczny, a jego adres odpowiada
   308 do strony w języku źródłowym; publikacja pochodna na migawce v1 zapisuje
   już v2. Budżet: 50 podstron × 5 języków ≤ 3 MB JSON i ≤ 50 ms parsowania
   (pomiar TL9 02.10 na najdłuższej recepcie: 2,3 MB, 10 ms); sparsowane migawki
   trzyma pamięć procesu, najwyżej 64, według identyfikatora — publikacje są
   niezmienne.
9. **`publish_site` bierze wersje związane z publikowanym źródłem**, także
   przetłumaczone z tego szkicu przed publikacją. Wersja, która była publiczna, a
   nie jest już publikowalna, zostaje w ostatniej opublikowanej postaci
   (przeniesiona z poprzedniej migawki), więc adresy nie „migają”; tak samo
   przechodzą wersje języka wyłączonego (ADR-071).
10. **Wstrzymanie po zmianie faktów (odpowiedź 5a).** Fakty
    (`content_protocol.facts`: kwoty, ceny z walutą zapisaną jak w źródle,
    godziny, adresy www, e-mail, telefon) wersji źródła związanej z wersją
    językową porównujemy z opublikowanym źródłem — per fragment w tym samym
    miejscu i jako multizbiór całej podstrony, co łapie powtórzone wartości i
    przestawione fragmenty — w treści i w tytule z opisem. Każda różnica ustawia
    `withheld`: adres odpowiada 307 do tej samej podstrony w języku źródłowym i
    znika z hreflang, sitemapy, menu i przełącznika; zmiana słów bez nowych faktów
    zostawia wersję online. Wraca z publikacją odświeżonej wersji. Rodzeństwo AI
    wpisu bloga zapisuje wersję źródła, z której powstało, i podlega tej samej
    regule (TL11).

### Publikacja pochodna i decyzje osoby

11. **Tłumaczenia wychodzą publikacją pochodną (ADR-065 uogólnione), nigdy przez
    `publish_site` za właściciela.** To opublikowana migawka plus dokładnie
    wymienione wpisy języków, hreflang ich klastra i `live_locales` — nigdy szkice,
    menu, wygląd, inne podstrony ani robocze teksty witryny. `Publication.reason`
    (`page_delete`, `locale_accept`, `locale_publish`, `locale_withdraw`,
    `translation_job`, `translation_revert`) trafia do rekordu, zdarzenia
    `sites.site.published` i historii. Referencje zdjęć przechodzą z poprzedniej
    publikacji (`carried_from`) bez sprawdzania gotowości — bezpiecznie, bo
    sprzątanie nie kasuje zdjęcia, do którego odwołuje się jakakolwiek publikacja
    (`shared/media/services.py:892-897`); sprawdza się tylko nowe. Kiedy i jak
    często zadanie publikuje (partie, strona główna najpierw, limit podstron) —
    ADR-069.
12. **Decyzje o wersji językowej należą do osoby.** Akceptacja oczekującej,
    odrzucenie, „Opublikuj tę wersję językową”, akceptacja zbiorcza (podgląd i
    digest) oraz „Zdejmij tę wersję językową” (wpis znika, adres odpowiada 308 do
    strony źródłowej, wraca ponowną publikacją) idą przez `assert_person_required`
    i są publikacjami pochodnymi. Akceptacja przenosi `body_pending` do
    `body_current` w tej samej transakcji. Wynik zadania w trybie automatycznym
    nie jest decyzją osoby: publikuje go pochodna publikacja `translation_job`
    według ADR-069, z zadaniem działającym jako członkostwo osoby, która raz
    wyraziła zgodę.
13. **Rollback przywraca migawkę razem z wersjami językowymi**; wskaźniki, pamięć i
    oczekujące zostają nietknięte, a uzgadnianie po rollbacku nie publikuje
    nowszych tłumaczeń bez kliknięcia. Cofnięcie zadania — ADR-069.
14. **Formularze i pomiar znają język.** Zapytanie wysłane przed publikacją pochodną
    jest przyjmowane po niej, gdy blok formularza na tej pozycji w tym języku się
    nie zmienił; `SiteInquiry.locale` i `PageViewDay.locale` (poza kluczem odsłon z
    ADR-060).

### Pozostałe treści

15. **Teksty całej witryny tłumaczy się po skrócie tekstu źródłowego**
    (`SiteTextTranslation`: hasło, stopka, etykiety linków stopki, nazwy kolekcji i
    tagów), nie po pozycji linku; publikacja bierze tylko zaakceptowane wiersze.
    Linki wewnętrzne w blokach i w stopce wyglądu ładunek publiczny lokalizuje przy
    odczycie do żywej wersji celu, z zachowaniem `rel` (ADR-061).
16. **Wpisy bloga zostają grupą tłumaczeń**: osobny wpis na język z własnym cyklem;
    AI zakłada i aktualizuje rodzeństwo przez istniejące serwisy i nowe
    `update_entry_metadata` (tytuł, zajawka, autor); rodzeństwo AI nigdy nie jest
    źródłem. x-default klastra — ADR-071.
17. **SCR per (podstrona, język).** W języku innym niż źródłowy bazą zestawu zmian
    jest `body_version` i złożone bloki wersji językowej; `translation.update`
    zapisuje tylko `PageTranslation` (bez `save_draft` i bez ruszania
    `Page.version`); `block.replace` przechodzi tylko przy niezmienionym podpisie
    struktury, a `block.insert`, `block.remove` i `block.reorder` dają
    `422 locale_structure_locked`. Na powierzchni `proposed` zapis trafia do
    `body_pending`, na `automated` do `body_current`, a publikacja idzie według
    grantu (ADR-035 §4). `ContentProposal.locale` jest w kluczu unikalności, a
    `sites.page.draft_saved` niesie `locale`. Kontrakt `content-change-set.v1`
    poszerza `locale` dopiero razem z tą semantyką (memex
    `content-change-set-is-owned-by-saas-core-the-loc`).
18. **Slugi wersji liczy kod z przetłumaczonego tytułu**: ASCII, ä/ö/ü/ß → ae/oe/
    ue/ss, cyrylica według BGN/PCGN bez znaków diakrytycznych; nigdy model.
    Unikalne w (witryna, język), różne od ścieżek kolekcji
    (`slug_conflicts_collection`), zamykane pierwszą publikacją, także pochodną.
19. **`Site.default_locale` nie zmienia się po założeniu strony** (dziś ustawia go
    tylko `create_site`); wersje językowe są od niego zależne.

## Zmiany wcześniejszych decyzji

- **ADR-027**, „Model edycji i publikacji”: niemutowalna `PageVersion` i zapis z
  wersją `Page` obowiązują dla języka źródłowego; inne języki — pkt 1–2. Atomowa
  publikacja obowiązuje dla `publish_site`; obok jest publikacja pochodna (pkt 11), a
  migawka niesie treść każdego języka (pkt 8). „Tłumaczenia, adresy i SEO”:
  zastępstwo z języka bazowego nie czyni wersji kompletną (pkt 6); hreflang tylko
  dla wersji z własną treścią; x-default i adresy — ADR-071. „Media”: „tylko
  `ready` wchodzi do publikacji” dotyczy pierwszego wejścia; referencja
  przeniesiona nie jest nowym użyciem (pkt 11).
- **ADR-044**: dla języka innego niż źródłowy baza to `body_version` i bloki wersji
  językowej, komendy blokowe według pkt 17, propozycje per język.
- **ADR-065**: pkt 3 staje się ogólną publikacją pochodną z `reason`
  (`page_delete`) i przeniesionymi referencjami — usunięte zdjęcie innej
  podstrony nie blokuje już usunięcia; pkt 4 — przekierowanie języka na stronę
  główną celuje w `/xx/`; pkt 8 — rollback obejmuje wersje językowe.
- **ADR-035 §4a**: blokada edycji `Page.editing_locked_until` dotyczy edytora
  źródła; wersja językowa ma własną blokadę (ADR-069).
- **Memex `wpisy-kolekcji-t-umaczy-sie-przez-grupe-strony-p`**: zdanie o stronach
  („jeden zestaw bloków plus PageTranslation na metadane”) przestaje obowiązywać;
  część o wpisach obowiązuje z pkt 16.

## Konsekwencje

- Kod czytający treść z migawki musi wybrać język (ładunek publiczny, formularz).
- Migawki rosną z liczbą języków; budżet i pamięć procesu z pkt 8, retencja to
  osobna polityka (ADR-027).
- Każda publikacja pochodna to nowy `publication_id` i zdarzenie z `reason`; SCR
  porównuje `content_hash` per język i pomija powody tłumaczeń (wpis w planie SCR).
- Po TL2 dotychczasowe strony `/en/` z samymi metadanymi odpowiadają 308 do strony
  źródłowej, a strony główne mają adresy `/` i `/xx/`; strony testowe HoofCare i
  MedPlano zmieniają adresy (`memex ops` w produktach).
- Szablony z katalogu, szablony firmy (ADR-063), sekcje i konwersje działają na
  treści źródłowej, a wersje językowe nadążają przez przeniesienie i tłumaczenie;
  zasiewanie wersji z `localizedBlocks` przepisów jest odłożone.
- Migracje: `sites` 0040 (TL8: `PageLocaleVersion` i pola treści), `reason`
  publikacji (TL9b), kolumny języka formularzy i odsłon (TL9d) — odwracalne;
  produkty dostają je przez `core:update`.

## Rozważane alternatywy

- **Swobodne zestawy bloków per język** — struktura się rozjeżdża, pozycje SCR i
  formularzy różnią się między językami, a zmiana źródła to tłumaczenie od nowa.
- **Nakładka per blok ze stałym kluczem bloku** — tożsamość bloku w każdej ścieżce
  zapisu i odwrócenie adresowania pozycją; ok. 3–5 dni więcej.
- **Osobna podstrona na język (wzór wpisów)** — menu i strona główna per język,
  `pages.max` liczony wielokrotnie; ok. 4–7 dni więcej.
- **Złożone bloki zapisane w wersji językowej** — dubluje dane i pozwala strukturze
  się rozjechać; **osobna tabela pamięci tłumaczeń** — druga kopia tego, co już
  jest w treściach.
- **`publish_site` po każdym zadaniu** — wypuszcza cudze szkice; **wskaźniki
  publikacji per podstrona** — przepisanie atomowej migawki, renderera i rollbacku.
- **Treść źródłowa z noindex albo kopia PL jako EN** — zły język dla odwiedzającego.
- **Nieaktualne wersje zawsze online z oznaczeniem** (odpowiedź b pytania 5) —
  stara cena dociera do klienta.

## Relacje

- **ADR-027, ADR-035, ADR-044, ADR-065** — zmiany wyżej; **ADR-031** — edytor
  dostaje tryb języka (TL15).
- **ADR-039, ADR-041, ADR-042** — nowe tabele mają wymuszone RLS i nie są publiczne
  (renderer czyta migawkę); append-only z furtką usuwania organizacji.
- **ADR-059, ADR-060, ADR-061, ADR-063** — oznaczenie obrazów AI bez zmian; język
  odsłony poza kluczem; lokalizowane linki zachowują `rel`; szablony firmy na
  treści źródłowej.
- **ADR-068, ADR-069** — model przez port, tryby, granice automatu, zadania i ich
  publikacje; **ADR-071** — języki firmy, dostępność na żywo, adresy, SEO i GEO.
