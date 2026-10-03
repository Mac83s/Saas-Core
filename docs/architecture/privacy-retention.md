# Usuwanie danych osobowych po czasie

Plan ustawień firmy D1–D2, odpowiedź właściciela 37a; ADR-078. Firma sama decyduje,
czy i po jakim czasie system usuwa dane osobowe jej klientów i osób, które do niej
napisały. Usunięcia nie da się cofnąć, więc dokument mówi dokładnie, co znika, co
zostaje i dlaczego.

**Zadanie w harmonogramie nie jest włączone.** Usuwa wyłącznie komenda
`manage.py privacy_retention --run`, uruchamiana ręcznie, dopóki koordynator nie
odbierze dowodu z działającego stosu (niżej „Dowód”).

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
  nie ma. W MedPlano nie ma jej do odpowiedzi z listy prawnej (minimalny okres
  przechowywania dokumentacji).

## Kto jest „po terminie”

- **Klient:** niezanonimizowany; jego najpóźniejsza wizyta (w dowolnym stanie)
  skończyła się przed granicą, czyli nic nie trwa i nic nie jest przed nim; klient
  bez żadnej wizyty liczy się od dnia założenia rekordu. Nigdy klient, którego inny
  moduł jeszcze potrzebuje (`register_retention_exclusion` — miejsce na zamówienia i
  dokumenty sprzedaży w okresie ustawowym, gdy powstaną).
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
  identyfikatorów (`FOR NO KEY UPDATE`), a to, czy mają wizytę kończącą się po
  granicy, jest sprawdzane jeszcze raz w nowym zapytaniu — rezerwacja zatwierdzona
  między wyszukaniem a blokadą zostawia klienta. Z drugiej strony `upsert_customer`
  blokuje znalezionego klienta i pyta o niego ponownie, więc rezerwacja złożona w
  trakcie przebiegu dostaje nowego klienta, a nie dopina wizyty do usuniętego;
- najwyżej `RUN_LIMIT` (200) rekordów na firmę i rodzaj danych w jednym przebiegu,
  reszta w następnym; ponowne uruchomienie niczego nie psuje;
- błąd w jednej firmie jest logowany, pozostałe firmy przechodzą, komenda kończy się
  kodem różnym od zera;
- jeden wpis w historii firmy na przebieg i rodzaj danych (`privacy.retention.run`):
  rodzaj, okres, liczba — nigdy osoba.

`--dry-run` liczy to samo i niczego nie zmienia; pokazuje też, co jeszcze czeka na
koniec okresu ochronnego.

## D1 — klient rezerwacji: wszystkie przechowywane kopie

Źródło: `booking.Customer`. Jedna funkcja `strip_customer`
(`shared/booking/services.py`) obsługuje ręczną anonimizację z panelu i przebieg.

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
| Rozmowy z asystentem | osoby z firmy | `assistant.retention.conversation_days` po ostatniej wiadomości (ustawienie platformy, robocza wartość 90) | `assistant-purge` | `shared.assistant` |
| Wersje profilu firmy dla asystenta (`assistant_assistantprofileversion`) — zapowiedziane | firmy; wolny tekst i nazwiska osób z firmy | najnowsza zostaje, starsze po tylu dniach co rozmowy | jeszcze brak — wejdzie przez wspólną rejestrację | `shared.assistant` |
| Zużycie portu modeli | platformy, bez treści | 396 dni | `purge_model_port_usage` | `shared.model_port` |

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
  włączeniem harmonogramu.

## Czego jeszcze nie ma

- zadanie w harmonogramie (czeka na odbiór dowodu);
- reguła dla gospodarstw i minimum dla gabinetów (`settingsDefaults` profilu i dolna
  granica z profilu) — po decyzji właściciela produktu i odpowiedzi z listy prawnej;
- reguły modułów ustawiane przez platformę (rozmowy asystenta, wersje profilu) nie
  są jeszcze zarejestrowane: rejestracja je przyjmuje (`platform_days(<klucz>)`, bez
  okresu ochronnego — test z regułą próbną), a moduły przejdą pod nią, gdy
  harmonogram będzie włączony; do tego czasu zostają przy własnych zadaniach.
