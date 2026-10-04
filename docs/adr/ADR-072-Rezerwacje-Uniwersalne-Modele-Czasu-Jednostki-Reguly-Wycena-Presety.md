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
  obejmują je jak zdjęcia produktu. (Plaster 5c zapisał zdjęcia jako listę na
  jednostce, bez wersji zestawu — „Rozstrzygnięcia plastra 5c”.)
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
  sezonu; dni tygodnia i godziny zawężają ją do weekendu albo szczytu. Kolejność
  na dany dzień i godzinę zmieniło uzupełnienie z 2026-10-03 niżej (decyzja
  75b); pierwotnie: jednostka przed grupą przed ofertą (jak reguły, §5), potem
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
- **Dopłaty i kaucja (faza 3c).** `Extra` należy do oferty: obowiązkowa jest na
  każdej rezerwacji, wybieraną klient bierze do `max_quantity` razy. Dopłata
  „za osobę” liczy osoby liczone do pojemności. Rabat za długość nie obejmuje
  dopłat. Kaucja to dopłata rodzaju `security_deposit`: jedna kwota na
  rezerwację, bez VAT (`np`), poza sumami wyceny (`security_deposit_minor`) —
  pobraną i zwracaną opisze zamówienie (ADR-073). Dopłaty się nie usuwa, tylko
  wyłącza; rezerwacja przekładana zachowuje dopłatę, którą wzięła, także gdy
  firma ją potem wyłączyła, a nowa rezerwacja wziąć jej już nie może.
- **Po przeglądzie arytmetyki (03.10).** Ustalenia doprecyzowane po niezależnym
  przeglądzie cennika i wyceny:
  - `included_people` wymaga podania dopłaty za kolejną osobę (0 to świadoma
    odpowiedź „za darmo”); bez niej osoba ponad cenę kosztowałaby 0 i zabierała
    ze sobą dopłatę kategorii.
  - „Za każdą noc albo dzień” (`extra_person_per_time_unit`) dotyczy też kwot
    kategorii i zostaje tak, jak zapisał właściciel; przy cenie liczonej raz
    jest odmową, a nie cichym wyłączeniem.
  - Oferta, która ma cenę gdziekolwiek w swoim zasięgu — własną, grupy albo
    jednostki, także wyłączoną — jest ofertą z ceną: rezerwacja, dla której
    żadna cena nie obowiązuje, dostaje `price_missing`, nigdy 0. „Za darmo”
    znaczy usunąć cenę.
  - Rabat za długość daje próg najdłuższy z osiągniętych, a dłuższy próg musi
    mieć większy procent (`discount_must_grow`).
  - Jednostkę dobiera się najpierw według pojemności dla liczonych osób, potem
    według obciążenia.
  - Rezerwacja wyceniana ponownie (przełożenie) jest sprawdzana względem tego,
    z czym ją zapisano: zostaje na niej kategoria i dopłata wyłączone później
    oraz liczba sztuk, na którą dopłata już nie pozwala. Pojemność jednostki
    sprawdza się nadal.
  - Skrót wyceny nie zależy od kolejności pozycji (a więc od nazw), a wycena
    odmawia sumowania kwot w walucie innej niż waluta firmy
    (`currency_mismatch`).
- **Cena dla klienta i sposób płatności (faza 3d).** Klient zawsze czyta cenę
  brutto: `POST /booking/public/{slug}/quote/` i rezerwacja w jego linku
  podają pozycje w jego języku z kwotą brutto, sumę, kaucję i sposób
  płatności — bez netto, VAT i identyfikatorów firmy. Oferta niesie
  `payment_policy` (§8) jako ustawienie oferty: dziś `none` albo `on_site`;
  przelew, przedpłata i całość z góry dojdą z zamówieniami (ADR-073), a do
  odpowiedzi listy prawnej wpłatę przed pobytem nazywamy „przedpłatą”. Sposób
  płatności jest częścią pokazanej ceny, więc wchodzi do skrótu i do migawki.
  Klient nigdy nie dostaje ceny, której nie widział: rezerwacja z formularza
  i przełożenie własnej wizyty wymagają skrótu pokazanej ceny, gdy oferta ma
  cenę, a przy przełożeniu — gdy nowa cena jest inna niż dotychczasowa;
  inaczej odpowiedzią jest 409 `quote_changed` z nową ceną do pokazania.
  Biuro przekłada i rezerwuje bez tego wymogu.
  Progi anulowania z §8 przychodzą z zamówieniami w fazie 4: bez wpłat nie ma
  czego zwracać.
- **Ceny promocyjne.** Faza 3 nie ogłasza obniżek: rabat za długość to warunek
  ceny, a sezon to cena. Zanim pojawią się promocje (kody, sklep), cennik musi
  mieć historię cen — najniższa cena z 30 dni przed obniżką (dyrektywa
  Omnibus); dziś zmiany `PriceRule` są tylko w audycie.

## Uzupełnienie 2026-10-03: panel cen (faza 3e)

Ustalenia przyjęte przy budowie panelu cennika (`apps/frontend/src/modules/shared/booking/prices/`).

- **Gdzie firma ustawia ceny.** Każda oferta ma swój „Cennik” na liście usług:
  ceny (podstawowa, sezonu, weekendu albo szczytu), dopłaty z kaucją i sposób
  płatności; każda pozycja zapisuje się osobno. Ceny ofert rezerwowanych na
  daty — także ceny grup i jednostek — są dodatkowo pod „Sezony i zasady”,
  obok zasad tych samych terminów. Kolumna „Cena” na liście usług pokazuje
  cenę podstawową tak, jak ją wpisano; ile kosztuje rezerwacja, mówi wyłącznie
  wycena.
- **Podgląd „Jaka cena obowiązuje dnia…” pyta wycenę o sam cennik.**
  `POST /booking/quote/` z `price_only` odpowiada także dla terminu, którego
  nie da się zarezerwować: jednostka może być zajęta, zasada sezonu złamana,
  a oferta jeszcze wyłączona (szkic). Bez tego firma nie sprawdziłaby ceny na
  przyszłe lato ani ceny oferty przed jej włączeniem. Odmowy cennika zostają
  (`price_missing`, `unit_capacity_exceeded`). Rezerwacja wycenia się bez tej
  flagi. Która cena wygrała, mówi `price_rule_id` każdej pozycji — panel
  niczego nie liczy, nie zna kolejności cen i nie opisuje jej słowami, więc
  zmiana tej kolejności (odpowiedź 75b: cena z datą przed ceną podstawową,
  zakres rozstrzyga między cenami tego samego rodzaju — osobny przyrost) nie
  wymaga zmiany panelu.
- **„Za osobę za noc” to osobny wybór w panelu**, zapisany jako cena za
  jednostkę czasu z kwotą 0, zerem osób w cenie i dopłatą za każdą osobę za
  każdą jednostkę czasu. Wycena takiej ceny nie ma pozycji 0 zł ani „dodatkowej
  osoby”: osoby są ceną i idą pod nazwą oferty (`kind` = `price`), kategoria
  zachowuje swoją kwotę i nazwę. Gdy nikt nie płaci, pozycja 0 zł zostaje —
  oferta ma cenę, tyle że zerową.
- **Wycena w panelu.** „Nowa wizyta”, „Nowy pobyt” i zmiana dat pobytu
  pokazują wycenę serwera (pozycje, netto, VAT, brutto, kaucja obok sumy,
  sposób płatności) i wysyłają jej skrót; 409 `quote_changed` pokazuje „Cena
  się zmieniła” z nowymi kwotami, a kolejny zapis idzie już po nich. O osoby
  formularz wizyty pyta tylko wtedy, gdy cennik oferty od nich zależy (cena za
  osobę, osoby w cenie, kategorie, dopłata za osobę). Ceny przekreślonej nie
  ma nigdzie: rabat za długość to pozycja wyceny.
- **Cena na siatce obłożenia.** `GET /booking/occupancy/` podaje przy
  rezerwacji `gross_minor` i `currency` z zamrożonej wyceny — bez dodatkowego
  zapytania; blokada, rezerwacja bez ceny i cudza rezerwacja (UX-023) ich nie
  mają.

## Uzupełnienie 2026-10-03: cena na wybrane dni wygrywa z ceną podstawową (decyzja 75b)

Zmienia punkt „Która cena obowiązuje” uzupełnienia o cenniku i wycenie.

- **Decyzja właściciela 75b** (podjęta 03.10 przez koordynatora w imieniu
  właściciela): cena na wybrane dni — sezonu (z datami), dni tygodnia albo pory
  dnia — wygrywa z ceną podstawową niezależnie od tego, czy dotyczy jednostki,
  grupy czy całej oferty. „Domek 350, lipiec 500 dla wszystkich” daje w lipcu
  500, także w domku, który ma własną cenę podstawową.
- **Zasięg rozstrzyga tylko między cenami tego samego rodzaju.** Rodzaje są
  dwa: cena podstawowa (bez dat, dni tygodnia i godzin) oraz cena na wybrane
  dni. W obrębie rodzaju: jednostka przed grupą przed ofertą, potem sezon przed
  ceną bez dat, potem węższa przed szerszą (dni tygodnia i godziny przed samymi
  dniami albo samymi godzinami), potem późniejszy początek, potem później
  dodana. Domek z własną ceną lipcową zachowuje ją wobec lipcowej ceny oferty.
- **Reguły rezerwacji (§5) zostają bez zmian**: `BookingRule` zawsze ma daty,
  więc między regułami rozstrzyga sam zasięg.
- — Poprzednia kolejność (zasięg przed datami) kazała firmie powtarzać cenę
  sezonu w każdej jednostce, która ma własną cenę podstawową; zapomniany wpis
  dawał w sezonie cenę spoza sezonu. Odrzucone: trzy rodzaje (sezon, dni
  tygodnia, pora dnia) z zasięgiem na końcu — własna cena weekendowa domku
  przegrywałaby wtedy z ceną sezonu oferty, czego decyzja nie mówi.

## Uzupełnienie 2026-10-03: presety gotowe bez formularza publicznego (decyzje 67a i 68a)

Doprecyzowuje §10 („`ready` — rdzeń tej wersji przyjmuje takie rezerwacje”).
Decyzje podjął 03.10 koordynator w imieniu właściciela.

- **67a: gotowość nie czeka na formularz publiczny.** „Nocleg”, „Wypożyczalnia”
  i „Pobyt z opieką” są `ready` jako wersja 2: firma ustawia ofertę i ceny, a
  rezerwacje wpisuje zespół w panelu. Preset mówi to wprost: opis kończy się
  słowami „rezerwacja przez stronę — wkrótce”, a pole `onlineBooking` (`ready` |
  `soon`; API i polecenie asystenta: `online_booking`) pozwala to odczytać bez
  czytania opisu. Oferta z takiego presetu powstaje jako niewidoczna w
  rezerwacji online (`Service.online = false`).
- **Wersja `ready` niesie tylko to, co silnik umie dziś.** Okres na noce albo
  doby, jedna jednostka na rezerwację (także dobrana z grupy), bez osoby;
  cennik, dopłaty i kaucja z fazy 3; płatność `on_site`. Do kolejnych wersji
  zostają: zadatek, przelew i progi zwrotu (faza 4, zamówienia), pola własne i
  formularz publiczny (faza 5), kalendarze portali (faza 6), N sztuk w jednej
  rezerwacji. Wersja 1 zostaje w manifeście bez zmian: niesie wartości z planu
  (13a, 28a), do których wróci wersja z fazy 4. `requiredInputs` wersja 2 nie
  niesie — żadne polecenie nie zapisze jeszcze dat sezonów ani zdjęć, a pytanie
  bez miejsca na odpowiedź zatrzymywałoby założenie oferty.
- **„Wynajem przestrzeni na godziny” zostaje `soon`.** Decyzja 67a go wymienia,
  ale silnik okresu z fazy 2 liczy noce i doby, a `hour` odrzuca
  (`range_unit_not_ready`): rezerwacja na godziny potrzebuje godziny początku
  i końca w API pobytów, siatki startów i godzin otwarcia jednostki (pytanie
  otwarte w „Konsekwencjach”). Preset `ready`, którego zastosowanie kończy się
  odmową, byłby nieprawdą wobec firmy; staje się gotowy z tą częścią silnika.
- **68a: „Usługa u klienta” w wersji okrojonej (wersja 2).** Termin (`slot`) z
  osobą, wykonywany pod adresem klienta: adres zespół wpisuje w wizycie jako
  jej miejsce (ADR-066), a dojazd to przerwa przed wizytą — nowe, opcjonalne
  pole presetu `buffers` (domyślnie 30 minut przed), które zastosowanie
  kopiuje do oferty i które firma zmienia w ofercie. Okno przyjazdu i obszar
  dojazdu zostają w fazie 13. Osoba ma godziny pracy w miejscu, więc także
  taka oferta potrzebuje miejsca firmy — bazy, z której zespół wyjeżdża;
  konfigurator asystenta pyta o nią osobnym pytaniem (`offer_needs_base`).
- **Zastosowanie kopiuje więcej niż słowa.** Poza słownictwem oferta dostaje z
  presetu jednostkę okresu z godzinami początku i końca, przerwy, płatność na
  miejscu (polityki spoza tego, co oferta umie, są pomijane) i widoczność w
  rezerwacji online. Jednostek, cen, dopłat i kategorii uczestników nadal nie
  zakłada: preset je tylko podpowiada.

## Uzupełnienie 2026-10-04: faza 5 w plastrach

Faza 5 planu („Strona i formularz publiczny okresu”) to publiczna strona pobytów
i wynajmów: formularz, treść jednostek, bloki strony, szablon „Noclegi”, presety
przy zakładaniu firmy, katalog i języki. Jest za duża na jedno scalenie, więc
idzie plastrami jak faza 4 (ADR-073, „Uzupełnienie 2026-10-03”): każdy scalany
osobno po własnej pełnej bramce i każdy zostawia `main` działający bez
następnych. Kolejność wynika z jednego celu: najpierw gość rezerwuje pobyt od
początku do końca (5a, 5b), dopiero potem strona, która go do formularza
prowadzi.

| Plaster | Zakres | Migracje | Ekran |
| --- | --- | --- | --- |
| **5a** | Publiczne API pobytu: w katalogu formularza osobna lista `stays` (oferty okresu oferowane online, z tym, co gość wybiera, kategoriami uczestników i dopłatami), kalendarz przyjazdów i wyjazdów, plan pobytu z wyceną, rezerwacja ze skrótem wyceny i zgodami — z zamówieniem, przedpłatą przelewem i „na prośbę” tak jak przy terminie; link klienta dla pobytu: odczyt z jednostką i przeniesienie datami | — | brak (API); rezerwacja z formularza w „Obłożeniu” |
| **5b** | Formularz publiczny pobytu na stronie rezerwacji firmy (`/<język>/book/<slug>`): oferta, co rezerwuję, daty z kalendarza, goście, dopłaty, cena z kaucją i warunkami zwrotu, dane, zgody; potwierdzenie z danymi do przelewu albo terminem odpowiedzi; link klienta pokazuje pobyt i przenosi go datami; presety „Nocleg”, „Wypożyczalnia” i „Pobyt z opieką” w wersji 3 bez „wkrótce” | — | formularz publiczny, link klienta, wzorce ofert |
| **zgody** | Krok zgód obu formularzy (ADR-073, „Uzupełnienie 2026-10-04: krok zgód formularzy publicznych”): język bez tekstu regulaminu nie jest rezerwowany online — karta z językami, które go mają, i ostrzeżenia w panelu; nieobowiązkowa zgoda marketingowa z przełącznikiem firmy; zbyt częste pytanie o cenę mówi „spróbuj za chwilę” | — | formularz publiczny; Ustawienia › Dokumenty dla klientów, Języki, Rezerwacje |
| **5c** | Jednostka jako treść: zdjęcia, wyposażenie, flaga „publiczna”, `public_slug`, miasto ze słownika i współrzędne (tylko na serwerze); „od X zł/noc” z funkcji wyceny; pola w panelu i w katalogu formularza | booking | Ustawienia › Usługi i grafik (jednostka) |
| **5d** | Bloki Site Studio: lista jednostek, widget rezerwacji okresu (daty i goście prowadzą do formularza), kalendarz dostępności; formularz przyjmuje ofertę, jednostkę, daty i gości z adresu | — (kontrakt bloków) | edytor strony, strona firmy |
| **5e** | Systemowa strona jednostki na każdej opublikowanej stronie firmy (galeria, wyposażenie, kalendarz, rezerwacja) i blok mapy | według plastra | strona firmy |
| **5f** | Szablon „Noclegi” (start, domki, okolica, galeria, cennik, regulamin, kontakt z mapą) według listy „Szablony nastawione na konwersję”; strona prawna witryny z dokumentów firmy (ADR-073, „Otwarte technicznie”) | — | biblioteka szablonów, strona firmy |
| **5g** | Presety przy ręcznym zakładaniu firmy: gotowe do zastosowania, „wkrótce” z zapisem i pytaniem „Czego Ci brakuje?”; preset podpowiada kategorię katalogu i szablon strony. Ścieżka ręczna jest pierwsza — asystent (faza A6 jego planu) korzysta z niej, nie odwrotnie | według plastra | zakładanie firmy, Ustawienia |
| **5h** | Katalog: kategoria z presetu, odznaka i filtr „rezerwacja online” (rejestr profiles, §11), strona jednostki pod `/katalog/<miasto>/<firma>/<jednostka>`, podpisany token pochodzenia i kanał `catalog` na rezerwacji | booking (kanał na rezerwacji) | katalog |
| **5i** | Języki profilu (pilot PL, EN, DE): wszystko, co widzi gość — formularz, kalendarz, komunikaty odmów, e-maile — w językach firmy; orientacyjne przeliczenie walut na stronie w obcym języku (decyzja 16) | — | formularz, strona firmy |
| **5j** | Pola własne formularza (`booking.field`) z presetu i oferty | booking | oferta, formularz |

Rozstrzygnięcia tego uzupełnienia (decyzje techniczne, z powodem):

- **Pobyty w katalogu formularza to osobna lista.** `GET /booking/public/<slug>/`
  zostawia w `services` tylko terminy, a oferty okresu oddaje w `stays`. Zmiana
  jest addytywna: formularz sprzed 5b (także w produkcie, który jeszcze nie
  wziął rdzenia z 5b) nie pokaże oferty, której nie umie zarezerwować, a 5a
  można scalić bez 5b.
- **Gość wybiera to, co firma wystawiła, nie sztukę z puli.** Oferta okresu
  wymienia grupy i jednostki wolnostojące; w formularzu grupa to jeden wybór
  („Domek 6-os.”), a jednostkę z grupy dobiera serwer, najmniej obciążoną z
  tych, które mieszczą gości (§3). Jednostka przypięta do oferty wprost jest
  wyborem sama. API przyjmuje także brak wyboru (dowolna jednostka oferty), jak
  panel.
- **Jak daleko naprzód, mówi sezon, nie ustawienie terminów.** Ustawienie firmy
  `booking.online.horizon_days` (1–62 dni, domyślnie 15) to okno wyszukiwania
  wizyt i zostaje przy terminach — pobyt na lipiec rezerwuje się w styczniu.
  Zasięg pobytu ogranicza „okno naprzód” reguły sezonu (`rule_window`, §5), a
  bez reguły granica platformy `BOOKING_PERIOD_HORIZON_DAYS`; przyjazd dalej niż
  ona to 409 `beyond_booking_horizon`. Jedno publiczne zapytanie o dni
  przyjazdu obejmuje najwyżej 92 dni (stała ochronna modułu): kalendarz
  formularza pyta miesiącami, a szerokie okno to zarazem wolne zapytanie i
  powierzchnia do zbierania danych (ADR-030).
- **Pauza, wymagany kontakt i miejsce „nie online” działają jak przy
  terminach.** Wstrzymane rezerwacje online odmawiają także pobytu
  (`booking_paused`), formularz wymaga kontaktu z `booking.online.contact`, a
  jednostka w miejscu wyłączonym z rezerwacji online nie jest oferowana.
- **Dostępność i cena to jedna odpowiedź.** `POST …/stays/quote/` planuje pobyt
  tak jak rezerwacja (te same odmowy 400 i 409) i oddaje jego chwile, długość i
  wycenę w postaci dla klienta (`customer_quote`). Formularz nie składa ceny
  sam i nie pokazuje ceny terminu, którego nie da się zarezerwować.
- **Publiczny zapis pobytu nie przejdzie bez skrótu wyceny.** Rezerwacja i
  przeniesienie pobytu z kontekstu formularza, gdy wycena ma cokolwiek do
  pokazania, wymagają `quote_digest`: brak albo inny skrót to 409
  `quote_changed` z wyceną w `detail.quote` i nic się nie zapisuje. Przy
  terminach skrót zostaje opcjonalny dla zespołu (§7); wizyta z ceną
  rezerwowana z formularza wymaga go tak samo — od fazy 3d w kodzie, od
  kroku zgód (ADR-073, „Uzupełnienie 2026-10-04: krok zgód formularzy
  publicznych”) także w kontrakcie.
- **Pobyt przenosi się z linku datami.** Link klienta dostaje
  `…/self-service/<token>/stay/` (z podglądem): te same warunki co
  przełożenie wizyty (tryb samoobsługi, odcięcie, tylko `confirmed`), ta sama
  funkcja `move_stay` z wyceną na nowo i zamówieniem. Odpowiedź linku mówi,
  czy to pobyt (`time_model`, `range_unit`) i w jakiej jednostce (`unit_name`).
- **Presety przestają mówić „wkrótce” w 5b, nie w 5a.** Dopisek znika, gdy
  istnieje formularz, a nie samo API: wersja 3 presetów „Nocleg”,
  „Wypożyczalnia” i „Pobyt z opieką” ma `onlineBooking` `ready` i opis bez
  dopisku; poza tym niesie to samo co wersja 2. Wpłaty z góry nadal nie wybiera
  za firmę (ADR-073, „Preset nie wybiera wpłaty z góry za firmę”).
- **Token pochodzenia zostaje przy 5h.** Do pierwszego odnośnika z katalogu do
  formularza kanał wynika z tego, co serwer wie sam (`company_site`, `office`;
  ADR-073, „Rozstrzygnięcia plastra 4e”).
- **Bloki czytają dane na żywo przez publiczne API rezerwacji** (5d–5e):
  publikacja jest migawką, a wolne terminy i ceny nią być nie mogą. Blok niesie
  tylko wybór (która oferta, która grupa, układ); resztę rozstrzyga plaster.

### Rozstrzygnięcia plastra 5a (publiczne API pobytu)

- **Adresy.** `GET /booking/public/<slug>/` oddaje `stays`,
  `participant_categories` i `online.period_last_day`; obok niego
  `GET …/stays/starts/`, `GET …/stays/ends/`, `POST …/stays/quote/` i
  `POST …/stays/` (z `Idempotency-Key`); na linku klienta
  `POST /booking/self-service/<token>/stay/` i `…/stay/preview/`. Widoki są w
  `public_stay_views.py`, a to, co gość wybiera — w `public.public_stays`
  (stała liczba zapytań, przypięta testem).
- **Jedna funkcja dla panelu i formularza.** Formularz woła te same
  `stay_starts`, `stay_ends`, `book_stay` i `move_stay` co panel. O tym, kto
  pyta, rozstrzyga kontekst: w zakresie formularza (`booking.public.read`,
  `booking.public.manage`) `periods._offer` znajduje tylko ofertę oferowaną
  online i jednostki w miejscach oferowanych online, reszta jest jak nieistniejąca
  (404). Podgląd z formularza potrzebuje tylko zakresu odczytu.
- **Przenoszona rezerwacja zachowuje to, w czym ją zarezerwowano.** Pobyt
  przenoszony z linku klienta znajduje swoją ofertę i jednostkę także wtedy, gdy
  firma zdjęła ofertę z formularza albo wyłączyła miejsce z rezerwacji online —
  jak wizyta przekładana z linku. O tym, czy link może przenosić, mówią warunki
  samoobsługi zapisane w rezerwacji (B4), a pauza formularza przenoszenia nie
  zatrzymuje.
- **Plan dla gościa nie nazywa jednostki.** `…/stays/quote/` oddaje chwile,
  długość i wycenę, bez jednostki: z grupy rezerwacja bierze tę, która będzie
  wolna w chwili zapisu. Jednostkę nazywa dopiero rezerwacja (`unit_name` w
  odpowiedzi rezerwacji i linku, w języku klienta, gdy firma ją przetłumaczyła);
  przy wizycie `unit_name` jest puste — sala albo fotel to sprawa firmy.
- **Wymagany skrót to `assert_shown(…, required=True)`.** Jedno miejsce w
  `quote.py`: skrót jest wymagany, gdy `customer_quote` ma cokolwiek do
  pokazania (pozycje albo kaucję). Oferta bez cennika rezerwuje się bez skrótu.
- **Kategorie uczestników są wspólne dla firmy**, więc katalog oddaje je raz,
  i tylko gdy formularz ma pobyty; przy terminach formularz o uczestników nie
  pyta (stan sprzed fazy 5).
- **Poza 5a:** ekran (5b); lista dni dla przeniesienia z linku (klient podaje
  daty, a podgląd mówi, czy pasują — jak „Zmień daty” w panelu); okno naprzód
  dla oferty bez sezonu (dziś tylko reguła sezonu i granica platformy; własne
  okno oferty przyszło z 5c); wymagany skrót na publicznej ścieżce terminów
  (kontrakt mówi o nim od kroku zgód).

### Rozstrzygnięcia plastra 5b (formularz publiczny pobytu)

- **Jedno pole „Usługa” dla terminów i pobytów.** Strona rezerwacji firmy
  (`/<język>/book/<slug>`) wymienia w „Usługa” wizyty i oferty okresu razem;
  wybór oferty okresu otwiera jej formularz (`public-stay-flow.tsx`), wybór
  wizyty — dotychczasowy. Firma, która ma tylko oferty okresu, zaczyna od
  formularza pobytu. Wspólne części obu formularzy — dane klienta, dokumenty
  do akceptacji, dopłaty, karta „zarezerwowano” — są w
  `public-booking-parts.tsx`; formularz wizyty zachował swoje pola i
  identyfikatory.
- **Daty z list, nie z wpisywania.** „Przyjazd” wymienia dni, w które pobyt
  może się zacząć (okno 92 dni, „Późniejsze terminy” przesuwa je dalej),
  „Wyjazd” — dni, w które pobyt z tego przyjazdu może się skończyć, każdy z
  liczbą nocy albo dni. Formularz nie pokaże terminu, którego serwer nie
  przyjmie, i nie liczy niczego sam. Kalendarz w siatce przychodzi z blokiem
  kalendarza dostępności (5d) — te same odczyty, inny widok.
- **Cena i dostępność są odpowiedzią serwera na to, co wybrane.** Po każdej
  zmianie gości, dat albo dopłat formularz pyta o plan z wyceną
  (`…/stays/quote/`) i pokazuje go; do czasu odpowiedzi i po odmowie przycisk
  rezerwacji jest nieaktywny. Rezerwacja wysyła skrót wyceny, którą gość
  widzi; 409 `quote_changed` podmienia cenę i prosi o potwierdzenie jeszcze raz.
- **Odmowa słowami gościa.** Kody odmów, które gość może naprawić wyborem
  (`unit_capacity_exceeded`, `slot_unavailable`, `rule_min_length`,
  `rule_max_length`, `rule_notice`, `price_missing`,
  `beyond_booking_horizon`), mają własne zdania w językach gościa (pl, en, de);
  pozostałe mówią „tego terminu nie można zarezerwować”. Komunikaty serwera
  po polsku nie trafiają na stronę w innym języku. Pełne tłumaczenie odmów to 5i.
- **Goście to „Osoby” i kategorie firmy.** Osoby bez kategorii liczą się jak
  w wycenie (osoba standardowa); kategorie firmy („Dziecko”, „Pies”) mają
  własne pola. Ile osób mieści jednostka, mówi serwer w odmowie, a formularz
  pokazuje pojemność przy wyborze.
- **Link klienta: sprawdź, potem przenieś.** Klient podaje nowe dni, podgląd
  (`…/stay/preview/`) pokazuje nowy termin i cenę, i dopiero drugi przycisk
  przenosi pobyt ze skrótem tej ceny. Rezerwacja oczekująca (na wpłatę albo na
  odpowiedź) nie ma przenoszenia — tylko rezygnację, jak wizyta.
- **Presety w wersji 3.** „Nocleg”, „Wypożyczalnia” i „Pobyt z opieką” mają
  `onlineBooking` `ready` i opis bez dopisku; oferta z wersji 3 powstaje z
  włączonym „W rezerwacji online na stronie” (nadal jako wyłączona wersja
  robocza). Oferty założone z wersji 2 zostają ukryte przed formularzem, dopóki
  firma nie włączy ich sama. Test kontraktu wie, co formularz przyjmuje
  (`ONLINE`: termin w miejscu firmy, okres w miejscu firmy albo z odbiorem i
  zwrotem), i pilnuje, żeby preset rezerwowany przez stronę nie mówił „wkrótce”.
- **Przełącznik oferty zaczyna znaczyć to, co mówi.** Oferta okresu założona
  ręcznie miała „W rezerwacji online na stronie” włączone domyślnie, choć
  formularz jej nie pokazywał. Od 5b taka oferta — aktywna, z jednostką —
  jest na formularzu. Firma, która tego nie chce, wyłącza przełącznik; nota
  wydania mówi o tym wprost.
- **Katalog formularza w języku strony.** Formularz pyta katalog z `locale`
  strony (TL12b), więc nazwy ofert, jednostek, kategorii i dopłat — także usług
  terminowych — przychodzą w języku gościa tam, gdzie firma je przetłumaczyła.
- **Poza 5b:** kalendarz w siatce i daty w adresie formularza (5d); słowa
  oferty z presetu („Goście”, „Domek”) w formularzu i tłumaczenie wszystkich
  odmów (5i); wzorzec „Nocleg” z przedpłatą i progami zwrotu to osobna, kolejna
  wersja presetu (praca równoległa po fazie 4).

### Rozstrzygnięcia plastra 5c (jednostka jako treść)

- **Treść jest na jednostce, a gość dostaje ją tylko od jednostki
  „publicznej”.** `Resource` dostaje `public`, `public_slug`, `amenities`,
  `city_slug`, `latitude`, `longitude` i `photos` (migracja booking 0033).
  Jednostka niepubliczna zostaje rezerwowalna jak dotąd — z nazwą, opisem i
  pojemnością — ale bez zdjęć, wyposażenia i miejscowości. Flaga jest osobna
  od „W rezerwacji online” oferty: pierwsza mówi, co pokazujemy, druga — co
  można zarezerwować. Od 5e ta sama flaga decyduje o własnej stronie jednostki.
- **`public_slug` powstaje sam i jest jeden w firmie.** Jednostka publiczna
  bez adresu dostaje go z nazwy (jak oferta i miejsce); firma może go
  zmienić; zajęty to 400 `slug_taken`. Adresu nie używa jeszcze żadna strona
  (5e, 5h) — zapisujemy go teraz, żeby strona jednostki nie zaczynała od
  migracji danych.
- **Wyposażenie to zamknięta lista, nie tekst firmy.** `UNIT_AMENITIES`
  (`booking/unit_content.py`): klucz i słowa pl, en, de; gość dostaje słowa w
  swoim języku, panel i asystent czytają listę z `unit_options` w
  `GET /booking/setup/`. Powód: po wyposażeniu się filtruje i porównuje (katalog,
  faza 16), a własny wpis firmy to kolejny tekst do tłumaczenia na każdy język.
  To, czego lista nie ma, firma pisze w opisie jednostki (tłumaczonym jak
  dotąd). Plan mówił „lista z presetu + własne” — własne wpisy i lista per
  preset zostają na później; lista rośnie jak słownik miast.
- **Miejscowość ze słownika katalogu, współrzędne tylko dla firmy.**
  `city_slug` to wpis słownika `profiles.api.cities()` (400 `city_unknown`);
  publiczna odpowiedź oddaje `town` (`slug`, `name`). Współrzędne (obie albo
  żadna, zakresy w bazie) wracają tylko w odczycie konfiguracji dla zespołu —
  żadna publiczna odpowiedź ich nie zawiera (plan, „Wolne terminy w
  katalogu”).
- **Zdjęcia to uporządkowana lista na jednostce — bez wersji zestawu i bez
  referencji mediów** (zmienia zdanie §3 „Zdjęcia wskazuje niezmienna wersja
  ich zestawu”). Wersja zestawu istniała po to, żeby dało się zapisać
  referencje mediów, które są tylko do dopisywania. Referencje mają jednego
  czytelnika, który tu ma znaczenie — sprzątanie usuniętych mediów — a ono dla
  danych na żywo i tak pyta rejestr publicznych źródeł (ADR-074 pkt 7). Wiersz
  wersji na każdą zmianę kolejności, nowy rodzaj właściciela i migracja
  `shared.media` nie dawałyby więc nic, co ktoś czyta. Nowe zdjęcie musi być w
  bibliotece mediów, przeskanowane i nieusunięte (400 `photo_unavailable`),
  najwyżej 12 na jednostkę (`photos_too_many`).
- **Rejestr publicznych źródeł powstaje w rdzeniu, w zakresie, którego 5c
  potrzebuje.** `core.organizations.public_sources` (`PublicSource`,
  `register_public_source`, `shown_media_ids`): źródło `booking.units` mówi,
  które media pokazują jednostki firmy — wszystkie, także niepubliczne, bo
  biblioteka nie zabiera zdjęcia jednostce, którą firma dopiero przygotowuje —
  a `shared.media` nie usuwa obiektów usuniętego medium, dopóki jednostka je
  pokazuje (jak przy publikacji strony). Adresy, fakty do JSON-LD i media
  serwowane przez stronę firmy dojdą do tego samego rekordu z pierwszym
  czytelnikiem (5d–5e, sklep).
- **Zdjęcie ma publiczny adres przy formularzu.**
  `GET /api/v1/booking/public/<slug>/photos/<id>/<kopia>/` (`thumbnail`,
  `preview`) oddaje jedną z naszych kopii WebP — nigdy oryginał — tylko dla
  zdjęcia jednostki publicznej i włączonej tej firmy; każde inne zdjęcie to 404
  (cudza firma, jednostka niepubliczna albo wyłączona, plik spoza jednostek,
  nieznana kopia), a formularz, którego nie ma albo którego plan firmy nie
  obejmuje, odpowiada jak pozostałe adresy formularza (404, 403), bez treści.
  Formularz żyje na hoście platformy, gdzie żadna opublikowana strona nie
  ręczy za zdjęcie, więc ręczy za nie booking; bajty czyta
  `media.api.read_public_variant`. Odpowiedź jest niezmienna (nowe zdjęcie to
  nowy identyfikator), z długim `Cache-Control`. To zwykły widok Django, poza
  kontraktem OpenAPI — adres do `<img>`, nie operacja — i bez limitu zapytań
  formularza (30 na minutę), bo galeria kilku jednostek zużyłaby go sama.
- **„od X zł/noc” liczy funkcja wyceny.** `quote.from_prices`: dla oferty i
  jednostki najniższa cena jednej nocy albo dnia dla jednej osoby w ciągu
  najbliższych 365 dni — własna cena pobytu tak, jak ją liczy `quote_stay`
  (brutto, bez dopłat), z jednego odczytu cennika. Grupa mówi najniższą cenę
  swoich jednostek. Cena liczona raz za pobyt mówi „od X zł” bez „za noc”
  (`per`: `night`, `day` albo `stay`). To zapowiedź, nie wycena: nie patrzy na
  zajętość ani reguły sezonu, a cenę terminu mówi dopiero `…/stays/quote/`.
- **Wybór w formularzu niesie treść.** `stays[].units[]` i `stays[].groups[]`
  w `GET /booking/public/<slug>/` dostają `photos` (`id`, `thumbnail_url`,
  `preview_url`), `amenities`, `town` i `from_price`, a jednostka także
  `public_slug`; grupa — pula identycznych jednostek — pokazuje treść swojej
  pierwszej jednostki publicznej (po nazwie). Formularz rysuje przy wyborze
  miniaturę, miejscowość, „od X zł/noc” i wyposażenie, a pod wyborem zdjęcia,
  które otwierają się w dużej kopii. Liczba zapytań katalogu zostaje stała.
- **Pola treści w panelu widzi firma z pobytami.** Okno jednostki pokazuje
  sekcję „Co widzi gość” tylko wtedy, gdy firma ma ofertę okresu: gabinet albo
  stanowisko wizyty nie ma strony ani gości. Dozwolone wyposażenie i limit
  zdjęć panel czyta z `unit_options` w `GET /booking/setup/`, miejscowości ze
  słownika katalogu. Zdjęcie wgrywa się w oknie jednostki (kadr 4:3) do
  biblioteki mediów; zapis przed końcem skanowania to 400
  `photo_unavailable` ze zdaniem „spróbuj za chwilę”.
- **Oferta okresu ma własne okno naprzód.** `Service.booking_window_days`
  (ustawienie `booking.offer.booking_window_days`, puste — granica platformy):
  obowiązuje tam, gdzie reguła sezonu nie mówi własnego okna, tak jak
  wyprzedzenie oferty ustępuje wyprzedzeniu sezonu. Przyjazd dalej to ta sama
  odmowa `rule_window`.
- **Poza 5c:** strona jednostki i jej adres w użyciu (5e, 5h); zdjęcia
  jednostek serwowane przez stronę firmy i w blokach (5d); własne wpisy
  wyposażenia i lista per preset; polecenie asystenta dla treści jednostki
  (zapis idzie tym samym `save_resource`, więc polecenie to deklaracja, nie
  nowa logika); ponowne sprzątanie obiektu, gdy jednostka przestaje pokazywać
  usunięte zdjęcie (dziś zostaje, jak obiekt zdjęty z publikacji).

### Rozstrzygnięcia plastra 5d (bloki strony firmy)

- **Trzy bloki, każdy niesie tylko wybór.** `core.stay_units` (lista
  jednostek), `core.stay_search` (widget: termin i liczba osób) i
  `core.stay_calendar` (kalendarz wolnych terminów) mają w danych nagłówek,
  tekst, napis przycisku i `offer` — identyfikator oferty okresu albo nic
  („wszystkie oferty z formularza”); lista ma jeszcze `layout` (`cards`,
  `rows`). Jednostek, cen ani dni w danych bloku nie ma: publikacja jest
  migawką, a one nią być nie mogą. `offer` ma wzorzec w schemacie, więc nie
  jest tekstem do tłumaczenia; wersja językowa strony tłumaczy nagłówek, tekst
  i napis. Bloki są w bibliotece w kategorii „rezerwacja” (ADR-031 zamroził
  dziewięć sekcji; te trzy dochodzą tą decyzją, jak wcześniej cytat, produkt
  i galeria) i tylko tam, gdzie produkt ma publiczny formularz rezerwacji.
- **Co blok pokazuje, mówi serwer przy każdym odczycie strony.** Odpowiedź
  `GET /api/v1/public/site/` ma `live`: po pozycji bloku to, co pokazuje on
  teraz — adres formularza (`form_url`, `slug`), strefę, ostatni dzień
  przyjazdu, pauzę i oferty z tym, co gość wybiera (grupa albo jednostka), a
  dla listy także treść: zdjęcia po identyfikatorze, wyposażenie,
  miejscowość, „od X zł/noc”. Witryna pyta przez rejestr publicznych źródeł
  w rdzeniu (`PublicSource.site_blocks`, `live_site_blocks`), bo `shared.sites`
  nie zna rezerwacji; odpowiada `booking/site_blocks.py` tym samym odczytem
  co formularz (`public_stays`) w jego zakresie usługowym — jedna reguła tego,
  co jest online i co firma pokazuje. Strona bez takich bloków nie pyta
  nikogo.
- **Blok bez odpowiedzi nie jest sekcją.** Firma bez formularza albo bez planu
  z rezerwacjami, produkt bez publicznych rezerwacji, oferta zdjęta z
  formularza albo usunięta, brak ofert okresu — `live` nie ma wpisu i
  opublikowana strona takiego bloku nie rysuje wcale (pusty nagłówek „Nasze
  domki” byłby gorszy niż nic). Edytor rysuje w tym miejscu zarys i zdanie o
  tym, co pojawi się po publikacji; pole „Oferta” mówi, gdy firma nie ma
  żadnej oferty okresu.
- **Słowa słownika idą za językiem strony, tekst firmy za językami firmy.**
  Wyposażenie i to, co blok mówi sam („od”, „Zarezerwuj”, kalendarz), jest w
  języku strony (`siteUiTexts`, pięć języków platformy; inny czyta angielski).
  Nazwy i opisy są w języku strony, gdy firma je w nim napisała, inaczej w jej
  własnym. **Formularz jest linkowany w języku, w którym istnieje**
  (`clamp_content_locale`): język strony, gdy firma go ma, inaczej pierwszy
  język firmy, a dla firmy, której języków wdrożenie nie obsługuje — pierwszy
  język produktu. Strona formularza takiej firmy odpowiada w tym języku (dotąd
  odpowiadała 404 w każdym, choć API przyjmowało rezerwację).
- **Zdjęcia jednostek serwuje host strony, w naszych kopiach.**
  `PublicSource.served_media` (dla jednostek: `unit_content.public_photo_ids`
  — publiczne i włączone) dopuszcza w `sites.public_media` kopie `thumbnail`
  i `preview` zdjęcia, którego żadna publikacja nie wymienia; oryginał zostaje
  niedostępny, tak jak przy formularzu. Blok rysuje `/media/<id>/preview` z
  `srcset` obu kopii.
- **Wolne dni blok czyta z publicznego API rezerwacji pod hostem strony.**
  Widget i kalendarz pytają `…/booking/public/<slug>/stays/starts/` i
  `…/ends/` z przeglądarki, miesiąc po miesiącu. Bramka hostów
  (`http/hosts.py`) przepuszcza pod hostem spoza listy tylko `GET` i `HEAD`
  na adresach `/api/v1/booking/public/` — odczyty tego, co formularz mówi
  każdemu — i tylko pod hostem opublikowanej strony tej firmy, którą nazywa
  slug formularza („Zawężenie bramki hostów” niżej; do 2026-10-04 host o
  niczym nie decydował). Zapisy (wycena, rezerwacja) i wszystko z panelu
  zostają pod hostem platformy: rezerwuje się w formularzu.
- **Formularz przyjmuje wybór z adresu.** `/book/<slug>?offer=…&group=…|unit=…
  &from=…&to=…&people=…` otwiera formularz na ofercie, wyborze, dniach i
  liczbie osób z odnośnika (`stayFormHref` w `@saas-core/site-blocks`). To
  tylko podpowiedź: oferty spoza formularza, dnia z przeszłości albo liczby,
  która nie jest liczbą osób, formularz nie przyjmuje, a plan i cenę i tak
  mówi serwer dla tego, co zostało wybrane.
- **Daty wybiera się w siatce miesiąca, w formularzu i w blokach.**
  `StayDatePicker` zastępuje listy wyboru z 5b: pyta o dni przyjazdu
  miesiącami (nigdy ponad 92 dni okna publicznego), po wyborze przyjazdu o
  dni wyjazdu, zaznacza pobyt i mówi jego długość; słowa dostaje od tego, kto
  go pokazuje (komunikaty formularza albo teksty strony). Tydzień zaczyna się
  w poniedziałek, jak w pozostałych kalendarzach produktu.
- **Pozycja bloku to pozycja z publikacji.** Renderer pomija blok, którego
  czyszczenie z pozostałości szablonu nie zostawia poprawnym; bloki za nim
  zachowują pozycję, pod którą zna je serwer — po niej dostają `live`, a
  formularz kontaktowy wysyła wiadomość (dotąd pominięty blok przesuwał
  pozycję formularza za nim).
- **Poza 5d:** strona jednostki i `public_slug` w adresie (5e); sekcje
  biblioteki i szablon „Noclegi” z tymi blokami (5f) — dziś blok dodaje się w
  Bibliotece z „Dodaj pustą sekcję”; podgląd prawdziwych jednostek w edytorze; kategorie
  uczestników w widgecie (formularz pyta o nie sam); oznaczenie zdjęcia
  jednostki wygenerowanego przez AI (okno jednostki przyjmuje tylko wgrane
  pliki, API — każdy plik z biblioteki); ukrycie bloków w bibliotece firmy,
  która nie ma ofert okresu.

### Rozstrzygnięcia plastra 5e (strona jednostki)

- **Plaster 5e to strona jednostki i jej karta; blok mapy czeka na decyzję.**
  Mapa na stronie firmy to osadzony zasób obcego dostawcy (kafelki, klucz,
  adres IP gościa u dostawcy) — wybór dostawcy i zgoda gościa to decyzja
  właściciela, nie plastra. Reszta 5e nie zależy od mapy.
- **Karta jednostki to czwarty blok pobytów.** `core.stay_unit` v1 niesie
  `unit` — identyfikator jednostki, którą firma pokazuje gościom — i napis
  przycisku. Odpowiedź `live` daje treść (zdjęcia po identyfikatorze,
  wyposażenie w języku strony, miejscowość, „od X zł/noc”) i oferty, przez
  które jednostkę się rezerwuje, każdą z jednym wyborem. Karta rysuje galerię
  (każde zdjęcie otwiera dużą kopię), opis, całe wyposażenie i kalendarz
  wolnych dni z przyciskiem do formularza — ten sam komponent co blok
  kalendarza. Bez odpowiedzi karta nie jest sekcją.
- **Jednostka z puli mówi nazwą grupy.** Gość rezerwuje grupę, a sztukę
  dobiera serwer (§3), więc karta jednostki, która reprezentuje grupę, ma
  nazwę i opis grupy, treść jednostki i wybór `group`; jednostka przypięta do
  oferty wprost — własną nazwę i wybór `unit`. Kartę i stronę ma ta
  jednostka, której treść pokazuje formularz: przypięta wprost i publiczna
  albo pierwsza publiczna w swojej grupie. Druga publiczna sztuka tej samej
  puli strony nie ma — byłaby tą samą ofertą pod drugim adresem.
- **Strona jednostki jest systemowa: nikt jej nie publikuje.** Na każdej
  opublikowanej stronie firmy adres `/stay/<public_slug>/` odpowiada stroną,
  której jedynym blokiem jest karta tej jednostki z `main` (nazwa jest wtedy
  nagłówkiem strony). Witryna pyta źródło, gdy żadna opublikowana podstrona,
  wpis, indeks ani archiwum nie odpowiada pod adresem
  (`PublicSource.site_page`, `_find_source_page`); strona istnieje, dopóki
  formularz pokazuje jednostkę, i znika (404) razem z nią. Tytuł to nazwa i
  miejscowość, opis — początek opisu jednostki. Witryna bez publikacji takich
  stron nie ma.
- **Segment `stay` jest jeden dla wszystkich języków i zarezerwowany.** Jak
  `shop` w ADR-074 pkt 7 (dług adresowy ADR-071 pkt 14): `/stay/<adres>/` w
  języku strony, `/xx/stay/<adres>/` w innym. Źródło deklaruje segment
  (`PublicSource.page_segment`), a `first_segment_reserved` odmawia go nowym
  podstronom i ścieżkom kolekcji (`slug_reserved`); podstrona, która miała
  taki adres wcześniej, zostaje i wygrywa z systemową, bo opublikowane
  podstrony odpowiadają pierwsze. Słowo jest angielskie i ogólne: jednostką
  bywa domek, pokój i kajak, a adres per język wymagałby zamrożenia slugu
  wersji językowej, której ta strona nie ma.
- **Inny język tylko tam, gdzie jednostka ma w nim własną nazwę.** Strona
  jest zawsze w języku źródłowym witryny. W języku L istnieje, gdy L jest
  dostępny na stronie (ADR-071 pkt 8) i jednostka — albo grupa, którą
  reprezentuje — ma w L przetłumaczoną nazwę; inaczej `/L/stay/<adres>/`
  odpowiada 308 do strony w języku źródłowym (ADR-071 pkt 9, jak produkt w
  ADR-074) i nie ma go w `hreflang` ani w mapie strony. `x-default` to wersja
  w języku źródłowym. Firma, której języków wdrożenie nie obsługuje, ma
  stronę jednostki tylko w języku witryny.
- **Mapa strony wymienia strony jednostek**, każdą z wersjami językowymi i
  datą zmiany jednostki (`PublicSource.site_pages`). Odsłon strony jednostki
  licznik nie zapisuje: nie jest podstroną, wpisem ani kolekcją, a
  czwartego rodzaju wiersz licznika jeszcze nie ma.
- **Lista jednostek prowadzi do strony.** Wybór w odpowiedzi `live` listy
  dostaje `page_path` tam, gdzie jednostka ma stronę; karta listy linkuje
  nim nazwę. Witryna mówi źródłu, gdzie w danym języku leżą jego strony
  (`page_base` w `site_blocks`), bo adresy są jej. Katalog formularza oddaje
  `public_slug` także przy grupie — adres jednostki, która za nią mówi.
- **Poza 5e:** blok mapy (decyzja wyżej); dane strukturalne jednostki
  (`Accommodation`/`Product` w JSON-LD) i obraz do udostępnień — strona ma
  dziś ogólny graf strony; licznik odsłon; strona jednostki w katalogu (5h);
  token pochodzenia (5h); własny adres stron jednostek per firma albo język.

### Zawężenie bramki hostów dla odczytów formularza (2026-10-04)

Plaster 5d otworzył odczyty `/api/v1/booking/public/` pod **każdym** hostem:
wystarczyło, że żądanie było `GET` albo `HEAD`. Bloki potrzebują mniej, więc
bramka przepuszcza teraz dokładnie tyle.

- **Host musi być hostem opublikowanej strony.** Bramka pyta witryny
  (`sites.publication_routing.site_host_company`), tą samą drogą, którą
  renderer publiczny czyta host (`normalize_hostname` z portem, wspólne
  `_served_domain`): wiersz `Domain` o tym hoście ze statusem `verified` —
  domena własna klienta po weryfikacji DNS albo subdomena platformy strony —
  firma w stanie, w którym platforma ją obsługuje (`onboarding`, `active`),
  i strona z bieżącą publikacją. Domena `pending` albo `failed` to tylko
  roszczenie; strona bez publikacji nie ma podstrony, która by pytała.
- **Host i adres muszą nazywać tę samą firmę.** Slug formularza w adresie
  wskazuje firmę (`booking.site_blocks.form_company`, aktywna trasa
  formularza); strona firmy B pytająca o formularz firmy A to dla bramki
  nieznany host. Blok pokazuje oferty własnej firmy, więc żadna strona nie
  pyta w poprzek firm.
- **Wszystko inne to 400 jak dotąd** („Host nie należy do konfiguracji
  aplikacji”): host, pod którym nie serwujemy niczyjej strony, cudza strona,
  slug bez formularza, formularz wyłączony, firma zawieszona, każdy zapis i
  każdy adres spoza prefiksu. Pod hostem z `ALLOWED_HOSTS` nic się nie
  zmienia — formularz na hoście platformy czyta jak dotąd.
- **Warstwa HTTP nie zna modułów.** `http/hosts.py` ma dwa punkty
  rejestracji: witryny mówią, czyj jest host (`register_site_host`),
  rezerwacje — czyj jest adres (`register_site_reads`). Produkt bez witryn
  albo bez formularza nie rejestruje nic i wyjątku nie ma.
- **Żadna odpowiedź pod tym prefiksem nie buduje odnośnika z nagłówka
  `Host`.** Adresy zdjęć są ścieżkami bez hosta, adres formularza i
  dokumentów pochodzi z `FRONTEND_BASE_URL`. Pilnują tego dwa testy: każdy
  odczyt daje pod hostem strony bajt w bajt to samo co pod hostem platformy
  i nie zawiera hosta gościa, a kod modułu nie sięga po `get_host`,
  `build_absolute_uri` ani `HTTP_HOST`.
