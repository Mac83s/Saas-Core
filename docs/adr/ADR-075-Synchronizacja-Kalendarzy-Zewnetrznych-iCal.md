# ADR-075 — Synchronizacja kalendarzy zewnętrznych (iCal)

**Status:** Accepted — decyzje właściciela (plan rezerwacji uniwersalnych,
odpowiedzi 1–24 z 01–02.10.2026) i decyzje techniczne agenta (T1–T23 planu);
pozostałe rozstrzygnięcia techniczne tego ADR-u (z powodem w tekście): import
tylko do jednostek w fazie 6, adres eksportu kanału bez jego blokad, blokady z
importu tylko do odczytu, a w konflikcie i pod inną blokadą zajmujące termin,
wstrzymanie pustego pliku, kolejka `integrations`, połączenie na sprawdzony
adres, token eksportu bez wygasania, liczby i okna.
**Data:** 2026-10-02
**Rozszerza:** ADR-030 — blokada (`TimeOff`) ze źródłem z kalendarza
zewnętrznego; token eksportu i trasa zadań na wzór samoobsługi i przypomnień.
**Uzupełnia:** ADR-072 §4 („Blokady jednostek rozstrzyga `EXCLUDE`”) o blokadę
jednostki z importu (kanał, UID, konflikt, blokada pod inną blokadą, ponowna
aktywacja) i §5 o blokadę bez aktywnej alokacji, którą kalendarz też liczy (pkt 1
i 6); ADR-029 o pobranie cudzego kalendarza z połączeniem na sprawdzony adres
(pkt 4).
**Doprecyzowuje:** ADR-058, „Ustalenia fazy 3”, punkt „§3” („Nieobecność i
»Usuń z firmy« zdejmują osobę z wizyt”): dotyczy nieobecności wpisanej przez
człowieka; blokada z importu nikogo z wizyty nie zdejmuje (pkt 1).
**Stosuje:** ADR-071 pkt 1 i 20 (napis wydarzenia i e-maile do zespołu na osi
aplikacji, pkt 5 i 6), ADR-073 §5 (rejestr zakresów zadań `service`, pkt 3),
ADR-076 pkt 2 i 5–7 (klasy poleceń, błędy pól, „w imieniu”, podłoga OpenAPI;
pkt 7).

## Kontekst

Pilot (dwa domki na Mazurach) chce łączyć stronę z portalami (np. booking.com,
expedia.com, nocowanie.pl, noclegi.pl, airbnb.com, „być może też za
pośrednictwem GDS”), by pokazywała zajętość z „innych kalendarzy”. API
Booking.com i Airbnb mają tylko certyfikowani partnerzy, GDS nie dotyczy małych
obiektów — zostaje iCal. Plan `saas-core-rezerwacje-uniwersalne-i-sprzedaz`
(„Synchronizacja kalendarzy”, oś „Kalendarze zewnętrzne”, T12, faza 6) ustala
tajny adres iCal jednostki i osoby bez danych osobowych, import z portali co
15 minut z `ETag` do blokad jednostki ze źródłem i UID (oś: także osoby) i
alarm zamiast odwołania; w oknie opóźnienia podwójna rezerwacja jest możliwa.

Kod (main e381199): `TimeOff` nie ma źródła ani UID i leży poza `EXCLUDE`
(sprawdza go Python); `add_time_off` zdejmuje osobę z wizyt; `urllib` po
`validate_webhook_url` rozwiązuje nazwę drugi raz; `encrypt_secret` ma jeden
klucz. Jednostkę (T2), noc (T4, §1) i blokadę pod `EXCLUDE` (§4) daje ADR-072.

## Decyzja

Zasady ustala plan; mechanizmy, nazwy i liczby, których plan nie podaje (lista
w statusie), są decyzjami agenta z powodem w tekście.

### 1. Kanał portalu i blokada z importu

`CalendarChannel` to jeden portal jednej jednostki: `resource`, `label`
(„Booking.com”), `version`, zdrowie (pkt 3), własny adres eksportu (pkt 5) i
opcjonalny adres importu — sekret (adres prywatnego kalendarza daje całe
wydarzenia), więc zaszyfrowany `encrypt_secret` ze skrótem unikalnym w
jednostce, a API pokazuje tylko hosta; bez niego kanał tylko odbiera nasz
kalendarz. Najwyżej 10 kanałów na jednostkę i 300 na firmę. Faza 6 importuje
tylko do jednostek, eksport mają jednostka i osoba; import na osobie przyjdzie
później, osobną decyzją: w odróżnieniu od nieobecności (ADR-058) nie może
zdejmować z wizyt, a kalendarz pracownika wymaga oceny prywatności.

Blokada z importu to blokada jednostki z ADR-072 §4: `TimeOff` ze
`source = ical` (ręczna: `manual`), kluczem obcym `import_channel` (zapis planu
`ical:<kanał>`; usunięcie kanału zabiera jego blokady) i `external_uid` (UID,
przy powtórzeniu z początkiem wystąpienia), unikalnym w kanale. Czas trzyma
własnym wierszem `AppointmentResourceAllocation` pod istniejącym `EXCLUDE`. Gdy
termin trzyma już nasza rezerwacja, zostaje bez aktywnej alokacji i otwiera
konflikt (pkt 6). Gdy trzyma go inna blokada jednostki (ręczna albo z importu,
także z tego samego kanału), zostaje bez aktywnej alokacji i bez konfliktu
(ADR-072 §4), bo termin był już zamknięty i nasza sprzedaż nie jest zagrożona.
W obu przypadkach dalej zajmuje termin (pkt 6), a alokację dostaje, gdy
nakładanie zniknie. Z wydarzenia bierzemy tylko czas i UID — `SUMMARY`,
`DESCRIPTION`, `LOCATION`, `ATTENDEE` i `URL` (imię gościa, końcówka telefonu)
ani plik nie trafiają do bazy ani do logów. Blokady z importu są tylko do
odczytu (`time_off_imported`); zdejmuje je portal albo usunięcie kanału. Nowe
tabele są tenantowe z RLS (poza trasami z pkt 3 i 5), a ich klucze obce i
`import_channel` dochodzą do `booking_validate_tenant_relations()` jak w 0010.

### 2. Odczyt kalendarza

- `icalendar` czyta zawijanie linii i `VTIMEZONE`, ale powtórzeń nie rozwija —
  `RRULE`, `RDATE`, `EXDATE` i `RECURRENCE-ID` rozwija `recurring-ical-events`
  (dwie nowe zależności). Bierzemy `VEVENT` bez `STATUS:CANCELLED` i
  `TRANSP:TRANSPARENT`; `Z` i `TZID` idą do UTC, czas bez strefy i daty — w
  `Organization.timezone` (ADR-030).
- Wydarzenie całodniowe `[D1, D2)` na jednostce z nocami to noce D1…D2−1 i
  zajmuje ją jak rezerwacja tych nocy (T4): od zameldowania D1 do wymeldowania
  D2 plus przerwa po, przy różnych godzinach ofert — najszerszy zakres (lepiej
  zająć za dużo niż za mało). Gdzie indziej data to cały dzień.
- Okno: od początku dzisiejszego dnia lokalnego do 730 dni naprzód; różnica
  działa tylko w nim, więc portal gubiący przeszłe rezerwacje nie rusza
  historii. UID wydany przez nas w eksporcie tej jednostki to echo — pomijamy
  je; nieczytelne wydarzenie pomijamy i liczymy; ponad 2 MiB albo 2000
  wystąpień kończy przebieg błędem bez zmian.

### 3. Przebieg co 15 minut i zdrowie kanału

Kanał z adresem importu ma trasę `CalendarSyncRoute` bez danych osobowych
(zaszyfrowany kontrakt usługi `booking_calendar_sync`, `next_run_at`,
dzierżawa; wzór `ReminderRoute`, w `register_erasure_rows`). Kontrakt, jak przy
przypomnieniu (ADR-058 §7), nie wygasa po `TENANT_TASK_CONTEXT_TTL_SECONDS`
(45 dni; `expires=False`), bo kanał żyje latami; kontrakt, który się nie
otwiera, nie odrzuca trasy jak tam, tylko odsuwa ją o 6 h, a zapis kanału
podpisuje go od nowa. Zakres `booking_calendar_sync` booking wpina w rejestr
`register_service_scope` w `core.organizations`, który powstaje z fazą 4
(ADR-073 §5), nie w listę `_service_context` — rdzeń nie zna nazw modułów
shared.

Dyspozytor (beat co 60 s z `beatSchedule` deskryptora) dzierżawi do 200 tras po
terminie i wysyła przebiegi do kolejki `integrations` z konsumentem
`worker-integrations` (wzór `worker-ai`, ADR-059), żeby wolny portal nie
opóźniał e-maili — tylko przy świeżym śladzie życia konsumenta w cache; bez
niego kolejka nie rośnie, kanały przechodzą w `stale`, a `options/` to podaje.

Przebieg pobiera plik poza transakcją (pkt 4), potem w jednej transakcji, w
kontekście usługi organizacji, porównuje wydarzenia z blokadami kanału po
`external_uid` (dodaje, zmienia, usuwa), zapisuje `ETag` i `Last-Modified`,
sprawdza konflikty (pkt 6) i zdrowie. Wynik przepada, gdy `version` kanału
zmieniła się od startu; wynik, który usunąłby wszystkie przyszłe blokady,
stosujemy dopiero po drugim takim z rzędu (`empty_held`) — jeden pusty plik nie
otwiera zajętych nocy. Nowy adres importu dostaje termin na teraz; po sukcesie
(także 304) kolejny przebieg za 15 minut (T12) z rozrzutem, po błędzie odstęp
rośnie dwukrotnie do 6 h; „Sprawdź teraz” (`…/sync/`, 202) — najwyżej raz na 5
minut. Bez `booking.enabled` nic nie pobieramy, a blokady zostają.

Zdrowie: czasy ostatniej próby i sukcesu, wynik ostatniego przebiegu (enum w
`options/`), liczniki błędów z rzędu, blokad i pominiętych oraz stan `ok`,
`warning` (ostatni przebieg nieudany) albo `stale` (24 h bez sukcesu — raz na
serię komunikat i e-mail `booking.calendar_stale` do odbiorców z pkt 6,
`audience=staff` jak alarm).

### 4. Bezpieczne pobranie

- Tylko `https` (`webcal://` → `https://`) na porcie 443, bez danych logowania
  i fragmentu, host tylko na adresach publicznych (reguły `validate_webhook_url`
  przy zapisie i przed każdym pobraniem); `http://` dałby jawny token portalu.
- Połączenie idzie na adres sprawdzony przed chwilą (nazwa hosta w SNI i
  weryfikacji certyfikatu) — tak zamykamy DNS rebinding wykluczony w ADR-029.
- Bez przekierowań (ADR-029): 3xx kończy przebieg wynikiem `redirect`. Adres
  docelowy, sprawdzony tymi samymi regułami, zapisujemy zaszyfrowany przy
  kanale, API pokazuje tylko jego hosta, a „Użyj adresu docelowego”
  (`…/accept-redirect/` z `expected_version`, bez adresu w historii) przenosi
  go do kanału.
- `GET` z `If-None-Match` / `If-Modified-Since` i `Accept-Encoding: identity`,
  strumieniem do 2 MiB i 10 s na całość; treść musi być `VCALENDAR`. Funkcja
  żyje w `shared.notifications` (właściciel reguł ADR-029), wychodzi przez jego
  `api.py`, a log zna kanał, hosta, status i rozmiar — nigdy adres.

### 5. Eksport: tajny adres jednostki, osoby i kanału

`CalendarExportFeed`: jednostka albo osoba, opcjonalnie kanał jednostki
(`channel`), jeden aktywny adres na cel i kanał, token zaszyfrowany jak
`self_service_token_ciphertext` (uprawniony skopiuje adres ponownie),
`version`, `revoked_at`. Trasa `CalendarFeedRoute` bez danych osobowych (wzór
`SelfServiceRoute`, w `register_erasure_rows`) notuje, najwyżej raz na
godzinę, kiedy portal pobrał adres. Token ma co najmniej 256 bitów i nie
wygasa, bo portal subskrybuje adres latami; firma go unieważnia albo zmienia
(stary daje 404), a `end_person` (ADR-058) i usunięcie kanału unieważniają
adres osoby i kanału.

Treść: aktywne alokacje rezerwacji celu (u jednostki wiersze z `appointment`,
nie z `time_off`; każda rezerwacja, która trzyma termin, także oczekująca —
ADR-072 §9) i jego blokady ręczne (`source = manual`; u osoby nieobecności).
Adres kanału dodaje blokady z importu pozostałych kanałów jednostki, także te
bez aktywnej alokacji (pkt 1), nigdy własne: portal nie dostaje z powrotem
tego, co wysłał, więc jego echo nie podtrzyma blokady po anulowaniu (decyzja
agenta; plan mówi tylko o zajętości bez danych osobowych). Portal dostaje adres
kanału od razu, także bez importu (import dojdzie bez zmiany adresu); adres bez
kanału (np. do własnego kalendarza) nie niesie blokad z importu, więc pętli nie
zrobi.

Wydarzenie: stały napis „Zajęte” w języku panelu firmy
(`Organization.default_locale`, oś aplikacji ADR-071 pkt 1: napis czyta firma i
jej ludzie w portalu i we własnych kalendarzach, nie gość — TL10 go nie
przepina), czas i UID — bez klienta, usługi (w gabinecie bywa daną o zdrowiu)
i powodu nieobecności; UID to skrót identyfikatora z domeną platformy (uuid7
zdradza chwilę utworzenia). Jednostka z nocami dostaje daty (`VALUE=DATE`,
koniec = dzień wyjazdu): noc D jest zajęta, gdy zajętość nachodzi na czas od
zameldowania D do wymeldowania D+1; reszta — czas UTC; okno jak w pkt 2.
`GET /api/v1/booking/calendar/{token}.ics` działa bez sesji, w kontekście
usługi `booking_calendar_feed` dla jednego celu (bez `booking.enabled` — 404),
z limitem zapytań na token, nie na IP (portale pobierają z kilku adresów), z
`ETag` i 304, `Cache-Control: private` i `X-Robots-Tag: noindex`; ścieżki nie
zapisuje żaden log (`log_skip` w Caddy, maska w `JsonFormatter`).

### 6. Konflikt to alarm

Konflikt: blokada z importu nachodzi na aktywną alokację rezerwacji tej samej
jednostki, także oczekującej (T8; trzyma termin jak potwierdzona, ADR-072 §9).
Wydarzenia portalu odmówić nie można, więc synchronizacja nigdy nie odwołuje
ani nie przesuwa rezerwacji — to cudzy fakt do sprawdzenia przez firmę.

Wyścig importu z rezerwacją gościa rozstrzyga `EXCLUDE`: kto zapisuje drugi,
przegrywa — gość dostaje 409 `slot_unavailable`, import zapisuje blokadę bez
aktywnej alokacji i konflikt. Taka blokada, jak każda blokada z importu bez
aktywnej alokacji (pkt 1), dalej zajmuje jednostkę dla kalendarza, wyceny i
zapisu każdej innej rezerwacji (sprawdzenie w Pythonie, jak dziś `TimeOff`),
żeby jej część poza naszą rezerwacją się nie zwolniła.
Każdy przebieg, także po 304 i nieudanym pobraniu, sprawdza wszystkie blokady
kanału: otwiera brakujące konflikty (także z rezerwacją zapisaną w wyścigu z
tym sprawdzeniem), zamyka te, których nakładanie zniknęło, i zakłada alokację
blokady, z którą nic się już nie nakłada (ADR-072 §4).

`CalendarConflict`: `import_channel`, `time_off`, `appointment`,
`detected_at`, `resolved_at`, `resolution` (`gone` albo `acknowledged`); jeden
otwarty na parę, a przyjęty nie wraca, dopóki nakładanie trwa. Nowy konflikt
to w tej samej transakcji `notify_in_app` (`booking.calendar_conflict`,
`warning`) i e-mail `booking.calendar_conflict` (v1, PL/EN; `audience=staff`,
oś aplikacji — ADR-071 pkt 1 i 20) z kluczem idempotencji konfliktu do
aktywnych kont z `booking.appointment.manage` — to one przyjmują i przenoszą
rezerwacje. Treść: firma, czas, kanał, odnośnik — nigdy klient ani usługa
(ADR-030). Konflikt zamyka się sam (`gone`) albo przez
`POST …/conflicts/{id}/acknowledge/` z wpisem w historii.

### 7. Uprawnienia, historia i obsługa przez asystenta AI

- Kanały i adresy jednostki: `booking.appointment.manage`; adres osoby — to
  samo albo sama osoba z `booking.schedule.own` (ADR-058, ustalenia fazy 2);
  `booking.enabled` bez nowej cechy planu, bo iCal to funkcja każdego presetu.
- Historia (`OrganizationAuditAction`, migracja organizations), nigdy adres:
  `booking.calendar_channel.created|changed|deleted|redirect_accepted|synced`,
  `booking.calendar_feed.issued|rotated|revoked`,
  `booking.calendar_conflict.acknowledged`; `synced` to ręczne „Sprawdź teraz”
  (przebieg co 15 minut zapisuje zdrowie kanału, nie historię). Rodzaj aktora
  (`channel` = principal) i „w imieniu” (`acting_via`, `acting_ref`,
  `acting_trigger`) `record_audit` kopiuje z kontekstu (ADR-076 pkt 6; kolumny
  od A1a, organizations 0052).
- API `/api/v1/booking/calendar-sync/` (`channels/`, `channels/preview/`,
  `…/sync/`, `…/accept-redirect/`, `feeds/`, `conflicts/`, `…/acknowledge/`,
  `options/`) z logiką w `booking/calendar_sync.py` (widok, zadanie, komenda)
  spełnia zasadę AGENTS.md o asystencie AI: błędy w `errors` z polem i kodem
  (ADR-076 pkt 5) — `ical_url_invalid`, `calendar_channel_limit`,
  `time_off_imported`, a nieaktualna wersja — 409 `booking_version_conflict`
  (ADR-072 §11); `options/` podaje limity i zbiory. Każda operacja spełnia
  podłogę ADR-076 pkt 7: jawne `operationId`, `summary` i `description`, 400 z
  `ProblemDetails` i wymagany `Idempotency-Key` przy każdej mutacji poza
  `channels/preview/` (`x-dry-run: true`).
- Podgląd kanału pobiera plik w zadaniu na kolejce `integrations`
  (`POST …/channels/preview/` → 202 i stan do odpytania; wynik bez zapisu,
  ważny 10 min, z limitem na firmę), bo żądanie HTTP nie czeka na portal: ile
  blokad doda, zmieni i usunie, z którymi rezerwacjami wejdzie w konflikt, co
  pominie. Zadanie biegnie na kontrakcie usługi z pkt 3, bo kontraktu
  członkostwa nie da się wydać w kontekście „w imieniu” (ADR-076 pkt 6), a
  podgląd zlecony przez asystenta też musi ruszyć; uprawnienie sprawdza widok
  przed zleceniem. Inne mutacje mają `?dry_run=true` (usunięcie kanału: ile
  terminów zwolni i że portal straci nasz adres; nowy token: że portal musi
  dostać nowy).
- `Idempotency-Key` z hashem żądania zapisuje `BookingSetupMutation`
  (organizacja, akcja, principal, klucz, hash żądania, rodzaj i id wyniku;
  unikalny na organizacji, akcji, principalu i kluczu jak
  `booking_mutation_idem_uq`; tabela tenantowa z RLS), wspólny z konfiguracją
  z ADR-072 §11, bo `BookingMutation` ma klucz obcy do wizyty. Zapis niesie
  `expected_version`; nieaktualna to 409.
- Kanał i jego adres założone przez asystenta niosą identyfikator przebiegu
  (pochodzenie jak każda encja konfiguracji, ADR-072 §11), a do uruchomienia
  firmy (plan asystenta, AI-T6) kanał nie pobiera, a adres daje 404.
- Rejestr poleceń (ADR-076 pkt 2): odczyty, stan i podgląd kanału — `read`;
  założenie i zmiana kanału i adresu, „Sprawdź teraz”, „Użyj adresu docelowego”
  i przyjęcie konfliktu — `apply`; usunięcie kanału i nowy token —
  `irreversible` (osobne kliknięcie), bo otwierają terminy albo zrywają import
  lub eksport. Podgląd polecenia jest czysty, bez wywołań zewnętrznych (ADR-076
  pkt 1), więc pliku portalu nie pobiera — skutki importu pokazuje wcześniejszy
  odczyt `channels/preview/`.

## Konsekwencje

- Okno podwójnej rezerwacji to nasze odpytywanie (do 15 min) plus odpytywanie
  portalu (Airbnb: co 3 h — Pomoc Airbnb, art. 99); zapis w regulaminie firmy
  jest już na liście `desk/regulamin-i-pytania-prawne.md` (§2) i nie blokuje
  (decyzja 21).
- Adres kanału odcina echo wprost, ale portal, który eksportuje też noce
  zablokowane cudzym kalendarzem albo ustawieniami (Airbnb: dostępność, czas
  przygotowania, wyprzedzenie, minimalny pobyt — art. 99), odsyła nasze
  rezerwacje pod własnym UID: każda wraca jako konflikt, jego noce blokują
  stronę i przez adresy kanałów inne portale, a dwa takie portale mogą
  podtrzymać blokadę po anulowaniu (A → my → B → my → A). Faza 6 sprawdza
  eksport portali pilota przed alarmem w e-mailach; portal, który odróżnia
  rezerwacje od blokad, dostaje tryb „tylko rezerwacje” — rozpoznanie po
  `SUMMARY` wyłącznie w pamięci, bez zapisu.
- Dwie blokady z różnych kanałów na tych samych nocach to echo albo podwójna
  sprzedaż między portalami, nie do rozróżnienia bez pochodzenia wydarzeń:
  druga zostaje bez aktywnej alokacji i bez konfliktu (pkt 1), alarm dotyczy
  tylko naszych rezerwacji, a widok obłożenia pokazuje oba kanały.
- iCal łączy jednostkę z jednym ogłoszeniem; „typ pokoju × 3” to zadanie
  channel managera (faza 14). Katalog (faza 16) liczy wolne noce tą samą
  funkcją kalendarza, więc blokady z importu działają i tam.
- `_load` musi czytać blokady tylko pytanych celów, bo import dokłada ich setki;
  odbiorców alarmu wyznacza nowy odczyt `core.organizations` (aktywne konta z
  uprawnieniem), bo dziś booking pisze tylko do osób na wizycie.
- Adresy portali i tokeny eksportu to pierwsze długo żyjące sekrety cudzych
  systemów w `encrypt_secret` (faza 6, przed sekretami trybu `own` z fazy 13,
  ADR-073 §6), więc lista kluczy (`MultiFernet`) wchodzi już z fazą 6, a
  `encrypt_secret` i `decrypt_secret` wychodzą przez `notifications/api.py` —
  booking przestaje importować `notifications.security`.
- Webhooki z ADR-029 mają tę samą lukę drugiego rozwiązania nazwy, a ścieżka
  samoobsługi z tokenem (ADR-030) trafia dziś do logów; obie zamkną osobne
  zmiany funkcją pobrania i maską z tego ADR-u.
- Faza 6 niesie to, czego `git pull` nie przeniesie: zależności `icalendar` i
  `recurring-ical-events` (przebudowa obrazu), usługę `worker-integrations`
  (też w overlayach produktów), przeładowanie Caddy po zmianie Caddyfile'ów
  (`log_skip`), zmianę zmiennej kluczy w `.env` i migracje — `memex ops` w tej
  samej sesji. Portal tylko z `http://` nie zadziała.
- Liczby tego ADR-u (2 MiB, 10 s, 2000, 730 dni, 10 i 300 kanałów, 200 tras,
  6 h, 24 h, 5 i 10 min) to ustawienia wdrożenia sprawdzane przy starcie (klasa
  C planu ustawień), nie decyzje właściciela. Pułapki fazy 6 dla skilla
  `develop-booking`: import nikogo nie zdejmuje z wizyty, blokady z importu są
  tylko do odczytu, a bez aktywnej alokacji (konflikt, inna blokada) dalej
  zajmują termin; eksport poza logami.
- Poza zakresem: import na osobie (pkt 1, później); Google Calendar i Outlook
  osób dwustronnie (OAuth), channel manager — faza 14; API portali, GDS, CalDAV.

## Odrzucone

- **Rezerwacje i klienci z wydarzeń portali** — iCal nie niesie danych gościa,
  a rezerwację i pieniądze prowadzi portal; powstaliby fikcyjni klienci.
- **Odwołanie rezerwacji albo odrzucenie wydarzenia przy konflikcie** — plan
  każe alarmować; odrzucenie ukryłoby prawdziwą podwójną rezerwację.
- **Blokada z importu na jednostce tylko w `TimeOff`** — import i rezerwacja
  gościa wygrałyby obie; jedynym sędzią wyścigu zostaje `EXCLUDE` (ADR-030).
- **Jeden adres eksportu celu z blokadami z importu dla wszystkich portali** —
  portal dostawałby z powrotem własne wydarzenia, a echo podtrzymywałoby
  blokadę po anulowaniu.
- **Przejście co minutę przez wszystkie firmy** (`billing_organization_ids()` i
  transakcja na firmę) — co minutę czytałoby rejestr firm przez drzwi
  `PRE_TENANT_DB` i otwierało transakcję w każdej firmie, także bez kanałów;
  trasa z terminem czyta tylko pilne kanały, a kontrakt `service` niesie firmę.
- **Podążanie za przekierowaniem, `http://`, własny parser** — ADR-029, jawny
  token portalu, znane źródło błędów (strefy, zawijanie, powtórzenia).
- **Token eksportu pokazywany raz albo wygasający, limit zapytań na IP** —
  portale dochodzą z czasem, subskrybują latami i pobierają z wielu adresów.
- **Częstsze odpytywanie** — T12; drugą połowę okna i tak wyznacza portal.
