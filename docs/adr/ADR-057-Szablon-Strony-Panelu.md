# ADR-057: Szablon strony panelu klienta

Status: zaakceptowana, 2026-09-24 (decyzja właściciela co do zakresu, projekt
techniczny w tym dokumencie). Rozszerza ADR-054 o stronę, na której lista stoi.

## Kontekst

Właściciel produktu, na zrzutach magazynu w HoofCare i Saas-Core: „chodzi mi,
aby ujednolicić widoki panelu”. Wymagania z 24.09:

1. wszystkie strony w jednakowej szerokości, na stałym szablonie strony, z
   jednakowym ładowaniem i wersją z prawym panelem na pomoc i narzędzia;
2. podstrony (np. Stany, Katalog, Dokumenty, Ustawienia magazynu) jako
   odnośniki w lewym menu, rozwijane, nie zawsze widoczne;
3. strona w rozsądnej szerokości, z opcją rozszerzenia od krawędzi do
   krawędzi na szerokim ekranie;
4. tabele z kolumną akcji: wybrane zawsze widoczne, reszta pod „…”;
5. pasek filtrów magazynu był „rozsypany” — do zaprojektowania raz dla
   wszystkich list.

Stan przed decyzją (odczyt 2026-09-24): 22 strony panelu ustawiały szerokość
same (`max-w-4xl`, `5xl`, `6xl`, `7xl`, odstępy `px-4` albo `px-5`), nagłówek
był w stronie albo w module, raz z akcjami, raz bez. Zakładki sekcji były
paskiem nad treścią, a magazyn i wiadomości miały drugie, własne zakładki
wewnątrz strony. Filtry stały z etykietą nad polem, obok przycisków akcji, i
zawijały się w dwa rzędy.

## Decyzja

1. **Szerokość należy do układu, nie do strony.** `panel/layout.tsx` ma jeden
   `<main>` (`PanelMain`): domyślnie 80 rem (`max-w-7xl`) z odstępami jak
   dotąd; przełącznik w nagłówku panelu (`WidthToggle`, od 1536 px — niżej nie
   ma czego rozszerzać) rozciąga go na całą szerokość. Wybór zapisuje cookie
   `panel-width`, które czyta serwer — pierwszy render ma właściwą szerokość,
   bez mignięcia. Strona nie ustawia własnej szerokości ani `<main>`.
2. **Strona to `PanelPage`** (`apps/frontend/src/components/panel/panel-page.tsx`):
   eyebrow (sekcja, a na stronie zagnieżdżonej link w górę — np. „‹
   Gospodarstwa”), tytuł `h1`, opis, akcje strony po prawej, linia komunikatu
   po ostatniej czynności (`aria-live`) i treść. Bez hooków — renderuje ją
   zarówno strona serwerowa, jak i moduł kliencki. `PanelSection` to część
   strony z kilkoma listami (tytuł i „dodaj” po prawej), `PanelHelp` — karta
   pomocy.
3. **Prawy panel** (`aside` w `PanelPage`): obok treści od 1280 px, pod nią
   niżej. Pierwsze użycie: rodzaje dokumentów magazynowych obok ich listy.
4. **Jedno ładowanie.** `panel/loading.tsx` pokazuje `PanelSkeleton` przy
   każdym przejściu między stronami; lista przed danymi pokazuje
   `ListSkeleton` z `@saas-core/ui` — ten sam, który rysuje `DataTable`.
5. **Podstrony są adresami i rozwijają się w lewym menu.** Sekcja to wpis w
   `PANEL_SECTIONS` (`lib/panel-navigation.ts`); pozycja menu z więcej niż
   jedną dostępną stroną dostaje przycisk rozwijania (`aria-expanded`), a
   sekcja, w której się jest, jest otwarta. Bieżąca strona to najgłębsze
   dopasowanie adresu (`currentPage`), bo pierwsza strona bywa korzeniem
   sekcji. Na telefonie te same strony są dodatkowo zakładkami nad treścią
   (`SectionTabs`, `lg:hidden`) — menu jest tam szufladą. Magazyn ma cztery
   adresy (`/panel/inventory`, `/items`, `/documents`, `/settings`), wiadomości
   dwa (`/panel/notifications`, `/automation`), strona www dostała Search
   Console.
6. **Pasek listy: „co oglądam”.** Toolbar `DataTable` to jeden rząd:
   wyszukiwanie z ikoną (`DataTableSearch`, także dla list szukanych przez
   API), filtry z etykietą w tej samej linii i tej samej wysokości
   (`DataTableFilter` dla selecta, `DataTableField` dla innej kontrolki, np.
   comboboksa). **Akcje strony** (Przyjmij dostawę, Nowy dokument, Dodaj
   gospodarstwo) idą do nagłówka strony, nie do paska. To zamyka punkt ADR-054
   „wspólny komponent filtra dołożymy, gdy dwa ekrany będą go potrzebować” —
   potrzebuje go pięć.
7. **Kolumna akcji.** `RowActions` przyjmuje `inline` z ikoną: te działania są
   osobnymi przyciskami w wierszu, reszta pod „…”. Na telefonie karta ma
   miejsce na jeden przycisk, więc wszystko jest w „…”. Działanie może być
   linkiem (`link: <Link href>`) — zostaje wtedy linkiem, nie udaje przycisku.
   `DataTable` przyjmuje `emptyAction` — wyjście z pustej listy (wyczyść
   wyszukiwanie, dodaj pierwszą pozycję).

## Konsekwencje

- Kalendarz dostał widok **Lista**: miesiąc kursora jako `DataTable` (termin,
  klient, usługa, pracownik, status, szczegóły), tymi samymi strzałkami.
- Gospodarstwa, zwierzęta i zwierzęta gospodarstwa są na `DataTable`; wiersz
  gospodarstwa prowadzi do karty, telefonu, zwierząt tego gospodarstwa
  (`/panel/animals?farm=`) i edycji, wiersz zwierzęcia — do karty zwierzęcia.
- Produkty (HoofCare, MedPlano) dostają szablon przez `core:update`; ich
  własne strony przechodzą na `PanelPage` w swoim repozytorium.
- Zakładki edytora strony www (Strony, Treść, Blog, Publikacja…) zostają w
  stronie: to etapy pracy nad jedną witryną, nie podstrony sekcji. Tak samo
  zakładki karty gospodarstwa — należą do jednego rekordu.

## Odrzucone

- **Szerokość per strona z listą wyjątków** — dokładnie stan, który zastaliśmy.
- **Przełącznik szerokości w `localStorage`** — serwer go nie widzi, więc
  pierwsza klatka miałaby złą szerokość.
- **Podstrony wyłącznie w menu** — na telefonie menu jest szufladą, sąsiednia
  strona sekcji byłaby dwa stuknięcia dalej.
- **Wszystkie akcje wiersza jako przyciski** — przy pięciu działaniach wiersz
  przestaje być czytelny; decyzja właściciela to „wybrane + …”.
