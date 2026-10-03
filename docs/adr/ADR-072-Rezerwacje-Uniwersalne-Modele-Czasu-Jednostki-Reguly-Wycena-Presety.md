# ADR-072 — Rezerwacje uniwersalne: modele czasu, jednostki i grupy, reguły i wycena, presety

**Status:** Accepted — decyzje właściciela (plan rezerwacji uniwersalnych,
odpowiedzi 1–24 z 01–02.10.2026 oraz 28a i 29a z 02.10.2026, §8) i decyzje
techniczne agenta (T1–T23 planu); pozostałe rozstrzygnięcia techniczne tego
ADR-u (z powodem w tekście): puste `Appointment.staff` (§2), blokada jednostki
jako alokacja (§4), kod VAT `np` (§6), VAT na pozycji i nazwy pozycji w dwóch
językach (§7), `CREATED` dopiero przy potwierdzeniu (§9), okno odbioru jako
`session` (§10), addytywne `booking.api` z `include_pending` i
`BookingSetupMutation` (§11), ważność linku samoobsługi od końca rezerwacji
(Konsekwencje); termin `pending_payment` — za ADR-073 §5.
**Data:** 2026-10-02
**Właściciel:** zespół SaaS Core
**Rozszerza:** ADR-030 — okres i wydarzenie (§1), blokady jednostek pod
`EXCLUDE` (§4), horyzont 62 dni tylko dla terminów (§5), migawka wyceny (§7).
**Zmienia:** ADR-030 w zdaniu „płatność i zaliczka są poza pierwszym zakresem
W9” (§6–§8); ADR-027 — usuwanie obiektu „gdy żadna publikacja go nie
referencjonuje” (zdjęcia jednostek, §3); ADR-058 §2 i niezmiennik prowadzącego z „Ustaleń fazy 3” (§2 tutaj)
oraz ADR-058 §3 w zakresie zawężonym w §9, z ich alternatywami odrzuconymi.
**Uzupełnia:** ADR-050, ADR-063 §2, ADR-073–ADR-075.
**Stosuje:** ADR-069 (źródła tłumaczeń,
`docs/architecture/translation-sources.md`; §11), ADR-071 (języki treści i
język klienta, `Organization.public_locales`; §7, §9–§11), ADR-076 (błędy pól,
„w imieniu”; §11).

## Kontekst

Pierwsze realne zapytanie — dwa domki na Mazurach — wymaga pobytu na noce,
sezonów, zadatku i synchronizacji z portalami. Właściciel 01.10 (decyzja 1):
rezerwacje powstają w rdzeniu i od razu obsługują wizytę, okres i wydarzenie z
miejscami, a produkty dokładają swoje przez punkty rozszerzeń (ADR-049); 02.10
(decyzja 22): budujemy od razu. Plan: memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`; stan kodu (main e381199) podaje
każdy punkt.

## Decyzja

### 1. Jedna rezerwacja, trzy modele czasu (T1, T4)

Każda rezerwacja — wizyta, pobyt, wynajem, miejsce na zajęciach — to
`Appointment` z tym samym klientem, historią, samoobsługą i przypomnieniami;
czas trzymają aktywne alokacje rezerwacji, a w wydarzeniu — wystąpienie (§3).
`Service.time_model` to `slot` (dzisiejszy silnik, ADR-058 §5), `range` (okres
od–do wybrany przez klienta; `range_unit`: `night`, `day`, `hour`) albo
`session` (miejsca w wystąpieniu z pojemnością). Istniejące oferty dostają
`slot`; oferta z rezerwacjami nie zmienia modelu. `duration_minutes` (dziś
5–1440) opisuje `slot` i domyślne wystąpienie `session`; w `range` jest puste i
CHECK długości go nie obejmuje, bo długość wynika z reguł.

Noc to data lokalna z godziną zameldowania i wymeldowania oferty, przeliczona na
UTC w strefie firmy (ADR-030); zajętość trwa od zameldowania do wymeldowania
plus przerwa po, więc wyjazd 11:00 i przyjazd 16:00 tego dnia się nie kłócą.
`day` ma godzinę odbioru i zwrotu, `hour` — start i koniec w godzinach otwarcia.

### 2. Oferta bez osoby (T5) — zmienia ADR-058 §2

`staff_count` przyjmuje 0–10 (dziś 1–10); zero w ofercie, której rezerwacja nie
zajmuje osoby: jednostka albo miejsce w wydarzeniu (osobę i salę trzyma
wystąpienie). Osobę przy jednostce wybiera firma w ofercie, nie klient (auto z
kierowcą: `staff_count` ≥ 1). `Appointment.staff` jest puste wtedy i tylko
wtedy, gdy `staff_required = 0` (CHECK); z osobami niezmiennik ADR-058 i
`crew.set_crew` działają bez zmian. Alternatywa „`Appointment.staff` jako pole
opcjonalne”, odrzucona w ADR-058, bo wakat opisuje znacznik, wraca w tym
zakresie: rezerwacja bez osoby nie ma wakatu, a fikcyjny „pracownik jednostki”
powtórzyłby błąd fikcyjnego członkostwa klienta (ADR-030). Godziny otwarcia
jednostki to `AvailabilityRule` wskazująca osobę albo jednostkę (CHECK:
dokładnie jedno), więc czas lokalny i DST liczy ten sam kod; `night` i `day` są
całodobowe.

### 3. Jednostki, grupy i wydarzenia (T2, T3)

- Jednostka to rozszerzony `Resource`: pojemność, opis, wyposażenie, zdjęcia,
  `public_slug`, `Location`, miasto ze słownika katalogu, współrzędne tylko na
  serwerze, flaga `public`, godziny otwarcia. Zdjęcia wskazuje niezmienna wersja
  ich zestawu, bo referencje mediów są tylko do dopisywania; sprzątanie mediów i
  publiczne źródła zdjęć (rejestr w `core.organizations`, ADR-074 pkt 7)
  obejmują je jak zdjęcia produktu.
- Grupa (`ResourceGroup`: „Domek 6-os.”) to pula identycznych jednostek;
  jednostka należy najwyżej do jednej, żeby dobór liczył jedną pulę. Na N sztuk
  serwer dobiera wolne najmniej obciążone (ADR-058 §4); brak N wolnych to
  konflikt terminu. Przepięcie na inną jednostkę grupy ma oczekiwaną wersję;
  `Appointment.resource` to pierwsza aktywna alokacja.
- Wymagane `ServiceResource` oferty `slot` zostają pulą „jeden z” (dziś pierwszy
  wolny według id), od fazy 2 z doborem najmniej obciążonej, bez migracji do
  grup; `range` wskazuje jednostkę albo grupę.
- Liczone miejsca są tylko w wydarzeniu: wystąpienie zajmuje osobę i salę, a
  miejsca liczy pod blokadą swojego wiersza (`select_for_update` działa, bo
  wiersz istnieje). Kształt wystąpień ustala faza 8.

### 4. Blokady jednostek rozstrzyga `EXCLUDE`

`TimeOff` (dziś poza `EXCLUDE`) dostaje `source` (`manual` | `ical`), klucz obcy
`import_channel` (kanał z ADR-075; usunięcie kanału usuwa jego blokady, strażnik
relacji między tenantami obejmuje kolumnę) i `external_uid` (UID wydarzenia,
przy powtórzeniu z początkiem wystąpienia), unikalny w kanale. Każda blokada
jednostki — ręczna i z importu — trzyma czas własnym wierszem
`AppointmentResourceAllocation`, który należy do rezerwacji albo do blokady
(`appointment` | `time_off`, CHECK: dokładnie jedno), pod istniejącym `EXCLUDE`:
ograniczenie nie sięga do drugiej tabeli, a sprawdzenie w Pythonie nie
rozstrzyga wyścigu (ADR-030). Ręczna blokada na rezerwację albo na inną
blokadę tej jednostki to 409. Blokada z importu nachodząca na naszą rezerwację
zostaje zapisana bez aktywnej alokacji i otwiera konflikt (`CalendarConflict`,
ADR-075) — alarm, nigdy odwołanie. Blokada z importu, której czas trzyma już
inna blokada (ręczna albo z importu, także z tego samego kanału), też zostaje bez
aktywnej alokacji,
ale bez konfliktu: alarm dotyczy tylko naszych rezerwacji. Taka blokada dalej
zajmuje termin (ADR-075 pkt 6), a kolejny przebieg importu zakłada jej
alokację, gdy nakładanie zniknie. Nieobecność osoby działa jak dziś (ADR-058).
Import w fazie 6 obejmuje tylko jednostki (osoby później), eksport — jednostki
i osoby.

### 5. Reguły i wyszukiwanie okresu (T6, T7) — rozszerza ADR-030

`BookingRule` to wiersz z zakresem dat lokalnych (sezon) i zasięgiem — oferta,
grupa albo jednostka; wygrywa bardziej szczegółowy, przy remisie późniejszy
początek. Pola: minimalna i maksymalna długość, wielokrotność (7 — pełne
tygodnie), dni początku i końca, wyprzedzenie, okno naprzód, zamknięcie, przerwa
po. Sezony to jawne daty ze „skopiuj na kolejny rok”, bo daty sobót przesuwają
się co roku.

Kalendarz okresu to jedno zapytanie o alokacje i blokady jednostek (§4) oraz ich
reguły (T7); wynik to dni początku i końca. `BOOKING_SLOT_HORIZON_DAYS` (≤ 62)
zostaje granicą zapytania o starty `slot`, nie oknem rezerwacji; kalendarz
okresu ma własną (ustawienie platformy, domyślnie 18 miesięcy z T7, co mieści
przykładowe okno planu 540 dni), a odległość od dziś ogranicza reguła okna.
Rezerwacja sprawdza jeden pobyt walidacją, nie listą dni (ADR-058 §5). Tej samej
funkcji kalendarza i wyceny użyje katalog (faza 16) w publicznym kontekście
każdej firmy, bez `PRE_TENANT_DB`.

### 6. Cennik (T6, T22)

- `PriceRule`: podstawa `per_booking`, `per_time_unit`, `per_person` albo
  `per_group`; zasięg i daty jak reguły; nadpisania dniem tygodnia i porą dnia;
  osoby w cenie i dopłata za kolejną; ceny kategorii uczestników (z flagą „liczy
  się do pojemności”); rabat za długość.
- `Extra`: nazwa, kwota, podstawa (także `per_person_per_time_unit`),
  obowiązkowa albo do wyboru, stawka VAT. Kaucja to osobna kwota, nie przychód.
  Opłatę miejscową firma pobiera dla gminy, więc to pozycja bez VAT z kodem `np`
  („nie podlega”), do potwierdzenia przez księgową.
- Jedna waluta cennika: `Organization.currency` z listy platformy (PLN, EUR, USD
  — decyzja 16); kwota niesie walutę, a zmianę waluty firmy z cennikiem odrzuca
  ADR-073 §8 (`currency_in_use`). Ceny brutto albo netto według ustawienia
  firmy; stawka VAT to kod (dziś 23, 8, 5, 0, `zw`, jak w magazynie, ADR-055
  §1), bo zwolnienie to nie 0%; ADR-040 dotyczy tylko abonamentów platformy.

### 7. Jedna wycena `quote`, zamrożona w rezerwacji

`quote` to jedna funkcja serwera bez zapisu: z oferty, okresu, jednostek,
uczestników i dopłat liczy pozycje (noce według sezonów, osoby, dopłaty, rabaty;
kaucja osobno), sumy netto, VAT i brutto, walutę i polityki z §8, a przy
naruszeniu reguł zwraca błędy z kodem i polem. Kwoty to liczby całkowite w
jednostkach drobnych; VAT i procent liczy się na pozycji (zaokrąglenie do
jednostki drobnej, połówki w górę), bo pozycje przechodzą 1:1 do zamówienia
(ADR-073) i programu do faktur (T15). Widget, panel, asystent i zapis wołają tę
samą funkcję; zapis liczy ją na nowo w transakcji i zamraża w
`Appointment.quote`, a niezgodny skrót pokazanej wyceny (`quote_digest`) daje
409 `quote_changed` z nową wyceną.

`quote` przyjmuje język klienta (ADR-071 pkt 21) i zamraża nazwy pozycji w tym
języku obok nazw w języku źródłowym oferty, jak nazwa usługi zamrożona w języku
klienta w TL12; brak tłumaczenia daje nazwę źródłową. — Migawki nie da się
później poprawić, a czytają ją dwie strony: e-maile, samoobsługa i plik .ics
mówią do gościa jego językiem, a panel i program do faktur (T15) — językiem
firmy.

### 8. Potwierdzenie, miejsce, płatność i anulowanie należą do oferty

Oferta niesie `confirmation` (`instant`, `on_request` z czasem odpowiedzi w
godzinach, `quote_request` — faza 13), politykę płatności (`none`, `on_site`,
`transfer`, `deposit`, `full`), zadatek procentem albo kwotą, termin przelewu w
dniach, dopłatę reszty X dni przed albo na miejscu i progi anulowania „co
najmniej N dni przed → % zwrotu”. Wszystko trafia do migawki, a zwrot liczy się
z niej. Pieniądze opisuje ADR-073; gdzie zamówień nie ma (ADR-073 §1), oferta
przyjmuje tylko `none` i `on_site`, więc `pending_payment` nie powstaje.

Decyzja właściciela 28a: przy zadatku progi zwrotu obejmują domyślnie tylko
zadatek, a dopłata wraca w całości. Firma zmienia to przełącznikiem w
ustawieniach oferty „Progi zwrotu obejmują też dopłatę”, w presecie Nocleg
wyłączonym. To ustawienie firmy, nie samo pole danych: API oferty je odczytuje,
pokazuje w podglądzie i zmienia, jak inne polityki płatności (§11), a warianty
i wartość domyślną podaje w odpowiedzi. W kontrakcie presetów i w migawce wyraża je
`cancellation.appliesTo`: `deposit` — wyłączony, `paid` — włączony (wszystkie
wpłaty). Przy `transfer` i `full` zadatku nie ma, więc nie ma też
przełącznika: progi obejmują całą wpłatę (`paid`). — Wartość domyślna trzyma
się słów 13a („zwrot zadatku”), a firma, która chce zatrzymać część dopłaty,
wybiera to jawnie, zamiast zgadywać regułę ukrytą w kodzie.

Decyzja właściciela 29a: dopłata niewpłacona w terminie niczego nie anuluje
sama. Gość dostaje przypomnienia, a firma alert (ADR-073 §5); rezerwacja
zostaje `confirmed`. O odwołaniu decyduje firma, a odwołanie z powodem
„niewpłacona dopłata” rozlicza zadatek według progów, jak rezygnację gościa.
Każde inne odwołanie przez firmę zwraca co najmniej wszystkie wpłaty; czy przy
zadatku należy się więcej (art. 394 § 1 KC), sprawdza lista prawna. — Tylko
firma wie, czy przelew jest w drodze i czy warto czekać; automat odwołałby pobyt
za jeden spóźniony przelew.

Miejsce (`business`, `customer`, `online`, `pickup_return`) przy `customer`
korzysta z miejsca wizyty (ADR-066). Pole typu `consent` zapisuje akceptację w
dzienniku zgód (T16, ADR-073 §9); pozostałe pola własne to dane klienta: nie
trafiają do e-maili, logów ani historii zmian, a anonimizacja je czyści.

### 9. Rezerwacje oczekujące (T8) — zawęża ADR-058 §3

- `AppointmentStatus` dostaje `pending_request` (oferta `on_request`) i
  `pending_payment` (wpłata przed potwierdzeniem, którą da się złożyć z góry —
  online albo przelewem, ADR-073 §5; bez żadnej z tych metod należność idzie na
  miejscu, a rezerwacja jest `confirmed`); obie trzymają termin tymi samymi alokacjami co `confirmed`, bez
  „wstępnych” blokad i ich wyprzedzania.
- ADR-058 §3 (odpowiedź właściciela 1 z 24.09: bez stanów oczekujących i
  wstępnych blokad) obowiązuje dalej dla ofert `instant` z polityką `none` albo
  `on_site`. Oferta `on_request` albo z wpłatą przed potwierdzeniem — także
  Nocleg według 13a („dopóki nie ma płatności online — zadatek przelewem w 3
  dni, inaczej rezerwacja wygasa”) — tworzy rezerwację oczekującą, która trzyma
  termin jak potwierdzona. Podstawą zawężenia są 13a (wpłata), oś
  „Potwierdzenie” planu i T8 („na prośbę”).
- Termin `pending_request` (odpowiedź firmy w godzinach) wygasza booking przez
  trasę bez danych osobowych z kontraktem `service` organizacji (wzorzec
  `ReminderRoute`, ADR-058 §7; zakres przez `register_service_scope`, ADR-073 §5),
  nie zapytaniem po tenantach. Termin
  `pending_payment` należy do commerce: rozstrzyga `Payment.due_at`, a zadanie
  terminów commerce (ten sam wzorzec) wygasza płatność, anuluje zamówienie, a
  handler źródła zwalnia rezerwację w tej samej transakcji (ADR-073 §5);
  `Appointment.hold_expires_at` to kopia `due_at` do wyświetlania.
- Booking jest źródłem zamówień `R` (ADR-073 §1): handler potwierdza po wpłacie,
  a rezerwacji, której nie da się już przyjąć (wygasła, termin zajęty), odmawia
  bez wyjątku i commerce zleca zwrot. Formularz i link samoobsługi wołają
  `commerce.api` w kontekście `public_booking_context` z zakresem
  `commerce.public.pay`; token wiąże płatność z jednym zamówieniem, kwoty liczy
  serwer.
- Akceptacja prowadzi do `pending_payment` albo `confirmed`; odmowa, rezygnacja
  i wygaśnięcie — do `canceled` z powodem w historii. E-mail potwierdzenia,
  przypomnienie i rezerwacja materiałów (ADR-055 §7) przychodzą z `confirmed`;
  przełożyć można tylko potwierdzoną. Obserwatorzy dostają `CREATED` przy
  potwierdzeniu, a o odmowie, wygaśnięciu i rezygnacji z oczekującej — nic, więc
  produkty (HoofCare: `CREATED` → „zaplanowana”) nie widzą niepotwierdzonych.
- E-maile do gościa z §8–§9 (przyjęta prośba, odmowa, wygaśnięcie; dane do
  przelewu z terminem, przypomnienie dopłaty i zwrot wysyła commerce, ADR-073)
  to szablony `audience=customer` w języku klienta (`Customer.locale` przycięty
  do `public_locales`, ADR-071 pkt 21), z łańcuchem żądany → en → pl
  rozstrzyganym przy kolejkowaniu (ADR-071 pkt 20).

### 10. Presety jako dane (T13, T23; odpowiedzi 13a, 14 a+b)

- Kontrakt `packages/contracts/booking-presets/` (schemat JSON Schema 2020-12,
  manifest i 13 presetów planu w plikach `core.<klucz>.v<N>.json`) pilnuje test
  Ajv (strict); opublikowanej wersji się nie zmienia. Preset niesie wartości osi
  oferty z planu, słownictwo pl i en, dane potrzebne od firmy (`requiredInputs`:
  daty sezonów, minimum nocy, zdjęcia — z nich konfigurator asystenta liczy
  brakujące pytania), kategorię katalogu i szablon strony (pomijane, gdy typ
  organizacji ich nie ma); kwot i stawek VAT nie niesie, bo zależą od waluty i
  kraju firmy. Schemat sprawdza w kluczach języków tylko kształt `^[a-z]{2}$`,
  który przepuściłby `cz`, więc test sprawdza je z rejestrem języków treści
  `packages/contracts/locales/registry.json` (ADR-071 pkt 2).
- `readiness`: `ready` — rdzeń tej wersji przyjmuje takie rezerwacje (dziś tylko
  „Wizyta u specjalisty”; test pilnuje, by używał tylko tego, co umie silnik);
  `soon` — „wkrótce” z zapisem na listę i „Czego Ci brakuje?” (14 a+b).
  Słownictwa, pól, dopłat i uczestników schemat wymaga tylko od `ready`. Preset
  `soon` niesie z planu nazwę, opis, model czasu i wartości z tabeli presetów;
  wartości spoza tabeli to propozycje agenta, które zastąpi wersja `ready` z
  fazy uruchamiającej preset (preset 9 w fazie 2: od razu albo na prośbę,
  zapytanie ofertowe w fazie 13, jak w tabeli).
- Preset 13 („Odbiór zamówienia w oknie”) to wystąpienia `session` z
  pojemnością, choć tabela mówi „slot + sklep” — decyzja techniczna agenta:
  zamówienia na okno to liczone miejsca, które T3 dopuszcza tylko w wydarzeniu,
  a start `slot` idzie siatką 5 minut. Dostawa `pickup` sklepu wskazuje
  wystąpienie, a zamówienie zajmuje jedno miejsce (ADR-074).
- Wartości domyślne (Nocleg według 13a i 28a: od razu, zadatek 30% przelewem w
  3 dni, reszta 14 dni przed, zwrot zadatku 100/50/0% z dopłatą poza progami,
  16:00 i 11:00) są podpowiedzią. Do rejestru ustawień platformy obowiązuje
  plik, a zmiana to nowa wersja presetu; potem rejestr deklaruje ustawienie
  klasy A z wartością z pliku jako domyślną, a operator ją nadpisuje (T23).
- Zastosowanie to kopia, nie odwołanie (ADR-063 §2): powstaje nieaktywna oferta
  z pochodzeniem (§11), a słownictwo staje się jej treścią. Treść źródłową
  oferta dostaje w języku źródłowym treści booking (pierwszy język firmy,
  ADR-071 pkt 4) ze słownictwa presetu w tym języku; preset bez tego języka daje
  słownictwo en, a bez niego pl (łańcuch jak w e-mailach, ADR-071 pkt 20),
  które firma poprawia przed uruchomieniem oferty — jak nasiona szablonu w
  innym języku (ADR-071 pkt 6). Pozostałe języki presetu, które firma ma w
  `public_locales`, trafiają do wierszy tłumaczeń (§11) z
  `Provenance(origin="template")`, więc automat może je później nadpisać. Słowa
  w panelu (oś aplikacji) pochodzą w pl/en z oferty i presetu, nie z wierszy
  treści. Panel, strona i asystent czytają presety z
  `GET /api/v1/booking/presets/`; API i loader (kopia w obrazie,
  `BOOKING_PRESET_CONTRACTS_PATH`, system check) powstają z pierwszym
  czytelnikiem: fazą A2 asystenta albo fazą 5.
- Produkt dokłada presety w profilu (`organizationTypes[]`, ten sam schemat,
  własna przestrzeń nazw; `serviceTemplates` zostają). Pole i walidację w
  `deployment-check` dodaje faza 5 z wpisem w dokumentacji wydania (ADR-049), a
  reguły, które dziś sprawdza tylko test, przenosi do wspólnego modułu
  kontraktu.

### 11. Treść, pochodzenie, rozszerzenia i asystent

- Treść ofert, jednostek, grup, dopłat, kategorii uczestników i pól ma wiersze
  tłumaczeń na język we wspólnej bazie tłumaczeń booking (TL12 planu
  wielojęzyczności): język, wersja z blokadą przy zapisie, pochodzenie per pole
  (`content_protocol.provenance.Provenance` w tym samym wierszu,
  translation-sources.md §4), klucz idempotencji ze skrótem i flagi zastępstw.
  Język wiersza sprawdza jedna funkcja z ADR-071 pkt 3 (`locale_not_in_registry`,
  `locale_not_enabled`; w bazie CHECK formatu `^[a-z]{2}$`, bez `choices`).
- Źródła `booking.service`, `booking.resource`, `booking.resource_group`,
  `booking.extra`, `booking.participant_category` i `booking.field` to rekordy
  na żywo (podstawa `published`, zapis `live`, prawo publikacji = prawo edycji
  encji, ADR-069 pkt 3). Rejestruje je
  `content_protocol.registry.register_translation_source` w `AppConfig.ready` od
  fazy powstania encji, gdy TL5 jest już w `main` (inaczej razem z TL12), jak
  produkty sklepu (ADR-074 pkt 8). Każde nowe źródło to w jednym commicie
  adapter, rejestracja, zgłoszenia `notify_source_changed` w serwisach, test
  kontraktu i wiersze w tabelach §5 i §8.1 translation-sources.md (§12 tam). —
  Silnik nie pisze tabel booking (ADR-069 pkt 3), więc blokady, audyt i
  idempotencja zapisu tłumaczeń zostają w booking.
- Encja konfiguracji (oferta, jednostka, grupa, reguła, reguła ceny, dopłata)
  niesie pochodzenie: `preset_id` i wersję, gdy powstała z presetu, oraz
  identyfikator przebiegu asystenta, gdy założył ją asystent — wtedy jest
  nieaktywna do uruchomienia (plan asystenta, AI-T6).
- Rezerwacja zapisuje kanał (`company_site`, `catalog`) i podpisany token
  pochodzenia niezależnie od commerce; zamówienie je kopiuje, a sklep zapisuje
  je na swoim zamówieniu; token jest w adresie albo stanie widgetu, nigdy w
  ciasteczku. Przełącznik „Pokazuj wolne terminy w katalogu” (domyślnie
  wyłączony) to operacja API, a odznakę „rezerwacja online” booking zgłasza
  katalogowi rejestrem profiles (jak `register_catalog_terms`).
- `booking.api` zmienia się addytywnie: nowe argumenty `create_appointment` mają
  wartości domyślne (także dołączenie do istniejącego zamówienia — okno odbioru
  sklepu nie dostaje osobnego zamówienia `R`, a potwierdzenie idzie w e-mailu
  zamówienia); `list_appointments` i `appointment_for_tenant` pomijają
  `pending_*`, jeśli produkt nie poda `include_pending=True`. Puste
  `Appointment.staff` zmienia kształt danych produktów: wpis w dokumentacji
  wydania (ADR-049) i poprawka HoofCare (rodzaj wizyty przed
  `appointment.staff`) przychodzą z fazą 2.
- Nowe operacje są obsługiwalne przez asystenta (AGENTS.md): błędy z kodem i
  polem (`rule_min_length`, `unit_capacity_exceeded`, `quote_changed`,
  `booking_version_conflict`…; kształt `errors` z ADR-076 pkt 5), `dry_run`
  konfiguracji, audyt z brakującym dziś `booking.appointment.place_changed`
  (rodzaj aktora i „w imieniu”, ADR-076 pkt 6); cennik i polityki płatności,
  także przełącznik progów zwrotu z §8, asystent zmienia za zgodą z digestem
  (ADR-033).
- Klucz idempotencji konfiguracji zapisuje `BookingSetupMutation` (organizacja,
  akcja, principal, klucz, skrót żądania, rodzaj i id wyniku; unikalny na
  organizacji, akcji, principalu i kluczu jak `booking_mutation_idem_uq`; tabela
  tenantowa z RLS), bo `BookingMutation` wskazuje wizytę; służy też kanałom
  kalendarzy (ADR-075). Zapis niesie `expected_version`; nieaktualna to 409
  `booking_version_conflict`.

## Konsekwencje

- Fazy planu: 2 — §1–§5; 3 — §6–§8 (także dla terminów); 4 — §9 z ADR-073; 5 —
  presety przy zakładaniu; 6 — iCal (ADR-075); 8 — wydarzenia; 13 — pozostałe
  presety. Faza wydaje wersje presetów, które uruchamia.
- Migracje `booking` są odwracalne; nowe tabele mają wymuszone RLS, nowe kolumny
  FK trafiają do `booking_validate_tenant_relations()` migracją, której
  odwrócenie przywraca poprzednie ciało funkcji, a booking dostaje
  `shared.media` w `dependsOn`. Istniejące blokady zasobów dostają alokacje; ta,
  która już nachodzi na rezerwację albo na wcześniejszą blokadę tego zasobu
  (dziś nikt tego nie sprawdza) — nieaktywną, z raportem migracji, inaczej
  migracja padłaby na `EXCLUDE`.
- Limit 12a to kwota `booking.units.max` (Profil 3, Starter 15, Pro 100) w
  nowych wersjach planów, sprawdzana przez `decide_quota` z operacją zapisu
  (parametr `operation`, ADR-071 pkt 7) — tymczasowo wbrew zapisowi odpowiedzi
  11–12 („prowizje i limity w panelu administratora”; słowa 11a:
  „konfigurowalna przez administratora platformy w panelu, nie w kodzie”),
  zgłoszone właścicielowi 01.10 (T23); panel limitów przychodzi z fazą 4 planu
  ustawień.
- Kod rozgałęziony na `confirmed` (przypomnienia, kolejka, skład, miary)
  obsługuje oczekujące według §9; przełożenie pobytu dobiera jednostkę z grupy
  na nowo; link samoobsługi (dziś 30 dni od utworzenia) liczy ważność od końca
  rezerwacji, żeby dożył terminu dopłaty.
- Pytania do właściciela, z wartością tymczasową: reguły pobytu przecinającego
  granicę sezonów (z pilotem; do tego czasu sezon dnia przyjazdu); stawki VAT
  spoza Polski (słownik polski).
- Otwarte technicznie: `day` jako doba czy dzień kalendarzowy i siatka startów
  `hour`; okno naprzód dla `slot`; czy limit liczy zasoby używane obok osoby;
  „Termin na wyłączność” dla samych osób. Lista prawna (sprawdzenie zgodności,
  nie pytania biznesowe): zadatek a zaliczka (art. 394 KC) — jak nazwać wpłatę
  przed pobytem i jej zwrot według progów; odwołanie przez firmę przy zadatku
  (art. 394 § 1 KC); opłata miejscowa bez VAT; numer obiektu (UE 2024/1028).

## Odrzucone

- Osobne moduły okresu i wydarzeń — kopiowałyby klientów, alokacje, statusy,
  powiadomienia, samoobsługę i skład (T1).
- Nowy model jednostki obok `Resource` — dublowałby blokadę z `EXCLUDE` (T2).
- Pula jako licznik „N sztuk” — `EXCLUDE` nie wyrazi „suma ≤ N” (T3).
- Blokada jednostki tylko w `TimeOff` albo w osobnej tabeli — blokada i
  rezerwacja gościa mogłyby obie wygrać; import i tak nie odrzuca wydarzenia
  portalu, tylko otwiera konflikt.
- Cena jako pola `Service` (`price_minor`, `tax_rate_bp`, ADR-037 §4) — nie
  wyrazi sezonów, osób, dopłat ani zwolnienia z VAT.
- Wygaszanie `pending_payment` także w booking — dwa zadania na jednym terminie
  ścigałyby się, a zamówienie zostałoby otwarte przy odwołanej rezerwacji.
- Stała podstawa progów zwrotu bez przełącznika — firma, która zatrzymuje część
  dopłaty, nie mogłaby tego wyrazić (28a).
- Samoczynne odwołanie rezerwacji z niewpłaconą dopłatą — odwołałoby pobyt za
  spóźniony przelew bez decyzji firmy (29a).
- Presety w kodzie albo jako `serviceTemplates` — 5–1440 min nie opisze okresu,
  a szablonów usług żadne API nie zwraca, więc asystent ich nie widzi.
- Preset jako odwołanie — jego zmiana przepisałaby oferty firm.

## Uzupełnienie 2026-10-03: zastosowanie presetu i szkic oferty (faza 3.0)

Pierwszym czytelnikiem presetów jest konfigurator asystenta (A2), więc loader,
`GET /api/v1/booking/presets/` i zastosowanie powstały przed cennikiem.

- **Zastosowanie tworzy samą ofertę** (`presets.apply_preset`, polecenie
  `booking.preset.apply@1`): firma podaje nazwę i — dla modelu `slot` — czas
  trwania, resztę daje preset. Osób ani miejsc nikt za firmę nie dobiera: bez
  `staff_ids` i `location_ids` oferta ich nie ma. Stosuje się tylko preset
  `ready`; odmowa ma kod na polu `preset_id`: `preset_unknown`,
  `preset_not_ready`, a `preset_not_allowed` jest zarezerwowany dla presetów
  typu organizacji (faza 5). Pokwitowanie to `service.create`, jak przy
  zwykłej nowej usłudze.
- **Pochodzenie** (§11) to pola oferty: `preset_id`, `preset_version` i
  `origin_ref` — rozmowa (`conversation:<uuid>`), gdy ofertę założył asystent,
  także poleceniem `booking.offer.create@1`.
- **Szkic** (`Service.draft`) to oferta, której od założenia nikt nie włączył.
  Tylko szkic bez rezerwacji można usunąć (`setup.discard_draft`, pokwitowanie
  `service.discard`; odmowy `not_a_draft`, `service_has_bookings`) — razem z
  powiązaniami, własnymi sezonami i tłumaczeniami. To jest cofnięcie
  `discard_run` poleceń, które zakładają szkice. Oferta choć raz włączona
  zostaje na zawsze i można ją tylko wyłączyć: mogła trafić na stronę, do
  odnośników i do historii. Oferty sprzed migracji `booking` 0024 szkicami nie
  są, bo nie wiadomo, czy były włączone.
- **Słownictwo etapami.** Zastosowanie kopiuje słowa presetu w języku
  źródłowym firmy (łańcuch z §10: pierwszy język firmy, potem en, potem pl) do
  `Service.vocabulary`. Wiersze tłumaczeń słownictwa w pozostałych językach
  firmy, o których mówi §10, powstaną z pierwszym czytelnikiem tych słów —
  formularzem publicznym presetów w fazie 5, gdy słownictwo stanie się polem
  źródła `booking.service`. Do tego czasu nikt by ich nie czytał, a oferta
  wskazuje niezmienną wersję presetu, z której faza 5 je dopisze.

## Uzupełnienie 2026-10-03: cennik i wycena (fazy 3a–3b)

Ustalenia, których §6–§7 nie rozstrzygały, przyjęte przy budowie cennika
(`prices.py`) i wyceny (`quote.py`).

- **Która cena obowiązuje.** Cena bez dat to cena podstawowa, z datami —
  sezonu; dni tygodnia i godziny zawężają ją do weekendu albo szczytu. Na dany
  dzień i godzinę: jednostka przed grupą przed ofertą (jak reguły, §5), potem
  sezon przed ceną podstawową, potem węższa przed szerszą, potem późniejszy
  początek. Noc należy do dnia, w którym się zaczyna.
- **Dzień przyjazdu decyduje** o podstawie ceny, o tym, czy kolejne osoby płacą
  za każdą jednostkę czasu, czy raz, i o rabacie za długość — tak jak sezon dnia
  przyjazdu decyduje o regułach (§5, Konsekwencje). Kolejne noce bierze się z
  cen o tej samej podstawie; noc bez ceny to odmowa `price_missing`.
- **Kto jest w cenie.** `included_people` obejmuje tych uczestników liczonych do
  pojemności, którzy zapłaciliby najwięcej, więc gość nie płaci więcej za to, w
  jakiej kolejności wpisał osoby. Kategoria nieliczona do pojemności (pies) nie
  zajmuje miejsca „w cenie” i płaci swoją kwotę albo nic, gdy cena jej nie
  wymienia. Cena „za osobę” liczy każdą osobę: kwotą ceny albo kategorii.
- **Rabat za długość** obejmuje wszystko, co liczy się za jednostkę czasu (cenę
  i dopłaty za osoby za noc), jako osobna ujemna pozycja na stawkę VAT.
- **Brutto albo netto** to ustawienie firmy `pricing.entry.amounts`
  (domyślnie brutto, klasa zmiany `publish`): zmiana niczego nie przelicza,
  tylko inaczej czyta wpisane kwoty. Dotyczy cennika usług, pobytów i dopłat;
  cena sprzedaży produktu w magazynie zostaje netto (uzgodnione z planem
  ustawień i z magazynem; czy sklep ma iść za tym przełącznikiem — pytanie
  fazy 9).
- **Oferta bez cennika** rezerwuje się jak dotąd: wycena nie ma pozycji, ale
  rezerwacja i tak zapisuje, kto przychodzi. Rezerwacje sprzed fazy 3b nie mają
  wyceny i przełożenie im jej nie dodaje.
- **Skrót wyceny** liczy się z ceny, nie ze słów: jest ten sam w każdym języku.
  409 `quote_changed` niesie nową wycenę w `detail.quote`. Przełożenie wizyty
  albo pobytu, który ma wycenę, liczy ją od nowa dla tych samych osób.
- **Pojemność jednostki** sprawdza wycena (`unit_capacity_exceeded` na polu
  `participants`), bo to ona zna uczestników.
