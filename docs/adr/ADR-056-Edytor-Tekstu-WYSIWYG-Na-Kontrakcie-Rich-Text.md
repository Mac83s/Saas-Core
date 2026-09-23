# ADR-056: Edytor tekstu WYSIWYG na kontrakcie `core.rich_text`

Status: zaakceptowana, 2026-09-23 (decyzje właściciela w planie memex
`saas-core-site-studio-rich-content-and-full-width`, etap 2b). Zmienia zasadę
z fazy 1 bogatej treści: „nie dodajemy zależności edytora ani
`contentEditable`” ([site-rich-content.md](../architecture/site-rich-content.md),
[site-studio-editor.md](../architecture/site-studio-editor.md)).

## Kontekst

Bogata treść (`core.rich_text` v2/v3) jest zapisywana jako JSON węzłów:
akapit, śródtytuł ze stałą kotwicą, lista do dwóch poziomów, cytat, uwaga,
ilustracja; przebiegi tekstu mają tylko pogrubienie, kursywę i link z listy
dozwolonych adresów. Faza 1 dała do tego panel pisania bez nowej zależności:
formatowanie w polu tekstowym przez `**`, `*` i `[etykieta](adres)`.

Właściciel ocenił to jako rozwiązanie tymczasowe: klienci mają pisać jak w
Wordzie i nie znać składni. Nowa zależność edytora jest świadomie przyjęta.
Miejsce pisania: ten sam edytor w panelu bocznym i w trybie „Pisz na pełnym
ekranie”, obok płótna, które pokazuje prawdziwy układ sekcji.

## Decyzja

1. **Edytor to TipTap 3 (ProseMirror, licencja MIT)** w module sites
   aplikacji panelu. Ładuje się tylko w panelu; renderer publiczny i
   `@saas-core/site-blocks` nie dostają zależności.
2. **Schemat edytora jest kontraktem `core.rich_text`, węzeł w węzeł**
   (`rich-text-schema.ts`): śródtytuł 2–4 bez znaczników z atrybutem
   kotwicy, pozycja listy = jeden akapit i najwyżej jedna podlista, cytat i
   uwaga = jeden przebieg tekstu z polami, ilustracja = węzeł atomowy.
   Czego schemat nie pomieści, tego edytor nie wytworzy — wklejony HTML jest
   parsowany tym samym schematem.
3. **Zapisywany jest wyłącznie JSON kontraktu.** Konwersja JSON ⇄ dokument
   edytora to czyste funkcje (`rich-text-doc.ts`); przejście przez edytor
   zachowuje każdą treść dostarczaną z produktem (seedy katalogu i recepty
   stron) bez zmian — pilnuje tego test. Jedyna normalizacja to kanoniczne
   przebiegi (sąsiednie o tych samych znacznikach łączą się, dłuższe niż
   limit dzielą się). Puste akapity, śródtytuły i pozycje list, które
   dopiero powstają, nie trafiają do zapisu; karty (cytat, uwaga,
   ilustracja) zostają zawsze.
4. **Kotwica śródtytułu powstaje raz** — z pierwszego tekstu, unikalna — i
   nie zmienia się przy edycji tekstu; kotwice sekcji i śródtytułów dalej
   dzielą jedną przestrzeń nazw strony (serwer odrzuca powtórzenie).
5. **Jedna historia cofania.** Edytor nie ma własnego stosu: zatwierdza
   zmiany do formularza strony (RHF) po pauzie i przy wyjściu z pola, a
   Ctrl/Cmd+Z w edytorze wywołuje „Cofnij” strony. Zmiana wartości z
   zewnątrz (cofnięcie, płótno, import szablonu) ładuje edytor od nowa.
6. **Limity kontraktu** (160 węzłów, 64 przebiegi, 200 znaków śródtytułu,
   40/20 pozycji listy) są komunikatami walidacji formularza, nie cichym
   ucinaniem tekstu.

## Konsekwencje

- Kontrakt danych, renderer, publikacje, API, Content Operations i blueprinty
  się nie zmieniają; zmienia się tylko warstwa edycji w panelu.
- Panel dostaje ~100 kB (gzip) kodu edytora, ładowanego dopiero przy polu
  bogatej treści.
- Interakcje `contentEditable` (pisanie, skróty, wklejanie, cofanie) testujemy
  w przeglądarce (Playwright); jsdom sprawdza konwersję, schemat i logikę.
- Panel pisania ze składnią `**` znika, gdy edytor obejmie wszystkie węzły;
  do tego czasu działa bez zmian.
- `InlineText` na płótnie zostaje przy natywnych polach (pojedyncze
  przebiegi, śródtytuły, podpisy).

## Odrzucone

- **Pisanie bezpośrednio na płótnie**: układy dzielące tekst na rozdziały
  (chapters, timeline, numbered_sections, alternating_chapters,
  problem_solution) na czas edycji musiałyby pokazać ciągły tekst zamiast
  układu; największy koszt i ryzyko.
- **Dwie historie cofania (ProseMirror i strony)**: rozjeżdżają się przy
  cofnięciu z zewnątrz i przy imporcie szablonu.
- **Zapis HTML z edytora**: łamie zasadę renderera bez HTML dostarczanego
  przez klienta (ADR-031) i wymagałby sanitizacji na każdej ścieżce.
- **Lexical, Slate**: bez przewagi dla tego kontraktu; TipTap daje gotowe
  listy, skróty i parser wklejania na schemacie ProseMirror.

## Relacje

- rozszerza ADR-031 (wizualny Site Studio) i ADR-020 (formularze RHF + Zod);
- nie zmienia ADR-027 (brak dowolnego page buildera): edytor pisze tylko w
  węzłach kontraktu.
