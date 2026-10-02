# ADR-073 — Zamówienie, płatności klienta końcowego i tryby operatora

**Status:** Accepted — decyzje właściciela (plan rezerwacji uniwersalnych,
odpowiedzi 1–24 z 01–02.10.2026) i decyzje techniczne agenta (T1–T23 planu);
pozostałe rozstrzygnięcia techniczne tego ADR-u (z powodem w tekście): kierunek
zależności, rejestr źródeł i `commerce.enabled` (§1), termin płatności w
commerce i przelew zamiast online (§5), skrzynka zdarzeń i lista kluczy (§6),
podstawa progu zwrotu i kaucja z linku (§8), dokumenty w customers (§9).
**Data:** 2026-10-02
**Częściowo zastępuje:** ADR-037 §1 (zależność od booking), §2 (konta Express,
prowizja w katalogu), §3 (`AppointmentPayment`, `tax_rate_bp`; „nigdy z
formularza” tylko w trybie `platform`), §4 (cena, waluta i `tax_rate_bp` jako
pola `Service`, jedno okno 15 min, wygaszanie w booking), §5 pkt 3 i 5, §6
(trasa w trybie `own`, treść skrzynki), §7 („i zdarzeniem”, podstawa zwrotu),
§8 („organizacja nie wybiera operatora”); ADR-036 §5 („zostaje w
`shared.booking`”). Reszta ADR-037 wraca z odroczenia jako źródło przepływu i
księgi. **Zmienia (z ADR-072):** ADR-030, zdanie „płatność i zaliczka są poza
pierwszym zakresem W9”. **Doprecyzowuje:** ADR-036 §8 (dokumenty sprzedaży,
§9). **Uzupełnia:** ADR-072, ADR-074, ADR-075. **Nie zmienia:** ADR-026,
ADR-032, ADR-034, ADR-040, ADR-042.

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
- Tabele mają wymuszone RLS i strażnika relacji; księga, wersje dokumentów,
  zgody i nadpisania prowizji są tylko do dopisywania (furtka usunięcia tenanta,
  ADR-042), trasy bez danych osobowych w `register_erasure_rows`. Booking nie ma
  kluczy obcych do commerce, bo działa też bez niego.

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
  (ADR-036 §5) powstaje tutaj, a `Customer.locale` żyje w customers (TL10).

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
  `tax_rate` (§8), migawka nazwy, `source`, `source_reference`. Pozycje
  przychodzą gotowe z `quote` (ADR-072 §7) albo z koszyka (ADR-074); commerce
  cen nie liczy, a złożonych pozycji nie zmienia — korekta to nowa pozycja.
  Bony, karnety i kody rabatowe (faza 10) też należą do commerce.
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
  3 dni”), uogólnione przez ten ADR: przelew zachowuje wpłatę z góry.
- Oferta z wpłatą przed potwierdzeniem (`transfer`, `deposit`, `full`) tworzy
  `pending_payment`, które trzyma termin jak potwierdzona (ADR-072 §9, zawężenie
  ADR-058 §3 oparte na 13a); bez commerce ten stan nie powstaje.
- **Termin należy do commerce**: rozstrzyga `Payment.due_at` (online domyślnie
  15 minut, rekomendacja ADR-037; przelew — dni z oferty, Nocleg 3). Zadanie
  terminów czyta trasę bez danych osobowych (`payment_id`, `organization_id`,
  `due_at`, niewygasający kontrakt `service` organizacji; wzorzec
  `ReminderRoute`, ADR-058 §7) i w jednej transakcji wygasza płatność, anuluje
  zamówienie, a handler źródła zwalnia rezerwację (z powodem w historii) albo
  towar. `Appointment.hold_expires_at` to kopia `due_at` do wyświetlania, a
  booking sam wygasza tylko `pending_request` (odpowiedź firmy), tą samą drogą.
- Płatność online potwierdzona po terminie wraca zwrotem (odmowa handlera, §1);
  spóźniony przelew firma zwraca albo rezerwuje od nowa. Dopłata (`balance`) po
  terminie niczego nie anuluje: przypomnienie i decyzja firmy (Konsekwencje).

### 6. Port płatności: tryby `platform` i `own` (T11)

- `PaymentProviderConnection` (pola ADR-037 §3) dostaje `mode` (`platform` |
  `own`) i `adapter` (`stripe_connect`, `przelewy24`, `payu`, `simulated`),
  jedno na firmę i adapter; tryb wybiera firma, metody daje `capabilities`.
- **`platform`** (faza 7, po W9.5.2S): Stripe Connect, direct charges z
  `application_fee_amount`; zwroty, spory i opłaty obciążają firmę (ADR-037 §2).
  Konta według rekomendacji Stripe z fazy 7, nie Express. Konto platformy to
  samo co abonamenty, ale zdarzenia kont połączonych mają osobny endpoint i
  sekret, bo Stripe wysyła je osobno (sprawdzić w fazie 7) — odstępstwo od
  zapisu planu o jednym zestawie webhooków. Jeden operator na deployment
  (`COMMERCE_PROVIDER`: `stripe_connect` | `simulated` poza produkcją).
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
  dni do początku w strefie firmy. Próg ma podstawę `appliesTo` (preset i
  oferta, ADR-072 §8): `deposit` — procent zadatku, `paid` — wszystkich wpłat.
  Nocleg ma `deposit`, bo 13a mówi o „zwrocie zadatku” (≥ 30 dni 100%, 14–29 dni
  50%, < 14 dni 0%), a inne wpłaty wracają wtedy w całości: o dopłacie wpłaconej
  14 dni przed przyjazdem 13a milczy, więc do odpowiedzi właściciela gość
  rezygnujący później odzyskuje ją całą (też lista prawna: zadatek a zaliczka,
  art. 394 KC). Odwołanie przez firmę zwraca co najmniej wszystkie wpłaty; czy
  przy zadatku należy się więcej (art. 394 § 1 KC) — lista prawna. Online zwraca
  adapter, ręczną wpłatę firma oddaje sama; zwrot spoza progów wymaga powodu.
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
  `0`, `zw` jak `VatRate` magazynu), bo `zw` to nie `0`; netto i brutto liczy
  `quote` (ADR-072 §6–§7), stawkę wybiera firma. ADR-040 dotyczy abonamentów.

### 9. Dokumenty, zgody, faktury (T15, T16)

- Dokumenty firmy dla klientów (regulaminy rezerwacji i sklepu, polityki
  prywatności i anulowania) żyją w `shared.customers`, najniższym module
  wspólnym dla rezerwacji, zamówień i sklepu. Edytowalny szkic zatwierdza osoba
  z firmy po ponownym uwierzytelnieniu (plan asystenta, A2), co zapisuje wersję
  tylko do dopisywania, obowiązującą od daty; tylko taką przyjmują rezerwacja i
  zamówienie. Wersja ma wiersz treści na język (wzór `PublicProfileTranslation`;
  kod `^[a-z]{2}$` sprawdza serwis do czasu rejestru języków, TL1) i jest
  źródłem tłumaczeń (TL-T17, ADR-069); automat tłumaczy dokument prawny zawsze
  do akceptacji (TL-T25).
- Zgody to dziennik tylko do dopisywania (nie `PolicyAcknowledgement` z ADR-036
  §8): wpis wskazuje klienta, wersję i język dokumentu (albo zgodę
  marketingową, albo pole `consent`, ADR-072 §8) i źródło napisem (`source`,
  `source_reference`). To on jest migawką wersji z T16, więc booking nie dostaje
  nowego klucza obcego.
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
  z zakresem `commerce.public.pay`, dopisanym do jego uprawnień. Token wiąże
  płatność z jednym zamówieniem, kwotę liczy serwer; link samoobsługi żyje do
  końca rezerwacji (ADR-072), więc dożywa terminu dopłaty.
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
  wersje planów z `commerce.enabled`; numer booking uzgodnić z TL10, TL12 i
  ADR-067), lista kluczy i sekret webhooka kont połączonych idą do `memex ops`.
  Zdarzeń domenowych commerce nie emituje do pierwszego konsumenta (ADR-024).
- Subskrypcje na starszych wersjach planów dostaną `commerce.enabled` po zmianie
  planu albo nadpisaniem operatora (`EntitlementGrant`, T18), a do tego czasu
  działają jak bez cechy (§1). Panel oferuje dziś też GBP, a backend każdy kod
  ISO: faza 3 daje firmie z walutą spoza listy zmianę z podglądem przed
  pierwszym cennikiem, a listy panelu czytają `options` z API.
- Otwarte pytania do właściciela (w nawiasie wartość do odpowiedzi): zwrot
  dopłaty przy późnej rezygnacji (§8: cała); dopłata niezapłacona w terminie
  (§5: przypomnienie i decyzja firmy, nic się samo nie anuluje); okno płatności
  online (15 min); stała część prowizji w EUR i USD; prowizja od zatrzymanej
  kaucji (brak); plany z `commerce.own_account.enabled`; połączenie płacące u
  firmy z `platform` i `own` (jedno aktywne, wybiera firma); VAT spoza Polski.
- Otwarte technicznie: konfiguracja kont Stripe (faza 7) i to, czy strona
  prawna witryny pokazuje bieżącą wersję dokumentu. Sprawy prawne i księgowe
  (sprzedawca, PSD2, zadatek a zaliczka, kaucja i jej VAT, przechowywanie
  zamówień, VAT prowizji, paragony, spółka konta Stripe) — na liście prawnej.

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
