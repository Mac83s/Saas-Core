# Usuwanie danych osobowych po czasie

Plan ustawień firmy D1–D2, odpowiedź właściciela 37a; ADR-078. Firma sama decyduje,
czy i po jakim czasie system usuwa dane osobowe jej klientów i osób, które do niej
napisały. Usunięcia nie da się cofnąć, więc dokument mówi dokładnie, co znika, co
zostaje i dlaczego.

**Zadanie w harmonogramie jest włączone od 03.10.2026**, po odbiorze dowodu z
działającego stosu (niżej „Dowód”): przebieg uruchamia się raz na dobę, w nocy.
Operator wstrzymuje go zmienną `PRIVACY_RETENTION_SCHEDULE_ENABLED=false` (niżej
„Harmonogram”); komenda `manage.py privacy_retention --run` zostaje do uruchomień
ręcznych.

## Ustawienia

Obszar „Prywatność i dane” (`/panel/settings/privacy`), oba domyślnie `off`:

| Klucz | Znaczenie | Gdzie oferowane |
|---|---|---|
| `booking.retention.customers` | `off` albo 12, 24, 36 miesięcy od ostatniej wizyty klienta | tylko w profilu z `features.customerRetention` (dziś `business` i `vps-dev`) |
| `sites.retention.inquiries` | `off` albo 12, 24, 36 miesięcy od zapytania | wszędzie, gdzie jest moduł stron |

- Zmienia je `organization.settings.manage`; polecenia asystenta mają klasę
  `irreversible`, więc asystent sam ich nie włączy.
- **Decyzja należy do firmy.** Liczy się tylko wartość zapisana przez firmę
  (`product_default=False`, zasięg wyłącznie firmy): żaden profil ani wartość
  platformy nie uruchomi usuwania.
- **Podgląd** przed zapisem: ilu osób albo zapytań wybór dotyczy teraz, od którego
  dnia najwcześniej, i że tego nie da się cofnąć.
- **Okres ochronny `GRACE_DAYS` = 7 dni** od ostatniej zmiany wartości: nic nie
  znika. Przy włączeniu albo skróceniu okresu każdy aktywny właściciel dostaje e-mail
  (szablon `system.retention_scheduled`): kto, co, ilu dotyczy teraz, od którego dnia
  i gdzie to wyłączyć. Wydłużenie okresu nie wysyła nic.
- **Dlaczego „Dane klientów” nie wszędzie.** W profilu z rejestrem gospodarstw wizyta
  wisi na karcie gospodarstwa (`shared.farms`: `keeper_name`, `email`, `phone`,
  `address`, `notes`), więc klient rezerwacji po anonimizacji zostałby rozpoznawalny
  przez kartę, a opis ustawienia obiecywałby więcej, niż się dzieje. Gospodarstwa
  dostaną własną regułę, uzgodnioną z właścicielem produktu; do tego czasu grupy tam
  nie ma.
- **Gabinety (MedPlano): usuwanie danych klientów po czasie zostaje wyłączone**
  (odpowiedź właściciela 9 z 04.10.2026) — grupy „Dane klientów” w tym profilu nie ma
  i nie ma niczego do zbudowania. Gdyby kiedyś została gabinetom zaoferowana,
  **najkrótszy okres do wyboru to 5 lat** (wartość robocza właściciela, do
  potwierdzenia przez prawnika — minimalny okres przechowywania dokumentacji).
  „Najkrótszy okres” to dolna granica tego, co gabinet mógłby wybrać; dzisiejsze 12,
  24 i 36 miesięcy nie byłyby tam dostępne, a dopóki funkcja jest wyłączona, liczba
  niczego nie dotyczy.

## Kto jest „po terminie”

- **Klient:** niezanonimizowany; jego najpóźniejsza wizyta (w dowolnym stanie)
  skończyła się przed granicą, czyli nic nie trwa i nic nie jest przed nim; klient
  bez żadnej wizyty liczy się od dnia założenia rekordu. Nigdy klient, którego inny
  moduł jeszcze potrzebuje (`register_retention_exclusion`): **kupujący z zamówienia,
  za które wzięto pieniądze, zostaje do końca okresu zapisu sprzedaży** — niżej,
  „Zapis sprzedaży”. Podgląd ustawienia mówi, ilu klientów po terminie zostaje i
  dlaczego.
- **Migawka kupującego** na zamówieniu zanonimizowanego klienta: zapis sprzedaży,
  którego okres minął (przemiatanie `commerce.buyers`, niżej).
- **Zapytanie:** przyszło przed granicą, przeczytane czy nie, i jeszcze ma dane osoby.
- Granica to pełne miesiące kalendarzowe wstecz (`cutoff_for`).

## Przebieg

`core/organizations/retention.py`, wywoływany komendą:

- firma po firmie, każda we własnej transakcji i własnym tenancie (jak przemiatania
  billingu, ADR-039); ustawienie firmy jest czytane w tej samej transakcji, więc
  firma, która przed chwilą wyłączyła usuwanie, niczego nie traci; firma z `off` nie
  jest czytana wcale;
- każdy zapis nazywa firmę w samym zapytaniu (`organization_id` w `WHERE`), nie
  polega na samym RLS;
- **blokada i ponowne sprawdzenie:** klienci po terminie są blokowani w kolejności
  identyfikatorów (`FOR NO KEY UPDATE`), potem — tak samo — wszystkie ich wizyty, i
  dopiero z zablokowanych wierszy czytane jest, czy któraś kończy się po granicy.
  Rezerwacja zatwierdzona między wyszukaniem a blokadą zostawia klienta. Przełożenie
  wizyty (`reschedule_appointment`, `move_stay`) blokuje wizytę, nie klienta: to w
  toku każe przebiegowi poczekać i jest potem widziane, to późniejsze czeka na
  przebieg. W zapytaniu blokującym wizyty nie ma daty — wiersz, który jeszcze nie
  pasuje, nie byłby ani zablokowany, ani oczekiwany. Kolejność blokad: klient, potem
  wizyta; przełożenie bierze samą wizytę, więc nic nie czeka w kółko. Z drugiej
  strony `upsert_customer` blokuje znalezionego klienta i pyta o niego ponownie,
  więc rezerwacja złożona w trakcie przebiegu dostaje nowego klienta, a nie dopina
  wizyty do usuniętego;
- **wykluczenia innych modułów** (`register_retention_exclusion`) są czytane przy
  układaniu listy „po terminie” i **drugi raz pod blokadą**: `erase_customers`, mając
  zablokowanych klientów i ich wizyty, pyta `excluded_ids(…, among=<zablokowani>)`.
  Moduł dostaje wtedy listę kandydatów i sam blokuje to, od czego zależy jego
  odpowiedź. Pierwsze wykluczenie rejestruje commerce (plaster 4i): blokuje
  zamówienia tych klientów i dopiero potem czyta księgę, a każdy zapis do księgi
  bierze najpierw blokadę zamówienia — wpłata oznaczona między wyszukaniem a blokadą
  zatrzymuje klienta tak samo jak nowa wizyta, wpłata w toku każe przebiegowi
  poczekać. Kolejność blokad: klient, wizyta, zamówienie;
- reguła platformy w dniach (`platform_days`) nie ma okresu ochronnego, więc wartość
  poniżej jednego dnia (albo nie-liczba) znaczy „brak reguły”, nigdy „usuń
  wszystko”; kto rejestruje takie przemiatanie, deklaruje na kluczu rozsądne minimum;
- firma, której transakcja się nie zatwierdziła, jest w wyniku tylko jako nieudana —
  jej liczby trafiają do „usunięto” dopiero po zatwierdzeniu;
- najwyżej `RUN_LIMIT` (200) rekordów na firmę i rodzaj danych w jednym przebiegu,
  reszta w następnym; ponowne uruchomienie niczego nie psuje;
- błąd w jednej firmie jest logowany, pozostałe firmy przechodzą, komenda kończy się
  kodem różnym od zera;
- jeden wpis w historii firmy na przebieg i rodzaj danych (`privacy.retention.run`):
  rodzaj, okres, liczba — nigdy osoba.

`--dry-run` liczy to samo i niczego nie zmienia; pokazuje też, co jeszcze czeka na
koniec okresu ochronnego.

### Harmonogram

Zadanie `privacy-retention-run` (`core/organizations/tasks.py`,
`run_privacy_retention`) uruchamia ten sam przebieg co noc o 02:30 UTC. Godzina jest
z zegara, a nie „co 24 godziny”: licznik harmonogramu zaczyna od nowa przy każdym
wdrożeniu, więc przy codziennych wdrożeniach odstęp nigdy by nie minął.

**Wyłącznik operatora:** `PRIVACY_RETENTION_SCHEDULE_ENABLED=false` w `.env` stosu i
ponowne utworzenie kontenera workera (`docker compose up -d worker`; sam `restart`
nie wczyta zmienionego `.env`). Zadanie czyta przełącznik przy każdym uruchomieniu i
kończy się bez usuwania (wpis w logu `privacy_retention_schedule_paused`); wpis
harmonogramu zostaje, więc powrót to `true` i ten sam krok. Usunięcia nie da się
cofnąć, dlatego wstrzymanie nie wymaga wdrożenia. Komenda uruchamiana ręcznie
przełącznika nie czyta.

## Zapis sprzedaży: kupujący na zamówieniu z wpłatą (plaster 4i)

ADR-073, „Rozstrzygnięcia plastra 4i”; odpowiedź właściciela 7 z 04.10.2026. Kod:
`shared/commerce/retention.py`.

- **Okres**: `BUYER_RETENTION_YEARS` = **5 pełnych lat kalendarzowych** po roku
  ostatniego wpisu księgi zamówienia, w strefie czasowej firmy (wartość robocza do
  odpowiedzi prawnika; jedna stała, nie ustawienie firmy). Wpłata z 2026 roku trzyma
  kupującego do końca 31.12.2031; od północy 1.01.2032 czasu firmy — już nie. Z dwóch
  dat wpisu (kiedy się stało, kiedy zapisano) liczy się późniejsza.
- **Co jest zapisem sprzedaży**: zamówienie, którego wpłaty (`charge`) dają razem
  więcej niż zero. Wpłata oznaczona przez pomyłkę i wycofana niczego nie trzyma;
  zamówienie opłacone i zwrócone zostaje zapisem. Zamówienie bez wpłaty nie trzyma
  niczego.
- **Przebieg firmy** („Dane klientów”) takiego klienta **omija w całości** do końca
  okresu — karta klienta, wizyty i migawka zostają — i usuwa go razem z migawką, gdy
  okres minie. Podgląd ustawienia podaje liczbę takich klientów i powód.
- **Ręczna anonimizacja** czyści kartę klienta i wizyty jak zawsze; **zostaje sama
  migawka kupującego** (`Order.buyer_name`, `buyer_email`, `buyer_phone`) na
  zamówieniach będących zapisem sprzedaży w okresie. Kopie e-maili i powód zwrotu
  znikają od razu. Panel mówi to przed potwierdzeniem („Usuń dane klienta…” na
  stronie zamówienia, `GET /booking/customers/<id>/anonymize/preview/`) i po nim
  (zamówienie: „Dane kupującego zostają w tym zamówieniu do …”).
- **Po okresie** migawkę usuwa przemiatanie `commerce.buyers` we wspólnym przebiegu
  (co noc, w każdej firmie, bez okresu ochronnego — to okres z prawa, nie kliknięcie
  firmy; najwyżej `RUN_LIMIT` na firmę i przebieg). Zamówienia są blokowane, a księga
  czytana ponownie spod blokady: wpis dopisany między wyszukaniem a blokadą zaczyna
  okres od nowa. To samo przemiatanie usuwa migawkę zamówienia, które przestało być
  zapisem sprzedaży (jedyną wpłatę wycofano jako pomyłkę po anonimizacji klienta).
- **Wpłata oznaczona po anonimizacji** niczego nie przywraca: migawki już nie ma.
- **Do potwierdzenia z prawnikiem**: sam okres i zakres danych, oraz to, czy
  przebieg firmy ma zostawiać kupującego w całości (jak dziś), czy czyścić kartę i
  wizyty po okresie wybranym przez firmę i zostawiać tylko migawkę (jak ręczna
  anonimizacja). Zmiana to jedna linia rejestracji wykluczenia w `commerce/apps.py`.

## D1 — klient rezerwacji: wszystkie przechowywane kopie

Źródło: `customers.Customer` (moduł `shared.customers`, ADR-073 §2; tabela
`booking_customer`). Jedna funkcja `strip_customer`
(`shared/customers/services.py`) obsługuje ręczną anonimizację z panelu i przebieg:
czyści wiersz klienta, a potem woła w tej samej transakcji każdy moduł, który
zarejestrował, co sam trzyma o kliencie (`register_customer_anonymizer`). Booking
rejestruje `strip_customer_visits` (`shared/booking/services.py`) — wiersze tabeli
niżej dotyczące wizyt, linków i wiadomości. Commerce rejestruje `strip_buyer`
(`shared/commerce/orders.py`) — migawkę kupującego na zamówieniu — razem z odczytem
tego, co po czyszczeniu zostanie (`keeps`; „Zapis sprzedaży”, wyżej). Moduł, który
zacznie trzymać dane klienta (sklep: dane dostawy), rejestruje własne
czyszczenie i dopisuje swoje wiersze do tej tabeli.

| Kopia | Co zawiera | Co się dzieje | Powód |
|---|---|---|---|
| `Customer.display_name`, `email`, `phone`, `contact_hash` | dane kontaktowe | **usuwane** („Zanonimizowany klient”, puste pola, nowy skrót, `anonymized_at`) | to jest usuwana dana |
| `Appointment.customer_notes` | uwagi klienta do wizyty (w gabinecie: zdrowie) | **usuwane** | — |
| `Appointment.place_address` | ulica wizyty u klienta | **usuwane** | — |
| `Appointment.place_town` | miejscowość wizyty | zostaje | nie wskazuje osoby (ADR-066), potrzebna w statystykach dojazdów |
| `NotificationMessage.recipient_email`, `recipient_hash`, `context` wiadomości do klienta (potwierdzenie, przypomnienie, zmiana, odwołanie) | adres, jego skrót, termin i link do zarządzania wizytą | **usuwane od razu** (`scrub_messages`), niezależnie od wieku | moduł powiadomień czyści je sam po 30 dniach; przy anonimizacji nie czekamy |
| wiadomości do osób z firmy o tej samej wizycie | adres pracownika, termin, usługa | zostają do własnych 30 dni | nie zawierają danych klienta |
| `EmailSuppression.recipient_hash` | skrót adresu, który odbił albo zgłosił spam | zostaje | lista „nie pisz więcej” musi przeżyć klienta; wpis nie wskazuje wizyty ani osoby |
| `NotificationAttempt` | wynik i kody doręczenia | zostaje | bez danych osoby |
| Link „zarządzaj wizytą” (`SelfServiceRoute`) | token okaziciela do jednej wizyty | **unieważniany** | po anonimizacji nie ma komu służyć |
| `BookingMutation.request_hash` | skrót całego żądania | zostaje | nieodwracalny, bez pola osoby; trzyma idempotencję |
| `OrganizationAuditEntry` rezerwacji | identyfikatory, terminy, miejscowość przy zmianie miejsca | zostaje | bez imienia, adresu, telefonu i uwag; historia jest tylko do dopisywania |
| `AppNotification.payload` (powiadomienia zespołu) | identyfikator wizyty, termin, nazwa usługi | zostaje | bez danych klienta |
| `Appointment` (termin, usługa, osoba z firmy, kwoty), historia stanów, materiały, dokumenty magazynu z `source_reference` | fakty o wizycie | zostaje | zapis pracy firmy; klient jest już nienazwany |
| `Customer.locale`, `created_at` | język, data rekordu | zostaje | nie wskazują osoby |
| `Order.buyer_name`, `buyer_email`, `buyer_phone` (`shared.commerce`, ADR-073 §3) — zamówienie bez wpłaty albo po okresie zapisu sprzedaży | migawka kupującego z chwili złożenia zamówienia | **usuwane** („Zanonimizowany klient”, puste pola) | to jest usuwana dana |
| te same pola na zamówieniu, za które wzięto pieniądze, w okresie zapisu sprzedaży | migawka kupującego | **zostaje do końca 5. pełnego roku kalendarzowego** po roku ostatniego wpisu księgi; potem usuwa ją przemiatanie `commerce.buyers` | zapis sprzedaży firmy (plaster 4i, wyżej); wartość robocza do odpowiedzi prawnika |
| `Order` (numer, kwoty, status, kanał), `OrderLine` (pozycje, stawki) | fakty o sprzedaży | zostaje | zapis sprzedaży firmy, także gdy kupujący jest już nienazwany |
| `OrganizationAuditEntry` zamówień | numer, źródło, kanał, kwota | zostaje | bez danych kupującego |
| E-mail z danymi do przelewu (`commerce.transfer_details`, ADR-073 §5) | adres klienta i treść wiadomości (numer zamówienia, kwota, rachunek firmy) | **usuwane** — zapisane kopie czyści `strip_buyer` od razu, jak e-maile rezerwacji | adres to dana klienta |
| `commerce_paymentroute` (trasy terminów wpłat) | identyfikator płatności i firmy, termin, kontrakt zadania | zostaje do usunięcia firmy | bez danych klienta |
| `booking_requestroute` (trasy terminów odpowiedzi na prośby, ADR-072 §9) | identyfikator rezerwacji i firmy, termin, kontrakt zadania | znika z odpowiedzią albo wygaśnięciem prośby, najpóźniej z usunięciem firmy | bez danych klienta |
| `Payment`, `LedgerEntry` (`shared.commerce`, ADR-073 §4) | kwoty, sposób zapłaty, czas i identyfikator osoby z firmy, która oznaczyła wpłatę | zostaje | bez danych klienta; księga jest tylko do dopisywania |
| `Refund` (`shared.commerce`, ADR-073 §8) | kwota, sposób i czas zwrotu, identyfikator osoby z firmy, która go oznaczyła, oraz `reason` — własne słowa firmy o zwrocie ponad warunki | kwoty zostają; **`reason` usuwane** (`strip_buyer`), bo wolny tekst firmy może nazywać klienta | wolny tekst traktujemy jak daną klienta |
| E-maile o dopłacie, rozliczeniu wpłaty i zwrocie (`commerce.balance_details`, `commerce.balance_overdue`, `commerce.refund_settled`, `commerce.refund_marked`, `commerce.refund_withdrawn`, ADR-073 §5, §8) | adres klienta i treść wiadomości (numer zamówienia, kwoty, sposób zwrotu, rachunek firmy; nigdy powód zwrotu) | **usuwane** — zapisane kopie czyści `strip_buyer` od razu, razem z danymi do przelewu | adres to dana klienta |
| Dziennik zgód (`customers_consentrecord`, ADR-073 §9) — także zgody marketingowe i ich wycofania | który wiersz klienta albo które zapytanie (sam identyfikator), który tekst dokumentu, skrót tekstu albo zdania zgody, źródło i czas | zostaje | bez danych osoby: po anonimizacji wskazuje nienazwanego klienta; dziennik jest tylko do dopisywania i jest dowodem firmy, że tekst został pokazany. Lista „Zgody marketingowe” takiego klienta już nie pokazuje |
| Karta gospodarstwa (`shared.farms`) | dane hodowcy | **zostaje — własna reguła** | dlatego grupy nie ma w profilu z gospodarstwami (wyżej) |
| Rozmowa z asystentem (`assistant_assistantmessage`) | cokolwiek pracownik wpisał, także nazwisko klienta | zostaje do wygaśnięcia rozmowy | nie da się jej znaleźć po identyfikatorze klienta; ogranicza ją retencja rozmów asystenta |

## D2 — zapytanie ze strony: wszystkie przechowywane kopie

Źródło: `sites.SiteInquiry`; funkcja `erase_inquiries`
(`shared/sites/inquiry_retention.py`).

| Kopia | Co zawiera | Co się dzieje | Powód |
|---|---|---|---|
| `SiteInquiry.name`, `email`, `phone`, `message` | dane i treść | **usuwane** (puste pola, `erased_at`) | to jest usuwana dana |
| `SiteInquiry.request_hash` | skrót całego formularza | **zastępowany** | pozwalałby potwierdzić znaną treść |
| `SiteInquiry.idempotency_key` | nagłówek z przeglądarki pytającego | **zastępowany** | nie nasz, więc nie wiemy, co zawiera |
| `SiteInquiry` — wiersz: data, strona, język, publikacja, pozycja bloku, `read_at` | fakt zapytania | zostaje | statystyki strony liczą zapytania z tych wierszy; bez danych osoby |
| `NotificationMessage.context` powiadomień o zapytaniu — każdego odbiorcy, po `causation_id = site-inquiry:<id>` | imię, e-mail, telefon, treść | **usuwane od razu** | jak w D1 |
| `OrganizationAuditEntry` `sites.inquiry.received` / `.read` | identyfikatory | zostaje | bez danych pytającego |

Panel pokazuje takie zapytanie jako „Dane usunięte” z datą i stroną.

## Poza zasięgiem przebiegu — do powiedzenia firmie wprost

- **E-maile już doręczone** klientowi i kopie na skrzynkach firmy.
- **Dziennik wysyłek u dostawcy poczty** (Resend): ma własną retencję, poza systemem.
- **Tekst wpisany ręcznie** w polach, które nie są danymi klienta:
  `StockDocument.counterparty`/`note`, `TimeOff.reason`, rozmowa z asystentem.
- **Dane dowieszone przez produkt** do wizyty — produkt rejestruje własne czyszczenie.
- **Kopie zapasowe bazy.** Do uzupełnienia po odczycie z VPS: jakie zadania kopii
  istnieją dla baz `saas-core`, `hoofcare`, `medplano`, najstarszy i najnowszy zrzut,
  czy coś opuszcza host. Dane usunięte dziś zostają w kopii tak długo, jak kopia żyje
  — firma musi znać tę liczbę.
- **Logi** aplikacji, workera i proxy: nie zapisują treści wiadomości ani danych
  klienta z założenia (sekrety i dane osobowe nie trafiają do logów), ale adres IP i
  ścieżka żądania publicznego formularza są w logu proxy przez jego własny okres.
- **Broker i wyniki zadań** (Redis): argumenty zadań to identyfikatory i podpisany
  kontrakt tenanta, nie dane osoby; żyją do wykonania zadania.
- **Pamięć podręczna**: klucze limitów formularza to skróty, wygasają same.
- **Śledzenie błędów**: jeśli jest włączone, zdarzenie może nieść fragment żądania —
  do sprawdzenia przy jego konfiguracji.
- **Eksporty danych** powiadomień: treść znika po wygaśnięciu eksportu (niżej).
- **Pliki e-maili na dysku** tam, gdzie działa plikowy backend poczty (lokalnie i na
  dev VPS, `EMAIL_FILE_PATH`): pełna treść i adres, poza bazą. Lokalnie to samo
  dotyczy Mailpita. Produkcja wysyła przez dostawcę i plików nie ma.

## Inne reguły retencji w systemie (nie są ustawieniem firmy)

| Dane | Czyje | Reguła | Mechanizm | Właściciel |
|---|---|---|---|---|
| Wiadomości e-mail (`NotificationMessage.recipient_email`, `recipient_hash`, `context`) | odbiorcy | `NOTIFICATIONS_RETENTION_DAYS` (30) od wysyłki | `tasks.scrub_expired`, co godzinę, firma po firmie | `shared.notifications` |
| Eksporty danych powiadomień | firmy | do wygaśnięcia eksportu | to samo zadanie | `shared.notifications` |
| Rozmowy z asystentem | osoby z firmy | `assistant.retention.conversation_days` po ostatniej wiadomości (ustawienie platformy, robocza wartość 90) | wspólny przebieg, przemiatanie `assistant.conversations` (`platform_days`) | `shared.assistant` |
| Wersje profilu firmy dla asystenta (`assistant_assistantprofileversion`) | firmy; wolny tekst i nazwiska osób z firmy | najnowsza zostaje zawsze; wcześniejsza znika po tylu dniach co rozmowy, liczonych od chwili, gdy zastąpiła ją następna | wspólny przebieg, przemiatanie `assistant.profile_versions` (`platform_days`) | `shared.assistant` |
| Zużycie portu modeli | platformy, bez treści | 396 dni | `purge_model_port_usage` | `shared.model_port` |
| Migawka kupującego na zamówieniu zanonimizowanego klienta | klienta firmy | 5 pełnych lat kalendarzowych po roku ostatniego wpisu księgi (stała `BUYER_RETENTION_YEARS`) | wspólny przebieg, przemiatanie `commerce.buyers` | `shared.commerce` |

Znane ograniczenie reguły 30 dni: po oczyszczeniu wiadomości znikają też zdarzenia
dostawcy i ich trasa. Odbicie albo skarga, które przyjdą później, nie znajdą trasy i
zostaną odrzucone — taki adres nie trafi na listę „nie pisz więcej”. Zdarzenie po 30
dniach jest rzadkie; ograniczenie jest przyjęte świadomie.

Na listę przeglądu bezpieczeństwa, nie na teraz: skrót adresu e-mail bez soli
(`sha256(lower(email))` w `EmailSuppression.recipient_hash`) pozwala sprawdzić, czy
znany adres jest w bazie. Skrót z kluczem (HMAC po zapisanej wartości) naprawia to bez
ponownego zbierania adresów.

Otwarte dla tego, kto zbuduje usuwanie konta użytkownika:
`AssistantConversation.created_by` i `AssistantProfileVersion.created_by` mają
`PROTECT` do użytkownika.

## Dowód

- `tests/test_privacy_retention.py`: domyślnie nic; tylko własny wybór firmy; podgląd
  z liczbą i dniem; e-mail do właścicieli i tydzień bez usuwania; przebieg usuwa
  osobę z każdej kopii i zostawia wizytę; dwie firmy z danymi po terminie, jedna
  wyłączona — nietknięta; wyłączenie po podglądzie; błąd jednej firmy; limit;
  wizyta zarezerwowana w trakcie; rezerwacja po usunięciu dostaje nowego klienta;
  wyjątek innego modułu; grupa tylko tam, gdzie profil ją oferuje; zapytania.
- **Baza testowa czyta ponad RLS**, więc testy nie dowodzą izolacji. Dowód na
  działającym stosie pod prawdziwą rolą bazy (firma A włączona, B wyłączona, B
  nietknięta, klienci A po terminie zanonimizowani, pozostali nietknięci, kopie w
  powiadomieniach usunięte) jest pierwszym włączonym przebiegiem lokalnie — przed
  włączeniem harmonogramu. Zrobiony 03.10.2026 na `:8080` ręcznym `--run` (firmy A
  i B, przebieg czekający na blokadę biura w dwóch sesjach psql, powrót klienta jako
  nowy rekord) i odebrany przez koordynatora; dopiero po nim wszedł wpis harmonogramu.
- `test_privacy_retention.py`: wpis harmonogramu jest zarejestrowany, a przy
  wyłączniku operatora zadanie niczego nie usuwa.
- `tests/test_commerce_buyer_retention.py` (plaster 4i): ostatnia sekunda piątego
  roku i pierwsza po nim w strefie firmy; klient z dwoma zamówieniami (opłacone
  trzyma kupującego, nieopłacone nie); wpis księgi dopisany po latach i wpis zapisany
  później, niż się wydarzył; wpis dopisany między wyszukaniem a blokadą; wpłata
  wycofana jako pomyłka przed anonimizacją i po niej; wpłata oznaczona po
  anonimizacji; przebieg firmy omija kupującego do końca okresu, pyta ponownie pod
  blokadą i mówi w podglądzie, ilu zostaje; podgląd anonimizacji przez API. Jak
  wszystkie testy — ponad RLS; izolację tabel commerce dowiódł działający stos przy
  plastrach 4e–4h, 4i nie dodaje tabeli.

## Czego jeszcze nie ma

- reguła dla gospodarstw (po decyzji właściciela produktu) i dolna granica okresu
  z profilu dla gabinetów — niebudowana, bo w MedPlano funkcja zostaje wyłączona
  (wyżej: najkrótszy okres, gdyby ją zaoferować, to 5 lat);
- historia cen przed promocjami (druga połowa plastra 4i w ADR-073) — należy do
  cennika rezerwacji, nie do retencji;
- pozostałe reguły platformy z tabeli wyżej (wiadomości e-mail, zużycie portu modeli)
  zostają przy własnych zadaniach; asystent przeszedł pod wspólny przebieg 03.10
  (`platform_days`, bez okresu ochronnego). Reguła platformy obowiązuje w każdej
  firmie, więc `--dry-run` wypisuje ją tylko tam, gdzie jest co usunąć — firma z
  własną regułą jest na liście od chwili jej włączenia, także z zerem.
