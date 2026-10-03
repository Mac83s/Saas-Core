# ADR-055: Magazyn uniwersalny dla firm (`shared.inventory` v2)

Status: zaakceptowana, 2026-09-23 (decyzje właściciela w planie memex
`magazyn-materia-o-w-od-pakietu-korektora-do-kare`). Zastępuje model magazynu
v1 z 21.09 (pakiet korektora HoofCare), zachowując jego zasady: stan to suma
ruchów, zapas należy do osoby, praca w terenie nie staje przez stan, średnia
ważona.

## Kontekst

Magazyn v1 powstał dla HoofCare: kategorie korektora (klocek, opatrunek, lek)
wpisane w rdzeń, jeden magazyn firmy i zapasy osób, ruchy bez dokumentów.
Właściciel chce z niego **uniwersalny, pełny system magazynowy dla firm**, z
którego korzystają inne moduły: rezerwacje (produkty przy wizycie), praca w
terenie HoofCare i przyszły sklep internetowy — bez przebudowy magazynu przy
każdym z nich. Moduł jest domyślnie włączony we wszystkich produktach.

## Decyzja

1. **Towar to pozycja katalogu (`InventoryItem`) = jeden SKU.** Nazwa, SKU, EAN,
   kategoria, jednostka, stan minimalny, średnia ważona cena zakupu, cena
   sprzedaży netto i stawka VAT (23, 8, 5, 0, zw). Warianty (rozmiar, kolor) to
   osobne pozycje; sklep zgrupuje je w swojej karcie. Tłumaczenia nazwy, opis i
   zdjęcia dojdą razem ze sklepem.
   > Doprecyzowane przez
   > [ADR-074](ADR-074-Sklep-Www-Na-Zamowieniu-i-Magazynie.md) pkt 2
   > (2026-10-02): cena sprzedaży netto i stawka VAT pozycji są ceną przy
   > wizycie; w sklepie cenę niesie wariant, a stawkę produkt, a serwis zapisu
   > wariantu podpowiada je z pozycji jako wartości domyślne. Wariant fizyczny
   > wskazuje jedną pozycję, a pozycja należy do najwyżej jednego aktywnego
   > wariantu; tłumaczenia, opis i zdjęcia ma produkt sklepu, nie pozycja.
2. **Kategorie należą do firmy** (`InventoryCategory`), a ich zestaw startowy
   deklaruje produkt per typ organizacji: `organizationTypes[].inventory.categories`
   w profilu. Typ bez deklaracji dostaje zestaw rdzenia (Produkt, Materiał,
   Narzędzie, Inne). Firma dopisuje własne; startowych nie usuwa.
3. **Pozycje standardowe deklaruje produkt:**
   `organizationTypes[].inventory.defaultItems` (klucz, nazwa PL/EN, kategoria,
   jednostka). Powstają leniwie przy pierwszym dostępie firmy do magazynu, z
   `system_key`; można je edytować i ukryć, nie usunąć. Rdzeń nie nazywa
   żadnej branży (ADR-049) — HoofCare deklaruje Klocek, Opatrunek, Lek.
4. **Miejsca składowania** (`StockLocation`): magazyny firmy (kilka) i zapas
   osoby (jeden na człowieka). Magazyn główny i zapas osoby powstają leniwie.
5. **Dokumenty** (`StockDocument` z wierszami): PZ przyjęcie zewnętrzne, WZ
   wydanie zewnętrzne, RW rozchód wewnętrzny (zużycie), PW przychód wewnętrzny,
   MM przesunięcie między miejscami, INW inwentaryzacja. Numeracja
   `RODZAJ/RRRR/NNNN` osobno dla firmy, rodzaju i roku. Szkic można zmieniać;
   zatwierdzenie tworzy ruchy i zamraża dokument. Pomyłkę prostuje **korekta** —
   nowy dokument tego samego rodzaju, który cofa ruchy korygowanego. Wydruk PDF
   później (decyzja 23.09).
6. **Stan** (`InventoryBalance`) to suma ruchów per pozycja i miejsce, trzymana
   obok księgi; ma też `reserved`. Dostępne = stan − zarezerwowane.
7. **Rezerwacje stanu** (`StockReservation`) należą do źródła (moduł i jego
   identyfikator, np. wizyta): rezerwacja przy potwierdzeniu, zużycie przy
   zakończeniu, zwolnienie przy odwołaniu.
8. **Brak pokrycia:** zużycie w pracy (wizyty, teren) i dokumenty wewnętrzne
   ostrzegają, ale zapisują — ujemny stan jest do wyjaśnienia. Sprzedaż (WZ ze
   sklepu) jest blokowana, gdy towaru nie ma.
9. **Wycena:** średnia ważona krocząca liczona przy przyjęciu z ceną (PZ, PW);
   rozchód wyceniany średnią z chwili ruchu.
10. **Uprawnienia:** `inventory.read` (podgląd), `inventory.use` (zużycie z
    własnego zapasu, produkty przy wizycie), `inventory.manage` (dokumenty,
    ceny, katalog, inwentaryzacja).
11. **Operacje dla innych modułów** (`shared/inventory/api.py`): stan osoby,
    dostępność, rezerwacja, zwolnienie rezerwacji źródła, zużycie (dokument RW
    ze źródłem, idempotentny), cofnięcie zużycia źródła (korekta RW). Moduły nie
    importują modeli magazynu.
12. **Historia zmian:** zatwierdzenie i korekta dokumentu, zmiany katalogu,
    kategorii i dostawców mają własne akcje z „było → jest”.
13. **Dane v1** były testowe (HoofCare, 21.09) i zostają wyczyszczone migracją;
    schemat zmienia się odwracalnie.

## Uzupełnienie 2026-09-24: produkty przy wizycie (faza 6)

- Usługa rezerwacji niesie listę produktów (`Service.materials`: pozycja,
  ilość, rozliczenie „zużycie” albo „sprzedaż klientowi”). Wizyta dostaje jej
  kopię z nazwą i ceną sprzedaży z chwili zapisu (`Appointment.materials`);
  osoba z `inventory.use` może ją zmienić przy tworzeniu i do zakończenia.
- JSON zamiast kluczy obcych: magazyn nie jest zależnością rezerwacji, a produkt
  bez magazynu w profilu nie istnieje. Pozycje sprawdza `booking/materials.py`
  przez `inventory.api.describe_items`; w kopii z usługi pozycja ukryta po
  ustawieniu usługi jest pomijana, żeby nie blokować klientowi rezerwacji.
- Potwierdzenie (utworzenie) rezerwuje stan w magazynie głównym, zakończenie
  wystawia RW (zużycie) i WZ (sprzedaż) bez blokady brakiem towaru, odwołanie
  zwalnia rezerwację. Źródło dokumentów i rezerwacji: `booking.appointment`.
- Klient (strona publiczna, self-service) nie widzi produktów wizyty.
- Rdzeń dostał akcję „Zakończ wizytę” w kalendarzu panelu — wcześniej kończył
  wizyty tylko HoofCare.

### Uzupełnienie 2026-09-24: rodzaje wizyt z własnym materiałem

Decyzja właściciela (faza 7 planu magazynu, odpowiedź 4A): wizyty HoofCare nie
biorą produktów przez kalendarz. Korektor zdejmuje materiał przy każdej krowie
ze swojego zapasu (RW `hoofcare.entry`), a zakończenie wizyty w kalendarzu
zdjęłoby go drugi raz — z magazynu głównego.

- Deskryptor modułu dostaje opcjonalne `backend.appointmentKindsWithOwnMaterials`
  — podzbiór jego `appointmentKinds`; kompozycja odmawia rodzaju, którego moduł
  nie dodaje. Rdzeń składa je w `settings.APPOINTMENT_KINDS_OWN_MATERIALS`.
- `booking.materials.takes_materials(kind)`: dla takich rodzajów usługa i wizyta
  odmawiają produktów (400), wizyta nie kopiuje ich z usługi, a zakończenie ich
  nie rozlicza (nawet wpisanych wcześniej). API panelu mówi to flagą
  `takes_materials` przy usłudze i wizycie; panel chowa wtedy edytor produktów.

## Uzupełnienie 2026-09-25: partie i daty ważności

Decyzje właściciela z 25.09 (faza 9 planu magazynu, odpowiedzi 1a–5a):

- Pozycja może prowadzić partie (`tracks_lots`, przełącznik w karcie; produkt
  może go włączyć pozycji standardowej przez `defaultItems[].tracksLots`).
  Partia (`InventoryLot`) to numer i opcjonalna data ważności, unikalna w
  obrębie pozycji. Przyjęcie (PZ, PW) i inwentaryzacja zakładają partię po
  numerze; rozchód może ją wskazać.
- Ruch i wiersz dokumentu niosą partię. **Stan partii w miejscu to suma jej
  ruchów** — bez osobnej tabeli stanów, więc `InventoryBalance`, rezerwacje i
  wszystko, co z nich czyta, zostają bez zmian.
- Rozchód bez wskazanej partii bierze partie **FEFO** (pierwsze traci ważność,
  pierwsze wychodzi): ważne od najkrótszej daty, bez daty na końcu, a
  przeterminowane dopiero wtedy, gdy innych nie ma. Wybór zapada w jednym
  miejscu księgowania (`_post`), więc tak samo dla kalendarza, terenu i
  przyszłego sklepu; blokada pozycji w tym samym miejscu szereguje rozchody, żeby
  dwa nie wzięły tej samej partii. Czego nie ma w partiach, schodzi bez partii
  (stan poniżej zera jak dotąd); MM przenosi te same partie do drugiego miejsca;
  korekta odwraca ruchy razem z partią.
- Inwentaryzacja pozycji z partiami liczy partia po partii: wiersz bez partii
  wolno podać tylko, gdy żadna partia nic tu nie ma (inaczej liczyłby partie
  drugi raz), a policzenie po partiach zeruje stan bez partii w tym miejscu —
  na półce nie ma towaru bez partii.
- Przeterminowana partia w pracy tylko ostrzega; **sprzedaż (WZ) zatwierdzana w
  panelu odmawia** partii po terminie (`stock_lot_expired`, 409), towaru bez
  ważnej partii i wskazanej partii, której nie starcza (`stock_shortage`). WZ z wizyty (`consume`) omija partie po
  terminie, ale nie zatrzymuje zakończenia wizyty.
- „Najbliższa ważność” w stanach to najwcześniejszy termin partii w miejscu —
  także już miniony — a nie partia, którą FEFO weźmie jako następną. Pozycja,
  która przestała prowadzić partie, nie pokazuje dawnych partii jako stanu.
- „Kończy się ważność” to termin w ciągu 30 dni; stan (`expired`, `expiring`,
  `ok`, `no_date`) liczy się w dniu firmy (jej strefa czasowa).
- Moduły dostają partie przez `api.py`: `consume` przyjmuje partię jako trzeci
  element wiersza (nieznana partia nie zatrzymuje pracy — wtedy FEFO),
  `holder_stock` zwraca partie zapasu w kolejności FEFO, `source_lots` mówi,
  które partie zeszły dla źródła, `describe_items` — kategorię i czy pozycja
  prowadzi partie.
- Panel: przełącznik w karcie pozycji, partia i data przy przyjęciu, wybór
  partii przy rozchodzie („automatycznie — najkrótsza ważność”), najbliższa
  ważność w stanach i podstrona **Partie i ważność** (`/panel/inventory/lots`).
- Karencja leków nie należy do magazynu: zostaje w HoofCare, a rejestr
  gospodarstw niesie jej koniec na wpisie kartoteki (ADR-051, uzupełnienie
  25.09).

## Uzupełnienie 2026-10-03: stan minimalny, powiadomienie i ustawienia (faza 10a)

- **Minimum to dane, nie ustawienie.** Pozycja ma swoje minimum (`minimum_quantity`,
  jak dotąd) i dotyczy ono magazynów. Jedno miejsce może mieć własne:
  `InventoryBalance.minimum_quantity` (pozycja × miejsce, `PUT /inventory/minimums/`,
  historia `inventory.minimum.changed`). Kolejność: minimum miejsca → w magazynie
  minimum pozycji → zapas osoby bez własnego nie ma żadnego; `0` przy miejscu znaczy
  „tu bez minimum”, `null` — dziedziczy. Osobnej tabeli nie ma: wiersz stanu to już
  „pozycja w tym miejscu”, a nikt nie odbudowuje stanów z ruchów.
- **Jedna reguła „do uzupełnienia”:** dostępne (stan − zarezerwowane) ≤ minimum.
  Liczy ją serwer (`below_minimum` w wierszu stanu, `GET /inventory/low-stock/`),
  panel jej nie powtarza. Pozycja z minimum, której w magazynie głównym nigdy nie
  było, jest na liście z zerem; inne miejsca liczą tylko to, co w nich było albo ma
  tam własne minimum.
- **Powiadomienie raz dziennie, domyślnie wyłączone** (decyzja koordynatora 03.10:
  dotąd nic nie wychodziło, więc wdrożenie niczego nie zaczyna wysyłać; ADR-078
  „domyślne = dziś”). Zadanie co godzinę, firma po firmie w jej tenancie: pierwsza
  godzina dnia firmy równa albo późniejsza niż `inventory.alerts.hour`, w której coś
  jest do uzupełnienia, wysyła wiadomość w panelu i e-mail. Kluczem jest lokalna data
  firmy, więc godzina powtórzona przy zmianie czasu nie wysyła drugi raz, a godzina,
  której nie było, nie gubi dnia. Odbiorcy: kto prowadzi magazyn albo sam właściciel;
  przy zapasach osób — także osoba, o swoim. E-mail podaje pozycje i miejsca, nigdy
  ludzi. Plan bez magazynu zostawia wybór, nie wysyła.
- **Ustawienia firmy (ADR-078, M3–M6)** w obszarze „Magazyn”: `inventory.alerts`
  (`low_stock` off/daily, `places`, `recipients`, `holder`, `hour`), `inventory.lots`
  (`expiring_days` 1–365, domyślnie 30 — kategoria może mieć własne
  `InventoryCategory.expiring_days`; `expired_sale` block/warn, domyślnie block) i
  `inventory.materials` (`source` main/lead_person). Praca przy partii po terminie
  tylko ostrzega i nie jest ustawieniem (decyzje 21.09 i 25.09).
- **Skąd schodzą produkty wizyty (M5), zmienia uzupełnienie 24.09:** miejsce wybiera
  magazyn (`inventory.api.visit_place`), kalendarz tylko pyta — magazyn główny albo
  zapas osoby prowadzącej wizytę (gdy ma konto). Rezerwacja stoi tam, gdzie powstała;
  zakończenie wizyty zdejmuje z miejsca wskazanego w tej chwili.
- `shared.inventory` zależy od `shared.notifications` (powiadomienie); każdy profil z
  magazynem już je składał.

## Uzupełnienie 2026-10-03: raporty (faza 10b)

- **Dwa raporty, tylko dla prowadzących magazyn** (`inventory.manage`; pokazują, ile
  firma zapłaciła — odpowiedź 43a): `GET /inventory/reports/stock-value/` (ilość ×
  średnia cena pozycji; według pozycji, kategorii albo miejsca, sumy per waluta) i
  `GET /inventory/reports/usage/` (zużycie RW i sprzedaż WZ w okresie dni firmy, do
  366 dni, stronicowane).
- **Zużycie liczy ruchy po cenie z dnia ruchu** (`unit_cost_minor`), więc późniejsza
  dostawa nie zmienia przeszłości. Korekta to ruch w drugą stronę: odejmuje się w
  okresie, w którym ją wystawiono. Przesunięcia (MM), przyjęcia i inwentaryzacja nie
  są zużyciem. Wartość sprzedaży to cena z wiersza WZ.
- **Magazyn nie zna wizyt.** Moduł, który zdejmuje towar (`consume` ze `source`),
  mówi raportom, czym była jego referencja: `inventory.api.register_usage_source(
  source, describe)` zwraca dla referencji `UsageContext` — wizytę, usługę, klienta,
  osobę. Rezerwacje rejestrują `booking.appointment`; produkt rejestruje swoje źródła
  w swoim repozytorium (HoofCare: `hoofcare.entry`). Dokument bez źródła to korekta
  albo strata firmy — wiersz „poza wizytami”.
- **Grupowania:** pozycja; osoba (prowadzący wizytę, gdy źródło go zna, inaczej osoba,
  z której zapasu zeszło, inaczej wystawiający dokument); usługa; klient; wizyta po
  wizycie — „koszt wizyty” (koszt materiałów i wartość sprzedaży).
- **Nazwisko klienta** podaje źródło tylko czytającemu, który widzi wizyty wszystkich
  (`booking/visibility.sees_others`, UX-023); inaczej wizyta jest w raporcie bez tego,
  czyja była (`hidden`). Nazwiska są wyłącznie w grupowaniach „klient” i „wizyta”.
- **Cena sprzedaży na WZ wizyty:** `consume(unit_prices=…)` zapisuje na wierszach WZ
  cenę uzgodnioną przy rezerwacji; wcześniej WZ z wizyty nie niosło ceny, więc dla
  starych wizyt raport pokaże koszt bez wartości sprzedaży.

## Konsekwencje

- Dziesięć tabel tenantowych z wymuszonym RLS (ADR-039): pozycja, kategoria,
  miejsce, dostawca, dokument, wiersz dokumentu, ruch, stan, rezerwacja i licznik
  numeracji. Jeden strażnik relacji sprawdza każdy klucz obcy do tabel magazynu.
- Profil produktu zyskuje opcjonalne pole `organizationTypes[].inventory`;
  profile bez niego nie zmieniają artefaktu ani hasha.
- Stare endpointy v1 (przyjęcie, wydanie, zwrot, korekta) działają dalej jako
  skróty tworzące zatwierdzone dokumenty PZ, MM oraz PW/RW (korekta stanu), dopóki panel nie
  przejdzie na dokumenty.
- Import CSV i PDF dokumentów to kolejne fazy planu (partie i ważność —
  uzupełnienie 25.09; stan minimalny, powiadomienie i raporty — uzupełnienia 03.10).

## Odrzucone

- **Ruchy bez dokumentów** (v1): prościej, ale bez numeracji i zatwierdzania
  nie da się tego pokazać księgowej.
- **Kategorie jako stała lista w rdzeniu:** to słownik korektora w rdzeniu,
  sprzeczny z ADR-049.
- **Osobny magazyn na leki:** jedna torba korektora, dwa magazyny (decyzja
  21.09).
