# ADR-041 — izolacja tabel czytanych przed poznaniem tenanta

- Status: Accepted
- Data: 2026-09-05
- Kontekst decyzji: ADR-039 §6 (luka w regule wykrycia), plan 13 pozycja P1

## Kontekst

ADR-039 ustalił, że każda tabela tenantowa ma wymuszone RLS, o ile moduł nie
zadeklaruje jej jako publicznej. 3 września okazało się, że reguła wykrycia w
teście pytała o dziedziczenie `TenantScopedModel` i nie widziała siedmiu tabel,
które niosą organizację zwykłym kluczem obcym. Wszystkie siedem nie ma **ani
jednej polityki**, w tym `organizations_membership` — tabela decydująca o tym,
kto należy do której firmy. Odczyt członkostw z ustawionym `app.organization_id`
zwraca dziś członkostwa wszystkich organizacji naraz.

Nie da się tego zamknąć jedną migracją, bo każda z tych tabel jest czytana albo
zapisywana **zanim wiadomo, o którego tenanta chodzi**. Pełna lista tych
ścieżek, ustalona z kodu:

1. **middleware tenanta** — szuka członkostwa po `(organizacja, użytkownik)`,
   żeby dopiero z niego zbudować kontekst; w tym momencie `SET LOCAL` jeszcze
   nie padł;
2. **lista organizacji** (`list_organizations`) — czyta członkostwa po
   użytkowniku wraz z organizacjami; ścieżka jest zwolniona z middleware;
3. **przyjęcie zaproszenia** — szuka zaproszenia po haszu tokenu, dołącza
   organizację i rolę, czyta i tworzy członkostwo; też zwolniona;
4. **procesor Stripe** — rozpoznaje tenanta po `BillingProfile.external_customer_id`,
   zanim dotknie czegokolwiek tenantowego;
5. **przyjęcie webhooka** — zapisuje `StripeWebhookEvent` w chwili odbioru,
   przed odczytaniem payloadu; organizacja jest wtedy nieznana;
6. **przemiatania w tle** — `billing_organization_ids()` czyta wszystkie
   organizacje, bo lifecycle, rekonsyliacja i dostarczanie powiadomień muszą
   odwiedzić każdą po kolei;
7. **wpisy audytowe** powstają na tych samych ścieżkach, m.in. przy tworzeniu
   organizacji, gdy tenant jeszcze nie istnieje;
8. **role globalne** (`organization IS NULL`) są wspólnym katalogiem czytanym
   przez wszystkich, a role własne organizacji dołączają się do zapytań z
   punktów 1–3.

## Decyzja

### 1. Trzeci reżim: tabele platformowe

ADR-039 zna dwa reżimy: prywatny (RLS) i publiczny (czytany przez renderer bez
kontekstu). Dochodzi trzeci: **tabela platformowa** — wiersz wskazuje
organizację, ale nie należy do niej, tylko do platformy.

Jedyną taką tabelą dzisiaj jest `billing_stripewebhookevent`. Zdarzenie
zapisujemy w chwili odbioru, po weryfikacji podpisu, a organizację ustalamy
dopiero czytając payload — wiersz z definicji rodzi się bez tenanta. To nie
jest tabela klienta: to skrzynka odbiorcza dostawcy płatności, w której klient
nie ma nic swojego poza identyfikatorem, który sam ujawnił Stripe'owi.

Deklaracja stoi w deskryptorze modułu jako `backend.platformTables`, obok
`publicTables`, i podlega tej samej walidacji: tabela musi należeć do modułu,
który ją deklaruje, i musi istnieć w schemacie. Test izolacji nie wymaga od
niej RLS.

### 2. Osobna tożsamość bazodanowa dla odczytów sprzed tenanta

Pozostałe sześć tabel dostaje **zwykłą politykę po `app.organization_id`** —
dokładnie tę, którą ADR-039 już ustanowił — a ścieżki z listy w Kontekście
czytają przez **drugie połączenie do tej samej bazy, rolą, która RLS omija**.

Wybór jest podyktowany tym, że **wyjście musi być policzalne**. Nie chodzi o
to, żeby uczynić ominięcie niemożliwym — logowanie musi jakoś przeczytać
członkostwa — tylko o to, żeby lista miejsc, w których to robimy, dała się
wypisać jednym poleceniem i żeby jej wzrost był widoczny w przeglądzie zmian.
Połączenie nazwane w kodzie spełnia to lepiej niż flaga sesyjna, którą można
ustawić wszędzie, i lepiej niż polityka z wyjątkiem, którą trzeba czytać ze
zrozumieniem, żeby zobaczyć, co przepuszcza.

**Kontrolą jest test, nie dyscyplina.** Zbiór miejsc używających tego
połączenia jest zadeklarowany na liście; test porównuje listę z rzeczywistością
i psuje się, gdy ktoś doda siódme miejsce bez dopisania go do listy. Bez tego
testu drugie połączenie jest tylko wygodniejszym obejściem.

Konfiguracja: druga pozycja w `DATABASES` wskazująca tę samą bazę inną rolą,
router, który **nigdy nie kieruje tam niczego automatycznie** (tylko jawne
`.using(...)`), oraz zakaz uruchamiania na niej migracji. Rola ma prawo do
odczytu i zapisu tych sześciu tabel i nic ponadto.

### 3. Klasyfikacja siedmiu tabel

| Tabela                                 | Reżim                        | Dlaczego                                                                 |
| -------------------------------------- | ---------------------------- | ------------------------------------------------------------------------ |
| `organizations_membership`             | RLS + drzwi                  | decyduje, kto należy do której firmy; logowanie i przełącznik czytają po użytkowniku |
| `organizations_organization`           | RLS + drzwi                  | rejestr, do którego rozwiązuje się odpowiedź na tamto pytanie; także przemiatania |
| `organizations_invitation`             | RLS + drzwi                  | token czyta ktoś, kto jeszcze nie jest członkiem; wiersz niesie adres e-mail |
| `organizations_billingprofile`         | RLS + drzwi                  | procesor Stripe rozpoznaje po nim tenanta; wiersz niesie adres i numer VAT |
| `organizations_organizationauditentry` | RLS + drzwi                  | powstaje na tych samych ścieżkach, m.in. przy tworzeniu organizacji       |
| `organizations_role`                   | RLS z dopuszczeniem `organization IS NULL` | katalog globalny nie jest danymi tenanta; rola własna firmy już tak |
| `billing_stripewebhookevent`           | **platformowa**              | rodzi się bez tenanta, należy do platformy, nie do klienta                |

### 4. Kolejność wdrożenia

Odwrotnie niż w migracji, tak samo jak przy `shared.billing` (ADR-039 §5):
**najpierw ścieżki, potem polityki**. Polityka założona przed przepisaniem
odczytu nie wywala błędu — zwraca pusty wynik, czyli logowanie przestaje
działać po cichu.

1. **tabele platformowe** — pole w deskryptorze, walidacja, test i deklaracja
   `billing_stripewebhookevent` (zrobione tym ADR-em);
2. **drzwi** — rola bazodanowa, sekret, compose, konfiguracja Django, lista
   dozwolonych miejsc i test, który jej pilnuje;
3. **migracja tabel po jednej**, zaczynając od dwóch niosących dane osobowe
   (`billingprofile`, `invitation`), bo tam koszt wycieku jest największy, a
   ścieżki sprzed tenanta są pojedyncze i już wyodrębnione.

Do zakończenia kroku 3 wpisy zostają na liście długu w teście izolacji z
jawnym uzasadnieniem. Zdejmuje się je pojedynczo, razem z migracją.

## Uzupełnienie wdrożeniowe (2026-09-05)

Krok 3 zakończony: `0025` (profil billingowy, zaproszenie), `0026` (członkostwo,
audyt), `0027` (role), `0028` (rejestr). Dwie rzeczy wyszły przy przepisywaniu
ścieżek i zawężają tę decyzję, nie odwracają jej.

**Renderer publiczny nie używa drzwi.** Cztery ścieżki publiczne sprawdzały
status organizacji złączeniem, czyli odczytem rejestru bez tenanta. Puszczenie
ich drzwiami byłoby cofnięciem się: renderer jest najbardziej wystawioną
powierzchnią produktu, a rola drzwi czyta ponad politykami — jeden błąd tam
sięgałby członkostw i zaproszeń każdego tenanta, czyli dokładnie tego, czemu ten
ADR ma zapobiec. Zamiast tego host nazywa tenanta: `tenant_is_servable`
ustawia go i czyta status od środka. Osobny test pilnuje, żeby żaden moduł
publiczny nie pojawił się na liście drzwi.

**Wpisy audytowe nie dostały polityki drzwi.** Tabela jest wymieniona w §3 jako
„RLS + drzwi", ale każda ścieżka, która pisze audyt, ustawia tenanta wcześniej,
więc drugie wejście byłoby otwarte i nieużywane.

**Polityka ról jest asymetryczna.** Odczyt dopuszcza `organization IS NULL`
(katalog globalny), zapis nie — żaden tenant nie dopisze sobie roli globalnej.

## Konsekwencje

- polityki pozostają jednym zdaniem, tym samym dla wszystkich modułów; nie
  trzeba ich czytać ze zrozumieniem, żeby wiedzieć, co przepuszczają;
- powstaje druga rola bazodanowa i drugi sekret w każdym środowisku, a wraz z
  nimi obowiązek, żeby nie miała praw, których nie potrzebuje;
- `.using(...)` jest młotkiem: nic w bazie nie odróżni logowania od zwykłego
  zapytania puszczonego tą samą drogą. Dlatego kontrolą jest test listy, a nie
  wiara w to, że nikt tak nie zrobi;
- przemiatania w tle przechodzą przez te same drzwi świadomie — dziś czytają
  wszystkie organizacje i po wdrożeniu polityk inaczej nie mogą;
- test izolacji uczy się trzeciego reżimu, więc „tabela bez RLS" przestaje być
  jednoznaczna z „dziura" i zaczyna wymagać deklaracji, którą widać w
  deskryptorze.

## Alternatywy odrzucone

- **zmienna sesyjna `app.user_id` i polityki „tenant albo moje wiersze"** —
  kusząca, bo odzwierciedla to, co aplikacja naprawdę robi przy logowaniu. Ale
  polityka dla `organizations_organization` musiałaby zawierać podzapytanie do
  członkostw, każde uwierzytelnione żądanie musiałoby otwierać transakcję, żeby
  `SET LOCAL` miał gdzie zadziałać, a przemiatania w tle — które legalnie
  czytają wszystkie organizacje — nadal nie miałyby odpowiedzi;
- **funkcje `SECURITY DEFINER`** — najwęższe możliwe wizjery i żadnych nowych
  poświadczeń. Odrzucone, bo każdy odczyt sprzed tenanta stałby się ręcznie
  pisanym SQL-em obok modelu, a te dwa rozjeżdżają się przy pierwszej zmianie
  pola;
- **deklaracja wszystkich sześciu jako publiczne** — zgodne z literą ADR-039 i
  darmowe, ale `publicTables` znaczy „renderer czyta to bez kontekstu", a nie
  „nie umiemy tego zamknąć". Nazwanie długu funkcją to najgorszy rodzaj
  porządku;
- **zostawienie jak jest** — izolacja tabeli decydującej o przynależności
  opiera się wyłącznie na kodzie aplikacji, a jeden zapomniany filtr wystarcza,
  żeby pokazać cudze członkostwa.

## Relacje

- rozszerza ADR-039 o trzeci reżim i zamyka lukę opisaną w jego §6;
- korzysta z kontraktu modułów ADR-021 (deklaracja w deskryptorze);
- pozycja P1 planu 13; do zakończenia kroku 3 wpisy stoją na liście długu w
  `tests/test_tenant_isolation_regimes.py`.
