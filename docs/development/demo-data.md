# Dane demo stosu testowego — `manage.py seed_demo`

Po zalogowaniu na stos testowy (lokalny albo staging `*.goldenstar.cloud`) są już
firmy, które coś opowiadają: zespół, kalendarz z przeszłością i przyszłością,
zamówienia w każdym stanie, dokumenty z dziennikiem zgód, opublikowana strona.
Służą do sprawdzenia produktu i do pokazu — bez wyklikiwania.

Komenda działa w kontenerze backendu i można ją uruchamiać wielokrotnie. Znajduje to,
co założyła poprzednio (organizację po slugu, konto po e-mailu, ofertę i jednostkę po
nazwie, rezerwację po kluczu idempotencji) i dopisuje tylko to, czego wymaga nowy
dzień: rezerwacje dni, które weszły w zasięg, kolejny krok historii, na który przyszedł
czas. Niczego nie usuwa i niczego, co firma ma już po swojemu, nie zmienia.

**Uruchom ją w dniu pokazu.** Stany „czeka na odpowiedź” i „czeka na przelew” mają
terminy (48 godzin, 3 dni) — produkt sam je zamyka, gdy termin minie. Każde
uruchomienie dokłada świeże.

## Uruchomienie

```bash
# staging na VPS (hasło wpisane raz przez `read -s` do pliku 0600):
docker exec -i -e DEMO_SEED_ENABLED=1 saas-core-backend-1 \
  python manage.py seed_demo --password-stdin < /root/.demo-seed-password

# lokalnie (hasło z KONTA-TESTOWE.md, nie z historii powłoki):
docker compose exec -T -e DEMO_SEED_ENABLED=1 backend \
  python manage.py seed_demo --password-stdin < plik-z-haslem

# co powstałoby — bez hasła, bez zapisu:
docker compose exec -T backend python manage.py seed_demo --list

# tylko wybrane firmy (klucze pokazuje --list; można podać kilka razy albo po przecinku):
… python manage.py seed_demo --password-stdin --scenario domki --scenario kajaki
```

Pierwsze uruchomienie trwa około pół minuty, kolejne kilka sekund. Na końcu komenda
wypisuje konta i dla każdej firmy pięć ścieżek do przeklikania z adresami tego stosu.

Zabezpieczenia:

- bez `DEMO_SEED_ENABLED=1` w środowisku tego uruchomienia komenda odmawia;
- odmawia przy `APP_ENV=production` i przy Stripe w trybie live (stosy na VPS-ie mają
  `APP_ENV=local` i https — to dozwolone);
- hasło kont nie przechodzi przez argv ani repozytorium: `--password-stdin`, plik
  `DEMO_SEED_PASSWORD_FILE` albo `DEMO_SEED_PASSWORD`; co najmniej 12 znaków;
  istniejące konta demo dostają to hasło przy każdym uruchomieniu;
- wszystkie konta i wszyscy klienci demo mają adresy w domenie `.test` — scenariusz
  z innym adresem konta zostaje odrzucony, zanim cokolwiek powstanie;
- cudzej firmy o tym samym slugu ani konta operatora komenda nie przejmuje;
- **żadnego wywołania modelu**: teksty stron w innych językach są w repozytorium,
  a firma, która ma włączone automatyczne tłumaczenia (i nie obsługuje jej atrapa
  modelu), jest pomijana w całości — zapisy danych demo zleciłyby jej płatne
  tłumaczenia;
- zdjęcia jednostek to wyłącznie ilustracje szablonów stron z repozytorium (opisy
  mówią „zdjęcie poglądowe”); nic nie jest pobierane ani generowane.

## Jak powstaje przeszłość

Komenda pisze przez serwisy modułów — te same drzwi, których używa panel i formularze
publiczne — więc dane są takie, jakie produkt mógł wytworzyć sam: z historią,
zamówieniem, zapisami w księdze, dziennikiem zgód i e-mailami. Przeszłość powstaje tak
samo: serwis jest wołany z zegarem procesu komendy ustawionym na chwilę, w której rzecz
się wydarzyła (`DemoRun.clock`). Wizyta sprzed tygodnia jest zarezerwowana trzy dni
przed nią i opłacona w jej dniu; żadna data nie jest wpisywana do wiersza. Zegar zmienia
tylko proces komendy — działający backend i workery go nie widzą.

Firma, którą komenda zakłada, jest „założona” 900 dni wcześniej i wtedy dostaje swoje
ustawienia (języki, rachunek, dokumenty, oferty, cennik), żeby jej przeszłość miała się
w czym wydarzyć. Firma istniejąca wcześniej dostaje brakujące rzeczy z datą bieżącą.

Rezerwacje są funkcją kalendarza, nie uruchomienia: każdy dzień i każdy tydzień ma te
same rezerwacje, kiedykolwiek komenda działa. Każda historia firmy jest grana w jednej
transakcji, od najstarszego kroku — zadania cykliczne nie spotkają rezerwacji „sprzed
trzech dni”, której „przedwczorajsza” wpłata jeszcze nie zapisano.

## E-maile

Komenda wysyła to, co wysyła produkt (potwierdzenie rezerwacji, dane do przelewu,
informację o zwrocie), bo idzie przez te same serwisy. Żeby nie było ich setki:
klienci z przeszłości rezerwują telefonicznie i nie mają e-maila, a przez formularz
publiczny rezerwuje tylko kilku — z wyprzedzeniem, więc przypomnienia wyjdą w swoim
czasie, nie po fakcie. Pierwsze uruchomienie kolejkuje **około 70 wiadomości** na
trzy firmy, uruchomienie tego samego dnia — żadnej, kolejnego dnia — kilka. Komenda
wypisuje liczbę na końcu („e-maile w tym uruchomieniu: N”). Lokalnie trafiają do
Mailpita; na VPS-ie adresy `.test` nie mają dokąd dojść.

## Co powstaje (Business)

Trzy firmy na planie pro bez płatności (`billing/demo.py`), każda z rachunkiem do
przelewów — zmyślonym: numer ma poprawną sumę kontrolną, ale kod banku z samych zer,
a nazwa posiadacza mówi „konto testowe” (`commerce/demo.py`).

### Studio Testowe — wizyty (`--scenario studio`)

Konta: `wlasciciel@saas.test` (właściciel), `kierownik@saas.test` (menedżer),
`pracownik@saas.test` (pracownik).

- **Usługi i cennik**: „Konsultacja” (150 zł, w sobotę 180 zł, dodatek „Materiały
  szkoleniowe” 40 zł, płatność na miejscu), „Sesja we dwoje” (dwie osoby),
  „Warsztat indywidualny” — **na prośbę**, firma ma 48 godzin na odpowiedź,
  „Pakiet startowy” — **przelew z góry** w 3 dni, zwrot 100% do 7 dni i 50% do 2 dni
  przed terminem. Zespół ma godziny 7–21; 11 listopada firma jest zamknięta.
- **Kalendarz**: wizyty z ostatnich 7 dni, dzisiejsze i na 7 dni naprzód; wakat
  w „Do przydzielenia” („Sesja we dwoje” z jedną osobą); nieobecność klienta; wizyta
  odwołana przez firmę.
- **Prośby**: codziennie jedna prośba o „Warsztat indywidualny” z formularza —
  dzisiejsza czeka, wcześniejsze są przyjęte, odrzucone z powodem albo wygasły.
- **Zamówienia**: opłacone gotówką na miejscu, do zapłaty, czekające na przelew
  z terminem, wygasłe bez wpłaty, anulowane; jedno **zwrócone** (rezygnacja 11 dni
  przed — zwrot całości oznaczony) i jedno **anulowane z rozliczeniem** (rezygnacja
  4 dni przed — połowa do zwrotu, jeszcze nieoddana).
- **Klienci**: telefoniczni bez e-maila i internetowi z e-mailem, część ze zgodą
  marketingową; **jeden zanonimizowany**; trzech sprzed ponad roku — to ich pokaże
  podgląd usuwania danych po czasie (ustawienie zostaje **wyłączone**).
- **Wzorce ofert**: zapis na wzorzec „wkrótce” — „Zajęcia grupowe” — z notatką.
- **Magazyn** (`inventory/demo.py`): pozycje, przyjęcie PZ, wydania MM, zużycie RW, zwrot.
- **Strona**: jednostronicowa, pl i en — tylko gdy firma nie ma jeszcze strony.

### Domki nad Jeziorem — noclegi (`--scenario domki`)

Konta: `domki@saas.test` (właścicielka), `recepcja.domki@saas.test` (menedżer).

- **Oferta z wzorca „Nocleg”** („Wzorce ofert” → szkic → jednostki → włączenie): doby
  16:00–11:00, przedpłata 30% przelewem w 3 dni, reszta 14 dni przed przyjazdem,
  zwrot przedpłaty w całości do 30 dni i w połowie do 14 dni przed.
- **Cztery jednostki** ze zdjęciami, wyposażeniem i miejscowością (Mikołajki): dwa
  domki w puli, apartament, chata — ta jedna z **dokładnym punktem na mapie**.
- **Cennik**: cena za noc z 4 osobami w cenie i dopłatą za kolejne, dziecko i pies
  jako kategorie, **rabat za długość** od 3 nocy, sezon letni i świąteczny;
  dopłaty: sprzątanie końcowe, opłata miejscowa, pościel; **kaucja** 500 zł.
  Sezony rezerwacji: co najmniej 2 noce; latem najpóźniej dobę przed przyjazdem.
- **Pobyty** z ostatnich 4 tygodni, trwające i na 9 tygodni naprzód.
- **Zamówienia w każdym stanie**: czeka na przelew, opłacone częściowo (przedpłata
  wpłacona, dopłata przed terminem albo po terminie), opłacone, **zwrócone**,
  **anulowane z rozliczeniem** (połowa przedpłaty do zwrotu), wygasłe bez wpłaty.
- **Strona z szablonu „Noclegi”** z uzupełnionymi miejscami `[Uzupełnij: …]`:
  rezerwacja, jednostki z ceną „od”, mapa, kalendarz wolnych terminów; strony
  jednostek `/stay/…` i dokumentów `/documents/…`; języki pl, en i — gdzie profil ma
  niemiecki — de.

### Kajaki Krutynia — wypożyczalnia (`--scenario kajaki`)

Konto: `kajaki@saas.test` (właściciel).

- **Oferta z wzorca „Wypożyczalnia”**: dni 9:00–18:00, płatność na miejscu, pula trzech
  kajaków i rodzinne canoe, cena za dzień z rabatem od 3 dni, **kaucja** 200 zł, dowóz.
- **Wypożyczenia** z ostatnich 7 dni, dzisiejsze i przyszłe; odwołane przez firmę.
- **Strona** z blokami pobytów (lista jednostek, kalendarz wolnych dni, mapa), pl i en.

### W każdej firmie

- **Dokumenty dla klientów** (`customers/demo.py`): regulamin rezerwacji po polsku
  i angielsku oraz polityka prywatności po polsku — zatwierdzone przez właściciela.
  Każdy tekst zaczyna się zdaniem, że to **przykład pokazowy, nie porada prawna**.
  Rezerwacje z formularza akceptują je, więc **dziennik zgód** się wypełnia.
- **Tłumaczenie „Do akceptacji”** (`translation/demo.py`): angielska wersja polityki
  prywatności jest zlecana **tylko tam, gdzie działa atrapa modelu**
  (`MODEL_PORT_TEST_DOUBLE`, nigdy na stosie pod https). Firma trafia wtedy na listę
  atrapy, wynik („[en] tekst źródłowy”) czeka w „Tłumaczenia → Do akceptacji”.
  Gdzie indziej krok jest pomijany i komenda to mówi.
- **Teksty w innych językach** — strony, nazwy ofert, jednostek i dopłat — pochodzą
  ze scenariusza i są zapisane jako **zaimportowane** (`import`): panel pokazuje
  „Zaimportowane”, nie „Tłumaczenie AI” i nie poprawkę osoby.

## Przewodnik do pokazu

Adresy z prefiksem panelu i strony komenda wypisuje dla danego stosu (lokalnie
`http://business.localhost:8080`, strony firm `http://<slug>.business.localhost:8080`).

**Studio Testowe** (`wlasciciel@saas.test`)

1. `/panel/calendar` — wizyty z ostatnich dni, dzisiejsze i przyszłe; w
   `/panel/calendar/queue` „Sesja we dwoje” czeka na drugą osobę.
2. `/panel/calendar/requests` — dzisiejsza prośba czeka: „Przyjmij” albo „Odmów”.
3. `/panel/orders` — filtr „Stan”: czeka na przelew, opłacone, anulowane, zwrócone.
4. `/panel/settings/services` — cennik z ceną sobotnią i dodatkiem; „Wzorce ofert”
   (`/panel/settings/services/presets`) z zapisem na „Zajęcia grupowe”.
5. `/panel/settings/privacy` — „Po 12 miesiącach” → „Zapisz zmiany”: okno mówi, ilu
   klientów dotyczy zmiana; „Anuluj”. Dziennik zgód: `/panel/settings/consents`.

**Domki nad Jeziorem** (`domki@saas.test`)

1. Strona firmy — szablon „Noclegi”, języki, strona domku, mapa, regulamin.
2. Formularz rezerwacji (`/book/…`) — cena za noc, rabat, kaucja, przedpłata, zgody.
3. `/panel/calendar/occupancy` — obłożenie czterech jednostek.
4. `/panel/orders` — każdy stan; w anulowanym: ile wraca według progów zwrotu.
5. `/panel/settings/documents` — dokumenty; `/panel/sites/translations/review` —
   tłumaczenie do akceptacji (gdzie działa atrapa).

**Kajaki Krutynia** (`kajaki@saas.test`)

1. Strona wypożyczalni — jednostki z ceną za dzień, kalendarz wolnych dni.
2. Formularz rezerwacji — dni, cena za dzień, kaucja osobno.
3. `/panel/calendar/occupancy` — trzy kajaki i canoe.
4. `/panel/orders` — opłacone przy wydaniu, do zapłaty, anulowane.
5. `/panel/settings/services` — oferta z wzorca, pula jednostek, cennik.

## Punkt rozszerzenia (ADR-049)

Rdzeń zakłada konta, organizacje, członkostwa i języki (`core/organizations/demo.py`);
moduły dopisują swoje części przez `register_demo_part(name, part, order=…,
describe=…)` w `ready()`:

| kolejność | część | co robi |
| --- | --- | --- |
| 1 / 990 | `notifications` | liczy wiadomości przed i po |
| 2 / 60 | `translation` | pomija firmę z włączoną automatyką; zleca tłumaczenie atrapie |
| 10 | `billing.plan` | plan bez płatności |
| 15 | `organizations.languages` | języki firmy |
| 20 | `commerce.transfer`, `farms.link` | rachunek do przelewów; karta gospodarstwa |
| 25 | `customers.documents` | regulamin i polityka prywatności |
| 30 | `booking.calendar` | katalog, cennik, historie rezerwacji |
| 40 | `inventory.warehouse` | magazyn |
| 50 | `sites.site` | strona firmy |

Produkt:

- zastępuje scenariusz Business własnym — `register_demo_scenario(factory)` w `ready()`
  modułu wertykalnego. `DemoOrganization` niesie konta, typ organizacji, plan, języki
  (`locales`), opis w jednym zdaniu (`story`), ścieżki przewodnika (`paths`), moduły,
  bez których firma nie ma sensu (`requires`), firmy, które idą razem z nią (`needs`),
  i dane modułów pod nazwą części: `booking`, `commerce`, `customers`, `sites`,
  `inventory`; `farms.links` między organizacjami. Kształty opisują docstringi modułów;
- opowiada rezerwacje funkcją `booking["stories"](plan)`: `plan.visit(…)` i
  `plan.stay(…)` planują rezerwację w chwili, w której została złożona (zespół albo
  formularz publiczny), a `.then(krok, chwila, …)` — co się z nią działo. Kroki modułów
  wspólnych: `booking.accept`, `booking.decline`, `booking.expire`, `booking.cancel`,
  `booking.complete`, `booking.no_show`, `booking.anonymize`, `commerce.pay`,
  `commerce.refund`, `commerce.lapse`;
- dodaje własne kroki — `register_demo_step(name, handler)` — i własne części, które
  grają historie przez `DemoRun.play(key, stories)`. Krok dostaje historię z notatkami
  poprzednich kroków (`story.memo`: `appointment_id`, `customer_id`, `order`) i sam
  rozpoznaje, co zrobił we wcześniejszym uruchomieniu.
