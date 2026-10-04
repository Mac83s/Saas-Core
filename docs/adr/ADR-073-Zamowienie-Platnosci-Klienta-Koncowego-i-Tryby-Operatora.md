# ADR-073 — Zamówienie, płatności klienta końcowego i tryby operatora

**Status:** Accepted — decyzje właściciela (plan rezerwacji uniwersalnych,
odpowiedzi 1–24 z 01–02.10.2026 oraz 28a i 29a z 02.10) i decyzje techniczne
agenta (T1–T23 planu); pozostałe rozstrzygnięcia techniczne tego ADR-u (z
powodem w tekście): kierunek zależności, rejestr źródeł i `commerce.enabled`
(§1), strażnik `deployment-check` dla customers bez booking (§2), `draft` bez
numeru dla `pending_request` (§3), termin płatności w commerce, przelew zamiast
online, należność na miejscu bez `pending_payment` i rejestr
`register_service_scope` (§5), skrzynka zdarzeń, lista kluczy oraz osobny
endpoint i sekret webhooków kont połączonych — odstępstwo od planu (§6),
kaucja z linku (§8; podstawa progu zwrotu to decyzja właściciela 28a),
dokumenty w customers z tekstem tylko do dopisywania (§9), ścieżki gościa pod
`commerce.public.pay` (§11).
**Data:** 2026-10-02
**Częściowo zastępuje:** ADR-037 §1 (zależność od booking), §2 (konta Express,
prowizja w katalogu), §3 (`AppointmentPayment`, `tax_rate_bp`; „nigdy z
formularza” tylko w trybie `platform`), §4 (cena, waluta i `tax_rate_bp` jako
pola `Service`, jedno okno 15 min, wygaszanie w booking), §5 pkt 1 (warunek
`charges_enabled`), 3 i 5, §6 (trasa w trybie `own`, treść skrzynki), §7
(„i zdarzeniem”, podstawa zwrotu), §8 („organizacja nie wybiera operatora”,
wartość `stripe`); ADR-036 §5 („zostaje w `shared.booking`”). Reszta ADR-037
wraca z odroczenia jako źródło przepływu i księgi. **Zmienia (z ADR-072):**
ADR-030, zdanie „płatność i zaliczka są poza pierwszym zakresem W9”.
**Doprecyzowuje:** ADR-036 §8 (dokumenty sprzedaży, §9). **Uzupełnia:**
ADR-072, ADR-074, ADR-075. **Nie zmienia:** ADR-026, ADR-032, ADR-034, ADR-040,
ADR-042.

## Kontekst

Właściciel 01.10: każda rezerwacja i każdy zakup w sklepie to zamówienie z
numerem, zgodami i płatnością; płatności klientów firm idą przez platformę —
najpierw Stripe Connect z naszą prowizją, port gotowy na własne konto firmy
(decyzje 3 i 2a). ADR-037 (odroczony od 02.09) opisał jedną wizytę, bez sklepu,
zadatku z dopłatą, kaucji i własnego konta; `Customer` jest dziś w booking.

## Decyzja

### 1. Moduły i kierunek zależności

- **`shared.customers`** (`dependsOn: ["core.organizations"]`,
  `/api/v1/customers`, `customers.read` i `customers.manage`, bez cechy planu):
  klient, dokumenty firmy i zgody (§2, §9).
- **`shared.commerce`** (deskryptor z ADR-037 §1, z `shared.customers` zamiast
  `shared.booking`): cecha `commerce.enabled` w każdym planie (wniosek z 7a:
  okresy i sklep są w każdym planie, a potrzebują zamówienia) i
  `commerce.own_account.enabled` dla `own` (płatna opcja, 2a). Pozycja wskazuje
  źródło napisem (`source`, `source_reference`), jak `StockReservation`.
- **`shared.booking`** zależy od customers, a commerce używa opcjonalnie
  (`ACTIVE_MODULES` i leniwy import, wzorzec `shared/booking/materials.py`); bez
  commerce albo bez cechy przyjmuje tylko `none` i `on_site` (ADR-072 §8).
- **Rejestr źródeł** `commerce.api.register_order_source(kind, prefix, handler)`
  (jawny punkt rozszerzenia z `AppConfig.ready`, ADR-024): booking — `R`, sklep
  — `Z` (ADR-074). Handler działa w transakcji zmiany stanu zamówienia, w
  punkcie zapisu. Przejście od operatora (opłacone, zwrócone, spór) zapisuje się
  zawsze; gdy źródło go nie przyjmie (rezerwacja wygasła, termin zajęty),
  handler zwraca odmowę zamiast wyjątku, a commerce zleca zwrot i zgłoszenie
  operatorskie (ADR-037 §6). Przejście od firmy albo klienta przy odmowie
  wycofuje się całe; zlecone przez źródło nie wraca do jego handlera; wywołania
  operatora (anulowanie intencji, zwrot) idą po commicie z kluczem idempotencji.
  Do tego `place_order(...)` w transakcji źródła i `ORDER_MODEL` dla tabel
  szczegółów (wzór `APPOINTMENT_MODEL`).
- Tabele mają wymuszone RLS i strażnika relacji; księga, wersje dokumentów i
  ich teksty, zgody i nadpisania prowizji są tylko do dopisywania (furtka
  usunięcia tenanta, ADR-042), trasy bez danych osobowych w
  `register_erasure_rows`. Booking nie ma kluczy obcych do commerce, bo działa
  też bez niego.

### 2. Klient w `shared.customers`, ta sama tabela (T10)

- `Customer` przechodzi samym stanem modelu (`SeparateDatabaseAndState`,
  odwracalne); tabela `booking_customer` z RLS i mapą wyzwalacza zostaje w
  migracjach booking (0002, 0003, 0010). Deskryptor nie wyrazi, że customers ma
  wtedy tabelę tylko obok booking (odwrotna zależność to cykl), więc
  `deployment-check` odrzuca profil z customers bez booking, dopóki osobna,
  odwracalna migracja nie odda customers tabeli, polityki i strażnika — przed
  pierwszym profilem sklepu bez rezerwacji (ADR-074).
- Dopasowanie (`customers.api.match_or_create`) i anonimizacja działają jak
  dziś; `create_appointment(customer_data=…)` zostaje kontraktem produktów.
  Anonimizacja woła w swojej transakcji `register_customer_anonymizer`: booking
  czyści uwagi, ulicę wizyty i pola własne (ADR-072 §8), commerce — migawkę
  kupującego, sklep — dane dostawy; endpoint zostaje w booking. `Customer.user`
  (ADR-036 §5) powstaje tutaj. `Customer.locale` (dziś w booking, z wyborami
  pl/en) przechodzi stanem razem z modelem; wybory zdejmuje TL10 (ADR-071 pkt
  3) migracją tej aplikacji, która wtedy trzyma stan `Customer` (Konsekwencje).

### 3. Zamówienie: `Order` i `OrderLine` (T9)

- `Order`: `number`, `customer`, migawka kupującego (nazwa, e-mail, telefon,
  dane do faktury z opcjonalnym NIP), `currency`, `status`, `channel`
  (`company_site`, `catalog`) z podpisanym tokenem pochodzenia, `version`. Kanał
  i token zapisuje rezerwacja niezależnie od commerce (ADR-072 §11), zamówienie
  je kopiuje, sklep zapisuje na swoim; token jedzie w adresie albo stanie
  widgetu, nigdy w ciasteczku.
- Numer `{prefiks}/{rok}/{NNNN}` (`R/2026/0001`) powstaje przy złożeniu z
  licznika (firma, prefiks, rok) pod `select_for_update`, z rokiem w strefie
  firmy (`timezone.localdate()` przy UTC myli go w noc sylwestrową).
- `OrderLine`: `kind` (`booking`, `product`, `extra`, `discount`, `voucher`,
  `delivery`, `fee`), `quantity`, `unit_gross_minor`, `unit_net_minor`,
  `tax_rate` (§8), migawka nazwy w języku klienta i w języku źródłowym
  (ADR-072 §7), `source`, `source_reference`. Pozycje przychodzą gotowe z
  `quote` (ADR-072 §7) albo z koszyka (ADR-074); commerce cen nie liczy, a
  złożonych pozycji nie zmienia — korekta to nowa pozycja. Nazwa w języku
  klienta trafia do jego e-maili i samoobsługi, źródłowa — do panelu i programu
  do faktur; migawki nie da się poprawić później. Bony, karnety i kody rabatowe
  (faza 10) też należą do commerce.
- Statusy `draft`, `awaiting_payment`, `partially_paid`, `paid`, `fulfilled`,
  `completed`, `canceled`, `refunded` zmienia tylko commerce; to skrót dla list,
  o pieniądzach rozstrzyga księga, a `fulfilled` zgłasza źródło.
- Gdzie commerce działa, rezerwacja należy do jednego zamówienia założonego w
  jej transakcji (ADR-037 §5 pkt 1); stare wizyty zostają bez zamówień. Okno
  odbioru sklepu podpina się pod zamówienie `Z` nowym, opcjonalnym argumentem
  `booking.api.create_appointment` (zmiana addytywna, ADR-072 §11), bez osobnego
  `R` i z potwierdzeniem w e-mailu zamówienia. `pending_request` zakłada `draft`
  bez numeru i płatności; numer i należności powstają przy akceptacji (ADR-072
  §9), odmowa daje `canceled`.

### 4. Płatność opłaca zamówienie (uogólnienie ADR-037 §3)

- `Payment` zamiast `AppointmentPayment` wskazuje `order` i dostaje `kind`
  (`deposit`, `balance`, `full`, `security_deposit`), `method` (`online`,
  `transfer`, `cash`, `cash_on_delivery`), `connection`, `due_at`, `version` i
  status `authorized` (blokada kaucji); najwyżej jedna oczekująca na rodzaj.
  `Refund` i `Dispute` wiszą na `Payment`.
- `LedgerEntry` (rodzaje ADR-037 §3) wiąże zamówienie i płatność; wpłata ręczna
  to `charge` bez opłat, zwrot ręczny — `refund`. Kaucja ma własne rodzaje
  (`security_received`, `security_returned`, `security_retained`) poza
  należnością i podstawą prowizji. Suma wpisów zamówienia odtwarza należność,
  wpłaty, prowizję, opłatę operatora, zwroty i wypłatę — to bramka fazy 7.

### 5. Należność, metody ręczne i termin płatności

- Polityka płatności i progi anulowania to dane oferty w migawce (ADR-072 §8);
  zamówienie zamienia je na płatności z terminami (bez rezerwacji termin podaje
  źródło, np. sklep). Metody ręczne — gotówka i terminal, przelew z numerem
  zamówienia w tytule, za pobraniem — działają od fazy 4; wpłatę oznacza firma.
  Online wymaga połączenia z `charges_enabled`; bez niego należność idzie
  przelewem, jeśli firma podała rachunek, a dopiero bez niego — na miejscu. To
  domyślne Noclegu z 13a („dopóki nie ma płatności online — zadatek przelewem w
  3 dni”), uogólnione przez ten ADR: przelew zachowuje wpłatę z góry. Gdy
  należność idzie na miejscu, rezerwacja powstaje jako `confirmed` (jak
  `on_site`), bez `pending_payment` i bez `due_at` — wpłaty na miejscu gość
  nie złoży przed rozpoczęciem rezerwacji, więc wstrzymanie skończyłoby się
  tylko wygaśnięciem. Polityki `transfer` bez rachunku firmy serwis oferty nie
  przyjmuje (`transfer_account_missing`) i z tego samego powodu nie usuwa
  rachunku, z którego taka oferta korzysta.
- Oferta z wpłatą przed potwierdzeniem (`transfer`, `deposit`, `full`), której
  wpłatę da się złożyć z góry — online albo przelewem — tworzy
  `pending_payment`, które trzyma termin jak potwierdzona (ADR-072 §9,
  zawężenie ADR-058 §3 oparte na 13a); bez commerce ten stan nie powstaje.
- **Termin należy do commerce**: rozstrzyga `Payment.due_at` (online domyślnie
  15 minut, rekomendacja ADR-037; przelew — dni z oferty, Nocleg 3). Zadanie
  terminów czyta trasę bez danych osobowych (`payment_id`, `organization_id`,
  `due_at`, niewygasający kontrakt `service` organizacji; wzorzec
  `ReminderRoute`, ADR-058 §7) i dla wpłaty przed potwierdzeniem w jednej
  transakcji wygasza płatność, anuluje zamówienie, a handler źródła zwalnia
  rezerwację (z powodem w historii) albo towar. `Appointment.hold_expires_at`
  to kopia `due_at` do wyświetlania, a booking sam wygasza tylko
  `pending_request` (odpowiedź firmy), tą samą drogą.
- **Zakresy kontraktów `service`** moduły wpinają w nowy rejestr
  `core.organizations.register_service_scope` z `AppConfig.ready` (rola i
  dozwolone uprawnienia; moduł może dopisać własne uprawnienie do zakresu
  innego modułu), nie w listę `_service_context` — rdzeń nie zna nazw modułów
  shared. Rejestr powstaje z fazą 4, bo ona pierwsza dodaje zakresy:
  wygaszanie `pending_request` (booking), terminy płatności (commerce) i
  `commerce.public.pay` w `public_booking` (§11); dzisiejsze wpisy listy
  przenoszą do niego booking i sites. ADR-075 (iCal) i ADR-074 (termin
  przelewu sklepu) korzystają z tego samego rejestru.
- Płatność online potwierdzona po terminie wraca zwrotem (odmowa handlera, §1);
  spóźniony przelew firma zwraca albo rezerwuje od nowa.
- **Dopłata po terminie** (decyzja właściciela 29a, 02.10): niezapłacona w
  terminie `balance` niczego nie wygasza ani nie anuluje, a rezerwacja zostaje
  `confirmed`. Gość dostaje przypomnienia, a firma alert; o odwołaniu
  rezerwacji decyduje sama firma, a takie odwołanie rozlicza zadatek według
  progów z migawki (§8). Zadanie terminów przy `balance` tylko zgłasza
  zaległość; nic nie dzieje się automatycznie, bo firma wie, czy przelew jest
  w drodze, a automat odwołałby rezerwację za jeden spóźniony przelew.
- E-maile do gościa z tej sekcji (dane do przelewu z terminem, przypomnienie
  dopłaty, zwrot) to szablony `audience=customer` w języku klienta
  (`Customer.locale` przycięty do `public_locales`, ADR-071 pkt 21) z
  łańcuchem żądany → en → pl rozstrzyganym przy kolejkowaniu (ADR-071 pkt 20);
  alert dla firmy — `audience=staff`, oś aplikacji (ADR-071 pkt 1).

### 6. Port płatności: tryby `platform` i `own` (T11)

- `PaymentProviderConnection` (pola ADR-037 §3) dostaje `mode` (`platform` |
  `own`) i `adapter` (`stripe_connect`, `przelewy24`, `payu`, `simulated`),
  jedno na firmę i adapter; tryb wybiera firma, metody daje `capabilities`.
- **`platform`** (faza 7, po W9.5.2S): Stripe Connect, direct charges z
  `application_fee_amount`; zwroty, spory i opłaty obciążają firmę (ADR-037 §2).
  Konta według rekomendacji Stripe z fazy 7, nie Express. Konto platformy to
  samo co abonamenty, ale zdarzenia kont połączonych mają osobny endpoint i
  sekret, bo Stripe wysyła je osobno (sprawdzić w fazie 7) — odstępstwo od
  zapisu planu o jednym zestawie webhooków. Jeden operator trybu `platform` na
  deployment (`COMMERCE_PROVIDER`: `stripe_connect`, odtąd zamiast `stripe` z
  ADR-037 §8, bo wartość to nazwa adaptera; `simulated` poza produkcją).
- **`own`** (faza 13): własne konto firmy, najpierw Przelewy24, bo Stripe nie
  daje P24 noclegom (MCC 7011, 7033, 6513) ani medycynie. Firma wpisuje
  `merchantId`, `posId`, klucz CRC i `secretId`; `charges_enabled` daje dopiero
  udane wywołanie testowe API operatora jej kluczami, `capabilities` — lista
  metod operatora. Opłacone dopiero po `PUT /transaction/verify`; bez prowizji.
- Sekrety `own` i tokeny programu do faktur szyfruje `encrypt_secret` (nie
  wracają z API, nie trafiają do logów ani audytu). Lista kluczy (`MultiFernet`)
  dla wszystkiego, co ono szyfruje (też tokeny samoobsługi i kontrakty tras),
  wchodzi z fazą 6: adresy portali i tokeny eksportu (ADR-075) to pierwsze
  długo żyjące sekrety cudzych systemów. `encrypt_secret` i `decrypt_secret`
  wychodzą wtedy przez `notifications/api.py`, a booking przestaje importować
  `notifications.security`.
- Webhook ma globalny adres per adapter; firmę wyznacza indeks routingu bez
  danych osobowych (wzorzec `SelfServiceRoute`): w `platform`
  `external_account_id` (ADR-037 §6), w `own` losowy identyfikator trasy w
  adresie powiadomienia, zanim podpis sprawdzi klucz CRC firmy. Skrzynka
  zdarzeń to tabela platformowa (ADR-041 §1) z samymi identyfikatorami (id i typ
  zdarzenia, konto albo trasa, id obiektu, czasy operatora i podpisu, stan,
  próby); obiekt z danymi płacącego commerce pobiera od operatora w kontekście
  firmy i trzyma tylko w tabelach tenantowych, które obejmują anonimizacja
  (ADR-030) i usunięcie tenanta (ADR-042). Rekonsyliacja: lista z
  `billing.api.billing_organization_ids()`, potem transakcja z `SET LOCAL` na
  firmę (`billing_tenant_scope` wchodzi do `billing.api`; dziś jest prywatny).

### 7. Prowizja platformy

- Procent plus kwota stała według planu (3a): Profil 2% + 0,50 zł, Starter
  1,5% + 0,30 zł, Pro 1% + 0 zł (11a). Stawki to ustawienie platformy z datą
  wejścia w życie (T23); do panelu „Platforma” — wartość domyślna w rejestrze
  ustawień i `platform_setting --operator --reason` (faza 1 planu ustawień).
- Nadpisanie stawki firmy z datą ważności, powodem i autorem (T18) to rekord w
  commerce z fazy 7, ale nie operacja API firmy: działa za bramką operatora
  (staff, MFA, poziom 2 sprawdzany wprost, ponowne uwierzytelnienie — U2 i S-T7
  planu ustawień) i pisze ścieżką operatora w cudzym tenancie (osobny ADR).
- Prowizję liczy się raz, przy tworzeniu płatności online w `platform`, ze
  stawki z tej chwili (nadpisanie przed planem) i zapisuje w płatności; zwrot
  oddaje ją proporcjonalnie (3a: `refund_fee_reversal`, w Stripe
  `refund_application_fee`). Płatności ręczne, `own` i kaucja jej nie mają.

### 8. Zwroty, kaucja, waluta i podatek

- **Zwrot.** Rezygnacja klienta liczy zwrot z progów w migawce, według pełnych
  dni do początku w strefie firmy; Nocleg: ≥ 30 dni 100%, 14–29 dni 50%, < 14
  dni 0% (13a, „zwrot zadatku”). Czego progi dotyczą, rozstrzyga decyzja
  właściciela 28a (02.10): domyślnie tylko zadatku, a dopłata i inne wpłaty
  wracają w całości. Firma zmienia to jawnym przełącznikiem „Progi zwrotu
  obejmują też dopłatę” w ustawieniach oferty w panelu (w presecie Nocleg
  wyłączony). To ustawienie firmy czytane i zmieniane przez API oferty (panel i
  asystent, ADR-072 §11), a nie samo pole w danych, bo firma ma świadomie
  wybrać, czy gość traci część dopłaty. Migawka i kontrakt presetów zapisują je
  jako `cancellation.appliesTo` (ADR-072 §8): `deposit` — przełącznik
  wyłączony, `paid` — włączony, progi obejmują wszystkie wpłaty. Przy
  `transfer` i `full` zadatku nie ma, więc progi obejmują całą wpłatę (`paid`).
  Online zwraca adapter, ręczną wpłatę firma oddaje sama; zwrot spoza progów
  wymaga powodu.
- **Odwołanie przez firmę** zwraca co najmniej wszystkie wpłaty, poza
  odwołaniem za niezapłaconą dopłatę (29a, §5), które rozlicza zadatek według
  progów jak rezygnację gościa. Lista prawna sprawdza, czy wpłata nazwana
  zadatkiem jest nim w rozumieniu art. 394 KC (a nie zaliczką) i czy przy
  odwołaniu przez firmę należy się więcej (art. 394 § 1 KC); to sprawdzenie
  zgodności regulaminów z prawem, nie otwarta decyzja biznesowa.
- **Kaucja** (`security_deposit`) nie jest pozycją ani przychodem. Blokadę
  kartą zakłada klient z linku tuż przed przyjazdem, w oknie operatora (7 dni,
  do 30 dla noclegów i pojazdów z rozszerzoną autoryzacją); po pobycie firma
  pobiera część (pozycja `fee` z powodem) albo zwalnia. Poza oknem kaucja idzie
  przelewem albo gotówką.
- **Waluta** (16, T22): `Organization.currency` tylko z listy platformy (PLN,
  EUR, USD); zmianę waluty firmy z cenami albo zamówieniami odrzucamy
  (`currency_in_use`), bo tych kwot nikt nie przeliczy. Płatność zawsze w
  walucie zamówienia.
- **Podatek.** Pozycja niesie kod stawki z listy w kodzie (dziś `23`, `8`, `5`,
  `0`, `zw` jak `VatRate` magazynu oraz `np` — „nie podlega”, opłata
  miejscowa, ADR-072 §6), bo `zw` to nie `0`, a `np` to nie `zw`; netto i
  brutto liczy `quote` (ADR-072 §6–§7), stawkę wybiera firma. ADR-040 dotyczy
  abonamentów.

### 9. Dokumenty, zgody, faktury (T15, T16)

- Dokumenty firmy dla klientów (regulaminy rezerwacji i sklepu, polityki
  prywatności i anulowania) żyją w `shared.customers`, najniższym module
  wspólnym dla rezerwacji, zamówień i sklepu. Edytowalny szkic (od asystenta —
  z identyfikatorem przebiegu, §11) zatwierdza osoba z firmy przez
  `assert_person_required` ze step-upem `legal_document` (ADR-076 pkt 2 i 6),
  co zapisuje wersję tylko do dopisywania, obowiązującą od daty; tylko taką
  przyjmują rezerwacja i zamówienie.
- Wersja ma tekst na język jako wiersze tylko do dopisywania (język, tekst,
  skrót tekstu, pochodzenie `content_protocol.provenance.Provenance`, kto i
  kiedy zaakceptował): poprawka to nowy wiersz, więc tekst, na który klient się
  zgodził, nigdy się nie zmienia (nie wzór `PublicProfileTranslation`,
  Odrzucone). Każdy wiersz, także ręczne tłumaczenie, dopisuje osoba tą samą
  bramką co wersję. Język wiersza sprawdza jedna funkcja ADR-071 pkt 3
  (`locale_not_in_registry`, `locale_not_enabled`), a baza — CHECK formatu
  `^[a-z]{2}$` bez `choices`.
- Dokument to źródło tłumaczeń `customers.document` (TL-T17;
  `register_translation_source` z `saas_core/content_protocol`, ADR-069 pkt 2,
  protokół `docs/architecture/translation-sources.md`): rekord na żywo, podstawa
  `published`, zapis `live`, dokument prawny („Rozstrzygnięcia plastra 4d-2”
  niżej; pierwotnie: wersjonowane z zapisem `pending` i `live`). Automat tłumaczy
  go zawsze do akceptacji (ADR-069 pkt 16.1, TL-T25): wynik `pending` czeka poza
  wierszami wersji — w kolejce przeglądu silnika — a wiersz dopisuje dopiero
  akceptacja osoby (`write` z wyzwalaczem `acceptance`, przez
  `assert_person_required` ze step-upem `legal_document`). Zatwierdzenie nowej
  wersji zgłasza `changed` (`notify_source_changed`). Faza, która tworzy
  dokumenty, w jednym commicie rejestruje źródło (gdy rejestr TL5 jest już w
  main; inaczej robi to pierwsza faza po TL5), dopisuje je do tabel §5 i §8.1
  protokołu, dokłada test kontraktu (§11 protokołu) i dopisuje
  `shared.customers` do kontraktu `.importlinter` zakazującego importu
  `shared.translation`.
- Zgody to dziennik tylko do dopisywania (nie `PolicyAcknowledgement` z ADR-036
  §8): wpis wskazuje klienta i wiersz tekstu wersji w języku, który klient
  widział, ze skrótem tego tekstu (albo zgodę marketingową, albo pole
  `consent`, ADR-072 §8) oraz źródło napisem (`source`, `source_reference`). To
  on jest migawką wersji z T16, więc booking nie dostaje nowego klucza obcego.
- Faktury wyłącznie przez port integracji (Fakturownia, inFakt, wFirma; faza
  12): wysyłamy dane zamówienia, trzymamy numer, PDF i stan; KSeF ma program.
  Zamówienie i księga to zapis transakcji, nie dokument księgowy: ADR-042 §7
  obowiązuje, usunięcie tenanta je kasuje, a anonimizacja klienta od razu czyści
  migawkę kupującego, zostawiając kwoty, pozycje i księgę (ADR-030) — wyjątek
  retencji „dokumentów sprzedaży” z ADR-036 §8 nie ma tu czego trzymać.

### 10. Pieniądze klientów omijają platformę; sprzedawca otwarty

Pieniądze klienta trafiają tylko na konto firmy — połączone u operatora albo
własne; prowizję pobiera operator (zasada 7 planu; PSD2 art. 3 lit. b, motyw
11). Firma jako sprzedawca to założenie direct charges (ADR-037 §2), które
czeka na liście prawnej i nie blokuje budowy (decyzja 21).

### 11. Obsługiwalne przez asystenta AI (AGENTS.md, „Niezmienne zasady”)

- Złożenie, wpłata, zwrot, anulowanie, połączenie i rachunek do przelewów to
  serwisy z `api.py` dla panelu, komend i asystenta, za `commerce.payments.*` i
  `commerce.connection.manage`; połączenie zwraca link do formularza operatora,
  który klika osoba. Dokumenty i rachunek od asystenta niosą identyfikator jego
  przebiegu i do uruchomienia są nieaktywne (plan asystenta, AI-T6).
- Ścieżki gościa (zamówienie z formularza, płatność i dopłata z linku
  samoobsługi, rezygnacja ze zwrotem) wołają `commerce.api` w publicznym
  kontekście źródła (`public_booking_context`, ADR-030; sklep — ADR-074 pkt 4)
  z zakresem `commerce.public.pay`, który commerce dopisuje do jego uprawnień
  przez `register_service_scope` (§5). Token wiąże płatność z jednym
  zamówieniem, kwotę liczy serwer; link samoobsługi żyje do końca rezerwacji
  (ADR-072), więc dożywa terminu dopłaty.
- Błędy z polem i kodem (`currency_in_use`, `amount_exceeds_due`,
  `refund_exceeds_paid`, `connection_not_ready`…), `Idempotency-Key` z hashem
  żądania, `version` na `Order`, `Payment` i połączeniu (nieaktualna: 409),
  przebieg bez zapisu dla konfiguracji, wyliczenie zwrotu i wpłaty, `GET
  /api/v1/commerce/options/` (waluty, metody, polityki, stawka, terminy),
  stronicowane i filtrowane listy zamówień, audyt `commerce.*` („w imieniu” z
  A1a, ADR-076) i zgoda-digest z kliknięcia osoby na polecenie asystenta
  ruszające pieniądze (ADR-033).

## Konsekwencje

- Każdy profil i typ organizacji z `shared.booking` wymienia `shared.customers`
  (`compose()` nie dociąga zależności, `ModuleGateMiddleware` da 404 modułowi
  spoza typu — HoofCare: `trimming_company`, `farm`) — zmiana dla produktów z
  wpisem w `docs/operations/releases` (ADR-049). Customers i commerce wchodzą do
  `agro` (testy, kontrakt OpenAPI), `business` i `vps-dev`.
- Skill `develop-booking` zmienia się w tym samym commicie: płatności nie są już
  poza zakresem (ADR-072 §6–§9, pieniądze w zamówieniu), a `Service` i
  `Appointment` nie dostają pól ceny ani zadatku poza migawką wyceny i polityk;
  `develop-commerce-payments` powstaje z fazą 4.
- Migracje odwracalne (stan `Customer`, customers 0001, commerce 0001, audyt,
  wersje planów z `commerce.enabled`), lista kluczy i sekret webhooka kont
  połączonych idą do `memex ops`. Numery migracji booking, organizations i
  billing nadaje się po rebase na bieżący main tuż przed scaleniem. Main ma już
  A1a (organizations 0052, billing 0026), a równolegle piszą tam TL10
  (`public_locales`, `PublicLocalesChange`, limit języków, `Customer.locale`
  bez wyborów pl/en — w aplikacji, która w chwili TL10 trzyma stan `Customer`;
  migracja `public_locales` czyta języki klientów z modelu historycznego tej
  aplikacji) i TL12 (wiersze tłumaczeń booking). Zdarzeń domenowych commerce
  nie emituje do pierwszego konsumenta (ADR-024).
- Przełącznik „Progi zwrotu obejmują też dopłatę” (28a) wchodzi do panelu i
  API oferty z politykami anulowania (faza 3, ADR-072 §8), a działa od fazy 4,
  gdy są wpłaty. Przypomnienia dopłaty i alert dla firmy (29a) powstają z
  zadaniem terminów w fazie 4.
- Subskrypcje na starszych wersjach planów dostaną `commerce.enabled` po zmianie
  planu albo nadpisaniem operatora (`EntitlementGrant`, T18), a do tego czasu
  działają jak bez cechy (§1). Panel oferuje dziś też GBP, a backend każdy kod
  ISO: faza 3 daje firmie z walutą spoza listy zmianę z podglądem przed
  pierwszym cennikiem, a listy panelu czytają `options` z API.
- Otwarte pytania do właściciela (w nawiasie wartość do odpowiedzi): okno
  płatności online (15 min); stała część prowizji w EUR i USD; prowizja od
  zatrzymanej kaucji (brak); plany z `commerce.own_account.enabled`; połączenie
  płacące u firmy z `platform` i `own` (jedno aktywne, wybiera firma); VAT
  spoza Polski.
- Otwarte technicznie: konfiguracja kont Stripe (faza 7) i to, czy strona
  prawna witryny pokazuje bieżącą wersję dokumentu. Sprawy prawne i księgowe
  (sprzedawca, PSD2, zadatek a zaliczka i odwołanie przez firmę przy zadatku —
  art. 394 KC, kaucja i jej VAT, przechowywanie zamówień, VAT prowizji,
  paragony, spółka konta Stripe) — na liście prawnej jako sprawdzenia, nie
  pytania biznesowe.

## Odrzucone

- **Płatność przypięta do wizyty** — sklep nie ma wizyty, a zadatek, dopłata i
  kaucja to kilka płatności jednej sprzedaży.
- **Commerce zależne od booking** (ADR-037 §1) — cykl, bo rezerwacja zakłada
  zamówienie; **twarda zależność booking → commerce** — HoofCare i MedPlano
  niosłyby zamówienia, których nie używają.
- **Wpłaty na rachunek platformy** — usługa płatnicza z zezwoleniem KNF;
  **jeden operator bez wyboru** (ADR-037 §8) — noclegi nie dostaną P24.
- **Potwierdzenie przez obserwatora po commicie** — obserwatorzy połykają błędy;
  **wyjątek handlera cofający przejście od operatora** — księga rozjechałaby
  się z pobranymi pieniędzmi.
- **Wygaszanie `pending_payment` przez booking** (ADR-037 §4) — dwa zadania na
  jednym terminie; booking odwołałby wizytę przy otwartej intencji płatności.
- **Pełna treść zdarzeń w skrzynce platformowej** (jak `StripeWebhookEvent`) —
  dane płacących poza RLS i anonimizacją; powód ADR-041 §1 („klient nie ma nic
  swojego”) nie obejmuje klientów firm.
- **Blokada kaucji przy rezerwacji** — wygasa przed przyjazdem; **na zapisanej
  karcie bez klienta** — wymaga zgody na obciążenie pod jego nieobecność.
- **Podstawa progu zwrotu jako ukryte pole oferty** — firma nie wiedziałaby, że
  gość może stracić część dopłaty; właściciel wybrał jawny przełącznik (28a).
  **Automatyczne odwołanie przy niezapłaconej dopłacie** — decyzja o zerwaniu
  rezerwacji zostaje przy firmie (29a).
- **Tekst dokumentu w nadpisywanym wierszu tłumaczenia** (wzór
  `PublicProfileTranslation`) — poprawka zmieniłaby po cichu tekst, na który
  klienci już się zgodzili, i zepsuła dowód z dziennika zgód.

## Uzupełnienie 2026-10-03: faza 4 w plastrach

Faza 4 planu („Zamówienie bez operatora online”) to §1–§5 i §9 tego ADR-u oraz
ADR-072 §8–§9. Jest za duża na jedno scalenie, więc idzie plastrami: każdy
scalany osobno po własnej pełnej bramce i każdy zostawia `main` działający bez
następnych. Kolejność wynika z zależności: zamówienie zapisuje zgody, a zgody
wskazują klienta, więc klient i dokumenty są przed zamówieniem.

| Plaster | Zakres | Migracje | Ekran |
| --- | --- | --- | --- |
| **4a** | `shared.customers` jako moduł: `Customer` przechodzi stanem modelu (tabela `booking_customer` zostaje), `customers.api` (`Customer`, `CUSTOMER_MODEL`, `match_or_create`, `strip_customer`, `register_customer_anonymizer`), booking rejestruje swoje czyszczenie wizyt; strażnik `deployment-check` (§2); profile `business`, `agro`, `vps-dev`; nota dla produktów | customers 0001, booking 0029 (sam stan) | brak |
| **4b** | Dokumenty firmy i dziennik zgód (§9): rodzaje, szkic, wersja i wiersze tekstu tylko do dopisywania, zatwierdzenie przez osobę ze step-upem, publiczny adres dokumentu, dwa czytniki dla innych modułów; `customers.read`, `customers.manage`, `/api/v1/customers` | customers 0002 (tabele), 0003 (RLS, strażnik relacji, tylko do dopisywania), 0004 (uprawnienia ról) | Ustawienia › „Dokumenty dla klientów”; publiczna strona dokumentu |
| **4c** | Rezerwacja zapisuje zgody: formularz publiczny pokazuje regulamin rezerwacji i politykę prywatności obowiązujące w języku klienta, rezerwacja dopisuje wpisy dziennika (`source` `booking.appointment`), zgoda marketingowa osobno | — | formularz publiczny |
| **4d-1** | Polecenia asystenta dla dokumentów: `customers.documents.read@1` (odczyt) i `customers.document.draft.save@1` (zapis szkicu z identyfikatorem rozmowy), z evalami; panel mówi, że szkic napisał asystent | — | Ustawienia › „Dokumenty dla klientów” (szkic) |
| **4d-2** | Dokument jako źródło tłumaczeń `customers.document` (§9): adapter, tabele §5 i §8.1 protokołu, test kontraktu, `shared.customers` w kontrakcie `.importlinter` bez silnika; akceptacja tłumaczenia przez osobę ze step-upem w centrum tłumaczeń | — (rekord na żywo, „Rozstrzygnięcia plastra 4d-2”) | Tłumaczenia › „Do akceptacji”; Ustawienia › „Dokumenty dla klientów” (zlecenie brakujących języków) |
| **4e** | `shared.commerce`: `Order`, `OrderLine`, licznik numerów, `register_order_source`, `place_order`, `ORDER_MODEL`; booking jako źródło `R` zakłada zamówienie z pozycji zamrożonej wyceny w transakcji rezerwacji; migawka kupującego i jej czyszczenie przy anonimizacji; kanał (token pochodzenia — niżej, „Rozstrzygnięcia plastra 4e”); `commerce.enabled` w nowych wersjach planów; `GET /commerce/options/`, lista zamówień | commerce 0001–0004 (wersje planów publikuje 0004) | Zamówienia (lista, szczegół) |
| **4f-1** | Wpłaty ręczne (§4): `Payment`, `LedgerEntry` (tylko do dopisywania), oznaczenie wpłaty przez firmę (na miejscu, przelew) z podglądem, wycofanie wpłaty oznaczonej przez pomyłkę, status zamówienia z księgi (`partially_paid`, `paid`), `commerce.payments.manage` | commerce 0005–0007 | wpłaty w zamówieniu |
| **4f-2** | Przelew z terminem (§5): rachunek firmy do przelewów, polityki oferty `transfer`, `deposit`, `full` opłacane przelewem, `pending_payment` z `hold_expires_at`, handler źródła w rejestrze, `register_service_scope` w rdzeniu (z przeniesieniem dzisiejszych wpisów), zadanie terminów, e-maile z numerem zamówienia i danymi do przelewu | commerce 0008, booking 0030 | oferta („Cennik”), zamówienie, wizyta, Ustawienia › „Płatności klientów”, formularz publiczny i link klienta |
| **4g** | „Na prośbę” (ADR-072 §9): `confirmation` `on_request`, `pending_request`, akceptacja i odmowa w panelu, wygaszanie przez booking, zamówienie `draft` bez numeru do akceptacji, e-maile (przyjęta, odmowa, wygaśnięcie) | booking 0031 | kalendarz (wizyta), oferta („Edytuj usługę”), zamówienie, formularz publiczny i link klienta |
| **4h** | Progi anulowania (przeniesione z 3d) i zwroty ręczne (§8): progi i `appliesTo` w ofercie i migawce, wyliczenie zwrotu przy rezygnacji gościa i odwołaniu przez firmę, zwrot ręczny w księdze, przypomnienia dopłaty i alert dla firmy (29a) | booking, commerce | oferta, zamówienie, link samoobsługi |
| **4i** | Wyjątek retencji dla klientów z zapisami sprzedaży w okresie ustawowym i historia cen przed promocjami (niżej) | commerce, booking | Prywatność i dane (podgląd) |

Rozstrzygnięcia tego uzupełnienia (decyzje techniczne, z powodem):

- **4a nie ma adresu ani uprawnień.** Deskryptor `shared.customers` dostaje
  `urlPrefix` i `customers.*` dopiero w 4b, z pierwszym endpointem — moduł nie
  deklaruje tego, czego kod jeszcze nie ma. Ręczna anonimizacja (endpoint i
  audyt `booking.customer.anonymized`) oraz przebieg retencji
  (`booking.retention.customers`) zostają w booking: „po terminie” liczy się od
  wizyt, a klucz ustawienia firmy mają już zapisany. `Customer.user` (§2) nie
  powstaje w fazie 4 — przyjdzie z kontem klienta (ADR-036 §5), razem ze swoim
  pierwszym czytelnikiem.
- **Publiczny adres dokumentu** (4b) to strona platformy
  `/<język>/documents/<identyfikator>`; firmę wyznacza indeks routingu bez
  danych osobowych (`customers_documentroute`, wzorzec `PublicBookingRoute`),
  bo dokument musi mieć adres także u firmy bez własnej strony i w e-mailu.
  Strona prawna witryny firmy (Otwarte technicznie) zostaje na fazę 5.
- **Czytnik nie zastępuje języka.** `customers.api.current_document(kind,
  locale)` zwraca dokument tylko wtedy, gdy obowiązująca wersja ma wiersz w tym
  języku; inaczej nic. Zgoda na tekst w języku, którego klient nie wybrał, nie
  byłaby zgodą. Co z tego wynika dla rezerwacji w języku bez tekstu
  regulaminu — „Uzupełnienie 2026-10-04: krok zgód formularzy publicznych”.
- **Dziennik zgód przyjmuje podmiot bez klienta** (`customer` puste): pytający
  z formularza kontaktowego nie ma rekordu `Customer`, a wpis wskazuje go tylko
  przez `source` i `source_reference` (identyfikator zapytania). Jeden dziennik
  na wszystkie zgody; w dzienniku nie ma danych osoby, więc usunięcie zapytania
  niczego w nim nie zostawia.
- **Wersja zaczyna od jednego języka.** Zatwierdzenie szkicu dopisuje wersję z
  tekstem w języku szkicu; tekst w kolejnym języku firmy (albo poprawkę
  istniejącego) dopisuje osoba tą samą bramką jako nowy wiersz. Podgląd
  zatwierdzenia wymienia języki firmy, w których klienci nie dostaną dokumentu,
  dopóki nikt nie doda tekstu — to skutek reguły czytnika, powiedziany przed
  kliknięciem. Publiczna strona dokumentu, na której nikt niczego nie
  akceptuje, pokazuje wtedy tekst w języku wersji i mówi o tym wprost.
- **Operacje dokumentów są zablokowane wersją, nie kluczem.** Dokument ma
  licznik `version`; każdy zapis podaje `expected_version`, a powtórka na tej
  samej wersji kończy się 409 i niczego nie zmienia (wzór wizytówki), więc
  `Idempotency-Key` nie jest tu potrzebny. Polecenia asystenta (odczyt, zapis
  szkicu z `origin_ref`) przychodzą w 4d razem ze źródłem tłumaczeń — oba to
  „maszyna pisze do dokumentu prawnego”; serwis ma już ich kształt (podgląd,
  wersja, błędy z polem i kodem), a zatwierdzenie zostaje wyłącznie osobie.
- **Tekst dokumentu to zwykły tekst** (akapity i puste linie), bez znaczników:
  skrót liczy się z dokładnie tego, co klient zobaczył, a każdy kanał (strona,
  e-mail, formularz) pokazuje to samo.
- **Źródło tłumaczeń osobnym plastrem (4d)** — odstępstwo od słów §9 („w jednym
  commicie”): ręczna ścieżka (osoba dopisuje wiersz języka tą samą bramką) jest
  kompletna bez silnika, a adapter z testem kontraktu to osobny przegląd.
  Rejestr TL5 jest już w `main`, więc 4d zamyka to przed fazą 5.
- **Słowo „przedpłata”.** Do odpowiedzi z listy prawnej (zadatek czy zaliczka,
  art. 394 KC) panel, formularz i e-maile nazywają wpłatę z góry „przedpłatą”;
  wartość `deposit` w danych zostaje.
- **Co zamówienie trzyma o kliencie i jak długo (4i)** — zmienia ostatnie
  zdanie §9. Zamówienie z zaksięgowaną wpłatą jest dla firmy zapisem sprzedaży:
  migawka kupującego (nazwa, e-mail, telefon, dane do faktury) i klient zostają
  do końca okresu ustawowego, liczonego w pełnych latach kalendarzowych po roku
  ostatniego wpisu księgi zamówienia. Okres to nazwana stała commerce (robocza
  wartość 5 lat; pytanie na liście prawnej), nie ustawienie firmy. Commerce
  rejestruje wykluczenie (`register_retention_exclusion`), a `erase_customers`
  pyta o nie ponownie pod blokadą klientów
  (`docs/architecture/privacy-retention.md`). Zamówienie bez wpłaty niczego nie
  trzyma. Ręczna anonimizacja takiego klienta — do rozstrzygnięcia z listą
  prawną przed 4i (propozycja: czyści klienta i wizyty, migawka zamówienia
  zostaje do końca okresu). (Rozstrzygnięte odpowiedzią właściciela z 04.10 —
  niżej, „Rozstrzygnięcia plastra 4i”.)
- **Historia cen (4i).** Każda zmiana `PriceRule` dopisuje wiersz historii
  (kto, kiedy, kwota przed i po), bo promocje (faza 10) muszą pokazać najniższą
  cenę z 30 dni przed obniżką, a tej nie da się odtworzyć wstecz.

Rozstrzygnięcia plastra 4c (2026-10-04, decyzje techniczne z powodem):

- **Formularz pyta o dokumenty osobnym odczytem**
  `GET /booking/public/<slug>/consents/?locale=` (`booking.consents.shown`), nie
  polem katalogu: katalog pytany z językiem tłumaczy też nazwy ofert, a to inna
  zmiana niż pokazanie dokumentów. Odpowiedź to język rezerwacji i lista
  dokumentów, które mają tekst w tym języku: rodzaj, oświadczenie do
  zaznaczenia, `text_id`, numer wersji i adres strony dokumentu.
- **Język zgody to język rezerwacji**: ten, który podał klient, gdy firma go
  ma, inaczej pierwszy język firmy (ADR-071 pkt 21) — ten sam, w którym klient
  dostaje potwierdzenie. Nieznany język nie jest więc sposobem na pominięcie
  dokumentów, a powracający klient zgadza się na tekst w języku strony, na
  której rezerwuje teraz, nie w języku swojej pierwszej rezerwacji.
- **Zgody wymaga się od tego, kto rezerwuje sam.** W kontekście formularza
  publicznego rezerwacja musi wymienić `text_id` każdego obowiązującego
  dokumentu (`consents.documents`); brak albo inny tekst niż obowiązujący to
  409 `documents_changed` z listą do pokazania i wycofana rezerwacja (wzór
  `quote_changed`). Biuro rezerwujące w panelu niczego nie zaznacza i niczego
  nie zapisuje. Wywołujący, który sam pokazał dokumenty (produkt, formularz
  pobytów w fazie 5), przekazuje `BookingConsents` i podlega tej samej regule.
  Sprawdzenie i zapis są w jednym miejscu, `consents.record`, wołanym na
  początku `record_new_booking` — wspólnie dla wizyty i pobytu. Powtórka z tym
  samym kluczem oddaje pierwszą rezerwację i nie dopisuje drugiego wpisu.
- **Oświadczenia w jednej stałej.** `booking.consents.DOCUMENT_STATEMENTS`
  wyznacza, które dokumenty formularz pokazuje (regulamin rezerwacji, polityka
  prywatności), w jakiej kolejności i jakimi słowami: dwa osobne oświadczenia,
  „Akceptuję regulamin” i „Zapoznałem się z polityką prywatności” (robocze do
  odpowiedzi z listy prawnej). Słowa idą do formularza z API, więc zmiana to
  jedna stała, a nie pliki tłumaczeń frontendu.
- **Zgoda marketingowa to osobny wpis, którego formularz jeszcze nie zbiera**
  (stan plastra 4c; formularz zbiera ją od „Uzupełnienia 2026-10-04: krok zgód
  formularzy publicznych”).
  `BookingConsents.marketing` (treść zgody) dopisuje wpis `kind="marketing"`
  ze skrótem treści obok wpisów dokumentów. Pole w formularzu publicznym
  przyjdzie razem z treścią zgody od prawnika i z miejscem, w którym firma
  zobaczy, kto się zgodził — zgoda, której firma nie może odczytać, niczemu nie
  służy, a jej słowa to ryzyko prawne, nie decyzja techniczna. (Treść i lista
  zgód: niżej, „Zgody marketingowe w panelu”.)

Rozstrzygnięcia plastra 4d (2026-10-04, decyzje techniczne z powodem):

- **4d idzie w dwóch częściach.** Polecenia asystenta (4d-1) nie zależą od
  źródła tłumaczeń: wołają serwisy panelu, które są w `main` od 4b. Źródło
  (4d-2) wymaga zmian poza `shared.customers` — niżej — więc nie blokuje
  poleceń.
- **Asystent pisze szkic, nie wersję (4d-1).** `customers.document.draft.save`
  ma klasę `draft` bez modyfikatora `legal_document`: zapis szkicu w panelu nie
  wymaga step-upu, a rejestr nie dokłada kontroli, której ścieżka panelu nie ma
  (ADR-076 pkt 2). Zatwierdzenie nie ma polecenia w ogóle — zostaje osobie w
  panelu. Szkic niesie `origin_ref` rozmowy; panel mówi wtedy „Ten szkic
  napisał asystent AI”, dopóki osoba nie zapisze szkicu sama (jej zapis czyści
  `origin_ref`). Odczyt nie oddaje nazwisk zatwierdzających — wynik idzie do
  modelu, a te dane nie są mu potrzebne. Podgląd zapisu (`documents.plan_draft`)
  sprawdza to samo co zapis i niczego nie pisze.
- **Co 4d-2 musi rozstrzygnąć, zanim powstanie adapter** (odczyt protokołu i
  zestawu kontraktu z 04.10):
  1. *Każdy obiekt tego źródła jest dokumentem prawnym*, więc żaden wynik nie
     wychodzi sam (`decide_publication`, reguła 3). Zestaw kontraktu
     (`saas_core/testing/translation_sources.py`) zakłada obiekty nieprawne —
     scenariusze startują od `translate(...) == [("live", None)]` — i potrzebuje
     zdolności w rodzaju `legal_only`, przy której zestaw gra też osobę
     akceptującą wynik. To zmiana protokołu (§11 i §12 dokumentu protokołu).
  2. *Gdzie czeka wynik.* §9 mówi „wersjonowane, zapis `pending` i `live`” —
     wtedy adapter sam trzyma oczekujący tekst i potrzebna jest tabela
     (migracja `customers`). Bez migracji da się to zrobić jako rekord na żywo:
     wynik trzyma kolejka przeglądu silnika, a akceptacja to `write` z
     wyzwalaczem `acceptance`, który przez bramkę osoby i step-up dopisuje
     wiersz (`documents.add_text`). Druga droga jest krótsza i zgodna z tym, że
     wiersz tekstu jest publiczny od razu; wymaga poprawienia zdania w §9.
  3. *Czym jest fragment.* 4b zapisuje pochodzenie dla całego tekstu
     (`UNIT_KIND = "text"`), czyli jeden fragment na dokument. Jeden fragment
     idzie do modelu jednym wywołaniem ponad limit 6 000 znaków („a single unit
     over the limits goes alone”), a nowa wersja tłumaczy się od zera. Akapity
     jako fragmenty dają pamięć tłumaczeń między wersjami i mieszczą się w
     wywołaniach, ale wymagają pochodzenia per akapit w wierszu i reguły dla
     ręcznego tłumaczenia o innej liczbie akapitów.
  4. *Akceptacja na ekranie.* Akceptacja tłumaczenia dokumentu wymaga kodu z
     aplikacji (403 `step_up_required` z adaptera), więc centrum tłumaczeń musi
     umieć o niego zapytać — tak jak okno zatwierdzenia wersji w 4b.
  Do tego czasu ręczna ścieżka z 4b jest kompletna: osoba dopisuje tekst w
  kolejnym języku tą samą bramką co wersję.

Rozstrzygnięcia plastra 4d-2 (2026-10-04, decyzje techniczne z powodem;
odpowiedzi na cztery pytania wyżej):

- **Rekord na żywo, bez migracji (pytanie 2).** Wiersz tekstu jest publiczny i
  wiążący od chwili zapisu, więc źródło nie ma gdzie trzymać „oczekującego”:
  zapis zlecenia odpowiada `pending` / `legal_document` i niczego nie pisze, a
  tekst czeka w kolejce przeglądu silnika (`TranslationReviewItem.texts`).
  Akceptacja to `write` z wyzwalaczem `acceptance`, który dopisuje wiersz przez
  `documents.add_text` — tę samą bramkę osoby („Dokument dla klientów”) i ten
  sam świeży drugi składnik co tekst wpisany ręcznie. Tryb tłumaczeń firmy
  niczego tu nie zmienia: reguła dokumentu prawnego wyprzedza tryby, a gdyby
  zlecenie mimo to doszło do zapisu, odmówi mu serwis, nie adapter. Druga
  droga (własna tabela oczekujących tekstów) dublowałaby kolejkę silnika.
- **Jeden fragment — cały tekst (pytanie 3).** Tak 4b zapisuje pochodzenie
  (`UNIT_KIND = "text"`). Nowa wersja zaczyna bez tłumaczeń (wiersz należy do
  wersji i nie przechodzi na następną), poprawka tekstu źródłowego w wersji
  czyni tłumaczenia nieaktualnymi; tekst osoby jest wtedy chroniony i wynik
  czeka jako `overwrites_human`. Akapity jako fragmenty wymagałyby pochodzenia
  per akapit i reguły dla ręcznych tłumaczeń o innej liczbie akapitów —
  odłożone, aż koszt ponownego tłumaczenia całego dokumentu okaże się realny.
- **Która wersja jest źródłem.** Ta, która wchodzi w życie ostatnia
  (`documents.translated_version`: obowiązująca albo zatwierdzona na późniejszy
  dzień) — tłumaczenia mają być gotowe, zanim nowa wersja zacznie obowiązywać.
  Wersji obowiązującej, którą zaraz zastąpi następna, automat już nie tłumaczy;
  tekst do niej osoba nadal dopisuje ręcznie.
- **Zakres to dokument, nie firma.** Język jest „żywy” dla dokumentu, gdy
  dokument miał w nim tekst (w tej albo wcześniejszej wersji): automat zmian
  proponuje wtedy kolejną wersję w tym języku, a pierwsze wejście języka do
  dokumentu zostaje kliknięciem „Przetłumacz brakujące” z wyceną.
- **Kto co może.** Zlecenie i odczyt — `customers.read`; akceptacja —
  `customers.manage`, osoba i kod z aplikacji. Asystent nie akceptuje
  (etykieta „Dokument dla klientów” nie jest otwarta dla żadnego kanału):
  polecenie `translation.review.accept` odmawia już w podglądzie, bo źródło
  deklaruje `accepted_in_panel_only`. `revert` zlecenia niczego nie cofa —
  zlecenie niczego nie wypuściło, a akceptacja jest decyzją osoby.
- **Idempotencja bez tabeli.** Zaakceptowany wiersz pamięta zapis, który go
  dopisał (`provenance.write`: klucz i skrót treści) — powtórka akceptacji
  odpowiada tym wierszem, inna treść pod tym samym kluczem to
  `idempotency_conflict`. Zapis zlecenia nie zostawia śladu, więc jego powtórka
  odpowiada z samego stanu.
- **Zestaw kontraktu (pytanie 1)** dostał tryb `legal_only` (oraz `single_unit`
  i `persons_only` dla źródeł o takiej budowie): zestaw gra też osobę
  akceptującą — protokół §11. **Ekran (pytanie 4):** „Tłumaczenia → Do
  akceptacji” pyta o kod po 403 `step_up_required` i wysyła tę samą decyzję
  jeszcze raz; ekran dokumentu zleca brakujące języki i mówi, że tłumaczenie
  czeka.

Rozstrzygnięcia plastra 4e (2026-10-04, decyzje techniczne z powodem):

- **Zamówienie powstaje dla rezerwacji z ceną.** Rezerwacja, której zamrożona
  wycena ma pozycje, zakłada zamówienie w swojej transakcji
  (`booking/orders.py`, wołane z `record_new_booking` zaraz po zgodach —
  wspólnie dla wizyty i pobytu). Oferta bez cennika niczego nie sprzedaje za
  kwotę, więc zostaje bez zamówienia, tak jak rezerwacje sprzed wdrożenia (§3).
  Firma bez cechy `commerce.enabled` rezerwuje jak dotąd: `place_order` oddaje
  wtedy nic, a pytanie o cechę jest w commerce, nie w źródle.
- **Pozycja niesie kwoty wyceny, nie cenę jednostkową w dwóch postaciach** —
  doprecyzowanie §3 (`unit_gross_minor`, `unit_net_minor`). Podatek jest
  zaokrąglany na pozycji (ADR-072 §7), więc cena jednostkowa istnieje tylko po
  tej stronie, po której firma ją wpisała; drugą commerce musiałoby wyliczyć, a
  commerce cen nie liczy. `OrderLine` ma `unit_amount_minor` (czytane brutto
  albo netto według `Order.amounts`) oraz `net_minor`, `vat_minor` i
  `gross_minor` pozycji — liczby źródła. Suma pozycji obowiązujących to kwoty
  zamówienia.
- **Zmiana ceny to kolejna rewizja pozycji.** „Złożonych pozycji nie zmienia —
  korekta to nowa pozycja” (§3): gdy źródło wyceni rzecz od nowa (przeniesienie
  rezerwacji na droższy termin), `reprice_order` dopisuje pozycje z numerem
  rewizji o jeden wyższym i przestawia `Order.revision`; wcześniejsze wiersze
  zostają nietknięte, a baza odmawia ich zmiany i usunięcia (wyzwalacz, furtka
  usunięcia tenanta). Te same pozycje jeszcze raz niczego nie zmieniają. Pary
  pozycji odwracających nie ma: szczegół zamówienia pokazuje pozycje
  obowiązujące i kwotę każdej wcześniejszej rewizji.
- **Rejestr źródeł bez handlera do 4f.** `register_order_source(kind, prefix,
  targets=…)`: prefiks numeru i nazywanie tego, czego dotyczą pozycje (wizyta
  z terminem i dniem w kalendarzu — bez danych klienta). Handler z §1 przyjdzie
  z pierwszym przejściem, które commerce zleca źródłu (opłacenie i wygaśnięcie
  wpłaty przed potwierdzeniem, 4f); w 4e każdą zmianę zamówienia zleca źródło:
  złożenie, nową wycenę, anulowanie. Kształt handlera zaprojektowany bez
  wywołującego trzeba by poprawiać.
- **Statusy ustawiane w 4e:** `awaiting_payment` po złożeniu (albo `paid`, gdy
  nie ma nic do zapłaty) i `canceled` po odwołaniu rezerwacji. Pozostałe
  wartości z §3 są w kontrakcie, a ustawią je plastry, które przyniosą księgę
  (4f), „na prośbę” (4g: `draft`) i zwroty (4h).
- **Kanał z tego, co serwer wie sam; token pochodzenia z fazą 5.** Zamówienie
  zapisuje `company_site` dla rezerwacji z formularza publicznego i `office`
  dla zapisanej przez zespół (wartość dodana do listy z §3: rezerwacja biura
  nie przyszła żadnym kanałem sprzedaży). `catalog` jest w kontrakcie, ale
  nikt go jeszcze nie ustawia: podpisany token pochodzenia i kanał na samej
  rezerwacji (ADR-072 §11) powstaną razem z pierwszym odnośnikiem z katalogu
  do formularza (systemowa strona jednostki, faza 5) — token bez wystawcy nie
  ma czego potwierdzać, a do tego czasu żadna rezerwacja nie pochodzi z
  katalogu, więc niczego nie tracimy.
- **Migawka kupującego to nazwa, e-mail i telefon klienta z chwili złożenia.**
  Dane do faktury (§3) dojdą z pierwszym formularzem, który o nie pyta. Kaucja
  z wyceny nie jest pozycją i w 4e nie ma swojego pola — zostaje w wycenie
  rezerwacji do płatności `security_deposit` (§4, §8).
- **Uprawnienie `commerce.orders.read`** mają role systemowe `manager`, `admin`
  i `owner`: zamówienie pokazuje kontakt kupującego i przychód firmy.
  Polecenia asystenta dla zamówień przyjdą z pierwszą operacją, która coś
  zmienia (oznaczenie wpłaty, 4f); 4e ma same odczyty.
- **Szczegół zamówienia pokazuje zgody kupującego**: wpisy dziennika zgód
  rekordów, których dotyczą pozycje (`customers.api.consents_of`) — rodzaj
  dokumentu, wersja, język i czas, bez danych osoby. To pierwsze miejsce w
  panelu, w którym firma widzi dziennik zgód.
- **Licznik numerów** to wiersz na firmę, prefiks i rok (`OrderCounter`),
  blokowany `select_for_update` do końca transakcji zamówienia: numer nadaje
  się raz, a wycofane zamówienie nie zostawia dziury. Rok liczy się w strefie
  firmy.

Rozstrzygnięcia plastra 4f-1 (2026-10-04, decyzje techniczne z powodem):

- **4f idzie w dwóch częściach.** Oznaczenie wpłaty przez firmę i księga (4f-1)
  nie zależą od przelewu z terminem: działają dla każdego zamówienia, także
  płatnego na miejscu. Rachunek firmy, polityki z wpłatą przed potwierdzeniem,
  `pending_payment`, zadanie terminów i e-maile (4f-2) potrzebują zmian w
  booking i w rdzeniu, więc nie blokują księgi.
- **O pieniądzach rozstrzyga księga.** `paid_minor` to suma wpisów `charge` i
  `refund` zamówienia, `due_minor` — kwota pozycji obowiązujących minus ta
  suma; status zamówienia wylicza z nich jedna funkcja (`ledger.status_for`):
  nic do zapłaty to `paid`, część — `partially_paid`, anulowane zostaje
  anulowane. Przeniesienie rezerwacji po innej cenie nie rusza wpłat: zmienia
  tylko to, ile zostało (droższy termin po pełnej wpłacie daje
  `partially_paid`, tańszy — nadpłatę do oddania, którą pokazuje `due_minor`
  poniżej zera). Zwrot zapisze 4h.
- **Wpłata ręczna to `Payment` ze statusem `succeeded` i wpis `charge`.** Firma
  oznacza tylko `cash` (na miejscu: gotówka albo własny terminal) i `transfer`;
  `online` potwierdza operator, nigdy osoba (`method_not_manual`). Rodzaj
  wynika z kwoty: całość naraz — `full`, część — `deposit`, reszta —
  `balance`. Więcej niż zostało do zapłaty serwis odrzuca
  (`amount_exceeds_due`), wpłatę do anulowanego zamówienia też
  (`order_canceled`). Płatności planowane z terminem (`requires_payment`,
  `due_at`) założy 4f-2 przy złożeniu zamówienia; oznaczenie takiej wpłaty
  przestawi ją na `succeeded` tą samą funkcją.
- **Pomyłkę się wycofuje, nie kasuje.** Wpłata oznaczona przez pomyłkę dostaje
  status `canceled`, a księga wpis `charge` z przeciwnym znakiem — tabela księgi
  odmawia zmiany i usunięcia. To nie zwrot (`refund`, 4h): pieniądze nigdzie
  nie wróciły, a historia zamówienia pokazuje oba zdarzenia i osobę.
- **Blokada wersją zamówienia zamiast klucza** — odstępstwo od §11 dla wpłat
  ręcznych, jak w dokumentach (4b). Zapis podaje `expected_version`; powtórka
  na tej samej wersji (ponowienie po błędzie sieci, druga osoba przy biurku)
  dostaje 409 `order_version_conflict` i niczego nie zapisuje, więc wpłaty nie
  da się oznaczyć dwa razy. `Idempotency-Key` z hashem żądania przyjdzie z
  płatnością online (faza 7), gdzie powtórka musi oddać tę samą intencję
  operatora.
- **Podgląd** `POST …/payments/preview/` sprawdza to samo co zapis i mówi, ile
  będzie wpłacone, ile zostanie i jaki będzie status; niczego nie zapisuje.
- **Uprawnienie `commerce.payments.manage`** (role systemowe `manager`,
  `admin`, `owner`): oznaczenie wpłaty zmienia to, ile klient jest winien.
  Pracownik bez tego uprawnienia widzi wpłaty tylko wtedy, gdy czyta
  zamówienia. Polecenie asystenta dla wpłat i odnośnik z wizyty w kalendarzu do
  zamówienia przychodzą z 4f-2, razem ze zmianami w booking.

Rozstrzygnięcia plastra 4f-2 (2026-10-04, decyzje techniczne z powodem):

- **Rachunek firmy to grupa ustawień `commerce.transfer`** w rejestrze ADR-078
  (właściciel rachunku, numer, opcjonalnie bank; Ustawienia › „Płatności
  klientów”), a nie własna tabela: rejestr daje wersję, podgląd, historię i
  formularz. Numer to 26 cyfr (polski rachunek) albo IBAN, sprawdzany sumą
  kontrolną; odczyt oddaje go w grupach po cztery znaki. Zmienia go
  `commerce.payments.manage` **z kodem z aplikacji uwierzytelniającej** —
  podmieniony numer rachunku to miejsce, w które trafiają pieniądze klientów —
  i z tego samego powodu grupa nie ma polecenia asystenta (§11 „rachunek od
  asystenta jest nieaktywny do uruchomienia” spełnione najprościej: asystent
  rachunku nie pisze). Rachunku nie da się wyczyścić, dopóki oferta ma politykę
  `transfer` (`register_transfer_account_use`) albo jakaś wpłata przelewem jest
  oczekiwana (`transfer_account_in_use`).
- **Oferta niesie trzy pola**: `payment_policy` (`transfer`, `deposit`, `full`
  obok `none` i `on_site`), `deposit_percent` (1–99, domyślnie 30) i
  `transfer_due_days` (1–30, domyślnie 3). Kwota przedpłaty to procent ceny
  brutto zaokrąglony do całej jednostki (połówki w górę); reszta przy `deposit`
  idzie na miejscu — termin dopłaty przed pobytem i jej przypomnienia to 4h.
  Polityki z wpłatą z góry serwis oferty przyjmuje tylko tam, gdzie firma ma
  zamówienia (`orders_required`), a `transfer` — tylko z rachunkiem
  (`transfer_account_missing`); sprawdza to przy zmianie płatności, więc oferta
  ustawiona wcześniej zapisuje pozostałe pola także po utracie cechy.
- **Preset nie wybiera wpłaty z góry za firmę.** `apply_preset` ustawia z
  presetu tylko `none` i `on_site`; przy `transfer`, `deposit` i `full` oferta
  startuje z `none`, a procent i dni z presetu (`depositPercent`,
  `transferDueDays`) są już wpisane — politykę firma wybiera sama w „Cenniku”,
  bo wymaga ona zamówień w planie i (przy przelewie) rachunku. Preset nie może
  nie wystartować z ich braku, także w produkcie bez `shared.commerce`.
- **Wycena mówi, co się stanie.** Zamrożona wycena niesie `prepayment`
  (`kind`, `amount_minor`, `transfer_due_days`) tylko wtedy, gdy wpłatę da się
  złożyć z góry (cecha `commerce.enabled` i rachunek). Bez tego `deposit` i
  `full` idą na miejscu: wycena mówi `on_site`, a rezerwacja jest potwierdzona
  od razu — formularz nie obiecuje przelewu, którego nikt nie przyjmie.
  `prepayment` wchodzi do skrótu wyceny tylko, gdy jest, więc skróty rezerwacji
  sprzed 4f-2 się nie zmieniają.
- **Źródło prosi, commerce wyznacza termin.** Booking woła
  `request_prepayment(order, kind, amount_minor, transfer_days, before)` zaraz
  po `place_order`; commerce zakłada `Payment` (`requires_payment`, `transfer`,
  `due_at`), trasę terminu i wysyła dane do przelewu, a oddaje termin — albo
  nic, gdy wpłaty z góry złożyć się nie da. Termin to dni z oferty, **nigdy
  później niż początek rezerwacji** (`before`); rezerwacja, która zaczyna się
  już, nie czeka (wizyta w toku też nie). Kwoty liczy źródło — commerce nadal
  niczego nie wycenia.
- **Rezerwacja oczekująca** (`pending_payment`, `hold_expires_at` = kopia
  terminu) trzyma termin tymi samymi alokacjami co potwierdzona — także ta
  założona przez biuro w panelu, bo zadatek telefonicznej rezerwacji też ma
  termin. Potwierdzenie, przypomnienie, rezerwacja materiałów, powiadomienia
  osób z wizyty i `CREATED` dla obserwatorów przychodzą dopiero z
  potwierdzeniem; o rezygnacji i wygaśnięciu oczekującej obserwatorzy i osoby
  z wizyty nie dowiadują się niczego. Oczekującej nie da się przełożyć,
  zakończyć ani oznaczyć nieobecności; da się ją odwołać (firma) i z niej
  zrezygnować (link klienta).
- **Handler źródła ma dwa wywołania, oba w transakcji zmiany, która je
  spowodowała**: `prepaid(order)` — wpłata oczekiwana dotarła w całości — i
  `expired(order)` — termin minął, zamówienie jest już anulowane. Odmowa
  handlera („terminu nie da się już przyjąć”, §1) przyjdzie z płatnością
  online: przy wpłacie oznaczanej ręcznie zamówienie wygasłej rezerwacji jest
  anulowane i wpłaty nie przyjmuje (`order_canceled`).
- **Oznaczenie wpłaty oczekiwanej**: kwota co najmniej równa oczekiwanej
  przestawia ten sam wiersz na `succeeded` (metodą i kwotą faktycznej wpłaty)
  i potwierdza rezerwację; mniejsza jest osobną wpłatą i zmniejsza to, co
  nadal oczekiwane, do tego samego terminu. Wycofanie wpłaty częściowej
  przywraca kwotę oczekiwaną. **Wycofanie wpłaty po potwierdzeniu niczego nie
  odwołuje** — rezerwacja zostaje potwierdzona, a o jej odwołaniu decyduje
  firma (ta sama zasada co 29a: automat nie odwołuje rezerwacji za pomyłkę w
  księgowaniu).
- **Zadanie terminów** `commerce.tasks.expire_due_payments` (co minutę, z
  deskryptora modułu) czyta `commerce_paymentroute` — identyfikatory i termin,
  bez danych osobowych, z niewygasającym kontraktem `service` roli
  `commerce_deadlines` — i dla każdej trasy w tenancie zamówienia wygasza
  płatność, anuluje zamówienie (powód `payment_expired` w historii) i woła
  handler. Wpłata oznaczona w międzyczasie zostaje. `balance` po terminie
  niczego nie anuluje (29a) — jej zgłaszanie to 4h.
- **`register_service_scope` w rdzeniu** (`core.organizations.api`): moduł
  deklaruje z `AppConfig.ready` rolę kontraktu `service` i jej uprawnienia;
  `exact` — kontrakt niesie dokładnie ten zestaw (przypomnienia, zapytania ze
  strony, terminy płatności), inaczej dowolną jego część, a inny moduł może do
  zakresu dopisać własne uprawnienie. Wszystkie dotychczasowe wpisy listy
  `_service_context` przeniosły się do swoich modułów (booking, sites,
  inventory, translation); rdzeń nie zna już żadnej nazwy modułu shared.
- **E-maile.** Dane do przelewu (`commerce.transfer_details`: numer
  zamówienia jako tytuł, kwota, termin, rachunek, nazwa pierwszej pozycji w
  języku klienta) wysyła commerce; wygaśnięcie (`booking.pending_expired`) —
  booking, a biuro dostaje `booking.office_expired`, gdy firma włączyła
  powiadomienia biura. Wszystkie w pl, en i de, przez szablony powiadomień;
  żaden nie niesie danych innej osoby. Po wpłacie klient dostaje zwykłe
  potwierdzenie rezerwacji. E-mail z danymi do przelewu niesie też własny link
  klienta do rezerwacji (szablon w wersji 2; źródło podaje go w
  `request_prepayment(link=…)`) — to jedyna wiadomość, jaką klient ma, dopóki
  rezerwacja czeka, więc bez linku nie mógłby z niej zrezygnować po zamknięciu
  strony.
- **Odnośnik z wizyty do zamówienia**: `commerce.api.orders_of(source,
  references)` to jeden odczyt na listę wizyt; kalendarz dostaje `order`
  (`id`, `number`) tylko dla wywołującego z `commerce.orders.read`.
- **Poza 4f-2** zostały polecenia asystenta dla wpłat (zgoda z kliknięcia,
  ADR-033) — osobny przegląd razem z paczką asystenta.

Rozstrzygnięcia plastra 4g (2026-10-04, decyzje techniczne z powodem):

- **Oferta niesie `confirmation` (`instant`, `on_request`) i `response_hours`**
  (1–168, domyślnie 24). `quote_request` zostaje w kontrakcie presetów do fazy
  13; oferta go nie przyjmuje.
- **Na odpowiedź czeka tylko rezerwacja klienta.** `pending_request` powstaje
  dla rezerwacji z formularza publicznego oferty `on_request`; rezerwacja
  wpisana przez zespół w panelu (albo przez produkt przez `booking.api`) jest
  już odpowiedzią firmy, więc idzie od razu do `pending_payment` albo
  `confirmed`. Rezerwacja oczekująca trzyma termin tymi samymi alokacjami co
  potwierdzona, do `hold_expires_at` — godziny z oferty, nigdy później niż
  początek rezerwacji.
- **Zamówienie prośby to `draft` bez numeru.** `place_order(..., draft=True)`
  zapisuje zamówienie z pozycjami wyceny, bez numeru i bez ruchu licznika;
  `accept_order` nadaje numer przy akceptacji (historia: `commerce.order.drafted`,
  potem `commerce.order.placed`). Odmowa, rezygnacja i wygaśnięcie anulują
  szkic — numer nie powstał, więc numeracja nie ma dziur. Szkic nie przyjmuje
  wpłat (`order_not_placed`) i nie prosi o przedpłatę.
- **Akceptacja prowadzi do `confirmed` albo `pending_payment`.** O przedpłatę
  z zamrożonej wyceny booking prosi commerce dopiero przy akceptacji, więc
  termin przelewu liczy się od odpowiedzi firmy, nie od prośby. Przy
  `confirmed` klient dostaje zwykłe potwierdzenie; przy `pending_payment` —
  wiadomość „prośba przyjęta, czeka na wpłatę” i dane do przelewu z commerce.
- **Odpowiedź to dwa endpointy z kluczem**:
  `POST /booking/appointments/<id>/accept/` i `…/decline/`
  (`booking.appointment.manage`, `Idempotency-Key`). Rezerwacja, która już nie
  czeka na odpowiedź (wygasła, klient zrezygnował, ktoś odpowiedział), to 409
  `appointment_not_changeable`; ten sam klucz oddaje pierwszy wynik. Odmowa nie
  ma pola na powód: wolny tekst firmy w e-mailu do klienta to osobna decyzja
  (ADR-078, 36a — tekst bez linków), a powód w historii to `declined`.
- **Wygaszanie należy do booking** (ADR-072 §9): `booking_requestroute`
  (identyfikatory i termin, bez danych osobowych, kontrakt `service` roli
  `booking_requests`) i zadanie `booking.tasks.expire_pending_requests` co
  minutę. Prośba, na którą odpowiedziano w międzyczasie, zostaje.
- **E-maile** (pl, en, de): `booking.request_received` (z terminem odpowiedzi i
  linkiem do prośby — klient może z niej zrezygnować),
  `booking.request_accepted` (tylko gdy po akceptacji czeka wpłata),
  `booking.request_declined`, `booking.request_expired`. Osoby zarządzające
  rezerwacjami dostają `booking.office_request` i
  `booking.office_request_expired` **zawsze**, niezależnie od przełącznika
  powiadomień biura — prośba bez odpowiedzi wygasa, więc nie może przejść
  niezauważona.
- **Formularz mówi, że usługa jest na prośbę**: katalog publiczny niesie
  `confirmation` i `response_hours`, przycisk to „Wyślij prośbę o
  rezerwację”, a strona po wysłaniu i link klienta pokazują stan „czeka na
  odpowiedź firmy” z terminem. Plik kalendarza jest dopiero przy potwierdzonej.
- **Poza 4g**: osobna lista próśb w panelu (dziś: kalendarz, okno wizyty i
  powiadomienie), powód odmowy dla klienta, polecenia asystenta dla
  odpowiedzi na prośbę.

Rozstrzygnięcia plastra 4h (2026-10-04, decyzje techniczne z powodem):

- **Oferta niesie trzy pola**: `cancellation_refunds` — wiersze „co najmniej
  `min_days_before` dni przed początkiem → `refund_percent` zwrotu”, od
  najdłuższego wyprzedzenia, najwyżej sześć; `cancellation_applies_to`
  (`deposit` — domyślnie, `paid`; przełącznik 28a) i `balance_due_days_before`
  (0–365, puste: reszta na miejscu). Progi to lista, której rejestr ustawień
  nie ma jako typu, więc ich granice żyją w stałej `REFUND_THRESHOLDS`
  (`booking/cancellation.py`) wystawionej przez `GET /booking/setup/options/`;
  pozostałe dwa to klucze `booking.offer.*`. Klucz przełącznika to
  `booking.offer.cancellation_applies_to`, nie `…cancellation.applies_to` z
  planu ustawień: klucz grupy encji ma postać `<grupa>.<pole>`. Serwis odmawia
  progów, w których krótsze wyprzedzenie daje większy zwrot
  (`thresholds_not_descending`), i dwóch wierszy na tę samą liczbę dni
  (`duplicate_threshold`).
- **Brak progów znaczy „wszystko wraca”.** Oferta bez progów nie zapisuje
  niczego w migawce (`cancellation: null`, skrót wyceny bez zmian), a
  rezygnacja klienta oddaje wszystko, co wpłacił — tak, jak panel mówił przed
  4h („do oddania klientowi”). Mniej dni niż w ostatnim progu to 0%.
- **Migawka niesie warunki, na których klient rezerwował**: `quote.cancellation
  = {applies_to, refunds}` wchodzi do skrótu wyceny, więc zmiana progów między
  pokazaniem ceny a rezerwacją to 409 `quote_changed`, jak zmiana ceny.
  `applies_to` w migawce jest już rozstrzygnięte: `deposit` tylko tam, gdzie
  wycena ma przedpłatę będącą częścią ceny, inaczej `paid` (ADR-072 §8).
  Termin dopłaty jedzie w `quote.prepayment.balance_due_days_before`, tylko
  gdy oferta go ma.
- **Dni liczymy kalendarzem firmy**: data początku rezerwacji minus data
  rezygnacji, obie w strefie rezerwacji — nie pełne doby. Klient i firma
  sprawdzą to w kalendarzu bez godzin; rezygnacja o 23:30 liczy się jak
  rezygnacja tego dnia.
- **Kwotę liczy booking, pamięta commerce.** `booking.cancellation.refund`
  bierze migawkę, to, co wpłacono (`commerce.api.order_money`), i dzień; próg
  obejmuje przedpłatę (`min(wpłacono, przedpłata z migawki)`) albo wszystko, a
  reszta wpłat wraca w całości; połówki w górę do całej jednostki. Wynik idzie
  do `cancel_order(order, refund_minor=…)`; `None` znaczy „wszystko”. Commerce
  nadal niczego nie wycenia.
- **Kto odwołuje, ten rozstrzyga podstawę.** Rezygnacja klienta z linku —
  według progów. Odwołanie przez firmę — wraca wszystko, chyba że firma poda
  powód `balance_overdue` (29a), przyjmowany tylko wtedy, gdy dopłata jest po
  terminie (inaczej 400 `balance_not_overdue`); wtedy według progów.
  Rezerwacja, która jeszcze czekała (`pending_payment`, `pending_request`),
  nie była potwierdzona, więc częściowa wpłata wraca w całości — także przy
  wygaśnięciu terminu przedpłaty.
- **Zamówienie pamięta, ile jest do oddania**: `Order.refund_due_minor` to
  łączna kwota, która ma wrócić do klienta (z tym, co oddano wcześniej);
  „jeszcze do oddania” to ta kwota minus zwroty z księgi, nigdy więcej niż
  wpłacono (`ledger.refund_owed`). To nie jest przechowywana kwota wpłat: o
  pieniądzach nadal rozstrzyga księga, a pole zapisuje werdykt warunków z
  chwili odwołania, którego później nie da się odtworzyć.
- **Zwrot ręczny** (`Refund`, `commerce_refund` z RLS i strażnikiem relacji):
  firma oddaje pieniądze sama i oznacza zwrot — `POST
  /commerce/orders/<id>/refunds/` (z `…/preview/`, pod wersją zamówienia,
  `commerce.payments.manage`), wpis księgi `refund` z kwotą ujemną. Nie więcej,
  niż klient wpłacił (`refund_exceeds_paid`); w granicach tego, co wynika z
  warunków, bez powodu, ponad nie — z powodem słowami firmy (`reason_required`,
  §8 „zwrot spoza progów wymaga powodu”). Zwrot oznaczony przez pomyłkę się
  wycofuje (`…/refunds/<id>/void/`, wpis przeciwny). Powód widać tylko na
  stronie zamówienia, nie w historii zmian ani w e-mailu, a anonimizacja
  klienta go czyści — wolny tekst firmy może nazywać osobę. `Refund` nie wisi
  na `Payment` (§4): zwrot ręczny dotyczy zamówienia, nie jednej wpłaty;
  wskazanie płatności przyjdzie ze zwrotem przez operatora.
- **Dopłata to planowana płatność `balance`.** Po wpłacie przedpłaty
  (`prepaid`) booking woła `plan_balance(order, due_at=początek − dni)`;
  commerce zakłada `Payment` (`balance`, `requires_payment`, przelew) na to, co
  zostało do zapłaty. Bez rachunku firmy, gdy nic nie zostało albo termin już
  minął, planu nie ma i reszta idzie na miejscu, jak przed 4h. Przeniesienie
  rezerwacji przesuwa termin i kwotę tej samej płatności. Oznaczenie wpłaty
  pokrywającej dopłatę przestawia ten wiersz na `succeeded`; mniejsza zostawia
  resztę oczekiwaną — jak przy przedpłacie, tylko bez handlera `prepaid`.
- **Spóźniona dopłata niczego nie odwołuje (29a).** Trasa terminu
  (`commerce_paymentroute`) przy `balance` jest oglądana dwa razy: na
  `commerce.balance.remind_days_before` dni przed terminem (ustawienie firmy,
  0–30, domyślnie 3; 0 — bez przypomnienia) klient dostaje dane do przelewu
  jeszcze raz, a w terminie, gdy wpłaty nie oznaczono — wiadomość, że termin
  minął; osoby z `commerce.payments.manage` dostają wtedy powiadomienie w
  panelu (`commerce.balance_overdue`) i e-mail. Rezerwacja zostaje
  `confirmed`, płatność `requires_payment`. Plan ustawień (B19) proponował
  „w dniu terminu i 3 dni po”; przypomnienie **przed** terminem daje klientowi
  czas na przelew, a po terminie pierwszym ruchem jest decyzja firmy, nie
  kolejny automat.
- **E-maile** (pl, en, de dla klienta; pl, en dla firmy):
  `commerce.balance_details` (przy zaplanowaniu i jako przypomnienie),
  `commerce.balance_overdue`, `commerce.office_balance_overdue`,
  `commerce.refund_settled` (przy anulowaniu zamówienia z wpłatą: ile
  wpłacono i ile wraca). Link klienta do późniejszych wiadomości daje źródło
  (`OrderHandler.link`), bo commerce go nie przechowuje. O samym oznaczeniu
  zwrotu klient nie dostaje wiadomości — przelew jest potwierdzeniem.
  (Zmienione tego samego dnia: dostaje — „Uzupełnienie po 4h”, niżej.)
- **Ekrany**: „Cennik” oferty (reszta ceny: na miejscu albo przelewem N dni
  przed; „Rezygnacja klienta i zwrot” z progami i przełącznikiem), strona
  zamówienia („Do oddania klientowi”, „Zostaje po anulowaniu”, „Zwroty” z
  „Oznacz zwrot”), okno „Odwołać wizytę?” (ile wpłacono i ile wraca — `GET
  /booking/appointments/<id>/settlement/`; przy dopłacie po terminie pole
  wyboru powodu), formularz i link klienta (warunki rezygnacji przy cenie,
  „jeśli zrezygnujesz teraz, wraca…”, dane do przelewu dopłaty).
- **Poza 4h**: polecenia asystenta dla progów, zwrotów i wpłat (razem z
  poleceniami wpłat z 4f-2); e-mail do klienta o oznaczonym zwrocie; gotowy
  preset z progami (Nocleg w wersji 1 je ma, ale jest zapowiedzią — wersja w
  użyciu ich nie nazywa); status zamówienia `refunded`; dopłata planowana dla
  rezerwacji bez przedpłaty; zwrot i dopłata online (faza 7). (E-mail, preset,
  status i polecenia wpłat zamknięte w „Uzupełnieniu po 4h”, niżej.)

Uzupełnienie po 4h (2026-10-04, drobne pozycje zamknięte po fazie 4; decyzje
techniczne z powodem):

- **Klient dostaje e-mail o oznaczonym zwrocie.** `record_refund` wysyła
  `commerce.refund_marked` (pl, en, de): numer i przedmiot zamówienia, kwota i
  sposób („przelewem”, „na miejscu”). Powodu zwrotu w wiadomości nie ma — to
  słowa firmy, zostają na stronie zamówienia (§8). Dotąd o zwrocie mówił tylko
  sam przelew; klient, któremu firma oddała pieniądze na miejscu albo którego
  przelew jeszcze nie doszedł, nie miał żadnego śladu. Wycofanie zwrotu
  oznaczonego przez pomyłkę wysyła `commerce.refund_withdrawn` — inaczej
  klient czekałby na pieniądze, o których mu napisano. Jedna wiadomość na
  zwrot i krok; kopie czyści `strip_buyer` jak pozostałe (ten sam
  `causation_id`). Okna „Oznacz zwrot” i „Wycofać zwrot?” mówią o e-mailu przed
  zapisem, a przy kliencie bez adresu — że trzeba dać mu znać inaczej.
- **Status `refunded` jest używany**, a nie usunięty: zamówienie odebrane przez
  źródło jest `canceled`, a `refunded` („Zwrócone”) — gdy firma oddała pieniądze
  i warunki nie każą oddać nic więcej (`refunded_minor > 0` i
  `refund_owed_minor == 0`). Liczy to jedna funkcja, `ledger.status_for`;
  wycofany zwrot przywraca `canceled`. Lista zamówień odróżnia więc anulowane,
  które są rozliczone, od tych, które jeszcze czekają albo nic nie miały do
  oddania. Dla pieniędzy oba stany znaczą to samo — nikt już za takie
  zamówienie nie płaci i nikt go nie wycenia od nowa (`ledger.CLOSED_STATUSES`,
  w panelu `isClosed`). Bez migracji: wartość była w modelu od 0001. Odrzucone:
  usunięcie statusu — migracja i zmiana kontraktu po to, żeby lista mówiła
  mniej; `refunded` dla zamówienia nieanulowanego, któremu oddano wszystko —
  takie zamówienie nadal obowiązuje i czeka na wpłatę, więc „Do zapłaty” mówi
  prawdę.
- **Nocleg w wersji 4 niesie warunki na start**: przedpłata 30% przelewem z
  trzema dniami na wpłatę, reszta 14 dni przed pobytem, progi zwrotu przedpłaty
  100% do 30 dni, 50% do 14 dni, potem 0% (`core.lodging.v4.json`; wartości z
  wersji 1, która była zapowiedzią). Opis presetu i słowa zgody polecenia
  `booking.preset.apply@1` mówią, że to punkt wyjścia do zmiany w „Cenniku”.
  Samej przedpłaty preset nadal nie włącza („Preset nie wybiera wpłaty z góry
  za firmę”, wyżej): oferta startuje z `none`, z procentem, terminami i progami
  już wpisanymi. Opis presetu może mieć teraz 400 znaków (było 240) — zdanie o
  warunkach nie mieściło się obok opisu rodzaju. Test kontraktu presetów
  dopuszcza w presecie gotowym przedpłaty i progi (silnik obsługuje je od fazy
  4). Wersja 3 przyszła tego samego dnia z fazą 5b (goście rezerwują przez
  stronę); warunki stoją na niej, jako wersja 4.
- **Polecenia asystenta** dla zamówień, wpłat i odpowiedzi na prośbę: ADR-076,
  „Uzupełnienie 2026-10-04: zamówienia, wpłaty i prośby o rezerwację”.
  `void_payment` dostał `preview` (ta sama walidacja, bez zapisu). Polecenia
  zwrotów i progów oferty zostają otwarte — tam, pkt 7.

Uzupełnienie plastrów 4b–4g (2026-10-04, drobne zaległości zamknięte razem z 4h):

- **Wersja dokumentu nie wchodzi w życie przed wersją już zatwierdzoną** (4b,
  §9). `approve_draft` odmawia daty wcześniejszej niż najpóźniejsza data
  zatwierdzonej wersji (400 `before_latest_version`, także w podglądzie), a
  bez podanej daty proponuje najwcześniejszą możliwą (`effect.not_before`
  mówi, od którego dnia). Powód: wersja „od dziś” zatwierdzona po wersji na
  późniejszy dzień ustępowała tamtej, gdy jej dzień nadszedł (`_in_force`
  wybiera późniejszą datę), choć zatwierdzono ją ostatnią — klient dostawałby
  starszy tekst bez niczyjej decyzji. Ten sam dzień jest dozwolony: wygrywa
  wersja zatwierdzona później.
- **Tłumaczenie wpisane ręcznie da się potwierdzić bez zmian po poprawce
  źródła** (4d-2). Wiersz tekstu niesie `stale` — zaakceptowano go wobec innego
  tekstu w języku wersji, niż obowiązuje teraz; dla takiego wiersza `add_text`
  przyjmuje te same słowa i dopisuje nowy wiersz (ta sama bramka osoby i ten
  sam kod z aplikacji), który mówi, że tekst przeczytano wobec poprawionego
  źródła. Poza tym te same słowa to nadal 400 `text_unchanged`.
- **Powód odmowy** (4g, ADR-078 36a): `POST …/appointments/<id>/decline/`
  przyjmuje opcjonalne `reason` — do 300 znaków zwykłego tekstu, bez linków i
  adresów (400 `links`, ta sama reguła co tekst firmy w e-mailach). Trafia do
  e-maila `booking.request_declined` (szablon w wersji 2, jako „Wiadomość od
  <firma>”) i nigdzie więcej: historia rezerwacji i historia zmian firmy
  zapisują tylko `declined`, bo to słowa pisane do jednego klienta.
- **Lista próśb** (4g): `GET /booking/requests/` (dla zarządzających
  rezerwacjami; najpierw prośba, której czas na odpowiedź kończy się
  najwcześniej) i strona Kalendarz › „Prośby”. `GET /booking/overview/` niesie
  `requests` — liczbę próśb albo `null`, gdy firma niczego nie przyjmuje na
  prośbę i nic nie czeka; wtedy strony nie ma w menu.
- **Słowa**: okna „Odwołać wizytę?” i „Przełóż” mówią, że klient dostanie
  e-mail (serwer wysyła `booking.canceled` i `booking.rescheduled` każdemu, kto
  podał adres), a gdy adresu nie ma — że trzeba dać mu znać; dzwonek nazywa
  powiadomienia `booking.office_*`; „Do akceptacji” wymienia dokumenty dla
  klientów obok strony i wizytówki.

Rozstrzygnięcia plastra 4i (2026-10-04, po odpowiedzi właściciela 7 z 04.10;
decyzje techniczne z powodem):

- **Okres to jedna stała**: `commerce.retention.BUYER_RETENTION_YEARS = 5` —
  wartość robocza do odpowiedzi prawnika, nie ustawienie firmy (firma nie może
  wybrać krótszego przechowywania zapisów sprzedaży, niż każe prawo). Liczą się
  pełne lata kalendarzowe po roku ostatniego wpisu księgi zamówienia, **w
  strefie czasowej firmy**: wpłata z czerwca 2026 trzyma kupującego do końca 31
  grudnia 2031, a od północy 1 stycznia 2032 czasu firmy już nie. Wpis z 31
  grudnia 23:30 UTC jest dla firmy z Warszawy wpisem z nowego roku.
- **Która data wpisu.** Wpis księgi ma dwie daty: kiedy rzecz się stała
  (`occurred_at`) i kiedy ją zapisano (`created_at`). Liczy się późniejsza —
  wpis dopisany po czasie do wcześniejszego zdarzenia trzyma kupującego od
  chwili dopisania. Usunięcia nie da się cofnąć, więc w razie wątpliwości okres
  jest dłuższy, nie krótszy.
- **Zapis sprzedaży to zamówienie, za które naprawdę wzięto pieniądze**: wpisy
  `charge` dają razem więcej niż zero. Wpłata oznaczona przez pomyłkę i wycofana
  nie jest sprzedażą i niczego nie trzyma („zamówienie bez wpłaty niczego nie
  trzyma”); zamówienie opłacone i zwrócone w całości zostaje zapisem — wpłata
  była, a zwrot jest jej korektą. Okres liczy się od ostatniego wpisu
  dowolnego rodzaju, więc zwrot oznaczony po trzech latach zaczyna go od nowa.
- **Przebieg firmy omija kupującego do końca okresu** — tak, jak mówi zdanie
  tego ADR z 03.10 („migawka kupującego i klient zostają”). Commerce rejestruje
  wykluczenie przemiatania klientów (`register_retention_exclusion` pod kluczem
  `customers.api.CUSTOMER_RETENTION_SWEEP` — commerce nie nazywa booking) i
  podaje powód; podgląd ustawienia „Dane klientów” mówi, ilu klientów po
  terminie zostaje i dlaczego. Pod blokadą klientów `erase_customers` pyta o
  wykluczenia ponownie (`excluded_ids(…, among=…)`), a commerce przed odczytem
  księgi blokuje zamówienia tych klientów: każdy zapis do księgi bierze najpierw
  blokadę zamówienia, więc wpłata w toku każe przebiegowi poczekać i jest
  widziana, a późniejsza czeka na przebieg. Kolejność blokad: klient, wizyta,
  zamówienie. Gdy okres minie, przebieg firmy usuwa klienta razem z migawką.
  **Do potwierdzenia z prawnikiem (lista prawna, 04.10):** czy przebieg ma
  zostawiać takiego klienta w całości, czy — jak ręczna anonimizacja — czyścić
  kartę klienta i wizyty po okresie wybranym przez firmę, a zostawiać samą
  migawkę zamówienia. Druga wersja przechowuje mniej; to jedna linia
  (rejestracja wykluczenia w `commerce/apps.py`), reszta mechanizmu jest wspólna.
- **Ręczna anonimizacja czyści klienta i wizyty, a migawkę zostawia do końca
  okresu** (propozycja z 03.10, przyjęta). `strip_buyer` blokuje zamówienia
  klienta, czyta księgę spod blokady i czyści migawkę tylko tam, gdzie
  zamówienie nie jest zapisem sprzedaży w okresie. Zapisane kopie e-maili i
  powód zwrotu (wolny tekst firmy) znikają od razu także przy zostawionej
  migawce — nie są zapisem sprzedaży. Wpłata oznaczona **po** anonimizacji nie
  przywraca nazwiska: migawki już nie ma.
- **Po okresie migawkę usuwa wspólny przebieg prywatności**: przemiatanie
  `commerce.buyers` z regułą bez okresu ochronnego (to okres z prawa, nie
  kliknięcie firmy), w każdej firmie — także tam, gdzie „Dane klientów” nie są
  oferowane, bo ręczna anonimizacja jest wszędzie. Bierze zamówienia
  zanonimizowanych klientów, które nadal nazywają kupującego, blokuje je i czyta
  księgę ponownie; usuwa też migawkę zamówienia, które przestało być zapisem
  sprzedaży (jedyną wpłatę wycofano jako pomyłkę już po anonimizacji). Wpis w
  historii firmy jak przy innych przemiataniach: rodzaj, „5 lat”, liczba.
- **Bez migracji.** Zostawioną migawkę rozpoznaje się po tym, że różni się od
  zastępczej nazwy zanonimizowanego klienta albo ma e-mail lub telefon; nowe
  pole na zamówieniu niczego by nie dodało, a kosztowałoby migrację danych.
- **Panel mówi, co zostaje i dlaczego.** `GET
  /booking/customers/<id>/anonymize/preview/` (to samo uprawnienie co
  anonimizacja) oddaje listę tego, co zostanie, z dniem i powodem w pl i en —
  czyta rejestr, z którego korzysta samo czyszczenie
  (`register_customer_anonymizer(…, keeps=…)`). Strona zamówienia dostała
  „Usuń dane klienta…” z tym podglądem — pierwsze miejsce w panelu, w którym
  osoba może zanonimizować klienta (dotąd był tylko endpoint) — a zamówienie
  zanonimizowanego klienta mówi, do kiedy nazywa kupującego
  (`buyer_kept_until`, `customer_anonymized_at`). Przycisk jest tylko w profilu,
  który oferuje „Dane klientów” (`features.customerRetention`): w produkcie z
  kartą gospodarstwa klient zostałby nazwany na karcie, a okno obiecywałoby
  więcej, niż się dzieje; w gabinetach usuwanie danych klientów zostaje
  wyłączone (odpowiedź właściciela 9 z 04.10). Endpoint anonimizacji jest tam,
  gdzie był.
- **Poza 4i**: historia cen przed promocjami (druga połowa wiersza 4i w tabeli
  — zostaje otwarta, należy do cennika rezerwacji); polecenie asystenta dla
  anonimizacji (klasa `irreversible`, dane osoby — osobna decyzja); miejsce w
  panelu do anonimizacji klienta, który nie ma żadnego zamówienia (nie ma listy
  klientów).

Zgody marketingowe w panelu (2026-10-04, odpowiedź właściciela 6 z 04.10;
decyzje techniczne z powodem):

- **Treść zgody to jedna stała** `MARKETING_WORDING`, wystawiona przez
  `customers.api` razem z `marketing_wording(locale, firma)`: „Chcę otrzymywać
  oferty i promocje od {firma} e-mailem.” (pl, en, de; język bez własnego zdania
  nie ma zgody — o zgodę nie pyta się w innym języku). Formularz pokazuje to
  zdanie i — gdy klient je zaznaczy — rezerwacja przekazuje dokładnie ten tekst
  do `record_consent` (`kind="marketing"`). Pole w formularzach publicznych:
  „Uzupełnienie 2026-10-04: krok zgód formularzy publicznych”, niżej; stała
  jest jedna dla obu stron.
- **Dziennik trzyma skrót, nie słowa** (decyzja koordynatora z 04.10). Lista
  odtwarza zdanie, składając stałą z nazwą firmy i porównując skróty. Gdy żaden
  skrót nie pasuje — firma zmieniła nazwę albo zmieniono zdanie — wiersz nadal
  mówi, kto, kiedy i w którym formularzu się zgodził, i wprost, że słów z tamtego
  dnia nie da się już odtworzyć. Dlatego zmiana zdania w stałej jest decyzją, a
  nie poprawką. Otwarte: kolumna z treścią w dzienniku usunęłaby to ograniczenie.
- **Lista jest odczytem dziennika**: `GET /customers/consents/marketing/`
  (`customers.read`; `state=granted` albo `withdrawn`, stronicowana) — jeden
  wiersz na klienta, o stanie rozstrzyga jego ostatni wpis. Klient, którego dane
  usunięto, nie jest na liście (nie ma do kogo pisać); jego wpisy zostają.
- **Wycofanie to kolejny wpis** (`granted=False`, źródło `customers.panel`,
  odniesienie — wpis zgody): `POST /customers/consents/marketing/<klient>/withdraw/`
  (`customers.manage`) nazywa zgodę, którą osoba widziała; gdy nie jest już
  ostatnim wpisem klienta, odpowiedź to 409 `consent_changed` i nic nie powstaje
  — powtórka nie dopisuje drugiego wpisu. Historia firmy mówi, kto odnotował
  (`customers.consent.withdrawn`), bez nazwiska klienta. Ekran: Ustawienia ›
  „Zgody marketingowe”.
- **Poza zakresem**: wycofanie przez samego klienta (link w e-mailu), zgody osób
  bez rekordu klienta (pytający z formularza kontaktowego — dziennik je
  przyjmuje, lista ich nie pokazuje), eksport listy, osobna zgoda na telefon i
  SMS (lista prawna, 04.10) oraz polecenie asystenta (lista niesie dane osób).

## Uzupełnienie 2026-10-04: krok zgód formularzy publicznych

Decyzje właściciela z 2026-10-04 (po scaleniu formularza pobytów, ADR-072
plastry 5a–5b), wspólne dla formularza wizyty i pobytu, bez migracji:

- **Język bez tekstu regulaminu zamyka rezerwację online w tym języku.** Gdy
  firma ma obowiązujący regulamin rezerwacji, ale bez tekstu w języku
  rezerwacji, nikt w tym języku nie rezerwuje przez formularz: zapis to 409
  `booking_language_unavailable` z `detail.locales` — językami firmy, w
  których regulamin ma tekst — a `GET …/consents/` mówi to z góry (`bookable`,
  `bookable_locales`), więc formularz pokazuje kartę „w tym języku nie można
  zarezerwować online” z odnośnikami do formularza w tamtych językach, jak
  kartę pauzy. Powód: czytnik nie zastępuje języka (wyżej), więc dotąd klient
  w takim języku rezerwował bez żadnego regulaminu — umowa bez warunków, na
  które się zgodził. Reguła zmienia zdanie ADR-071 pkt 21 „rezerwacji nie
  odmawia się z powodu języka” w jednym miejscu: język, którego firma w ogóle
  nie ma, nadal przechodzi na jej pierwszy; odmowa dotyczy języka firmy bez
  tekstu regulaminu.
- **Blokuje tylko regulamin rezerwacji.** Polityka prywatności bez tekstu w
  języku nie jest pokazywana ani wymagana i niczego nie zamyka (obowiązek
  informacyjny firma spełnia też inaczej; umowy bez warunków — nie). Firma bez
  obowiązującego regulaminu rezerwuje we wszystkich swoich językach jak dotąd.
- **Reguła obowiązuje każdego, kto rezerwuje sam albo sam pokazał dokumenty**
  (kontekst formularza publicznego albo przekazane `BookingConsents`) — to ten
  sam warunek co przy `documents_changed`, w tym samym miejscu
  (`booking.consents.record`). Biuro w panelu rezerwuje klienta w dowolnym
  języku jak dotąd. Języki regulaminu czyta `customers.api.document_locales`
  (None: brak obowiązującej wersji), bo `current_document` nie odróżnia
  „nie ma dokumentu” od „nie ma tekstu w tym języku”.
- **Panel ostrzega tam, gdzie firma ustawia dokumenty i języki**: lista
  dokumentów, ekran regulaminu rezerwacji i Ustawienia › Języki mówią
  „Regulamin rezerwacji nie ma wersji w języku English — rezerwacja online w
  tym języku jest wyłączona”, a zatwierdzenie nowej wersji regulaminu mówi, że
  pozostałe języki zostaną zamknięte od dnia, w którym wersja zacznie
  obowiązywać (nowa wersja zaczyna od jednego języka). Ostrzeżenie liczy
  panel z listy dokumentów (`in_force.locales` wobec języków firmy); ekran
  języków dostaje je jako sekcję składaną przez stronę i odświeża po zmianie
  listy języków (`useCompanyLanguages`).
- **Zgoda marketingowa: jedno nieobowiązkowe pole, domyślnie odznaczone.**
  Brzmienie jest jedno i stałe: „Chcę otrzymywać oferty i promocje od {firma}
  e-mailem.” (en, de tak samo), w `customers.documents.MARKETING_WORDING`,
  czytane przez `customers.api.marketing_wording(locale, firma)`. Formularz
  dostaje zdanie z `GET …/consents/` (`marketing.statement`) i odsyła tylko
  `consents.marketing: true` — słowa wpisu wyznacza serwer, nie przeglądarka.
  Zaznaczone pole to osobny wpis dziennika `kind="marketing"` ze skrótem
  zdania, które klient widział (z nazwą firmy), i językiem. Dziennik trzyma
  tylko skrót, więc lista zgód w panelu rozpoznaje brzmienie tą samą funkcją.
  Język bez własnego zdania nie ma pola (zgody nie zbiera się w cudzym
  języku), a klient, który nie podał e-maila, nie zostawia wpisu — zgoda
  dotyczy e-maili.
- **Firma może pola nie pokazywać**: ustawienie `booking.online.marketing_consent`
  (grupa „Rezerwacja online”, domyślnie włączone). Wyłączone — formularz pola
  nie dostaje, a `consents.marketing` z formularza otwartego wcześniej niczego
  nie zapisuje.
- **Skrót wyceny na publicznej ścieżce terminów jest wymagany** — tak jak dla
  pobytu: wizyta z ceną rezerwowana z formularza bez `quote_digest` albo z inną
  ceną to 409 `quote_changed` z wyceną (zachowanie z fazy 3d, `seen=None` w
  `_visit_quote`; kontrakt i ADR-072 mówiły dotąd „opcjonalny”). Przełożenie
  wizyty z linku klienta nadal nie wymaga skrótu, dopóki cena się nie zmienia.
- **Poza tym krokiem:** cofnięcie zgody marketingowej i lista zgód w panelu
  (dziennik i ekran — osobna praca nad `shared.customers`); brzmienia w
  językach poza pl, en, de; strona prawna witryny z dokumentów firmy (ADR-072,
  plaster 5f).
