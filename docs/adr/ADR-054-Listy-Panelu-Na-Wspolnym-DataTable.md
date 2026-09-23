# ADR-054: Listy panelu klienta na wspólnym DataTable

Status: zaakceptowana, 2026-09-23 (decyzja właściciela). Doprecyzowuje ADR-020
w miejscu „components/data: DataTable, filtry, pagination, empty/error states”,
które do tej pory nie miało implementacji.

## Kontekst

Właściciel produktu postawił wymóg: listy na podstronach panelu klienta —
gospodarstwa, rezerwacje, magazyn, zespół i każda następna — mają mieć postać
listy zbudowanej na shadcn i być **ogólnym standardem budowania podstron panelu**.

Stan przed decyzją (odczyt 2026-09-23): `packages/ui` nie miał komponentu
tabeli. Siedem ekranów rysowało własny `<table>` z własnymi klasami, pozostałe
pokazywały listy w kartach. Każdy ekran inaczej sortował (albo wcale), inaczej
pokazywał pusty stan i ładowanie, a zespół miał własne menu działań wiersza.
Żadne API listy nie stronicowało.

## Decyzja

1. **Każda lista w panelu klienta używa `DataTable` z
   `@saas-core/ui/components/data-table`.** Moduł nie rysuje własnej tabeli ani
   listy kart. Typy kolumn (`ColumnDef`, `SortingState`) importuje z tego samego
   pliku, nigdy z `@tanstack/react-table` — zasada publicznego API `@saas-core/ui`.
2. **Silnik: TanStack Table** (ten, na którym stoi shadcn Data Table), z
   prymitywami shadcn `Table*` w `packages/ui/src/components/table.tsx`.
   Własne sortowanie i filtrowanie powtarzałoby się na każdym ekranie.
3. **Telefon: wiersz staje się kartą**, bez przewijania w poziomie. Ten sam DOM
   dla obu widoków — każde działanie istnieje raz, a stan focusu przeżywa zmianę
   szerokości. Tabela i jej elementy mają jawne role ARIA, bo część przeglądarek
   gubi semantykę tabeli, gdy CSS zmienia `display`. Kolumna oznacza się w
   `meta`: `primary` (tytuł karty), `actions` (róg karty, wąska kolumna),
   `label` (etykieta wartości na karcie).
4. **Dwa tryby.** Bez `rowCount` tabela sama sortuje, szuka i stronicuje
   przekazane `data` — dla krótkich list. Z `rowCount` robi to API: tabela
   pokazuje otrzymaną stronę, a każdą zmianę (strona, sortowanie, wyszukiwanie
   z opóźnieniem 300 ms) zgłasza w `onQueryChange`. Dłuższe listy (zwierzęta,
   ruchy magazynu, historia zmian) idą trybem serwera.
5. **Wyszukiwanie i sortowanie po polsku.** Wyszukiwanie pomija wielkość liter,
   znaki diakrytyczne i „ł” („lodz” znajduje „Łódź”); `searchText` pozwala
   szukać po wartościach spoza kolumn. Sortowanie tekstu używa `Intl.Collator`
   („Łukasz” stoi przy L, nie za Z); pierwsze kliknięcie zawsze rośnie.
6. **Działania wiersza: `RowActions`** — jeden przycisk 44 px z menu, oddający
   element wyzwalający, żeby dialog wrócił na niego focusem.
7. **Renderery kolumn są zwykłymi funkcjami, bez hooków.** `DataTable` wywołuje
   je wprost zamiast montować jako komponenty (`flexRender`). Strony budują
   kolumny przy każdym renderze; montowanie remontowałoby wtedy każdą komórkę,
   a dialog tracił element, do którego ma oddać focus. Stan należy do osobnego
   komponentu w komórce (jak `RowActions`).
8. **Teksty tabeli** (szukaj, brak wyników, strony) mają jedną przestrzeń
   `DataTable` w komunikatach PL/EN; strona bierze je przez
   `useDataTableLabels()` z `apps/frontend/src/lib/data-table-labels.ts`.

## Konsekwencje

- Pierwsze wdrożenie: lista zespołu (`team-panel.tsx`) — wspólne menu działań
  zastąpiło lokalne `RowMenu`, testy zachowały focus po dialogu i axe.
- Pozostałe listy (gospodarstwa, zwierzęta, magazyn, rezerwacje jako zakładka
  obok domyślnego kalendarza, ekrany HoofCare) przechodzą na standard w kolejnych
  przyrostach planu „Panel i katalog”; nowy magazyn powstaje od razu na nim.
- Filtry kolumnowe (np. status) na razie idą przez `toolbar` i filtrowanie
  danych po stronie strony. Wspólny komponent filtra dołożymy, gdy dwa ekrany
  będą go potrzebować w tym samym kształcie.
- Nowa zależność `@tanstack/react-table` w `packages/ui` (bez zależności
  pośrednich poza `@tanstack/table-core`).

## Odrzucone

- **Sam wygląd tabeli shadcn bez silnika**: sortowanie, wyszukiwanie i
  stronicowanie pisane osobno na każdym ekranie — dokładnie ten stan, który
  zastajemy.
- **Dwa osobne widoki (tabela i karty) przełączane klasą**: dublują przyciski
  i identyfikatory w DOM, czytniki ekranu i testy widzą każde działanie dwa razy.
- **Przełączanie widoku w JavaScript po szerokości ekranu**: rozjazd renderu
  serwera i klienta oraz mignięcie złego widoku przy ładowaniu.
