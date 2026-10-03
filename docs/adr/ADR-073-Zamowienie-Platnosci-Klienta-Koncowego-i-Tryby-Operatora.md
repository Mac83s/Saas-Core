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
  protokół `docs/architecture/translation-sources.md`): wersjonowane, podstawa
  `published`, zapis `pending` i `live`, dokument prawny. Automat tłumaczy go
  zawsze do akceptacji (ADR-069 pkt 16.1, TL-T25): wynik `pending` czeka poza
  wierszami wersji, a wiersz dopisuje dopiero akceptacja osoby (`review` przez
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
| **4d-2** | Dokument jako źródło tłumaczeń `customers.document` (§9): adapter, tabele §5 i §8.1 protokołu, test kontraktu, `shared.customers` w kontrakcie `.importlinter` bez silnika; akceptacja tłumaczenia przez osobę ze step-upem w centrum tłumaczeń | do rozstrzygnięcia (niżej) | Tłumaczenia |
| **4e** | `shared.commerce`: `Order`, `OrderLine`, licznik numerów, `register_order_source`, `place_order`, `ORDER_MODEL`; booking jako źródło `R` zakłada zamówienie z pozycji zamrożonej wyceny w transakcji rezerwacji; migawka kupującego i jej czyszczenie przy anonimizacji; kanał i token pochodzenia; `commerce.enabled` w nowych wersjach planów; `GET /commerce/options/`, lista zamówień | commerce 0001–0002, billing (wersje planów) | Zamówienia (lista, szczegół) |
| **4f** | Wpłaty ręczne i przelew z terminem (§4–§5): `Payment`, `LedgerEntry`, rachunek firmy do przelewów, polityki oferty `transfer`, `deposit`, `full` opłacane przelewem, `pending_payment` z `hold_expires_at`, `register_service_scope` w rdzeniu (z przeniesieniem dzisiejszych wpisów), zadanie terminów, oznaczenie wpłaty przez firmę, e-maile z numerem zamówienia i danymi do przelewu | commerce, booking, organizations | wpłata w zamówieniu, oferta |
| **4g** | „Na prośbę” (ADR-072 §9): `confirmation` `on_request`, `pending_request`, akceptacja i odmowa w panelu, wygaszanie przez booking, zamówienie `draft` bez numeru do akceptacji, e-maile (przyjęta, odmowa, wygaśnięcie) | booking | kalendarz, oferta |
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
  byłaby zgodą.
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
  zostaje do końca okresu).
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
- **Zgoda marketingowa to osobny wpis, którego formularz jeszcze nie zbiera.**
  `BookingConsents.marketing` (treść zgody) dopisuje wpis `kind="marketing"`
  ze skrótem treści obok wpisów dokumentów. Pole w formularzu publicznym
  przyjdzie razem z treścią zgody od prawnika i z miejscem, w którym firma
  zobaczy, kto się zgodził — zgoda, której firma nie może odczytać, niczemu nie
  służy, a jej słowa to ryzyko prawne, nie decyzja techniczna.

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
