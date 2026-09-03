# ADR-040 — VAT przez Stripe Tax, ceny netto i zakres Customer Portalu

**Status:** Accepted
**Data:** 2026-09-03
**Zatwierdzono:** 2026-09-03 (decyzje właściciela)
**Uzupełnia:** ADR-032 (oferta, plany i Customer Billing) o podatek i zakres
portalu; warunkuje odbiór W9.5.2S z ADR-034

## Kontekst

ADR-032 opisał ścieżkę klienta przez Stripe Checkout i Customer Portal, ale
nie rozstrzygnął podatku. Adapter Stripe powstał bez niego: `create_customer`
wysyła wyłącznie e-mail i nazwę, Checkout nie zbiera adresu ani numeru VAT, a
subskrypcja powstaje bez `automatic_tax`. Bez adresu kupującego Stripe Tax nie
ma z czego wyliczyć stawki, więc do dziś nie naliczaliśmy VAT w ogóle — co było
bez znaczenia na symulatorze i przestaje nim być z pierwszą prawdziwą
płatnością.

Równolegle doszły kredyty (pula przedpłacona kupowana jednorazowo), które nie
mieszczą się w portalu: Customer Portal obsługuje wyłącznie istniejącą
subskrypcję i nie sprzedaje niczego jednorazowo.

## Decyzja

### 1. Stripe Tax liczy podatek; sprzedajemy w PL i całej UE

Sprzedajemy firmom i konsumentom w całej Unii. Podatek wylicza Stripe Tax na
podstawie adresu kupującego i jego numeru VAT, a nie nasz kod — nie budujemy
własnej macierzy stawek.

Konsekwencje, które są warunkami odbioru W9.5.2S:

- `create_customer` wysyła adres z `BillingProfile` (kraj, ulica, kod, miasto)
  i nazwę prawną; bez adresu Stripe Tax zwraca błąd zamiast stawki;
- Checkout ma `billing_address_collection: required`, `tax_id_collection` oraz
  `customer_update` pozwalający zapisać adres i nazwę z powrotem na Customer —
  inaczej dane z Checkoutu giną i kolejna faktura liczy się z pustego adresu;
- subskrypcja i płatność jednorazowa mają `automatic_tax: {enabled: true}`;
- każda cena w Stripe ma jawne `tax_behavior`; cena bez niego jest odrzucana
  przez `automatic_tax`, więc komenda konfigurująca ceny musi je ustawiać i
  weryfikować;
- rejestracje podatkowe są konfiguracją konta Stripe, nie repozytorium.
  Minimum to Polska; sprzedaż konsumentom w innych krajach UE wymaga OSS.
  Poniżej unijnego progu 10 000 EUR sprzedaży transgranicznej B2C wolno
  naliczać stawkę krajową — używamy monitorowania progu w Stripe i rejestrujemy
  OSS, gdy Stripe zgłosi jego przekroczenie. To jest czynność prawna
  właściciela, nie zadanie wdrożeniowe.

Firma z ważnym numerem VAT UE spoza Polski dostaje odwrotne obciążenie, czyli
0%, i wymaga tego, aby numer był zebrany i zweryfikowany — dlatego
`tax_id_collection` jest obowiązkowe, a nie opcjonalne.

### 2. Ceny w katalogu są netto

`unit_amount_minor` w `PlanVersion` i `CreditPack` to kwota **netto**, a ceny w
Stripe mają `tax_behavior: exclusive`. Marża jest wtedy niezależna od kraju i
stawki, co przy sprzedaży w całej UE jest jedynym wariantem, w którym ten sam
plan zarabia tyle samo w Warszawie i w Budapeszcie.

Wynika z tego obowiązek po stronie interfejsu, nie Stripe: **konsumentowi
pokazujemy cenę brutto jako główną.** Prawo unijne wymaga podania ceny
końcowej osobie prywatnej, a stawka zależy od jej kraju. Panel liczy więc
kwotę brutto dla kraju z `BillingProfile` i pokazuje ją obok netto; dla
`customer_kind = person` brutto jest kwotą wiodącą, dla firmy — netto.
Ostateczną kwotę i tak potwierdza Checkout, bo dopiero on zna zweryfikowany
adres i numer VAT.

### 3. Zakres Customer Portalu

Portal obsługuje wyłącznie abonament i ma dokładnie te możliwości:

- zmiana metody płatności;
- historia faktur;
- zmiana danych do faktury wraz z numerem VAT — konieczna, bo od adresu zależy
  stawka, a klient musi móc poprawić go sam;
- anulowanie subskrypcji **na koniec okresu**. Anulowanie natychmiastowe jest
  wyłączone, bo kolidowałoby z karencją i trybem tylko-do-odczytu z ADR-026;
- zmiana planu ograniczona do dokładnie naszych trzech cen, zgodnie z ADR-032
  („do czasu wdrożenia natywnego schedule");
- **bez** wstrzymywania subskrypcji: stan „paused" nie ma odpowiednika w naszym
  cyklu życia i wpuszczenie go zrobiłoby dziurę w egzekwowaniu dostępu.

Identyfikator konfiguracji portalu jest jawnym ustawieniem deploymentu
(`STRIPE_PORTAL_CONFIGURATION_ID`) i jest podawany przy każdym otwarciu sesji.
Poleganie na domyślnej konfiguracji konta jest odrzucone: domyślną można
zmienić w dashboardzie tak, że żaden przegląd kodu tego nie zauważy.

### 4. Kredyty nie przechodzą przez portal

Zakup pakietu kredytów to osobne Checkout w trybie płatności jednorazowej,
otwierane z naszego panelu, z `automatic_tax` i tym samym Customer. Portal go
nie widzi i nie ma go widzieć. Potwierdzeniem zakupu jest wyłącznie webhook —
powrót z przeglądarki nie dodaje kredytów.

## Decyzje wymagające właściciela

Wykonane 2026-09-03: rynek (PL + UE, B2B i B2C), ceny netto, zakres portalu.
Otwarte i leżące poza repozytorium:

1. rejestracja OSS albo włączone monitorowanie progu 10 000 EUR w Stripe;
2. potwierdzenie z księgową, że sprzedaż usług cyfrowych do UE jest u nas
   rozliczana zgodnie z tym modelem;
3. czy wystawiamy własne dokumenty sprzedaży obok faktur Stripe — dziś adapter
   fakturowania z ADR-026 jest wewnętrzny i niczego nie wysyła.

## Konsekwencje

- adapter Stripe rośnie o adres, numer VAT i `automatic_tax`; komenda
  konfigurująca ceny musi ustawiać `tax_behavior`;
- `BillingProfile` staje się danymi wymaganymi przed pierwszą płatnością, a nie
  opcjonalnym uzupełnieniem — bez kraju i adresu Checkout nie ruszy;
- panel musi umieć pokazać kwotę brutto, więc potrzebuje stawki; bierzemy ją z
  Checkoutu i z faktur, nie z własnej tabeli stawek;
- zmiana `tax_behavior` w przyszłości oznacza nowe ceny w Stripe i nowe wersje
  planów; to jest powód, dla którego decyzja zapada teraz, a nie po pilocie;
- portal ma jedną konfigurację przypiętą w ustawieniach, więc jej zmiana jest
  widoczna w przeglądzie zmian.

## Alternatywy odrzucone

- własna macierz stawek VAT — 27 krajów, zmienne stawki i progi; utrzymywanie
  jej byłoby drugim produktem;
- ceny brutto — czytelniejsze dla konsumenta, ale ta sama cena daje inną marżę
  w każdym kraju UE; rozwiązujemy to prezentacją, nie modelem cen;
- poleganie na domyślnej konfiguracji portalu — niewidoczna w kodzie;
- sprzedaż kredytów przez portal — technicznie niemożliwa;
- zbieranie numeru VAT jako pola opcjonalnego w naszym formularzu zamiast przez
  `tax_id_collection` — Stripe nie zweryfikowałby go w VIES, więc odwrotne
  obciążenie byłoby stosowane na naszą odpowiedzialność.

## Relacje

- uzupełnia ADR-032 i warunkuje bramkę W9.5.2S z ADR-034;
- korzysta z `BillingProfile` (ADR-026) jako źródła adresu i numeru VAT;
- kredyty i ich zakup opisuje wpis decyzyjny „Credits are two buckets behind
  one balance" oraz `shared/billing/credits.py`.
