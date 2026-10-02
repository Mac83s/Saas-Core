# ADR-075 — synchronizacja kalendarzy zewnętrznych (iCal): eksport zajętości, import do blokad, konflikt to alarm

**Status:** Accepted — plan właściciela `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
(odpowiedzi 1–24 z 01–02.10.2026; „Synchronizacja kalendarzy”, oś „Kalendarze
zewnętrzne”, decyzja techniczna T12), faza 1, ADR 4.
**Data:** 2026-10-02
**Rozszerza:** ADR-030 — blokada (`TimeOff`) ze źródłem z kalendarza
zewnętrznego; token eksportu i trasa zadań na wzór samoobsługi i przypomnień.
**Doprecyzowuje:** ADR-058, „Ustalenia fazy 3” §2 („Nieobecność … zdejmują osobę
z wizyt”) dotyczy nieobecności wpisanej przez człowieka, nie blokady z importu.
**Uzupełnia:** ADR-029 o pobieranie cudzego kalendarza z połączeniem na adres
sprawdzony przed chwilą (pkt 4).

## Kontekst

Pilot (dwa domki na Mazurach) sprzedaje też przez booking.com, expedia,
nocowanie.pl, noclegi.pl i airbnb i chce widzieć zajętość z „innych
kalendarzy”. API Booking.com i Airbnb mają tylko certyfikowani partnerzy, GDS
nie dotyczy małych obiektów, więc wspólnym mianownikiem jest iCal. Plan ustala:
tajny adres iCal każdej jednostki i osoby (token do unieważnienia, zajętość bez
danych osobowych); adresy z portali pobierane co 15 minut z `ETag` i różnicowo
zamieniane w blokady ze źródłem i UID (oś „Kalendarze zewnętrzne”: import też
per osoba); nakładanie na naszą rezerwację to alarm w panelu i e-mail, nigdy
odwołanie; iCal niesie tylko zajętość, z opóźnieniem, więc w tym oknie podwójna
rezerwacja jest możliwa.

Stan kodu (main e381199): `TimeOff` (osoba albo zasób, czas, powód) nie ma
źródła ani UID i nie jest objęty `EXCLUDE` — silnik sprawdza go w Pythonie, a
`_load` czyta wszystkie blokady firmy w oknie; `add_time_off` zdejmuje osobę z
kolidujących wizyt. Trasy `SelfServiceRoute` i `ReminderRoute` nie mają danych
osobowych i są w `register_erasure_rows`. Żądanie wychodzące to
`validate_webhook_url` i `urllib` bez przekierowań, który rozwiązuje nazwę
drugi raz, więc łączy się z adresem, którego nikt nie sprawdził. Jednostkę
(T2), blokadę i noc (T4) definiuje ADR-072 z tej samej fazy; tu jest to, co z
nich wychodzi i co do nich przychodzi.

## Decyzja

Zasady ustala plan; nazwy i liczby, których plan nie podaje, ustala ten ADR.

### 1. Kanał importu i blokada z importu

`CalendarImportChannel` (tabela tenantowa: wymuszone RLS i strażnik
międzytenantowy): cel — jednostka (`resource`) albo osoba (`staff`), dokładnie
jedno; `label` („Booking.com”); adres zaszyfrowany `encrypt_secret` i jego
skrót, unikalny w celu; `version`; zdrowie (pkt 7). Adres jest sekretem — daje
zajętość, a adres prywatnego kalendarza całe wydarzenia — więc API pokazuje
tylko hosta, a log go nie zna. Najwyżej 10 kanałów na cel i 300 na firmę.

Blokada z importu to wiersz `TimeOff` z ADR-072 z `source = ical`, kluczem
obcym `import_channel` (zapis planu `ical:<kanał>`: usunięcie kanału zabiera
blokady, strażnik sprawdza powiązanie — `import_channel` dochodzi do
`booking_validate_tenant_relations()` migracją z poprzednim ciałem jako
odwrotnością, jak 0010) i `external_key` (UID, przy powtórzeniu z początkiem
wystąpienia), unikalnym w kanale. Z wydarzenia bierzemy tylko czas i klucz:
`SUMMARY`, `DESCRIPTION`, `LOCATION`, `ATTENDEE` i `URL` (bywa tam imię gościa
albo końcówka telefonu) ani pobrany plik nie trafiają do bazy ani do logów.
Blokady z importu są tylko do odczytu (`time_off_imported`, także w
`remove_time_off`); zdejmuje je portal albo usunięcie kanału.

### 2. Odczyt kalendarza

- Parser `icalendar` (nowa zależność; zawijanie linii, `VTIMEZONE` i
  powtórzenia z RFC 5545 to za dużo na własny) czyta `VEVENT` bez
  `STATUS:CANCELLED` i `TRANSP:TRANSPARENT` (czas „wolny” w kalendarzu osoby);
  powtórzenia rozwijamy w oknie. `Z` i `TZID` idą do UTC, czas bez strefy i
  daty — w `Organization.timezone` (ADR-030).
- Wydarzenie całodniowe `[D1, D2)` na jednostce z nocami to noce D1…D2−1 i
  zajmuje ją jak rezerwacja tych nocy (T4): od zameldowania D1 do wymeldowania
  D2 plus przerwa po; przy ofertach o różnych godzinach — najszerszy zakres, bo
  blokada ma raczej zająć za dużo niż za mało. Gdzie indziej data to cały dzień.
- Okno: wydarzenia kończące się po początku dzisiejszego dnia lokalnego i
  zaczynające przed upływem 730 dni; różnica działa tylko w nim, więc portal,
  który gubi przeszłe rezerwacje, nie rusza historii.
- UID wydany przez nas w eksporcie tego celu (portal odsyła nasz kalendarz)
  pomijamy jako echo; nieczytelne wydarzenie pomijamy i liczymy. Ponad 2 MiB
  albo 2000 wystąpień kończy przebieg błędem bez zmian.

### 3. Przebieg co 15 minut

Kanał ma trasę `CalendarSyncRoute` bez danych osobowych (kanał, organizacja,
zaszyfrowany kontrakt zadania organizacji o zakresie `booking_calendar_sync`,
`next_run_at`, dzierżawa) — wzór `ReminderRoute`, w `register_erasure_rows`.
Beat `dispatch_calendar_syncs` co 60 s dzierżawi do 200 tras po terminie i
wysyła zadania `sync_calendar_channel` do kolejki `integrations` z własnym
konsumentem (`worker-integrations`, wzór `worker-ai` z ADR-059), żeby wolny
portal nie opóźniał e-maili i przypomnień.

Przebieg pobiera plik poza transakcją (pkt 4), potem w jednej transakcji, w
kontekście usługi organizacji, porównuje wydarzenia z blokadami kanału po
kluczu (dodaje, zmienia, usuwa; czas liczy od nowa), zapisuje `ETag` i
`Last-Modified`, sprawdza konflikty (pkt 6) i zdrowie. Wynik przepada, gdy
`version` kanału zmieniła się od startu; ten sam plik daje tę samą różnicę.
Wynik, który usunąłby wszystkie przyszłe blokady kanału, stosujemy dopiero po
drugim takim przebiegu z rzędu — jeden pusty plik nie otwiera zajętych nocy.

Po sukcesie (także 304) następny przebieg za 15 minut (T12), z rozrzutem; po
błędzie odstęp się podwaja, do 6 h. Kontrakt, który się nie otwiera, odsuwa
trasę o 6 h (ADR-058 §7), a zapis kanału podpisuje go od nowa. „Sprawdź teraz”
(`…/sync/`) przestawia termin na teraz, najwyżej raz na 5 minut, i odpowiada
202. Bez `booking.enabled` przebieg nic nie pobiera, blokady zostają;
`end_person` (ADR-058) usuwa kanały osoby i unieważnia jej eksport.

### 4. Bezpieczne pobranie

- Tylko `https` (`webcal://` zamieniamy na `https://`), port 443, bez danych
  logowania i fragmentu, host wyłącznie na adresach publicznych — reguły
  `validate_webhook_url` przy zapisie i przed każdym pobraniem. `http://`
  odrzucamy: token portalu szedłby jawnie, a treść dałoby się podmienić.
- Połączenie idzie na adres sprawdzony przed chwilą (nazwa hosta zostaje w SNI
  i weryfikacji certyfikatu) — tak zamykamy DNS rebinding wykluczony w ADR-029.
- Bez przekierowań (ADR-029): 3xx kończy przebieg wynikiem `redirect` z adresem
  docelowym w zdrowiu kanału; firma może go zapisać zwykłą zmianą kanału.
- `GET` z `If-None-Match` / `If-Modified-Since` i `Accept-Encoding: identity`;
  strumieniem do 2 MiB i 10 s na całe pobranie; treść musi być `VCALENDAR`.
- Funkcja żyje w `shared.notifications` (właściciel reguł ADR-029) i wychodzi
  przez jego `api.py`. Log zna kanał, hosta, status i rozmiar — nigdy adres.

### 5. Eksport: tajny adres jednostki i osoby

`CalendarExportFeed` (tabela tenantowa): cel — jednostka albo osoba, jeden
aktywny na cel; token zaszyfrowany jak `self_service_token_ciphertext`, żeby
uprawniony mógł skopiować adres ponownie; `version`, `revoked_at`. Trasa
`CalendarFeedRoute` (skrót tokenu, organizacja, id adresu, `last_fetched_at`
co najwyżej raz na godzinę) — wzór `SelfServiceRoute`, w `register_erasure_rows`.
Token ma co najmniej 256 bitów i nie wygasa, bo portal subskrybuje adres
latami; firma go unieważnia albo zmienia, a stary daje 404.

`GET /api/v1/booking/calendar/{token}.ics` działa bez sesji, w jawnym kontekście
usługi `booking_calendar_feed`, który czyta tylko zajętość jednego celu; bez
`booking.enabled` — 404. Limit zapytań liczy się na token, nie na IP: portale
pobierają z kilku adresów dla wszystkich firm.

Treść: aktywne alokacje celu (każda wizyta, która trzyma termin) i wszystkie
jego blokady, także z importu ze wszystkich kanałów — tak drugi portal widzi
rezerwacje pierwszego — w oknie z pkt 2. Wydarzenie ma stały napis „Zajęte”
(język panelu firmy), czas i UID: bez klienta, usługi (w gabinecie bywa daną o
zdrowiu) i powodu nieobecności; UID to skrót identyfikatora z domeną platformy
(uuid7 zdradza chwilę utworzenia). Jednostka z nocami dostaje daty
(`VALUE=DATE`, koniec = dzień wyjazdu), bo portal noclegowy blokuje noce: noc D
jest zajęta, gdy zajętość nachodzi na czas od zameldowania D do wymeldowania
D+1; reszta — czas UTC. Odpowiedź ma `ETag` z 304, `Cache-Control: private` i
`X-Robots-Tag: noindex`; ścieżki nie zapisuje żaden log (`log_skip` w Caddy,
maska w `JsonFormatter`). Nie jest to wyszukiwanie publiczne z ADR-030 (62
dni): adres zna firma i portal, któremu go dała.

### 6. Konflikt to alarm

Konflikt: aktywna blokada z importu nachodzi na aktywną alokację wizyty tego
samego celu, także wizyty czekającej na potwierdzenie lub wpłatę (T8).
Synchronizacja nigdy nie odwołuje ani nie przesuwa wizyty, nie odrzuca
wydarzenia portalu i nie zdejmuje osoby z wizyty: nieobecność z ADR-058 to
decyzja człowieka, blokada z importu — cudzy fakt do sprawdzenia.

`CalendarConflict` (tabela tenantowa): kanał, blokada, wizyta, `detected_at`,
`resolved_at`, `resolution` (`gone` albo `acknowledged`), jeden otwarty na parę;
`time_off` dochodzi do strażnika. Każdy przebieg sprawdza wszystkie aktywne
blokady kanału, także po 304 i po nieudanym pobraniu: blokady nie obejmuje
`EXCLUDE`, więc rezerwacja gościa w wyścigu z importem może zapisać się obok —
wychwyci ją najbliższy przebieg. Nowa rezerwacja na zablokowany termin dostaje
409 `slot_unavailable`; wyścigi między wizytami dalej rozstrzyga `EXCLUDE`.

Nowy konflikt to w tej samej transakcji `notify_in_app`
(`booking.calendar_conflict`, `warning`) i e-mail `booking.calendar_conflict`
(v1, PL/EN) do aktywnych kont z `booking.appointment.manage` i osoby z kanału,
z kluczem idempotencji konfliktu. Treść: firma, czas, kanał, odnośnik — nigdy
klient ani usługa (ADR-030). Konflikt zamyka się sam, gdy nakładanie zniknie, albo
przez `POST …/conflicts/{id}/acknowledge/` z wpisem w historii.

### 7. Zdrowie kanału

Kanał niesie `last_attempt_at`, `last_success_at`, `last_result` (`ok`,
`not_modified`, `fetch_failed`, `http_error`, `redirect`, `too_large`,
`too_many_events`, `not_calendar`, `url_rejected`, `empty_held`),
`consecutive_failures`, `blocks_count`, `skipped_count`, `next_run_at` i stan
`health`: `ok`, `warning` (ostatni przebieg nieudany), `stale` (24 h bez
sukcesu — raz na serię komunikat i e-mail do osób z pkt 6). Panel pokazuje stan
kanału, blokady z nazwą kanału na widoku obłożenia i otwarte konflikty.

### 8. Uprawnienia, historia i obsługa przez asystenta AI

- Kanały i adres jednostki: `booking.appointment.manage`; osoby — to samo albo
  sama osoba z `booking.schedule.own`, jak godziny i nieobecności (ADR-058,
  ustalenia fazy 2). Entitlement `booking.enabled`, bez nowej cechy planu: iCal
  to funkcja przekrojowa każdego presetu.
- Historia: `booking.calendar_channel.created|changed|deleted|synced` (`synced`
  z liczbą zmienionych blokad, gdy coś się zmieniło),
  `booking.calendar_feed.issued|rotated|revoked`,
  `booking.calendar_conflict.acknowledged` — nigdy adres; wartości
  `OrganizationAuditAction` przychodzą z migracją organizations.
- API pod `/api/v1/booking/calendar-sync/` (`channels/`, `…/sync/`, `feeds/`,
  `conflicts/`, `…/acknowledge/`, `options/`) spełnia zasadę AGENTS.md „API
  obsługiwalne przez asystenta AI”: logika w `booking/calendar_sync.py`,
  wołanym przez widok, zadanie i komendę; serializery z `help_text`, enumami i
  granicami; Problem Details z polem i kodem (`ical_url_invalid`,
  `calendar_channel_limit`, `calendar_channel_changed`, `time_off_imported`…);
  limity, okno i zbiory wartości w `options/`; listy stronicowane z filtrami
  celu i stanu; „Sprawdź teraz” ze stanem do odpytania.
- Podgląd: mutacje konfiguracji przyjmują `?dry_run=true` i liczą ten sam plan
  bez zapisu — kanał pobiera plik raz (w żądaniu, 10 s) i mówi, ile blokad
  doda, zmieni i usunie, z którymi wizytami wejdzie w konflikt i co pominie
  (to jedyny skutek zewnętrzny, opisany w docstringu); usunięcie kanału mówi,
  ile terminów zwolni, zmiana tokenu — że portale muszą pobrać nowy adres.
- `Idempotency-Key` z hashem żądania trafia do wspólnego rekordu mutacji
  konfiguracji rezerwacji (z jednostkami i regułami ADR-072), bo
  `BookingMutation` zna tylko wizyty; zapis niesie `expected_version`, stara
  wersja to 409. Rodzaj aktora i „w imieniu” przyjdą z ADR-076 (zarezerwowany);
  do tego czasu historia zna kanał z `TenantContext.principal_kind`.
- W rejestrze komend zmiany mają ryzyko `apply`; usunięcie kanału i zmiana
  tokenu — z wyraźnym potwierdzeniem, bo otwierają terminy albo zrywają import.

### 9. Poza zakresem

Dwustronny Google Calendar i Outlook dla osób (OAuth) i channel manager (ceny,
reguły pobytu, liczby pokoi) — faza 14; bezpośrednie API portali; GDS; CalDAV.

## Konsekwencje

- Okno podwójnej rezerwacji ma dwie połowy: nasze odpytywanie (do 15 min) i to,
  jak często portal pobiera nasz adres — tego nie kontrolujemy. Zapis do
  regulaminu rezerwacji firmy jest już na liście memex
  `desk/regulamin-i-pytania-prawne.md` (§2) i nie blokuje (decyzja 21).
- iCal łączy jednostkę z jednym ogłoszeniem; ogłoszenia „typ pokoju × 3” nie
  wyrazi — to zadanie channel managera (faza 14). Katalog (faza 16) liczy
  wolne noce tą samą funkcją kalendarza, więc blokady z importu działają i tam.
- `_load` musi czytać blokady tylko pytanych celów, bo import dokłada ich setki.
- Faza 6 niesie to, czego `git pull` nie przeniesie: zależność `icalendar`,
  usługę `worker-integrations` (też w overlayach produktów), `log_skip` w trzech
  Caddyfile'ach i migracje — `memex ops` w tej samej sesji. `_service_context`
  w `core.organizations` dostaje zakres `booking_calendar_sync`.
- Jeden klucz Fernet: jego zmiana czyni adresy portali i tokeny eksportu
  nieczytelnymi, jak dziś linki samoobsługi; wersjonowanie kluczy to osobna
  decyzja (potrzebuje go też ADR-073). Webhooki z ADR-029 mają tę samą lukę
  drugiego rozwiązania nazwy — nowa funkcja pobrania zamknie ją osobną zmianą.
- Echo z UID-em zmienionym przez portal daje fałszywy konflikt do przyjęcia;
  portal tylko z `http://` nie zadziała; prywatny kalendarz z wieloletnią
  historią może przekroczyć 2 MiB — wtedy osobny kalendarz pracy.
- Liczby tego ADR-u (2 MiB, 10 s, 2000, 730 dni, 10 i 300 kanałów, 200 tras na
  minutę, 6 h, 24 h, 5 min) to ustawienia wdrożenia sprawdzane przy starcie
  (klasa C planu ustawień), nie decyzje właściciela. Skill `develop-booking`
  dostaje w fazie 6 pułapki: import nikogo nie zdejmuje z wizyty, blokady z
  importu są tylko do odczytu, eksport nie trafia do logów.

## Odrzucone

- **Wizyty i klienci z wydarzeń portali** — iCal nie niesie danych gościa, a
  rezerwację i pieniądze prowadzi portal; powstaliby fikcyjni klienci.
- **Odwołanie wizyty albo odrzucenie wydarzenia przy konflikcie** — plan każe
  alarmować; odrzucenie ukryłoby prawdziwą podwójną rezerwację.
- **Blokada z importu jako alokacja pod `EXCLUDE`** — wydarzenia portalu nie da
  się odmówić, więc odmowa bazy schowałaby konflikt; sprawdzenie w każdym
  przebiegu wykrywa nakładanie bez przebudowy alokacji.
- **Przejście co minutę przez wszystkie firmy** (`billing_organization_ids`) —
  booking nie zależy od billingu; trasa z terminem czyta tylko to, co pilne.
- **Przekierowania, `http://`, własny parser** — ADR-029, jawny token portalu,
  znane źródło błędów (strefy, zawijanie, powtórzenia).
- **Token eksportu pokazywany raz albo wygasający** — portale dochodzą z czasem
  i subskrybują latami, a adres daje tylko zajętość.
- **Limit zapytań eksportu na IP** — portale pobierają z kilku adresów naraz.
- **Częstsze odpytywanie** — T12; drugą połowę okna i tak wyznacza portal.
