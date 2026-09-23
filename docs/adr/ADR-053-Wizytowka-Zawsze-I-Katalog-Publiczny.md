# ADR-053: wizytówka powstaje zawsze, katalog publiczny stoi obok witryn

Status: zaakceptowana, 2026-09-23 (decyzja właściciela, z doprecyzowaniem w §10);
zaproponowana 2026-09-21. §8 zostanie zastąpiony osobnym ADR (wyszukiwarka).
**Zastępuje ADR-036 §4 tiret trzecie** („profil prosty bez strony" jako
jednostronicowa witryna z recepty `core.profile.v1`). Reszta ADR-036 pozostaje
obowiązująca w całości — w szczególności §3 (`PublicProfile` w `shared.profiles`),
§4 tiret pierwsze i drugie (`StaffMember.profile`, blok `core.profile` przez
odwołanie) oraz §5–§8.

## Kontekst

Właściciel produktu postawił wymóg (2026-09-21): **każda organizacja ma być
widoczna na listingu, więc wizytówka powstaje zawsze.** Strona internetowa
przestaje być alternatywą dla wizytówki i staje się opcją nad nią:

- organizacja **bez strony** — wpis w katalogu otwiera stronę wizytówki na
  platformie;
- organizacja **ze stroną** — wpis w katalogu prowadzi do jej domeny albo
  subdomeny.

ADR-036 §4 rozstrzygał to inaczej: profil prosty miał być jednostronicową
witryną z recepty `core.profile`, żeby nie powstał drugi renderer ani druga
ścieżka publikacji. Przy wymogu „wizytówka zawsze" ta konstrukcja się nie spina
i nie jest to kwestia gustu, tylko arytmetyki: organizacja ze stroną miałaby
**dwie witryny**, a plan `profile` ma `sites.max: 1`. Podniesienie limitu nic nie
ratuje — druga witryna zużywałaby limit stron, wpadała w publikację, w domeny i
w kolejkę propozycji, choć nikt nigdy nie miałby jej edytować jako strony.

Stan zastany na 2026-09-21, sprawdzony w kodzie:

- `shared.profiles` ma modele, serwisy i API `/api/v1/profiles/`, jedzie w
  profilach `agro`, `business` i `vps-dev`;
- **nie ma żadnego frontendu** — ani modułu w `apps/frontend/src/modules/shared/`,
  ani ekranu w panelu;
- **nie ma żadnego powiązania z `shared.sites`** — zero odwołań w obie strony,
  blok `core.profile` z ADR-036 §4 nie powstał;
- `PublicProfile` nie ma pojęcia publikacji, miasta ani kategorii;
- katalogu, listingu i wyszukiwarki nie ma w ogóle.

Wymóg dotyczy więc modułu, który istnieje, ale do którego nic nie dzwoni.

## Decyzja

### 1. Wizytówka to `PublicProfile`, nie witryna

Wizytówka organizacji jest wierszem `PublicProfile` o `subject_kind=organization`
z `shared.profiles`. Nie jest `Site`, nie ma `PageVersion`, nie przechodzi przez
publikację ADR-027 i nie zajmuje `sites.max`. Organizacja ma dokładnie jedną —
tak jak ADR-036 §3 już wymaga indeksem częściowym.

Witryna pozostaje dokładnie tym, czym jest dzisiaj. Żadna reguła ADR-027,
ADR-028 ani ADR-031 się nie zmienia.

### 2. Profil zakładamy leniwie, nie przy tworzeniu organizacji

`core.organizations` nie może utworzyć profilu — Core nie importuje Shared
(ADR-021, ten sam powód, dla którego ADR-036 §3 nie umieścił profilu w Core).
Zamiast zdarzenia albo outboxu profil powstaje **przy pierwszym odczycie
wizytówki organizacji** w `shared.profiles`: `get_or_create` z `display_name`
wziętym z nazwy organizacji.

„Zawsze istnieje" jest więc prawdą z punktu widzenia każdego, kto profil czyta,
a nie inwariantem pilnowanym przez drugi mechanizm zapisu. Organizacja, która
nigdy nie otworzyła ekranu wizytówki, nie ma wiersza i nie jest w katalogu —
i tak ma być, bo do katalogu wchodzi się publikacją, nie założeniem konta.

### 3. Publikacja wizytówki to osobny, jawny akt

`PublicProfile` dostaje `published_at` (nullable). Profil niepublikowany jest
szkicem widocznym wyłącznie w panelu. Nic nie publikuje się samo: profil zakładany
leniwie jest pusty, a pusty profil w katalogu byłby szkodą dla klienta i dla
katalogu.

### 4. Katalog jest osobną tabelą publiczną, a nie otwarciem `PublicProfile`

Powstaje `profiles_catalogentry` — jeden wiersz na opublikowaną wizytówkę
organizacji, zadeklarowany w `backend.publicTables` deskryptora `shared.profiles`.
Niesie wyłącznie to, co listing pokazuje i po czym filtruje: `organization`,
`profile`, `slug`, `city_slug`, `city`, `category`, `display_name`, `headline`,
`photo`, `published_at`, `site` (nullable) oraz wektor wyszukiwania.

`PublicProfile` i `PublicProfileTranslation` **zachowują wymuszone RLS bez zmian**.
Publiczna ścieżka działa jak renderer witryn z ADR-039: wpis katalogu jest
**deklaracją tenanta**, dokładnie tak jak `sites_domain` jest nią dla hosta.
`/katalog/<miasto>/<firma>` rozwiązuje slug w tabeli katalogu, sprawdza
`tenant_is_servable(organization_id)`, ustawia tenanta i dopiero wtedy czyta
profil pod polityką. Publiczne odczyty żyją w jednym pliku
`modules/shared/profiles/public_views.py` i **nie używają drzwi `PRE_TENANT_DB`**
(ADR-041 pkt 4 — najbardziej wystawiona powierzchnia nie dostaje połączenia
czytającego ponad politykami).

Dlaczego nie prościej, czyli nie „wpisz `profiles_publicprofile` w `publicTables`":
ta tabela trzyma także profile **osób** — pracowników z nazwiskiem, zdjęciem i
kontaktem (ADR-036 §3, rozstrzygnięcie właściciela nr 2). Otwarcie jej znaczyłoby,
że przed wyciekiem danych pracowników wszystkich tenantów stoi wyłącznie warunek
`WHERE` w zapytaniu. Osobna tabela katalogu nie filtruje profili osób — ona ich
nie zawiera. To ta sama różnica, którą ADR-039 zapisał po dwóch incydentach.

Tabela katalogu daje przy okazji dwie rzeczy, których tabela pod RLS dać nie może:
**globalnie unikalny adres** (`UNIQUE (city_slug, slug)` jest z definicji
międzytenantowy) i jedno tanie zapytanie listingu bez joinów po tenantach.

### 5. Dokąd prowadzi wpis

`CatalogEntry.site` wskazuje witrynę organizacji albo jest puste.

- **puste** — wpis otwiera `/katalog/<miasto>/<firma>` na platformie;
- **ustawione** — wpis prowadzi do adresu tej witryny; pierwszeństwo ma
  zweryfikowana domena canonical, potem subdomena platformy, tą samą regułą,
  którą panel stosuje już dziś.

Adresu nie denormalizujemy do kolumny. `sites_site`, `sites_publication` i
`sites_domain` są już tabelami publicznymi, więc listing dołącza je zapytaniem;
złączenie nie może się zestarzeć, a kolumna mogłaby. Gdy witryna nie ma jeszcze
publikacji albo zweryfikowanej domeny, wpis zachowuje się jak wpis bez witryny —
prowadzi na stronę katalogu, zamiast prowadzić w pustkę.

### 6. Strona wizytówki renderuje rekord, nie bloki

`/katalog/...` to trasy Next.js w aplikacji platformy, nie `site-renderer`.
Renderują ustrukturyzowany rekord w jednym z kilku stałych układów — bez bloków,
bez wersji, bez snapshotu, bez domen.

To nie jest druga ścieżka publikacji, przed którą ostrzegało ADR-036 §4:
ścieżka publikacji witryn zostaje jedna i nietknięta. Powstaje natomiast drugi,
znacznie prostszy widok publiczny — i to jest świadomy koszt tej decyzji.
Wybór układu jest polem `layout` na profilu, z zamkniętej listy w kontrakcie.
Recepty stron (`packages/contracts/page-templates/`) zostają przy witrynach i
nie są tu używane.

### 7. Miasto i kategoria ze słownika

Filtry katalogu i segment adresu muszą mieć stabilne wartości, więc obie osie są
słownikowe, a słownik jest kontraktem w `packages/contracts/catalog/`:

- **kategorie** — zamknięta lista per typ organizacji (ADR-050). Typ organizacji
  wybiera się już w onboardingu, więc lista kategorii jest krótka i sensowna;
- **miasta** — lista pozycji `{slug, name, voivodeship}`. `city_slug` jest
  kluczem w adresie.

Słownik jest **niepełny z założenia** i rośnie wraz z zasięgiem sprzedaży.
Kompletna lista miejscowości Polski w chwili, gdy pierwszy klient jest z Mazur,
byłaby danymi na zapas. Dopisanie pozycji to zmiana kontraktu widoczna w diffie —
i tak ma być, bo każda pozycja to publiczny adres.

Wartość spoza słownika jest odrzucana przy zapisie, nie naprawiana po cichu.

### 8. Wyszukiwarka to Postgres

Wyszukiwanie po katalogu robi Postgres: `tsvector` z konfiguracją `simple` nad
nazwą, nagłówkiem i kategorią, plus trigram na nazwie dla literówek. Bez osobnego
silnika, bez indeksera, bez kolejki.

Katalog jest jedną tabelą z jednym wierszem na opublikowaną wizytówkę; przy
skali, przy której to przestanie wystarczać, wymiana dotyczy jednego zapytania.
Osobny silnik wyszukiwania na tym etapie byłby drugim systemem do utrzymania i
drugim źródłem prawdy o tym, kto jest w katalogu.

### 9. Entitlement i plany

> Stan 2026-09-23: cecha `profiles.enabled` jest we wszystkich planach. Odebranie
> planowi `profile` cechy `sites.enabled` (akapit niżej) nie zostało wykonane —
> to decyzja cenowa właściciela, której jeszcze nie podjął.

Powstaje entitlement `profiles.enabled`, deklarowany przez `shared.profiles`.
Wizytówka jest podłogą oferty, więc cechę dostają wszystkie plany; publikacja w
katalogu sprawdza ją tak samo jak każda inna mutacja.

Plan `profile` (ADR-032) traci `sites.enabled`: po tej decyzji jest planem
wizytówki bez witryny, a nie planem witryny jednostronicowej. Zmiana idzie nową
`PlanVersion` — wersje planów są niezmienne (ADR-026, ADR-032), a downgrade nie
usuwa treści: witryna organizacji, która zejdzie na `profile`, zostaje do odczytu
i nie może być ponownie opublikowana.

### 10. Doprecyzowanie właściciela, 2026-09-23

1. **Wizytówka jest dostępna w każdym planie i dla każdego typu organizacji,
   któremu produkt da `shared.profiles`.** Rdzeń nie zakłada branży — nie wiadomo,
   w jakie branże wejdą produkty. HoofCare daje ją także gospodarstwom, z własną
   kategorią katalogu.
2. **Obecność w katalogu jest przełącznikiem „Pokazuj wizytówkę w katalogu”,
   domyślnie wyłączonym.** To §3 wyrażony w panelu: nie każdy chce być w
   katalogu, więc nikt nie trafia tam bez własnej decyzji. Włączenie tworzy
   wiersz katalogu, wyłączenie go kasuje (§4).
3. **Włączenie i wyłączenie mają osobne akcje historii zmian** —
   `profile.published` i `profile.withdrawn` z autorem — zamiast ogólnego
   `profile.updated`.
4. **Wyszukiwanie przechodzi na osobny silnik wielojęzyczny** z wyszukiwaniem po
   znaczeniu (Meilisearch, plan memex
   `saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`, faza 5).
   Opisze to osobny ADR; do jego wdrożenia obowiązuje §8.

## Konsekwencje

- `shared.profiles` zyskuje pierwszy frontend: ekran „Wizytówka" w grupie
  „Firma" panelu, bramkowany permissionem `profiles.manage`;
- deskryptor `shared.profiles` zyskuje `publicTables: ["profiles_catalogentry"]`,
  entitlement `profiles.enabled` i trasy publiczne; zależność rośnie o
  `shared.sites` (nullable FK do witryny) — kierunek shared → shared jest
  dozwolony, ale wiąże moduły, które dotąd się nie znały;
- `profiles_catalogentry` ma klucz obcy do `Organization`, więc obejmuje ją
  reguła ADR-039: albo RLS, albo deklaracja. Jest zadeklarowana, i to jej trzeba
  pilnować w `test_tenant_isolation_regimes.py`;
- usunięcie tenanta (ADR-042) musi kasować wpis katalogu — inaczej usunięta
  organizacja zostaje w publicznym listingu. Wiersz ma `organization_id`, więc
  obejmuje go istniejąca furtka, ale wymaga wpisu w inwentarzu erasure;
- cofnięcie publikacji wizytówki kasuje wiersz katalogu, a nie ustawia mu flagi:
  nieobecność w tabeli publicznej jest tańsza do udowodnienia niż warunek;
- katalog jest nową powierzchnią SEO platformy i nową powierzchnią ataku —
  publiczne trasy dostają limit zapytań i nie przyjmują dowolnych filtrów, tylko
  wartości ze słownika;
- ADR-036 §4 tiret trzecie przestaje obowiązywać; recepta `core.profile`
  (dziś v2) zostaje jako **szablon strony** dla witryn i nie jest wycofywana.

## Alternatywy odrzucone

- **Wizytówka jako jednostronicowa witryna (ADR-036 §4)** — nie spina się z
  „wizytówka zawsze": organizacja ze stroną miałaby dwie witryny i rozbity limit
  `sites.max`;
- **`profiles_publicprofile` jako tabela publiczna** — otwiera profile osób
  wszystkich tenantów; przed wyciekiem stoi wtedy warunek w zapytaniu zamiast
  granicy tabeli (§4);
- **Wpis katalogu bez własnej tabeli, liczony z `PublicProfile` przy odczycie** —
  odczyt międzytenantowy pod RLS zwraca zero wierszy, a nie błąd; to dokładnie
  ta klasa awarii, którą opisuje `change-tenant-data`;
- **Kolumna z gotowym adresem docelowym** — stałaby się nieaktualna przy zmianie
  domeny albo cofnięciu publikacji witryny, a złączenie po tabelach już
  publicznych jest darmowe przy rozmiarze strony listingu;
- **Miasto jako wolny tekst** — trzy zapisy jednego miasta to trzy adresy
  publiczne i trzy kubełki w filtrze;
- **Osobny silnik wyszukiwania** — drugi system i drugie źródło prawdy o
  zawartości katalogu, zanim pierwszy się zapełnił.
