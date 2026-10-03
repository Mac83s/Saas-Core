# Usuwanie danych osobowych po czasie

Stan: **mechanizm bez usuwania** (plan ustawień firmy D1–D2, odpowiedź właściciela
37a; ADR-078). Ten dokument jest listą do przeglądu przed krokiem, który faktycznie
usuwa: każda kopia danych osoby, którą system przechowuje, z rozstrzygnięciem
„usuwane” albo „zostaje” i powodem.

## Co jest dziś w kodzie

- **Ustawienia firmy**, obszar „Prywatność i dane” (`/panel/settings/privacy`),
  domyślnie `off`:
  - `booking.retention.customers` — `off` albo 12, 24, 36 miesięcy od ostatniej
    wizyty klienta (`shared/booking/retention.py`);
  - `sites.retention.inquiries` — `off` albo 12, 24, 36 miesięcy od zapytania
    (`shared/sites/inquiry_retention.py`).
  Zmienia je `organization.settings.manage`; klasa polecenia asystenta to
  `irreversible`, więc asystent sam ich nie włączy. Zmiana zostawia wpis w historii
  ustawień jak każda inna.
- **Podgląd** zapisu (ten sam, który panel pokazuje przed „Zapisz”): ile osób albo
  zapytań wybór obejmuje teraz, i że usunięcia nie da się cofnąć.
- **Kto jest „po terminie”:**
  - klient: niezanonimizowany, jego najpóźniejsza wizyta (w dowolnym stanie)
    skończyła się przed granicą, czyli nic nie trwa i nic nie jest przed nim; klient
    bez żadnej wizyty liczy się od dnia założenia rekordu;
  - zapytanie: przyszło przed granicą, przeczytane czy nie.
  Granica to pełne miesiące kalendarzowe wstecz (`cutoff_for`).
- **Przebieg na sucho** `manage.py privacy_retention --dry-run`
  (`core/organizations/retention.py`): firma po firmie, każda we własnej transakcji i
  własnym tenancie (jak przemiatania billingu, ADR-039); ustawienie firmy jest czytane
  w tej samej transakcji, więc firma, która przed chwilą wyłączyła usuwanie, nie jest
  liczona; firma z `off` nie jest czytana wcale. Bez `--dry-run` komenda odmawia.
- W kodzie **nie ma ścieżki, która usuwa albo zmienia rekord.** Test sprawdza, że
  przebieg nie wykonuje żadnego `INSERT`, `UPDATE` ani `DELETE` i że `SET LOCAL`
  poprzedza pierwszy odczyt klientów.

## D1 — klient rezerwacji: wszystkie przechowywane kopie

Źródło: `booking.Customer`. Ręczne `anonymize_customer`
(`shared/booking/services.py`) czyści dziś tylko pierwsze trzy wiersze tabeli.

| Kopia | Co zawiera | Krok usuwający | Powód |
|---|---|---|---|
| `Customer.display_name`, `email`, `phone`, `contact_hash` | dane kontaktowe | **usuwa** (jak `anonymize_customer`: „Zanonimizowany klient”, puste pola, nowy skrót, `anonymized_at`) | to jest usuwana dana |
| `Appointment.customer_notes` | uwagi klienta do wizyty (w gabinecie: zdrowie) | **usuwa** | jak dziś przy ręcznej anonimizacji |
| `Appointment.place_address` | ulica wizyty u klienta | **usuwa** | jak dziś |
| `Appointment.place_town` | miejscowość wizyty | zostaje | nie wskazuje osoby; decyzja z ADR-066, potrzebna w statystykach dojazdów |
| `NotificationMessage.recipient_email` (potwierdzenie, przypomnienie, zmiana, odwołanie) | adres klienta | **usuwa**, jeśli jeszcze jest | moduł powiadomień sam zastępuje adres po 30 dniach (`NOTIFICATIONS_RETENTION_DAYS`); krok domyka przypadki, w których tamto czyszczenie się nie wykonało (niżej) |
| `NotificationMessage.context` wiadomości do klienta | nazwa firmy, termin, link do zarządzania wizytą (z tokenem) | **usuwa**, jeśli jeszcze jest | jak wyżej |
| `NotificationMessage.recipient_hash` | `sha256` adresu, bez soli | **do decyzji** (propozycja: zastąpić skrótem identyfikatora wiadomości) | skrót adresu e-mail pozwala sprawdzić, czy znany adres dostał wiadomość — to dana pseudonimowa; dziennik doręczeń nie potrzebuje go po anonimizacji |
| `EmailSuppression.recipient_hash` | skrót adresu, który odbił albo zgłosił spam | zostaje | lista „nie pisz więcej” musi przeżyć klienta, inaczej firma napisze ponownie na adres, który tego zabronił; wpis nie wskazuje wizyty ani osoby |
| `NotificationAttempt` | wynik i kody doręczenia | zostaje | bez danych osoby |
| Link „zarządzaj wizytą” (`SelfServiceRoute`, `Appointment.self_service_token_ciphertext`) | token okaziciela do jednej wizyty | **unieważnia**, jeśli jeszcze działa | nie jest daną kontaktową, ale po anonimizacji nie ma komu służyć; dziś gaśnie przy odwołaniu, zakończeniu i nieobecności, a wizyta „potwierdzona” w przeszłości mogła go zachować |
| `BookingMutation.request_hash` | skrót żądania (m.in. dane klienta) | zostaje | sam skrót całego żądania, nieodwracalny i bez pola osoby; trzyma idempotencję |
| `OrganizationAuditEntry` rezerwacji | identyfikatory, terminy, miejscowość przy zmianie miejsca | zostaje | brak imienia, adresu, telefonu i uwag; historia jest tylko do dopisywania |
| `AppNotification.payload` (powiadomienia zespołu) | identyfikator wizyty, termin, nazwa usługi | zostaje | bez danych klienta |
| `Appointment` (termin, usługa, osoba z firmy, kwoty), `AppointmentStatusHistory`, materiały, dokumenty magazynu z `source_reference` | fakty o wizycie | zostaje | to zapis pracy firmy; klient jest już nienazwany |
| `Customer.locale`, `created_at` | język, data rekordu | zostaje | nie wskazują osoby |

Poza zasięgiem kroku — do powiedzenia firmie wprost:

- **e-maile już doręczone** klientowi i kopie na skrzynkach firmy;
- **tekst wpisany ręcznie** przez pracownika w polach, które nie są danymi klienta:
  `StockDocument.counterparty`/`note` (odbiorca wydania), `TimeOff.reason`, rozmowa
  z asystentem — system nie wie, że nazywają osobę;
- **pliki e-maili na dysku** w środowisku z plikowym backendem poczty (lokalnie i na
  dev VPS, `EMAIL_FILE_PATH`): pełna treść i adres, poza bazą. Produkcja wysyła przez
  dostawcę i plików nie ma; na dev VPS trzeba je czyścić osobno;
- **dane z modułu produktu** dowieszone do wizyty (np. HoofCare) — produkt rejestruje
  własne czyszczenie, tego repozytorium nie widać.

## D2 — zapytanie ze strony: wszystkie przechowywane kopie

Źródło: `sites.SiteInquiry`.

| Kopia | Co zawiera | Krok usuwający | Powód |
|---|---|---|---|
| `SiteInquiry.name`, `email`, `phone`, `message` | dane i treść | **usuwa** (puste pola, znacznik czasu usunięcia) | to jest usuwana dana |
| `SiteInquiry` — wiersz: data, strona, język, publikacja | fakt zapytania | zostaje | statystyki strony liczą zapytania z tych wierszy (`sites/measurement.py`); bez danych osoby |
| `SiteInquiry.request_hash` | skrót całego formularza | **usuwa** (zastąpiony) | po usunięciu treści skrót nie ma czego chronić, a pozwalałby potwierdzić znaną treść |
| `NotificationMessage.context` powiadomienia o zapytaniu — po jednym dla każdego odbiorcy | imię, e-mail, telefon, treść | **usuwa**, jeśli jeszcze jest — wszystkie wiadomości z `causation_id = site-inquiry:<id>`, nie tylko ta z klucza obcego | moduł powiadomień czyści `context` po 30 dniach; krok domyka przypadki niżej |
| `NotificationMessage.recipient_*` tych wiadomości | adres osoby z firmy | zostaje | to nie są dane pytającego |
| `OrganizationAuditEntry` `sites.inquiry.received` / `.read` | identyfikatory | zostaje | bez danych pytającego |

Poza zasięgiem kroku: e-mail z zapytaniem na skrzynce firmy; pliki e-maili na dysku
jak wyżej.

## Czyszczenie wiadomości po 30 dniach — luki do zamknięcia razem z krokiem

`scrub_notification_message` zastępuje adres i czyści `context` po
`NOTIFICATIONS_RETENTION_DAYS` (30), ale:

1. otwiera tenanta kontraktem podpisanym przy wysyłce (ważny 45 dni); dla wiadomości
   podpisanej członkostwem, które przestało być aktywne, odmawia i próbuje co
   5 minut bez końca — wiadomość zostaje nieoczyszczona;
2. usuwa `ProviderMessageRoute`, do którego `ProviderEventInbox.route` ma `PROTECT` —
   wiadomość ze zdarzeniem dostawcy wywróci czyszczenie wyjątkiem, którego zadanie
   nie łapie;
3. nie ma żadnego testu.

Krok usuwający nie może więc zakładać, że kopie w powiadomieniach już nie istnieją:
sprawdza je i czyści sam, w tenancie firmy. Naprawa samego czyszczenia po 30 dniach
należy do modułu powiadomień.

## Czego jeszcze nie ma (krok usuwający)

- usuwanie: funkcje modułów wywoływane z tego samego przebiegu, każda firma we
  własnej transakcji, ponowne uruchomienie niczego nie psuje;
- test „firma wyłączyła usuwanie między podglądem a przebiegiem — nic nie traci”
  (dziś: ten sam odczyt ustawienia w transakcji firmy, sprawdzony na przebiegu na
  sucho);
- zadanie w harmonogramie i wpis w historii firmy o każdym przebiegu („usunięto dane
  N klientów”), bez danych osób;
- minimum dla gabinetów: `settingsDefaults` profilu i dolna granica z profilu — po
  odpowiedzi z listy prawnej.
