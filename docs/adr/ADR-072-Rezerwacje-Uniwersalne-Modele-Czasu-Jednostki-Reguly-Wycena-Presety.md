# ADR-072 — Rezerwacje uniwersalne: modele czasu, jednostki i grupy, reguły i wycena, presety

**Status:** Accepted — plan właściciela `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
(odpowiedzi 1–24 z 01–02.10.2026) i jego decyzje techniczne T1–T8, T13, T22, T23.
**Data:** 2026-10-02
**Właściciel:** zespół SaaS Core
**Rozszerza:** ADR-030 — okres i wydarzenie (§1), horyzont 62 dni tylko dla
terminów (§5), migawka wyceny (§7); punkt „płatność i zaliczka są poza pierwszym
zakresem” przestaje obowiązywać (§6–§8 tutaj, pieniądze w ADR-073).
**Zmienia:** ADR-058 §2 (oferta bez osoby — §2 tutaj) i §3 (rezerwacje
oczekujące — §9 tutaj) wraz z odpowiadającymi im alternatywami odrzuconymi.
**Powiązane:** ADR-073 (zamówienie i pieniądze; zastępuje ADR-037 §4 cennikiem
z §6–§8), ADR-075 (import iCal na blokadach z §4); zarezerwowane, nienapisane:
ADR-069–ADR-071 (tłumaczenia i języki treści), ADR-076 (rejestr poleceń asystenta).

## Kontekst

Pierwsze realne zapytanie — dwa domki na Mazurach — wymaga pobytu na noce,
sezonów, zadatku i synchronizacji z portalami. Właściciel 01.10 (decyzja 1):
rezerwacje powstają w rdzeniu i od razu obsługują każdy wariant — wizytę, okres
i wydarzenie z miejscami; produkty dokładają swoje przez punkty rozszerzeń
(ADR-049). Decyzja 22 (02.10): budujemy od razu, w tempie dni.

Stan przed decyzją (main e381199): `Service.duration_minutes` ma 5–1440 min, bez
ceny i podatku; wolne starty liczy się tylko z grafików osób; `Appointment.staff`
jest wymagane, `staff_count` ma 1–10, a rezerwacja bez osoby jest odrzucana;
wymagane zasoby usługi działają jak „pierwszy wolny według id”; `TimeOff` nie
bierze udziału w `EXCLUDE`; stanu „czeka” nie ma (ADR-058 §3); `_check_horizon`
ogranicza szerokość jednego zapytania do 62 dni, a okna rezerwacji naprzód nie
ma; `serviceTemplates` (ADR-050) żyją tylko w pliku frontendu. Kształty, których
plan nie przesądza (puste `Appointment.staff`, blokada jako alokacja,
obserwatorzy, presety bez kwot), są decyzjami technicznymi tego ADR-u z powodem.

## Decyzja

### 1. Jedna rezerwacja, trzy modele czasu (T1, T4)

Każda rezerwacja — wizyta, pobyt, wynajem, miejsce na zajęciach — to
`Appointment` z tymi samymi alokacjami, klientem, historią, samoobsługą,
przypomnieniami i składem; nazwy modeli zostają, słowa daje oferta (§10).
`Service.time_model` to `slot` (dzisiejszy silnik, ADR-058 §5), `range` (okres
od–do wybrany przez klienta; `range_unit`: `night`, `day`, `hour`) albo
`session` (miejsca w wystąpieniu z pojemnością). Istniejące oferty dostają
`slot`; oferta z rezerwacjami nie zmienia modelu. `duration_minutes` opisuje
`slot` i domyślne wystąpienie `session`; w `range` jest puste i CHECK długości go
nie obejmuje.

Noc to data lokalna z godziną zameldowania i wymeldowania oferty, przeliczona na
UTC w strefie firmy (ADR-030); zajętość trwa od zameldowania do wymeldowania plus
przerwa po, więc wyjazd 11:00 i przyjazd 16:00 tego dnia się nie kłócą. `day` ma
tak samo godzinę odbioru i zwrotu, `hour` — start i koniec w godzinach otwarcia.

### 2. Oferta bez osoby (T5) — zmienia ADR-058 §2

`staff_count` przyjmuje 0–10; zero tylko w ofercie, która rezerwuje jednostkę.
`Appointment.staff` jest puste wtedy i tylko wtedy, gdy `staff_required = 0`
(CHECK); przy co najmniej jednej osobie niezmiennik ADR-058 §2 i `crew.set_crew`
działają bez zmian. Odrzucona w ADR-058 alternatywa „`Appointment.staff` jako
pole opcjonalne” wraca w tym zakresie: jej powód — wakat opisuje znacznik — nie
dotyczy rezerwacji bez żadnej osoby, a fikcyjny „pracownik jednostki” byłby tym
samym błędem co fikcyjne członkostwo klienta (ADR-030). Godziny otwarcia
jednostki to tygodniowe reguły jak grafik osoby: `AvailabilityRule` wskazuje
osobę albo jednostkę (CHECK: dokładnie jedno), więc czas lokalny i DST liczy ten
sam kod; `night` i `day` są całodobowe.

### 3. Jednostki, grupy i wydarzenia (T2, T3)

- Jednostka to rozszerzony `Resource`: pojemność w osobach, opis, wyposażenie,
  zdjęcia, `public_slug`, miejsce firmy (`Location`), miasto ze słownika katalogu
  i współrzędne tylko na serwerze, flaga `public`, godziny otwarcia.
- Grupa (`ResourceGroup`: „Domek 6-os.”, „Kajak 2-os.”) to pula identycznych
  jednostek; jednostka należy najwyżej do jednej. Na N sztuk z grupy serwer
  dobiera wolne najmniej obciążone (jak osoby, ADR-058 §4; zastępuje dzisiejszy
  „pierwszy wolny według id”), każdą w osobnym punkcie zapisu; brak N wolnych to
  konflikt terminu. O jednostkach rezerwacji mówią aktywne alokacje, a
  `Appointment.resource` zostaje jako pierwsza z nich; przepięcie na inną
  jednostkę grupy to operacja z oczekiwaną wersją (jak ADR-058 §9).
- Liczone miejsca są tylko w wydarzeniu: wystąpienie samo zajmuje osobę i salę,
  a miejsca liczy pod blokadą swojego wiersza — tu `select_for_update` działa,
  bo wiersz istnieje (por. ADR-030). Kształt wystąpień ustala faza 8.

### 4. Blokady jednostek rozstrzyga `EXCLUDE`

`TimeOff` dostaje `source` (`manual` albo `ical:<kanał>`, ADR-075) i
`external_uid`. Blokada jednostki zajmuje czas w tej samej tabeli co rezerwacje:
wiersz `AppointmentResourceAllocation` należy do rezerwacji albo do blokady
(CHECK: dokładnie jedno), bo `EXCLUDE` nie sięga do drugiej tabeli. Ręczna
blokada na rezerwację to 409; import nachodzący na rezerwację zapisuje blokadę
bez aktywnej alokacji, ze znacznikiem konfliktu — alarm, nigdy odwołanie.
Nieobecność osoby działa jak dziś (ADR-058). Blokady jednostek obsługuje API.

### 5. Reguły i wyszukiwanie okresu (T6, T7) — rozszerza ADR-030

`BookingRule` to wiersz z zakresem dat lokalnych (sezon) i zasięgiem — oferta,
grupa albo jednostka; wygrywa bardziej szczegółowy, przy remisie późniejszy
początek sezonu. Pola: minimalna i maksymalna długość, wielokrotność (7 — pełne
tygodnie), dni początku i końca, wyprzedzenie, okno rezerwacji naprzód,
zamknięcie, przerwa po. Bez sezonów cyklicznych: jawne daty i „skopiuj sezony na
kolejny rok”. Oferta `slot` zachowuje dzisiejsze pola.

Kalendarz okresu na 12–18 miesięcy to jedno zapytanie o aktywne alokacje i
reguły jednostek; wynik to dni początku i końca. `BOOKING_SLOT_HORIZON_DAYS`
(≤ 62) zostaje granicą szerokości zapytania o starty `slot`; kalendarz okresu ma
własną (ustawienie platformy, domyślnie 18 miesięcy), a odległość od dziś
ogranicza reguła okna. Rezerwacja sprawdza jeden pobyt walidacją, nie listą dni
(jak ADR-058 §5). Ta sama funkcja kalendarza i wyceny posłuży wyszukiwarce
katalogu (faza 16) w publicznym kontekście każdej firmy, bez `PRE_TENANT_DB`.

### 6. Cennik (T6, T22)

- `PriceRule`: podstawa `per_booking`, `per_time_unit`, `per_person` albo
  `per_group`; zasięg i daty jak reguły; nadpisania dniem tygodnia i porą dnia;
  osoby w cenie i dopłata za kolejną; ceny kategorii uczestników; rabat za
  długość. Kategorie uczestników mają flagę „liczy się do pojemności”.
- `Extra`: nazwa, kwota, podstawa (także `per_person_per_time_unit`),
  obowiązkowa albo do wyboru, stawka VAT. Kaucja to osobna kwota, nie przychód.
- Jedna waluta cennika firmy: `Organization.currency` z listy platformy (PLN,
  EUR, USD — decyzja 16); każda kwota niesie walutę, a zmiana waluty firmy, która
  ma cennik, jest odrzucana.
- Firma wpisuje ceny brutto albo netto; stawka VAT to kod ze słownika (dziś 23,
  8, 5, 0, `zw`, jak w magazynie, ADR-055 §1), nie punkty bazowe, bo zwolnienie to
  nie 0%. ADR-040 dotyczy abonamentów platformy, nie cennika firmy.

### 7. Jedna wycena `quote`, zamrożona w rezerwacji

`quote` to jedna funkcja serwera bez zapisu: z oferty, okresu, jednostek,
uczestników i dopłat liczy pozycje (noce według sezonów, osoby, dopłaty, rabaty;
kaucja osobno), sumy netto, VAT i brutto, walutę i polityki z §8, a przy
naruszeniu reguł zwraca błędy z kodem i polem. Kwoty to liczby całkowite w
jednostkach drobnych waluty; procent zaokrągla się raz na pozycję, połówki w
górę. Widget, panel, asystent i zapis wołają tę samą funkcję; zapis liczy ją na
nowo w transakcji i zamraża w `Appointment.quote`. Skrót pokazanej wyceny
(`quote_digest`), który się nie zgadza, daje 409 `quote_changed` z nową wyceną.
Pozycje migawki stają się pozycjami zamówienia (ADR-073).

### 8. Potwierdzenie, miejsce, płatność i anulowanie należą do oferty

Oferta niesie `confirmation` (`instant`, `on_request` z czasem odpowiedzi w
godzinach, `quote_request` — faza 13), politykę płatności (`none`, `on_site`,
`transfer`, `deposit`, `full`), zadatek procentem albo kwotą, termin przelewu w
dniach, dopłatę reszty X dni przed albo na miejscu i progi anulowania „co
najmniej N dni przed → % zwrotu”. Wszystko trafia do migawki, a zwrot liczy się z
migawki. Pieniądze i tryby operatora opisuje ADR-073; profil bez modułu zamówień
przyjmuje tylko `none` i `on_site`. Miejsce (`business`, `customer`, `online`,
`pickup_return`) przy `customer` korzysta z miejsca wizyty (ADR-066). Pola własne
formularza (tekst, liczba, wybór, data, zgoda) to dane klienta: nie trafiają do
e-maili, logów ani historii zmian, a anonimizacja je czyści.

### 9. Rezerwacje oczekujące (T8) — zmienia ADR-058 §3

- `AppointmentStatus` dostaje `pending_request` (oferta `on_request`) i
  `pending_payment` (wpłata przed potwierdzeniem: `transfer`, `deposit`, `full`).
  Obie trzymają termin tymi samymi aktywnymi alokacjami co `confirmed` — bez
  „wstępnych” blokad i bez ich wyprzedzania.
- `Appointment.hold_expires_at`: godziny na odpowiedź firmy, dni na przelew
  (Nocleg: 3, odpowiedź 13a) albo okno płatności online (ADR-073). Wygasza
  zadanie przez trasę bez danych osobowych z kontraktem `service` organizacji
  (wzorzec `ReminderRoute`, ADR-058 §7), nie zapytaniem po wszystkich tenantach.
- Akceptacja (`POST /booking/appointments/{id}/accept/`) prowadzi do
  `pending_payment` albo `confirmed`; odmowa (`…/reject/`), rezygnacja klienta i
  wygaśnięcie — do `canceled` z powodem w historii; wpłata (ADR-073) potwierdza.
- E-mail potwierdzenia, przypomnienie i rezerwacja materiałów (ADR-055 §7)
  powstają przy przejściu do `confirmed`; oczekująca ma własne wiadomości i link
  do rezygnacji. Przełożyć można tylko rezerwację potwierdzoną.
- Obserwatorzy dostają `CREATED` przy potwierdzeniu, a o odmowie i wygaśnięciu
  nic, więc produkty (HoofCare: `CREATED` → „zaplanowana”) nie widzą
  niepotwierdzonych; nowe rodzaje zmian dojdą addytywnie, z konsumentem.
- ADR-058 §3 obowiązuje dla ofert `instant`; odrzucona tam „wstępna blokada”
  wraca tylko jako jawny wybór oferty i trzyma termin jak potwierdzona.

### 10. Presety jako dane (T13, T23; odpowiedzi 13a, 14 a+b)

- Kontrakt `packages/contracts/booking-presets/`: schemat
  `booking-preset.v1.schema.json` (JSON Schema 2020-12), `manifest.json` i pliki
  `core.<klucz>.v<N>.json` dla 13 presetów katalogu planu; opublikowanej wersji
  się nie zmienia. Pilnuje go test Ajv (strict) w `packages/contracts/tests`.
- Preset niesie model czasu (z jednostką i godzinami), co się rezerwuje, ilość,
  uczestników, potwierdzenie, miejsce, podstawę ceny, podpowiedzi płatności,
  anulowania i dopłat, pola formularza, propozycję iCal, słownictwo pl i en
  (kolejne języki opcjonalnie) oraz istniejące kategorię katalogu i szablon
  strony. Kwot i stawek VAT nie niesie: zależą od waluty i kraju firmy.
- `availability`: `ready` — rdzeń tej wersji przyjmuje takie rezerwacje (dziś
  tylko „Wizyta u specjalisty”); `soon` — „wkrótce” z zapisem na listę i polem
  „Czego Ci brakuje?” (14 a+b). `ready` przychodzi nową wersją presetu w fazie,
  która go uruchamia; test pilnuje, by używał tylko tego, co umie silnik.
- Wartości domyślne (Nocleg według 13a: od razu, zadatek 30% przelewem w 3 dni,
  reszta 14 dni przed, zwrot 100/50/0% przy ≥ 30 / 14–29 / < 14 dniach, 16:00 i
  11:00) są podpowiedzią: z rejestrem ustawień platformy (S-T1) staną się
  ustawieniami klasy A z wartością z pliku jako domyślną, a API presetu nałoży
  nadpisania operatora. Limity planów zostają w wersjach planów (T23).
- Zastosowanie presetu to kopia, nie odwołanie (ADR-063 §2): powstaje nieaktywna
  oferta z pochodzeniem (`preset_id`, wersja), a słownictwo staje się jej treścią.
- Panel, strona i asystent czytają presety z API (`GET /booking/presets/`), nie
  z frontendu, w którym `serviceTemplates` są dziś niewidoczne dla asystenta.
  Faza, w której backend pierwszy raz je czyta, dodaje kopię w obrazie,
  `BOOKING_PRESET_CONTRACTS_PATH`, system check i loader z
  `Draft202012Validator`, jak przy szablonach stron.
- Produkt dokłada presety w profilu (`organizationTypes[]`, ten sam schemat,
  własna przestrzeń nazw; `serviceTemplates` zostają); pole i walidację w
  `deployment-check` dodaje faza 5 z wpisem w dokumentacji wydania (ADR-049).

### 11. Treść, rozszerzenia i asystent

- Treść ofert, jednostek, grup, dopłat, kategorii i pól to źródła tłumaczeń w
  rejestrze rdzenia (TL-T17, ADR-069), rejestrowane w fazie powstania, bez
  własnych tabel tłumaczeń; język treści to `^[a-z]{2}$` sprawdzany w serwisie.
- Produkt dokłada presety, tabelę szczegółów (`APPOINTMENT_MODEL`) i adaptery
  przez porty rdzenia; rejestr składników ceny powstaje z pierwszym użytkownikiem.
  `booking.api` zmienia się addytywnie (nowe argumenty `create_appointment` mają
  wartości domyślne), więc HoofCare działa bez zmian.
- Każda nowa operacja (oferta, jednostka, grupa, blokada, reguła, cena,
  zastosowanie presetu, akceptacja, przepięcie) to serwis za widokiem: opisane
  serializery z enumami i zakresami; Problem Details z kodem i polem
  (`rule_min_length`, `unit_capacity_exceeded`, `quote_changed`,
  `booking_version_conflict`…); podgląd `dry_run` dla konfiguracji; klucz
  idempotencji i oczekiwana wersja (nieaktualna to 409 — dzisiejszy setup ich nie
  ma); audyt w `OrganizationAuditAction` (z brakującym dziś
  `booking.appointment.place_changed`; rodzaj aktora i „w imieniu” z A1a,
  ADR-076); presety i wartości domyślne z API; listy stronicowane i filtrowane.
  Zmiana cennika i polityk płatności wymaga od asystenta zgody z digestem
  (ADR-033).

## Konsekwencje

- Fazy planu: 2 — §1–§5; 3 — §6–§7; 4 — §8–§9 z ADR-073; 5 — presety przy
  zakładaniu i ich API; 8 — wydarzenia; 13 — pozostałe presety. Faza wydaje nowe
  wersje presetów, które uruchamia.
- Migracje `booking` są odwracalne; nowe tabele (`ResourceGroup`, `BookingRule`,
  `PriceRule`, `Extra`, kategorie uczestników) mają wymuszone RLS, a każda nowa
  kolumna FK trafia do `booking_validate_tenant_relations()` migracją, której
  odwrócenie przywraca poprzednie ciało funkcji. Trasa wygaszania jest bez danych
  osobowych i w `register_erasure_rows`.
- Limit 12a to kwota `booking.units.max` (Profil 3, Starter 15, Pro 100) w nowych
  wersjach planów; subskrypcje na starszych wersjach są bez limitu do zmiany planu.
- Kod rozgałęziony na `confirmed` (przypomnienia, kolejka, skład, powiadomienia,
  miary) obsługuje oczekujące według §9. Przełożenie pobytu przyjmuje początek i
  koniec, liczy zajętość z migawki i dobiera jednostkę z grupy na nowo; link
  samoobsługi (dziś 30 dni od utworzenia) liczy ważność od końca rezerwacji.
- Otwarte: pobyt przecinający granicę sezonów (z pilotem); `day` jako doba czy
  dzień kalendarzowy i siatka startów `hour`; okno naprzód dla `slot`; czy limit
  liczy zasoby używane tylko obok osoby; stawki VAT firm spoza Polski; „Termin na
  wyłączność” dla samych osób; numer rejestracyjny obiektu (UE 2024/1028).

## Odrzucone

- Osobne moduły okresu i wydarzeń — kopiowałyby klientów, alokacje, statusy,
  powiadomienia, samoobsługę i skład (T1).
- Nowy model jednostki obok `Resource` — dublowałby blokadę z `EXCLUDE` (T2).
- Pula jako licznik „N sztuk” — `EXCLUDE` nie wyrazi „suma ≤ N” (T3).
- Blokada jednostki tylko w `TimeOff` albo w osobnej tabeli — blokada i
  rezerwacja gościa mogłyby obie wygrać.
- Podniesienie `BOOKING_SLOT_HORIZON_DAYS` dla okresów — to granica szerokości
  zapytania o starty, nie okno rezerwacji.
- Cena jako pola `Service` (`price_minor`, `tax_rate_bp`, ADR-037 §4) — nie
  wyrazi sezonów, osób, dopłat ani zwolnienia z VAT.
- Sezony cykliczne w pierwszej wersji — daty sobót przesuwają się co roku.
- Presety w kodzie albo jako `serviceTemplates` — 5–1440 min nie opisze okresu,
  a dane tylko we froncie są niewidoczne dla asystenta.
- Preset jako odwołanie — jego zmiana przepisałaby oferty firm.
- Statusy „wygasła” i „odrzucona” — wystarczy `canceled` z powodem w historii.
