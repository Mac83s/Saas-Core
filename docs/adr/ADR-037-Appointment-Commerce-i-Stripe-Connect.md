# ADR-037 — Appointment Commerce i Stripe Connect

**Status:** Deferred — 2026-09-02 właściciel zdjął MedPlano z priorytetu i
wyłączył P4/P5 z zakresu bazy; ADR wraca do rozpatrzenia (wraz z przeglądem
prawno-księgowym), gdy pierwszy serwis na bazie potrzebuje płatności za wizyty.
Nie dotyczy realnego Stripe dla abonamentów SaaS (W9.5.2S, ADR-032/ADR-034),
który wchodzi, gdy tylko właściciel dostarczy konto Stripe
**Data:** 2026-09-02
**Właściciel:** zespół SaaS Core
**Nie zmienia:** ADR-026, ADR-032 i ADR-034 — billing abonamentu SaaS pozostaje
osobną domeną; rozszerza ADR-030 o status `pending_payment` i pola ceny usługi

## Kontekst

Booking (ADR-030) pozostawił płatność i zaliczkę poza pierwszym zakresem.
`Service` nie ma ceny, waluty ani stawki podatku, a `Appointment` nie zna stanu
płatności. `shared.billing` rozlicza organizację z platformą za abonament i to
jest inna relacja niż płatność klienta końcowego za wizytę: inny płatnik, inny
odbiorca pieniędzy, inne obowiązki podatkowe i dokumentowe.

Plan poaudytowy (P4, P5) wymaga, aby klient mógł zapłacić za wizytę z góry —
depozyt albo całość — a platforma pobrała prowizję. Pytanie rozstrzygające
brzmi, kto jest sprzedawcą (merchant of record). Jeżeli platforma, to ona
odpowiada za VAT, dokumenty sprzedaży, zwroty i spory dla każdej usługi każdego
gabinetu. Jeżeli usługodawca, platforma jest operatorem technicznym i pobiera
opłatę. Plan przyjmuje wariant drugi; ten ADR nadaje mu kształt techniczny, a
przegląd prawny i księgowy ma go potwierdzić albo obalić przed P5.

## Proponowana decyzja

### 1. Osobny moduł `shared.commerce`

- nowy moduł `shared.commerce` z deskryptorem `dependsOn:
  ["core.organizations", "shared.billing", "shared.booking",
  "shared.notifications"]` (billing dla entitlementów, booking dla wizyt,
  notifications dla kolejki i outboxu), `urlPrefix: /api/v1/commerce`,
  permissions `commerce.payments.read`, `commerce.payments.manage`,
  `commerce.connection.manage`, entitlement `commerce.enabled` nadawany planem
  lub override'em;
- `shared.billing` nie jest rozszerzane o płatności wizytowe. Jeżeli oba moduły
  potrzebują tego samego klienta HTTP Stripe albo weryfikacji podpisu webhooka,
  ten kod trafia do wspólnego pakietu integracyjnego poza modułami domenowymi
  (np. `saas_core/integrations/stripe/`), nie do `shared.billing`;
- deployment bez `shared.commerce` (np. `core-only`) nie rejestruje żadnego
  endpointu płatności, a Booking działa jak dziś: rezerwacja bezpłatna albo
  płatna na miejscu.

### 2. Usługodawca jest sprzedawcą, platforma operatorem

- organizacja jest merchant of record: sprzedaje usługę, wystawia dokument
  sprzedaży i odpowiada za podatek. SaaS Core nie wystawia faktur ani paragonów
  za wizyty i nie prowadzi rozliczeń podatkowych organizacji;
- platforma pobiera prowizję jako `application_fee` od każdej udanej płatności;
  wysokość prowizji jest wersjonowaną daną katalogu (procent i kwota stała, per
  plan), nie stałą w kodzie;
- model Stripe: **Connect z kontami Express i direct charges** — płatność
  powstaje na koncie połączonym organizacji, opłaty Stripe obciążają to konto,
  a platforma pobiera application fee. Onboarding KYB jest hostowany przez
  Stripe; SaaS Core nie przechowuje dokumentów weryfikacyjnych;
- odrzucone: destination charges i konta Custom, bo czynią platformę sprzedawcą
  wobec klienta i stroną każdego sporu; konta Standard, bo dają organizacji
  pełny dashboard Stripe i rozbijają spójne UX prowizji — do ponownej oceny,
  gdy organizacje będą chciały własnego konta.

### 3. Model danych — tenantowy, RLS, bez danych kart

Wszystkie tabele są `TenantScopedModel` z wymuszonym RLS (ADR-022) i
wyzwalaczem cross-tenant.

- `PaymentProviderConnection` — jedno na organizację i providera: `provider`,
  `external_account_id`, `onboarding_status` (`not_started | pending |
  complete | restricted`), `charges_enabled`, `payouts_enabled`,
  `capabilities` (snapshot z providera: karty, BLIK, P24),
  `requirements_due_at`, `disabled_reason`, `synced_at`. Aktualizowane
  wyłącznie z webhooka `account.updated` i rekonsyliacji, nigdy z formularza;
- `AppointmentPayment` — jedna aktywna na wizytę: `appointment`, `kind`
  (`deposit | full`), `amount_minor`, `currency`, `tax_rate_bp` (snapshot),
  `platform_fee_minor`, `status` (`requires_payment | processing | succeeded |
  failed | canceled | expired`), `provider_intent_id`, `idempotency_key`,
  `expires_at`, `succeeded_at`. Kwoty w jednostkach mniejszych (grosze) jako
  liczby całkowite;
- `PaymentRefund` i `PaymentDispute` — powiązane z `AppointmentPayment`, każdy
  ze statusem providera i własnym identyfikatorem zewnętrznym;
- `LedgerEntry` — append-only, wyzwalacz zabrania UPDATE i DELETE; `kind` ∈
  `charge | provider_fee | application_fee | refund | refund_fee_reversal |
  dispute_hold | dispute_release | dispute_fee | payout`, `amount_minor` ze
  znakiem, `currency`, `occurred_at`, `source_event_id`. Suma wpisów per
  płatność odtwarza kwotę usługi, prowizję, opłatę providera, zwroty i wypłatę —
  to jest bramka P5;
- SaaS Core nie przechowuje numeru karty, CVC, tokenu karty ani danych KYB.
  Jedyne identyfikatory zewnętrzne to id konta, intentu, zwrotu i sporu.

### 4. Cena i polityka płatności należą do Booking (P4)

- `Service` otrzymuje `price_minor`, `currency`, `tax_rate_bp`,
  `payment_policy` (`none | on_site | deposit | full`), `deposit_minor` albo
  `deposit_percent` oraz `cancellation_policy` (okno bez opłat, potrącenie,
  no-show). Pola są w `shared.booking`, bo dotyczą oferty także wtedy, gdy
  commerce jest wyłączone (cena informacyjna, płatność na miejscu);
- `Appointment` zachowuje snapshot ceny, polityki i podatku z chwili
  rezerwacji — tak jak zachowuje nazwę usługi (ADR-030); późniejsza zmiana
  cennika nie zmienia istniejącej wizyty;
- `Appointment.status` dostaje wartość `pending_payment`. Taka wizyta blokuje
  slot przez te same alokacje `EXCLUDE` co potwierdzona, ale ma termin ważności
  (domyślnie 15 minut). Zadanie w kolejce W8 wygasza nieopłacone wizyty i
  zwalnia alokacje; klient nie może zająć slotu bez zapłaty na dłużej niż okno.

### 5. Przepływ płatności

1. klient wybiera slot; jeżeli polityka usługi to `deposit` albo `full` i
   organizacja ma `charges_enabled`, `create_appointment` tworzy wizytę
   `pending_payment` oraz `AppointmentPayment` `requires_payment` w jednej
   transakcji, a intent u providera powstaje po commicie z kluczem idempotencji;
2. klient płaci w hostowanym formularzu providera na koncie połączonym; metody
   płatności wynikają z `capabilities` połączenia, nie z listy w UI;
3. **return URL nie potwierdza niczego**: strona powrotu pokazuje „oczekujemy
   potwierdzenia" i odpytuje stan wizyty. Potwierdzenie przychodzi wyłącznie z
   webhooka `payment_intent.succeeded`, który w kontekście tenanta zmienia
   płatność na `succeeded`, wizytę na `confirmed`, zapisuje wpisy ledgeru i
   emituje `booking.appointment.confirmed` do outboxu (W8 wysyła potwierdzenie);
4. odmowa lub timeout zostawia wizytę w `pending_payment` do wygaśnięcia; klient
   może ponowić w oknie ważności tym samym intentem;
5. jeżeli organizacja nie ma połączenia albo `charges_enabled=false`, polityka
   `deposit | full` degraduje się jawnie do `on_site` z komunikatem w panelu —
   brak połączenia nie może blokować rezerwacji.

### 6. Webhooki, kolejność i rekonsyliacja

- endpoint webhooka jest globalny (bez sesji), weryfikuje podpis, a tenant
  wyznacza z `external_account_id` przez PII-free indeks routingu — ten sam
  wzorzec co token self-service w ADR-030; dopiero potem aktywuje
  `TenantContext` typu `service` i `SET LOCAL app.organization_id`;
- każde zdarzenie jest zapisywane raz po `event_id` (unikalny indeks) i
  przetwarzane idempotentnie; zdarzenie starsze niż ostatnio zastosowana wersja
  obiektu jest ignorowane, ale zapisane;
- zadanie rekonsyliacji porównuje codziennie stan lokalny z providerem dla
  płatności `processing`, zwrotów, sporów i wszystkich połączeń; rozbieżność
  tworzy zgłoszenie operatorskie (W8 support), nie cichą korektę;
- webhook nigdy nie tworzy wizyty ani nie zmienia jej terminu; może tylko
  potwierdzić, odrzucić, zwrócić lub oznaczyć spór.

### 7. Zwroty, anulowania, spory i no-show

- anulowanie przez klienta oblicza kwotę zwrotu z polityki zapisanej w
  snapshotcie wizyty; zwrot jest komendą z kluczem idempotencji, wpisem `refund`
  w ledgerze i zdarzeniem. Prowizja platformy jest korygowana proporcjonalnie
  (`refund_fee_reversal`) — czy tak ma być, potwierdza przegląd księgowy;
- spór (chargeback) zapisuje `dispute_hold` i powiadamia operatora oraz
  organizację; wynik zapisuje `dispute_release` albo `dispute_fee`. SaaS Core
  nie prowadzi obrony sporu; dostarcza dowody (termin, potwierdzenia, polityka);
- no-show z depozytem: depozyt pozostaje u organizacji zgodnie z polityką,
  wizyta dostaje status `no_show`, ledger się nie zmienia;
- korekty księgowe wykonuje się wyłącznie wpisami kompensującymi; żaden wpis
  nie jest edytowany.

### 8. Provider i środowiska

- wybór providera jest jawny przez `COMMERCE_PROVIDER` (`simulated | stripe`),
  analogicznie do `BILLING_PROVIDER` z ADR-034; local i staging używają
  `simulated`, który przechodzi ten sam port i te same stany, ale nie łączy się
  z siecią;
- jeden aktywny provider na deployment; organizacja nie wybiera operatora;
- adapter Mollie Connect jest dopuszczalnym drugim adapterem tego samego portu,
  ale nie powstaje przed dowodem potrzeby biznesowej;
- produkcja nie może działać na `simulated`; pierwszy płatny pilot wymaga
  bramki P5 planu poaudytowego oraz zaliczenia W9.5.2S dla subskrypcji.

## Decyzje wymagające właściciela

1. **Merchant of record** — potwierdzenie z prawnikiem i księgową, że
   organizacja jest sprzedawcą, a platforma operatorem pobierającym opłatę. Jeśli
   nie, ADR wraca do przeprojektowania (destination charges, faktury i VAT
   platformy). Rekomendacja: usługodawca jako sprzedawca.
2. **Model prowizji** — procent, kwota stała czy mieszany; czy zależy od planu;
   czy jest korygowany przy zwrocie. Rekomendacja: procent + kwota stała per
   plan, korekta proporcjonalna przy zwrocie.
3. **Okno ważności rezerwacji nieopłaconej** — rekomendacja 15 minut,
   konfigurowalne per deployment.
4. **Metody płatności** — BLIK, P24 i karty przez Connect w PL wymagają
   potwierdzenia dostępności i ograniczeń (capture, częściowy zwrot, spory) na
   koncie platformy; w UI nie deklarujemy metod, których capability nie
   potwierdzono.
5. **Dokumenty sprzedaży** — kto i czym wystawia paragon lub fakturę klientowi
   (kasa fiskalna online, system organizacji). SaaS Core wysyła tylko
   potwierdzenie płatności. Rekomendacja: poza zakresem w pierwszym wydaniu.
6. **Czy pilot MedPlano potrzebuje płatności** — pilot może wystartować na
   rezerwacjach bezpłatnych lub na miejscu, a commerce dołączyć jako druga faza;
   to skraca ścieżkę krytyczną planu o P5.

## Konsekwencje

- pojawia się drugi przepływ pieniędzy z osobnym modułem, ledgerem i runbookiem;
  koszt wejścia jest wyższy niż „dodanie ceny do usługi", ale każda złotówka
  daje się odtworzyć z ledgeru;
- Booking dostaje nowy status i zadanie wygaszania; testy wyścigów muszą objąć
  slot zajęty przez nieopłaconą wizytę;
- organizacja bez połączenia nadal działa — brak KYB nie blokuje produktu,
  tylko płatność z góry;
- webhook i rekonsyliacja stają się krytyczną infrastrukturą: ich awaria opóźnia
  potwierdzenia, ale nie tworzy fałszywych potwierdzeń;
- ADR-030 zostaje rozszerzony, nie zastąpiony.

## Alternatywy odrzucone

- rozszerzenie `shared.billing` o płatności wizytowe — mieszałoby dwie relacje
  pieniężne w jednym ledgerze i jednym providerze;
- platforma jako sprzedawca (destination charges) — przenosi VAT, dokumenty i
  spory każdej usługi na platformę;
- potwierdzenie wizyty na podstawie return URL — pozwala potwierdzić bez zapłaty;
- przechowywanie dokumentów KYB w SaaS Core — zbędne dane wrażliwe;
- wielu providerów do wyboru przez organizację w pierwszym wydaniu — wielokrotny
  koszt rekonsyliacji i runbooków bez potrzeby biznesowej;
- płatność bez blokady slotu — klient płaci za termin, który w międzyczasie
  zajął ktoś inny.

## Relacje

- rozszerza ADR-030 (Booking); korzysta z ADR-022 (RLS), ADR-024 (zdarzenia,
  outbox), ADR-029 (kolejka i support), ADR-036 (panel klienta, retencja);
- nie zmienia ADR-026, ADR-032, ADR-034 (billing SaaS);
- realizuje P4 i P5 planu poaudytowego; skill `develop-commerce-payments`
  powstaje razem z tym modułem (ADR-038);
- Stripe Connect dla platform SaaS:
  https://docs.stripe.com/connect/saas-platforms-and-marketplaces;
  Mollie Connect: https://docs.mollie.com/docs/connect-overview.
