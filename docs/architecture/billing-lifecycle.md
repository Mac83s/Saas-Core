# Cykl życia planu i płatności

Ten dokument istnieje, bo wszystkie usterki płatności z 3–4 września siedziały
w tym samym miejscu: **na szwie między dwoma kawałkami, z których każdy miał
własne zielone testy**. Powrót z przeglądarki a aktywacja planu. Aktywacja a
ponowny zakup. Zmiana dostawcy a identyfikator klienta. Katalog cen a dostawca.
Żadnego z tych szwów nie dało się zobaczyć, patrząc na pojedynczą falę wdrożenia
— widać je dopiero wtedy, gdy przejdzie się całą drogę klienta od „nie ma planu"
do „anulował i wrócił po miesiącu".

Mapa jest listą tych przejść. Każde ma powiedziane: **co je wyzwala**, **kto je
wykonuje**, **co w tym momencie widzi klient** i **czy ktokolwiek to udowodnił**.

## Jak czytać status

| Znak | Znaczenie                                                                    |
| ---- | ---------------------------------------------------------------------------- |
| ✅   | jest test, który przechodzi to przejście; nazwa testu stoi obok               |
| ⚠️   | kod istnieje po obu stronach, ale żaden test tego nie przechodzi              |
| ❌   | nie ma tego wcale albo jest tylko połowa (np. zapis bez dostarczenia klientowi) |

Reguła utrzymania: **status wolno podnieść tylko razem z testem**, a nowe
przejście dopisuje się do mapy w tym samym commicie, w którym powstaje kod.

## Stany

Stan subskrypcji (`SubscriptionState`) i tryb dostępu (`AccessMode`) to dwie
osobne rzeczy: pierwszy mówi, co się dzieje z płatnością, drugi — co klient może
zrobić w produkcie. Snapshot entitlementów niesie oba.

| Stan            | Dostęp                       | Co to znaczy dla klienta                            |
| --------------- | ---------------------------- | --------------------------------------------------- |
| brak subskrypcji | brak entitlementów           | widzi cennik, nie ma funkcji płatnych               |
| `unconfigured`  | `blocked`                    | Stripe zwrócił `incomplete` — płatność nieukończona |
| `trialing`      | `full`                       | okres próbny, pełne możliwości                      |
| `active`        | `full`                       | płaci i korzysta                                    |
| `grace_period`  | `full` do końca karencji     | płatność nie przeszła, ale nic mu jeszcze nie zabieramy |
| `read_only`     | `read_only`                  | dane są, edycja zablokowana                         |
| `canceled`      | `full` do końca opłaconego okresu, potem `read_only` | zrezygnował, dopłacone dni należą do niego |

`SubscriptionState.SUSPENDED` istnieje w enumie i **nie jest nigdzie ustawiany**
— to martwa wartość, do usunięcia albo do użycia świadomie.

## Przejścia

| #   | Z → do                                | Co wyzwala                                     | Kto wykonuje                    | Co widzi klient                          | Status i dowód                                                          |
| --- | ------------------------------------- | ---------------------------------------------- | ------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------- |
| 1   | brak planu → Checkout otwarty         | klient klika plan                              | panel → `create_setup_checkout` | strona płatności Stripe                  | ✅ `test_checkout_creates_customer_and_persists_idempotent_setup_intent` |
| 1a  | blokada: niepełne dane do faktury     | brak adresu (Stripe Tax nie policzy stawki)    | panel gasi przyciski, API 409   | „Najpierw uzupełnij dane do faktury"     | ✅ `test_the_overview_says_which_details_are_missing` + test panelu      |
| 2   | Checkout opłacony → plan uruchomiony  | `checkout.session.completed`                   | **webhook**; panel tylko odświeża | plan aktywny na ekranie po powrocie     | ✅ `test_checkout_links_verified_customer_to_metadata_organization`      |
| 2a  | powtórka zdarzenia / powrót panelu    | Stripe dostarcza ponownie                      | webhook + panel                 | nic (bez zmian)                          | ✅ `test_a_repeated_checkout_event_does_not_start_a_second_plan`         |
| 3   | `trialing` → `active`                 | koniec triala, pierwsza płatność przechodzi    | Stripe → webhook                | plan zmienia opis na „aktywny"           | ✅ `test_a_customer_walks_the_whole_lifecycle` (krok 3)                  |
| 3a  | to samo w symulatorze                 | scheduler co 5 minut (`advance_simulated_billing`) | zegar symulatora            | plan przechodzi w płatny okres           | ✅ `test_a_trial_whose_day_has_come_becomes_a_paid_period`               |
| 4   | ostrzeżenie przed końcem triala       | scheduler, doba przed `trial_end`              | scheduler zapisuje `BillingNotice`, notifications je dostarcza | wiadomość w dzwonku panelu i e-mail | ✅ `test_a_notice_reaches_the_people_who_can_act_on_it` + `test_trial_warning_is_scheduled_and_emitted_exactly_once` |
| 5   | `active` → `grace_period`             | `invoice.payment_failed`                       | webhook                         | pełny dostęp, informacja o zaległości    | ✅ `test_payment_failure_starts_grace_and_later_paid_event_restores_access` |
| 6   | `grace_period` → `active`             | `invoice.paid` w trakcie karencji              | webhook                         | wraca do normy                           | ✅ ten sam test                                                          |
| 7   | `grace_period` → `read_only`          | scheduler, `grace_period_end` (7 dni z planu)  | scheduler                       | dane widoczne, edycja zablokowana        | ✅ `test_expired_grace_period_becomes_read_only_without_deleting_data`   |
| 8   | zmiana planu (upgrade / downgrade)    | klient klika inny plan                         | Customer Portal + webhook       | portal Stripe, potem nowy plan w panelu  | ✅ `test_a_plan_change_in_the_portal_moves_the_local_plan_and_its_limits` + test panelu |
| 9   | anulowanie                            | klient anuluje w portalu                       | portal → `customer.subscription.updated` | pełny dostęp do końca okresu    | ✅ `test_canceled_webhook_keeps_full_access_until_provider_period_end`   |
| 10  | koniec opłaconego okresu po anulowaniu | scheduler, `current_period_end`               | scheduler                       | traci dostęp                             | ✅ `test_canceled_subscription_stays_full_until_paid_period_ends`        |
| 11  | powrót po zakończonym planie          | nowy Checkout                                  | webhook; **bez drugiego triala** | płaci od pierwszego dnia                 | ✅ `test_a_returning_customer_subscribes_again_and_pays_from_the_start`  |
| 12  | zakup bez triala wymaga 3DS           | Stripe zwraca `incomplete`                     | —                               | błąd, brak ścieżki dokończenia           | ❌ adapter odmawia jawnym komunikatem                                    |
| 13  | faktura po opłaceniu                  | `invoice.paid`                                 | kolejka + adapter faktur        | faktura tylko w portalu Stripe           | ✅ `test_canonical_request_and_adapter_result_are_durable_and_idempotent` |
| 14  | zgubiony webhook → naprawa            | scheduler co 5 minut                           | rekonsyliacja                   | nic (naprawa w tle)                      | ✅ `test_reconciliation_repairs_missing_past_due_webhook`                |
| 15  | zakup pakietu kredytów                | osobny Checkout w trybie `payment`             | webhook                         | ekran „Kredyty”: saldo, pakiety, historia | ✅ `test_billing_credit_checkout` + `test_billing_credits_api` + test panelu |

## Czego atrapy nie udowodnią

Testy podstawiają atrapę dostawcy, więc zgadzają się z kodem z definicji. Ta
lista to rzeczy, które sprawdza się **na prawdziwym koncie Stripe**, ręcznie, po
każdej zmianie w adapterze albo w konfiguracji konta:

1. **wersja API** — zdarzenie przychodzi w wersji przypiętej na endpointcie
   webhooka, a gdy endpoint nie przypina żadnej, w domyślnej wersji konta;
   niezgodność to 400 na każdym zdarzeniu (3–4 września);
2. **podpis webhooka** — sekret z `stripe listen` jest inny niż sekret endpointu
   produkcyjnego;
3. **identyfikatory z obcej przestrzeni** — `sim_customer_…` w Stripe,
   identyfikator z trybu testowego w produkcyjnym; oba kończą się
   `resource_missing`;
4. **Stripe Tax** — czy stawka wychodzi 23% dla PL i 0% dla firmy z UE z numerem
   VAT (sprawdzone 3 września przez `tax.calculations`);
5. **3DS** — karta `4000 0027 6000 3184` zamiast `4242 4242 4242 4242`;
6. **portal** — czy zmiana planu jest w nim faktycznie dostępna i ograniczona do
   naszych trzech cen.

## Znane braki, zebrane

- **3DS przy zakupie bez triala nie jest obsłużone** (12);
- `SubscriptionState.SUSPENDED` jest martwy.

## Kto dostaje ostrzeżenie

Ostrzeżenia trafiają do **osób, które mogą coś z nimi zrobić** — czyli do
członków z uprawnieniem `organization.billing.manage`. Nie na adres z faktury:
tam idą dokumenty i często siedzi tam księgowość, która planu nie zmieni.

Każde ostrzeżenie idzie dwiema drogami naraz: **wiadomość w produkcie**
(dzwonek w nagłówku panelu, `AppNotification`) i **e-mail** przez istniejący
system dostarczania. Poczta wychodzi z budynku i może nie dojść — trafi do spamu
albo do skrzynki, do której nikt nie zagląda — więc kopia zostaje tam, gdzie
dzieje się praca.

Treść nie jest zapisywana w bazie. Wiersz niesie `kind` i fakty, a zdanie składa
panel w języku czytelnika: dzięki temu jedna wiadomość jest polska dla jednej
osoby i angielska dla drugiej, a poprawka w tłumaczeniu nie wymaga migracji
danych.

## Kto pilnuje czasu

W trybie Stripe prawda o subskrypcji jest u dostawcy, a rekonsyliacja pobiera ją
co pięć minut — to ona łata zgubiony webhook. Symulator nie ma czego pobierać,
więc dostał własną połowę tej roboty: `advance_simulated_billing` przesuwa trial
w płatny okres i przewija okres, gdy ten dobiegnie końca. Każda z tych dwóch
funkcji milczy w trybie tej drugiej, więc nigdy nie biją się o ten sam wiersz.

Bez tego zegara lokalne wdrożenie stało w miejscu: trial założony w sierpniu
nadal był trialem we wrześniu, a panel odmawiał nowego zakupu, bo subskrypcja
wyglądała na żywą. Nic nie było zepsute — po prostu nie płynął czas.

## Cały cykl w jednym teście

`tests/test_billing_lifecycle_walk.py` przechodzi całą drogę w kolejności:
wybór planu → opłacony Checkout → trial → pierwsza płatność → nieudana płatność
→ karencja → tylko odczyt → ponowna płatność → zmiana planu → anulowanie →
koniec opłaconego okresu → powrót bez drugiego triala. Po każdym kroku sprawdza
to, co naprawdę widzi klient: stan subskrypcji, tryb dostępu i plan wraz z jego
limitami.

Ten test jest po to, żeby łapać **szwy**, a nie pojedyncze funkcje. Testy
jednostkowe zostają — one mówią, dlaczego coś nie działa; ten mówi, że droga
jako całość się nie rozpadła.

## Utrzymanie

Mapa jest częścią kontraktu, nie notatką. Zmiana w `shared.billing`, która
dodaje albo zmienia przejście, aktualizuje tę tabelę w tym samym commicie.
Status ⚠️ wolno podnieść na ✅ wyłącznie razem z testem przechodzącym to
przejście — nie z testem, który sprawdza kawałek po drodze.
