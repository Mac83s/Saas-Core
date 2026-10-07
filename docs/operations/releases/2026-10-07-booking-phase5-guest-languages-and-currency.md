# Rezerwacje uniwersalne, faza 5: języki i waluta gościa (5i) — wydanie 2026-10-07

Zakres: plaster 5i planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5i”). Jedna migracja: organizations 0060.

## Co się zmieniło

- **Gość widzi obok ceny, ile to mniej więcej w jego walucie.** Na stronie w
  języku, którego czytelnicy liczą w innej walucie niż firma (strona
  niemiecka albo angielska firmy z cenami w złotych; strona polska firmy z
  cenami w euro), po cenie stoi „≈ 68 €”, a pod spodem zdanie: „Kwoty po znaku
  ≈ są orientacyjne: kurs NBP z 7 paź 2026. Rezerwujesz i płacisz w PLN.”
  Dotyczy „od X zł/noc” i sumy wyceny — w formularzu rezerwacji, na kartach i
  stronach jednostek na stronie firmy, na wizytówce i stronie jednostki w
  katalogu, w potwierdzeniu i w linku klienta. **Rezerwacja, zamówienie,
  przelew i e-maile zostają w walucie firmy** — przeliczona kwota nigdzie się
  nie zapisuje.
- **Kurs z banku centralnego, raz dziennie.** Tabela A NBP (domyślnie) albo
  kursy referencyjne EBC — bezpłatne, bez klucza; wybór to ustawienie
  platformy „Źródło kursów walut” (`exchange_rates.source`). Zadanie w tle
  pyta bank co trzy godziny, dopóki nie ma dzisiejszej tabeli. Tabela starsza
  niż pięć dni nie jest pokazywana: strona nie ma wtedy kwoty orientacyjnej
  wcale.
- **Firma może to wyłączyć**: „Ustawienia › Rezerwacje › Rezerwacja online” →
  „Pokazuj gościom orientacyjną cenę w ich walucie” (domyślnie włączone).
- **Każda odmowa w języku gościa.** Reguła sezonu (dzień przyjazdu, długość
  pobytu, zamknięty termin), dzień zamknięcia firmy, pauza rezerwacji
  włączona w trakcie, za dużo sztuk dopłaty, rezerwacja, której nie można już
  zmienić z linku — każda ma własne zdanie po polsku, angielsku i niemiecku.
  Formularz wizyty mówi „Ten termin został właśnie zajęty” zamiast ogólnego
  „termin niedostępny albo dane nieprawidłowe”.
- **Formularz mówi słowami oferty.** Oferta założona ze wzorca pyta o „Gości”
  i każe wybrać „Domek” zamiast ogólnych „Osoby” i „Co rezerwujesz?” — po
  polsku i angielsku; po niemiecku zostają słowa ogólne (wzorce nie mają
  jeszcze niemieckich).
- **Strona jednostki zostaje w języku gościa.** `/de/stay/<domek>/` domku bez
  niemieckiej nazwy nie przenosi już na stronę polską: odpowiada po
  niemiecku, z nazwą i opisem firmy oznaczonymi jako polskie, poza indeksem
  wyszukiwarek. Indeksowane są nadal tylko języki, w których jednostka ma
  własną nazwę.
- **E-mail „zmieniła się osoba” po niemiecku** dla klienta niemieckiego
  (dostawał angielski), i niemieckie słowa pozycji wyceny („Zusätzliche
  Person”).

## Wdrożenie

- **Migracja organizations 0060** (`0060_exchange_rate_table`): tabela
  `organizations_exchangeratetable` — bez organizacji, bez RLS; odwracalna
  (cofnięcie usuwa tabelę z zapisanymi kursami, które zadanie pobierze na
  nowo).
- Przebudowa backendu i frontendu razem. **Bez nowych zmiennych
  środowiskowych.**
- **Wyjście na zewnątrz:** `worker` (zadanie `refresh_exchange_rates`,
  harmonogram `exchange-rates-refresh`, co trzy godziny o :20) łączy się z
  `https://api.nbp.pl` — albo z `https://www.ecb.europa.eu` po zmianie źródła.
  Zapora wychodząca, jeśli jest, musi to przepuścić.
- Po wdrożeniu raz, żeby nie czekać do trzech godzin na pierwszą tabelę:
  `python manage.py refresh_exchange_rates` (wypisuje źródło, dzień i kursy).

## Produkty (HoofCare, MedPlano) przy następnym `core:update`

- Migracja organizations 0060 na każdym stacku i to samo wyjście `worker` do
  `api.nbp.pl`.
- Publiczny formularz rezerwacji produktu (komponent rdzenia) dostaje zdania
  odmów i kwotę orientacyjną bez zmian w kodzie produktu. Kwota pojawi się
  tylko tam, gdzie strona jest czytana w języku z inną walutą niż waluta
  firmy — przy stronach wyłącznie polskich i cenach w złotych nic się nie
  zmienia.
- Słowa: `PublicBooking.createError` zastąpił `PublicBooking.visitRefused`;
  nowe `BookingSelfService.refused`, `BookingPrice.approxNote`,
  `Catalog.approxNote`, dłuższe `PublicBooking.stayRefused` (w `pl.json`,
  `en.json`, `public/de.json`). Produkt, który nadpisuje te przestrzenie w
  swoim slocie, dopisuje je u siebie (dziś żaden nie nadpisuje).
- Ustawienie `booking.online.price_conversion` jest domyślnie włączone;
  produkt, który chce inaczej, podaje wartość w `settingsDefaults` profilu.

## Czego to wydanie nie robi

- Nie przelicza niczego, co się płaci: nie ma płatności w walucie gościa.
- Nie tłumaczy treści samo: nazwy jednostek i ofert w en i de firma wpisuje
  albo zamawia w „Strona internetowa → Tłumaczenia”. Tłumaczenie żywym
  modelem nie było sprawdzane (konto OpenRouter puste) — tylko atrapą.
- E-maile o pobycie mówią nadal tylko początek („Termin: …”), bez dnia
  wyjazdu i jednostki.
