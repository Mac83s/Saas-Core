# ADR-073 — Zamówienie, płatności klienta końcowego i tryby operatora

**Status:** Accepted — decyzja właściciela 3 z 01.10.2026 (płatności klientów
przez nas, Stripe), odpowiedzi 2a, 3a, 7a, 11a, 13a, 16 i 21 (01–02.10) oraz
decyzje techniczne T9–T11, T15, T16, T18, T22, T23 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`.
**Data:** 2026-10-02
**Częściowo zastępuje:** ADR-037 §1 (zależność od `shared.booking`), §2 (konta
Express, prowizja jako dana katalogu), §3 (`AppointmentPayment`, `tax_rate_bp`),
§4 (cena i polityka na `Service`, jedno okno 15 min), §5 pkt 3 i 5 (zdarzenie
`booking.appointment.confirmed`, degradacja tylko do `on_site`), §8 (jeden
operator, firma nie wybiera); ADR-036 §5 w słowach „zostaje w `shared.booking`”.
Reszta ADR-037 — w tym §5–§7 i rodzaje `LedgerEntry` — wraca z odroczenia jako
źródło przepływu i księgi.
**Uzupełnia:** ADR-072. **Nie zmienia:** ADR-026, ADR-032, ADR-034, ADR-040,
ADR-042.

## Kontekst

Właściciel 01.10: każda rezerwacja i każdy zakup w sklepie to zamówienie z
numerem, zgodami i płatnością; płatności klientów firm idą przez platformę —
najpierw Stripe Connect z naszą prowizją, port od razu gotowy na własne konto
firmy (2a). ADR-037 opisał przepływ dla jednej wizyty i od 02.09 jest odroczony;
nie mieści sklepu, zadatku z dopłatą, kaucji ani własnego konta firmy.

Kodu płatności klienta końcowego nie ma (main e381199,
`deployments/business/deployment.json:11-23`), a `Customer` jest w booking
(`shared/booking/models.py:339-359`).

## Decyzja

### 1. Moduły i kierunek zależności

- **`shared.customers`** (`dependsOn: ["core.organizations"]`): klient,
  dokumenty firmy dla klientów i zgody (§2, §9).
- **`shared.commerce`** (`dependsOn: ["core.organizations", "shared.billing",
  "shared.customers", "shared.notifications"]`, `/api/v1/commerce`): uprawnienia
  z ADR-037 §1, cechy `commerce.enabled` (każdy plan, 7a) i
  `commerce.own_account.enabled` (tryb `own`, płatna opcja planu, 2a). Nie zna
  rezerwacji ani sklepu: pozycja wskazuje źródło napisem (`source`,
  `source_reference`), jak `StockReservation` magazynu. Kod Stripe wspólny z
  billingiem (dziś `shared/billing/provider.py:157-163`) idzie do
  `saas_core/integrations/stripe/` (ADR-037 §1).
- **`shared.booking`** dostaje `shared.customers` w `dependsOn`, a commerce używa
  opcjonalnie: `ACTIVE_MODULES` i leniwy import `commerce.api` (wzorzec
  `shared/booking/materials.py:32-33`). Bez commerce albo bez cechy
  `commerce.enabled` booking działa jak dziś.
- Źródło rejestruje się przez
  `commerce.api.register_order_source(kind, prefix, handler)` (booking:
  `booking.appointment`, `R`; sklep z ADR-074: `Z`). Commerce woła handler w
  transakcji, w której zmienia stan zamówienia (opłacone, wygasłe, anulowane,
  zwrócone); wyjątek wycofuje całość. Obserwatorzy wizyt działają po commicie i
  połykają błędy (`shared/booking/observers.py:52-69`), więc nie niosą przejść
  stanu ani pieniędzy.
- Tabele obu modułów: `TenantScopedModel`, wymuszone RLS, wyzwalacz cross-tenant,
  usuwanie według ADR-042; księga, wersje dokumentów, zgody i nadpisania prowizji
  są tylko do dopisywania z furtką `app.erasing_organization_id` (billing 0022).
  Indeksy routingu są bez RLS i danych osobowych, zgłoszone przez
  `register_erasure_rows`; ścieżki publiczne nie używają `PRE_TENANT_DB`. Booking
  nie dostaje kluczy obcych do commerce.

### 2. Klient w `shared.customers`, ta sama tabela (T10)

- `Customer` przechodzi samym stanem modelu (`SeparateDatabaseAndState`, booking
  0013 i customers 0001, odwracalne). Tabela zostaje `booking_customer`, a z nią
  RLS (booking 0002) i mapa wyzwalacza `customer → booking_customer` (booking
  0003, 0010). Danych nie kopiujemy.
- Dopasowanie (`customers.api.match_or_create`, dziś
  `shared/booking/services.py:512-528`) i anonimizacja przechodzą bez zmiany
  zachowania; `create_appointment(customer_data=…)` zostaje kontraktem produktów
  (HoofCare `vertical/hoofcare/services.py:203-215`). Anonimizacja woła w swojej
  transakcji rejestr `register_customer_anonymizer(name, fn)`: booking czyści
  uwagi i ulicę wizyt, commerce — migawkę kupującego. Reszta ADR-036 §5
  obowiązuje; nullable `Customer.user` powstanie już tutaj.

### 3. Zamówienie: `Order` i `OrderLine` (T9)

- `Order`: `number`, `customer`, migawka kupującego (nazwa, e-mail, telefon,
  dane do faktury z opcjonalnym NIP), `currency`, `status`, `channel`
  (`company_site`, `catalog`) z podpisanym tokenem pochodzenia (w adresie, nigdy
  w ciasteczku), zaakceptowane wersje dokumentów (§9), `version`.
- Numer `{prefiks}/{rok}/{NNNN}` (`R/2026/0001`) powstaje przy złożeniu, nie
  przy szkicu, z licznika (firma, prefiks, rok) pod `select_for_update`. Rok
  liczymy z daty w `Organization.timezone`; `timezone.localdate()` przy
  `TIME_ZONE = "UTC"` daje zły rok w pierwszej godzinie stycznia
  (`shared/inventory/services.py:836-842, 1324`).
- `OrderLine`: `kind` (`booking`, `product`, `extra`, `discount`, `voucher`,
  `delivery`, `fee`), `quantity`, `unit_gross_minor`, `unit_net_minor`,
  `tax_rate` (§8), migawka nazwy, `source`, `source_reference`. Pozycje
  przychodzą gotowe z `quote` (ADR-072) albo z koszyka (ADR-074); commerce cen
  nie liczy, a pozycji złożonego zamówienia nie zmienia — korekta to nowa
  pozycja.
- Statusy: `draft`, `awaiting_payment`, `partially_paid`, `paid`, `fulfilled`,
  `completed`, `canceled`, `refunded` — zmienia je tylko commerce. Status to
  skrót dla list; o pieniądzach rozstrzyga księga. `fulfilled` zgłasza źródło
  (rezerwacja zakończona, towar wydany), `completed` — zrealizowane i rozliczone.
- Gdzie commerce działa, każda rezerwacja należy do jednego zamówienia
  założonego w jej transakcji (ADR-037 §5 pkt 1); zamówienie może mieć kilka
  rezerwacji i produktów. Istniejące wizyty nie dostają zamówień wstecz.

### 4. Płatność opłaca zamówienie (uogólnienie ADR-037 §3)

- `Payment` zamiast `AppointmentPayment`: `order`, `kind` (`deposit`, `balance`,
  `full`, `security_deposit`), `method` (`online`, `transfer`, `cash`,
  `cash_on_delivery`), `connection` (puste przy ręcznych), `amount_minor`,
  `currency`, `platform_fee_minor`, `status` (zbiór ADR-037 §3 plus `authorized`
  dla blokady kaucji), `due_at`, `provider_payment_id`, `idempotency_key`,
  `version`; najwyżej jedna oczekująca na rodzaj. `Refund` i `Dispute` wiszą na
  `Payment`.
- `LedgerEntry` (rodzaje z ADR-037 §3, tylko do dopisywania) wiąże zamówienie i
  płatność. Wpłata ręczna to `charge` bez opłat, zwrot ręczny — `refund`. Suma
  wpisów zamówienia odtwarza należność, wpłaty, prowizję, opłatę operatora,
  zwroty i wypłatę — to bramka fazy 7.

### 5. Należność, metody ręczne i wygaszanie

- Polityka płatności i progi anulowania to dane oferty w migawce rezerwacji
  (ADR-072: `none`, `on_site`, `transfer`, `deposit`, `full`, dopłata X dni
  przed); zamówienie zamienia je na płatności z terminami.
- Metody ręczne działają przed operatorem (faza 4): gotówka lub terminal na
  miejscu, przelew na rachunek firmy z numerem zamówienia w tytule (wpłatę
  oznacza firma), w sklepie za pobraniem. Online — przy połączeniu z
  `charges_enabled`; bez niego należność idzie przelewem, jeśli firma podała
  rachunek (13a: „dopóki nie ma płatności online — zadatek przelewem w 3 dni”),
  a bez rachunku — na miejscu.
- Rezerwacja czekająca na zadatek albo całość trzyma termin tymi samymi
  alokacjami (`pending_payment`, ADR-072) do terminu płatności: online domyślnie
  15 minut (rekomendacja ADR-037), przelew — dni z oferty (Nocleg: 3).
- Wygaszanie czyta indeks terminów bez danych osobowych (`payment_id`,
  `organization_id`, `due_at`; wzorzec `ReminderRoute`) i działa w kontekście
  `service` firmy: płatność `expired`, intencja u operatora anulowana, zamówienie
  `canceled`, handler zwalnia rezerwację. Płatność online potwierdzona mimo to po
  terminie wraca zwrotem (webhook nie tworzy rezerwacji, ADR-037 §6); spóźniony
  przelew firma zwraca albo rezerwuje od nowa.

### 6. Port płatności: tryby `platform` i `own` (T11)

- `PaymentProviderConnection` (pola ADR-037 §3) dostaje `mode` (`platform` |
  `own`) i `adapter` (`stripe_connect`, `przelewy24`, `payu`, `simulated`), jedno
  na firmę i adapter. Tryb wybiera firma; metody wynikają z `capabilities`.
- **`platform`** (faza 7, po W9.5.2S): Stripe Connect, direct charges z
  `application_fee_amount`; zwroty, spory i opłaty Stripe obciążają firmę
  (ADR-037 §2). Konta według rekomendacji Stripe z chwili fazy 7 (Accounts v2
  albo v1 z controller properties), nie Express. Konto platformy to samo co
  abonamenty; zdarzenia kont połączonych mają osobny punkt i sekret. Operator
  jest jeden na deployment (`COMMERCE_PROVIDER`: `stripe_connect` | `simulated`,
  ten drugi poza produkcją); Mollie Connect zostaje kandydatem na drugiego.
- **`own`** (faza 13): własne konto firmy, najpierw Przelewy24 — Stripe nie daje
  P24 noclegom (MCC 7011, 7033, 6513) ani medycynie. Firma podaje `merchantId`,
  `posId`, klucz CRC i `secretId`; zamówienie jest opłacone dopiero po
  obowiązkowym `PUT /transaction/verify`. Bez naszej prowizji.
- Sekrety `own` i tokeny programu do faktur są szyfrowane w bazie, nie wracają z
  API i nie trafiają do logów ani audytu. Przed pierwszym z nich `encrypt_secret`
  dostaje listę kluczy (`MultiFernet`), bo jego jedyny klucz chroni też tokeny
  samoobsługi (`shared/notifications/security.py:50-96`).
- Webhook ma globalny adres per adapter; firmę wyznacza indeks routingu bez
  danych osobowych (wzorzec `SelfServiceRoute`): w `platform` po
  `external_account_id` (ADR-037 §6), w `own` po losowym identyfikatorze trasy w
  adresie powiadomienia, bo podpis P24 sprawdza się kluczem CRC firmy. Skrzynka
  zdarzeń to tabela platformowa (ADR-041 §1); rekonsyliacja idzie po firmach
  (`billing_organization_ids()`, `billing_tenant_scope()`).

### 7. Prowizja platformy

- Procent plus kwota stała zależne od planu (3a); start: Profil 2% + 0,50 zł,
  Starter 1,5% + 0,30 zł, Pro 1% + 0 zł (11a). Stawki są ustawieniem platformy z
  datą wejścia w życie (T23), nie stałą w kodzie ani daną wersji planu; do czasu
  rejestru ustawień — domyślne w kodzie i `platform_setting --operator --reason`.
- Nadpisanie stawki jednej firmy z datą ważności, powodem i autorem (T18,
  partnerzy pilotażowi) to rekord w `shared.commerce` zmieniany przez
  administratora platformy poziomu 2 (plan ustawień, U2), z fazą 7.
- Prowizję liczy się raz, przy tworzeniu płatności online w `platform`, ze stawki
  obowiązującej w tej chwili (nadpisanie przed planem), i zapisuje w płatności;
  zwrot oddaje ją proporcjonalnie do zwracanej kwoty (3a: `refund_fee_reversal`,
  w Stripe `refund_application_fee`). Płatności ręczne i `own` prowizji nie mają.

### 8. Zwroty, kaucja, waluta i podatek

- **Zwrot.** Rezygnacja klienta liczy zwrot z progów zamrożonych w rezerwacji —
  procent wpłat według pełnych dni do początku w strefie firmy (Nocleg: ≥ 30 dni
  100%, 14–29 dni 50%, < 14 dni 0%). Online zwraca adapter, ręczną wpłatę firma
  oddaje sama; odwołanie przez firmę zwraca całość, a zwrot spoza progów wymaga
  powodu w audycie.
- **Kaucja** (`security_deposit`) nie jest pozycją ani przychodem. Blokadę kartą
  zakłada klient z linku tuż przed przyjazdem, w oknie operatora (7 dni, do 30
  dla noclegów i wynajmu pojazdów z rozszerzoną autoryzacją), a firma po pobycie
  pobiera część albo zwalnia; poza tym oknem — przelew albo gotówka.
- **Waluta** (16, T22): jedna waluta cennika na firmę z listy ustawień platformy
  (PLN, EUR, USD); `Organization.currency` przestaje przyjmować dowolny kod
  (`core/organizations/models.py:78-82`), a zmianę waluty firmy z cenami albo
  zamówieniami odrzucamy (`currency_in_use`). Płatność jest zawsze w walucie
  zamówienia; przeliczenie na obcojęzycznej stronie to informacja z kursu dnia.
- **Podatek.** Pozycja niesie kod stawki z listy w kodzie (dziś `23`, `8`, `5`,
  `0`, `zw`, jak `VatRate` magazynu, `shared/inventory/models.py:34-39`), bo `zw`
  to nie `0`. Netto i brutto liczy `quote` według ustawienia firmy (ADR-072);
  stawkę wybiera firma jako sprzedawca. ADR-040 dotyczy tylko abonamentów.

### 9. Dokumenty, zgody, faktury (T15, T16)

- Dokumenty firmy dla klientów (regulaminy rezerwacji i sklepu, polityki
  prywatności i anulowania) mają wersje tylko do dopisywania, zgody klienta to
  dziennik tylko do dopisywania (akceptacja wersji, zgoda marketingowa osobno).
  Jedne i drugie żyją w `shared.customers`, najniższym module wspólnym dla
  rezerwacji (także bez commerce), zamówień i sklepu; zamówienie i rezerwacja
  zapisują zaakceptowane wersje. To nie `PolicyAcknowledgement` z ADR-036 §8.
- Faktury wyłącznie przez port integracji (Fakturownia, inFakt, wFirma; faza 12):
  wysyłamy dane zamówienia, trzymamy numer, link do PDF i stan; KSeF obsługuje
  program do faktur.
- Zamówienie i księga to zapis transakcji, nie dokument księgowy, więc ADR-042 §7
  obowiązuje, a usunięcie tenanta kasuje te wiersze. Anonimizacja klienta czyści
  migawkę kupującego; kwoty, pozycje i księga zostają (ADR-030).

### 10. Pieniądze klientów omijają platformę; sprzedawca otwarty

Pieniądze klienta trafiają tylko na konto firmy — połączone u operatora albo
własne; prowizję pobiera operator (zasada 7 planu; PSD2 art. 3 lit. b, motyw 11).
Firma jako sprzedawca to założenie direct charges (ADR-037 §2); potwierdzenie
prawne jest otwarte od 02.09 na liście `desk/regulamin-i-pytania-prawne.md` i nie
blokuje budowy (decyzja 21) — odpowiedź przecząca wraca do tego ADR-u.

### 11. Obsługiwalne przez asystenta AI (AGENTS.md, „Niezmienne zasady”)

- Złożenie, wpłata, zwrot, anulowanie, połączenie, rachunek do przelewów i
  nadpisanie prowizji to serwisy z `api.py`, wspólne dla panelu, komend i
  asystenta; połączenie zwraca link do formularza operatora, który klika osoba.
- Serializery z `help_text`, enumami i kwotami w jednostkach mniejszych z walutą;
  Problem Details z polem i kodem (`currency_not_allowed`, `amount_exceeds_due`,
  `refund_exceeds_paid`, `connection_not_ready`); `Idempotency-Key` przy każdej
  mutacji, `version` na `Order`, `Payment` i połączeniu (nieaktualny zapis: 409).
- Konfiguracja (połączenie, rachunek, nadpisanie prowizji) ma przebieg bez
  zapisu, zwrot i wpłata — wyliczenie przed wykonaniem; skutek u operatora go nie
  ma, bo jest zewnętrzny. `GET /api/v1/commerce/options/` podaje waluty, metody,
  polityki, stawkę prowizji i domyślne okna; listy są stronicowane i filtrowane.
- Akcje `commerce.*` trafiają do `OrganizationAuditAction`; rodzaj aktora i
  „w imieniu” dojdą z A1a (ADR-076, zarezerwowany). Polecenie asystenta
  ruszające pieniądze wymaga osobnej zgody-digestu z kliknięcia osoby (ADR-033).

## Konsekwencje

- Każdy profil z `shared.booking` musi wymienić `shared.customers`, bo
  `compose()` nie dociąga zależności (`config/composition.py:305-306`) — także
  HoofCare i MedPlano, z wpisem w `docs/operations/releases` (ADR-049). Nowe
  moduły dostają deskryptory, pokrycie evals i wiersze skilli;
  `develop-commerce-payments` (ADR-037) powstaje z fazą 4, a z `develop-booking`
  znika „Payments are out of scope” (`SKILL.md:107-108`).
- Migracje odwracalne: booking 0013, customers 0001, commerce 0001,
  organizations 0052, billing 0026 (wersje planów z `commerce.enabled`). Booking
  0013 uzgodnić z TL10 (`Customer.locale` po przeniesieniu żyje w customers),
  TL12 i ADR-067. Faza 7 zaczyna się po fazie 1 planu ustawień i W9.5.2S.
- Link samoobsługi żyje 30 dni od utworzenia (`shared/booking/services.py:547`),
  a link do dopłaty musi dożyć terminu — ważność ustala ADR-072. E-maile idą
  trwałą kolejką w języku klienta (pierwszy z `public_locales`, plan
  wielojęzyczności TL-T3). Zdarzeń domenowych commerce nie emituje, dopóki nie
  mają konsumenta; pierwsze przyjdzie z outboxem (ADR-024).
- Otwarte: co, gdy dopłata nie wpłynie w terminie (nic nie anuluje się samo);
  stała część prowizji dla EUR i USD; stawki VAT spoza Polski; konfiguracja kont
  Stripe; plany z `commerce.own_account.enabled`; okno płatności online; czy
  strona prawna witryny pokazuje bieżącą wersję dokumentu. Na liście prawnej:
  sprzedawca, PSD2 i KNF, zadatek czy zaliczka (art. 394 KC), faktura i VAT od
  prowizji, paragony, przechowywanie zamówień, spółka konta Stripe.

## Odrzucone

- **Płatność przypięta do wizyty** — sklep nie ma wizyty, a zadatek, dopłata i
  kaucja to kilka płatności jednej sprzedaży.
- **Commerce zależne od booking** (ADR-037 §1) — rezerwacja zakłada zamówienie,
  więc powstałby cykl; **twarda zależność booking → commerce** — HoofCare i
  MedPlano niosłyby zamówienia, których nie używają.
- **Wpłaty na rachunek platformy** — usługa płatnicza wymagająca zezwolenia KNF.
- **Jeden operator bez wyboru firmy** (ADR-037 §8) — noclegi i gabinety nie
  dostaną P24 przez Stripe.
- **Potwierdzenie przez obserwatora po commicie** — błąd ginie, a zamówienie i
  rezerwacja się rozjeżdżają.
- **Blokada kaucji przy rezerwacji** — wygasa przed przyjazdem; **na zapisanej
  karcie bez klienta** — wymaga zgody na obciążenie pod jego nieobecność.
