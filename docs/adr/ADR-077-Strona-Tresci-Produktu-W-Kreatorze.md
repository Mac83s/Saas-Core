# ADR-077 — Strona treści produktu w kreatorze: workspace platformy jako wydawca, mapa starych adresów, host produktu bez marketingu

**Status:** Accepted — decyzja właściciela z 2026-10-07 (memex, projekt `puppily`:
`puppily-s-first-stage-runs-on-the-site-builder-w`); rozstrzygnięcia techniczne
agenta w pakietach PB3b, PB3a (pkt 8) i PB3c (pkt 9) planu memex
`saas-core-wielojezycznosc-i-tlumaczenia-ai`.
**Data:** 2026-10-07

**Zmienia:** ADR-048 pkt 1 i 4 — wyjątek opisany w pkt 1; dla produktów, które z niego
nie korzystają, ADR-048 obowiązuje bez zmian. Kontrakt modułów §6 (ADR-049): typy
bloków stron przestają należeć wyłącznie do rdzenia (pkt 8).
**Rozszerza:** ADR-035 §1–2 (workspace platformy znów jest wydawcą — tam, gdzie
profil tak stanowi), ADR-028 (publiczny routing: odpowiedź 410), ADR-071
„Uzupełnienie 2026-10-07” pkt 6 (jedno 308 obejmuje też mapę starych adresów) i jego
„Świadome granice” (odnośnik do działu w treści), ADR-057 pkt 5 (menu panelu ma drugi
skład — wydawcy, pkt 9).

## Kontekst

ADR-048 rozstrzygnął, że strony marketingowe produktów to dedykowane trasy Next.js, a
kreator stron służy klientom. Powodem były bloki projektowane pod stronę małej firmy
i workspace platformy, którego nigdy nie uruchomiono (`provision_platform_workspace`
nadawał `sites.enabled` bez `sites.max`, więc `create_site` kończył się
`QuotaUnavailable`).

Puppily jest innym przypadkiem: nie stroną sprzedażową produktu, tylko serwisem treści
— 374 strony ras i 91 wpisów w pięciu językach (pl, en, de, es, ru). To dokładnie to,
co kreator umie: podstrony, działy z wpisami, wersje językowe z własnymi adresami,
hreflang, sitemapa, kanały, tłumaczenia. Właściciel zdecydował 2026-10-07, że pierwszy
etap Puppily powstaje w kreatorze, bez próby, a ruch z wyszukiwarek jest na tyle mały,
że każdy stary adres może się zmienić, o ile przekierowuje. Stary serwis ma 2197
adresów; część funkcji (ogłoszenia, konta) znika.

## Decyzja

### 1. Wyjątek od ADR-048: serwis treści produktu może powstać w kreatorze

Produkt, którego publiczna strona jest serwisem treści, buduje ją w `shared.sites`
jako stronę **workspace'u platformy** swojego deploymentu. Strony sprzedażowe produktów
(Business, HoofCare, MedPlano) zostają przy ADR-048. Wyboru dokonuje profil
deploymentu (pkt 4), nie kod: rdzeń nie zna żadnego produktu z nazwy.

### 2. Workspace platformy jako wydawca

`provision_platform_workspace` nadaje teraz to, o co kod naprawdę pyta:

| Cel | Wartość | Kto pyta |
| --- | --- | --- |
| `sites.enabled`, `storage.enabled` | włączone | każda operacja stron i mediów |
| `custom_domain.enabled` | włączone | `create_custom_domain`, akcje domeny |
| `sites.max` | 1 | `create_site` (`consume_quota`) |
| `storage.bytes` | `--storage-gib`, domyślnie 20 GiB | każdy upload (`reserve_quota`) |

- Nadania idą tą samą audytowaną ścieżką co override operatora dla klienta
  (`create_entitlement_override`), a migawka uprawnień powstaje z samych nadań
  (`refresh_internal_snapshot`): bez planu, bez subskrypcji, bez checkoutu.
- `pages.max` i `public_locales.additional.max` nie są nadawane: limit podstron
  istnieje tylko tam, gdzie plan go nazywa, a workspace platformy jest zwolniony z
  limitu języków (ADR-071).
- Komenda jest bezpieczna do powtórzenia przez dowolnego operatora: cel, który ma
  aktywne nadanie, zostaje nietknięty — także gdy operator zmienił jego wartość — a
  raport mówi, co obowiązuje po uruchomieniu, czytając migawkę. `--storage-gib` działa
  więc tylko przy pierwszym nadaniu; późniejsza zmiana to cofnięcie nadania i ponowne
  uruchomienie komendy.
- Poprawka przy okazji: cofnięcie i wygaśnięcie override'u w workspace platformy
  przeliczało migawkę ścieżką planu, której ten workspace nie ma. Teraz wszystkie trzy
  ścieżki (nadanie, cofnięcie, wygaśnięcie) wybierają migawkę wewnętrzną.
- **Bez zmian zostają odmowy:** nikt nie jest zapraszany do workspace'u platformy,
  nie powstaje on z rejestracji ani z API tworzenia organizacji, nie kupuje planu
  (`_refuse_platform_workspace`), a wejście wymaga MFA operatora. Kolejny redaktor to
  kolejny operator dopisany tą samą komendą. Reguły klientów się nie zmieniają.

### 3. Domeny: strona na domenie produktu, panel na domenie platformy

Strona wydawcy odpowiada na **własnej domenie produktu** (`puppily.pl`), dopiętej do
strony jak domena własna klienta i ustawionej jako kanoniczna. `platformDomain`
deploymentu jest subdomeną (`app.puppily.pl`): tam odpowiadają panel, logowanie i
formularze gości, a subdomeny platformy stron (`<etykieta>.app.puppily.pl`)
przekierowują jednym 308 na domenę kanoniczną. Sprawdzone w kodzie:

- proxy frontendu traktuje jako host aplikacji wyłącznie `platformDomain` (i
  `FRONTEND_CONTROL_HOSTS`); każdy inny host idzie do renderera stron;
- `_validated_custom_hostname` odmawia tylko domeny platformy i jej subdomen, więc
  domena nadrzędna jest dozwolona; weryfikacja to rekord TXT, więc działa na apeksie;
- certyfikat wydaje Caddy na żądanie po zgodzie `authorize_tls_hostname`.

Układ odwrotny (strona na `platformDomain`, panel gdzie indziej) wymagałby wyjątku w
proxy i w bramce hostów API — odrzucony.

### 4. Host platformy bez marketingu: `features.marketingSite`

Profil deploymentu może wyłączyć strony marketingowe rdzenia i katalog firm na hoście
platformy: `"features": { "marketingSite": false }`. Brak klucza znaczy „włączone”,
więc Business, HoofCare i MedPlano nie zmieniają się.

Przy wyłączonym przełączniku na hoście platformy:

- `/` (także z prefiksem języka) odpowiada 307 do logowania — tymczasowo, bo profil
  może marketing przywrócić, a 308 zostałoby w przeglądarkach;
- adresy marketingu i katalogu (`/pricing`, `/contact`, `/katalog/…`, strony z treści
  produktu) odpowiadają 404, a `sitemap.xml` nie wymienia żadnego;
- bez zmian działają strony zespołu (`/login`, `/register`, `/panel`, `/settings`,
  `/invitations`, …) i strony gości firm (`/book`, `/booking`, `/documents`).

Rozstrzyga proxy (`apps/frontend/src/proxy.ts`); układ grupy `(marketing)` trzyma tę
samą linię dla żądania, które by je ominęło. Przełącznik żyje w jednym pliku
(`marketing/enabled.ts`), bo czyta go też proxy. Backend go nie potrzebuje.

### 5. Mapa starych adresów strony

Strona, która zastępuje inną, dostaje mapę jej adresów: `SiteOldAddress`
(`sites_siteoldaddress`, wymuszone RLS) — stary adres → nowy adres na tej stronie
(`moved`) albo „usunięty na stałe” (`gone`).

**Kto buduje adres.** Tylko strona. Reguła nazywa ścieżkę, nigdy host ani pełny URL,
a odpowiedź podaje adres, pod którym ta ścieżka odpowiada **dziś**: cel reguły jest
przy każdej wizycie pytany w resolverze (`resolve_public_page(old_addresses=False)`).
Stąd:

- **jedno 308, nigdy łańcuch** — podstrona przemianowana po wczytaniu mapy, dział pod
  nową nazwą, wyłączony język: stary adres prowadzi od razu pod adres końcowy (dla
  wersji językowej wstrzymanej — 307, jak wszędzie);
- reguła nie prowadzi do innej reguły: cel jest pytany bez mapy, więc pętla i łańcuch
  są niemożliwe z konstrukcji;
- **reguła jest przekierowaniem tylko tam, gdzie jej cel dziś odpowiada**; inaczej
  stary adres to 404 (ADR-071, uzupełnienie 2026-10-07, pkt 6).

**Żywy adres wygrywa.** Resolver pyta mapę na końcu — po podstronach, wpisach,
indeksach, archiwach, stronach rekordów, po `SiteRedirect` i po dawnych nazwach
działów. Reguła dla adresu, który odpowiada, czeka za nim i zaczyna działać, gdy on
zniknie.

**Jak porównywany jest stary adres** (`old_addresses.address_key`, tak samo dla
pliku i dla żądania):

| Co przychodzi | Jak jest dopasowane |
| --- | --- |
| brak albo obecność końcowego `/`, podwojone `/` | bez znaczenia |
| wielkie i małe litery (`/Rasy-Psow/`) | bez znaczenia — małe litery (`lower`, nie `casefold`: `straße` i `strasse` to dwa adresy); żywe adresy strony zostają wrażliwe na wielkość liter jak dotąd |
| cyrylica zakodowana procentami (`%D0%BF…`) albo wpisana wprost | ten sam adres: dekodowanie do skutku (do trzech razy), potem NFC |
| prefiks języka, którego strona już nie używa (`/pl/…`) | część adresu jak każdy inny segment: `/pl/kontakt` to osobna reguła i nie pasuje do `/kontakt` |
| query string i fragment | ucinane przy porównaniu; przy 308 query gościa jedzie dalej, jak przy każdym przekierowaniu renderera |
| pełny URL w pliku (`https://stary.example/…`) | brana jest jego ścieżka |

**410.** Adres `gone`, pod którym nic nie odpowiada, dostaje status 410 i małą stronę
w języku czytelnika: język to pierwszy segment adresu, jeśli jest językiem strony
dostępnym dziś, inaczej język strony; na stronie jest odnośnik do strony głównej tego
języka i `noindex`. Adresy z mapy nie są stronami, więc nie ma ich w sitemapie ani w
hreflang.

Strona Next.js umie odpowiedzieć 404, ale nie 410, dlatego 410 daje proxy: przed
przekazaniem wizyty rendererowi pyta backend (`GET /api/v1/public/site/gone/`) i dla
adresu usuniętego przepisuje żądanie na `app/site-gone/route.ts`. Żeby strony bez
mapy nie płaciły za funkcję, której nie używają, odpowiedź mówi też, czy strona ma
jakikolwiek adres `gone` (`rules`); host bez nich nie jest pytany ponownie przez
minutę. Gdy backend nie odpowie w 2 s albo host dopiero dostał pierwszą regułę,
strona mówi te same słowa ze statusem 404 — do następnego pytania.

**Wczytywanie.** `manage.py load_old_addresses --host <host> --csv <plik> --operator
<e-mail> [--dry-run] [--replace]`: plik `stary adres,nowy adres` albo `stary
adres,gone`. `--dry-run` niczego nie zapisuje i pokazuje to samo podsumowanie; bez
`--replace` plik dopisuje i poprawia, z nim jest całą mapą. Odrzucony wiersz (cel
poza stroną, cel ze znakami `?`/`#`, ten sam stary adres z dwoma celami, brak celu)
zatrzymuje cały zapis. Raport wymienia też wiersze prawdziwe, ale warte obejrzenia:
cel, który dziś nie odpowiada; stary adres, który odpowiada na stronie; cel, który
sam przekierowuje; adres z kropką (pkt „Granice”). Jeden wiersz historii na
wczytanie, z licznikami i skrótem pliku. Górna granica to 20 000 reguł na plik —
ochronna, nie planowa.

### 6. Odnośnik do działu w treści idzie za językiem czytelnika

Domknięcie granicy zostawionej przez PB1: odnośnik w treści strony albo w wyglądzie
(stopka) prowadzący do działu w języku strony (`/blog/`) w wersji językowej prowadzi
pod nazwę działu w języku czytelnika (`/en/journal/`), jeśli dział ma tam choć jeden
wpis na liście; inaczej zostaje, jak go napisano. Adres składa wyłącznie
`collection_index_path` (`section_link_targets`).

### 7. Czcionki z cyrylicą

Bez zmiany w kodzie — sprawdzone: `packages/ui/src/styles/site-fonts.css` ma dla
Inter, Manrope, Nunito, Lora i Playfair Display osobny plik `cyrillic` pobierany
tylko przez stronę z cyrylicą (`unicode-range` z U+0400–045F, czyli pełny rosyjski z
`Ё`); DM Sans cyrylicy nie ma i jego zestawy schodzą do Inter; zestawy systemowe mają
ją same. Strona 410 używa czcionki systemowej.

### 8. Typy bloków produktu

Moduł `shared` albo `vertical` — w praktyce wertykał produktu — wnosi własne typy
bloków stron z własnych plików. Rdzeń nie zna ich z nazwy i żaden plik rdzenia się przy
tym nie zmienia (ADR-049). Kontrakt wykonywalny: `docs/architecture/site-block-types.md`.

**Nazwa.** `<id modułu>.<nazwa>`, np. `vertical.puppily.breed_index`; myślnik w
identyfikatorze modułu zapisuje się podkreśleniem. `core.*` zostaje rdzenia.

**Gdzie typ istnieje.** Tam, gdzie profil składa moduł. Backend czyta
`packages/contracts/site-blocks/modules/<id modułu>/manifest.json` wyłącznie dla
modułów z `ACTIVE_MODULES`; frontend bierze zestawy ze slotu
`apps/frontend/src/product/site-blocks.ts` i pomija te, których modułu nie ma w
`deployment.modules`. W składzie bez modułu zapis z takim typem dostaje `400
unknown_site_block_type`, `capabilities` go nie wymienia, a studio i strona publiczna
nie mają go w rejestrze — także wtedy, gdy pliki modułu leżą w tym samym repozytorium.
Bramką jest skład deploymentu, nie typ organizacji ani plan: czy firma ma co pokazać,
mówi źródło modułu.

**Jedna deklaracja, dwie połowy.** Manifest w kontraktach (typy, wersje, `serverBuilt`,
wyjątki tłumaczeń, sekcje biblioteki) czytają obie strony. Kod — komponent, formularz
studia, migratory — dokłada frontend przez `defineModuleSiteBlocks`, które odmawia, gdy
manifest i kod się rozchodzą. Manifest zepsuty zatrzymuje `manage.py check`
(`sites.E011`–`E013`), nie stronę gościa.

**Dwa rodzaje bloków.** Stawiany przez osobę — formularz z pól katalogu, sekcja
w bibliotece po rodzinach rdzenia, a gdy pokazuje rekordy, `live` z odpowiedzią źródła
publicznego. Budowany przez moduł dla własnej strony rekordu — `serverBuilt`, jak
`core.document`: w żadnej bibliotece i w żadnym zapisie; moduł sprawdza jego kształt
sam (`validate_built_site_block`). Rekordy i strony rekordów idą protokołem źródeł
publicznych (ADR-074 pkt 7 z uzupełnieniem 2026-10-07).

**Tłumaczenia.** Reguła rdzenia bez zmian: wolny string schematu jest fragmentem do
tłumaczenia. Czego schemat nie wyrazi — nazwa własna kopiowana do każdego języka, dana,
tekst o prawdziwych osobach — moduł podaje w manifeście (`translation`); tabela
wyjątków w `shared/sites/localized_bodies.py` zostaje tabelą rdzenia. Słowa bloku
budowanego przez moduł są słowami rekordu i tłumaczy je źródło tłumaczeń modułu.

**Wersje.** Jak w rdzeniu: linia od 1, schemat opublikowanej wersji się nie zmienia,
nowa wersja przychodzi z migratorem.

**Co to zmienia.** Zdanie kontraktu modułów (§6) „bloki stron należą do rdzenia”
przestaje dotyczyć typów bloków. Do rdzenia nadal należą szablony całych stron,
konwersje między typami sekcji i rodzaje pól formularza studia. Kontrakt
z SeoContentRank (ADR-035, ADR-046) zostaje, jaki był: blueprinty stron używają typów
rdzenia, a automatyzacja zmienia teksty bloku modułu tak jak każdego innego.

Dowód: testowy wertykał `vertical.sample`, którego nie składa żaden profil — blok
stawiany w dwóch wersjach i blok strony rekordu, zapisane, przetłumaczone jako
fragmenty, opublikowane, narysowane w studiu i na stronie, nieobecne w składzie bez
modułu (`apps/backend/tests/test_sites_module_blocks.py`,
`apps/frontend/src/modules/shared/sites/module-blocks*.test.tsx`).

### 9. Panel workspace'u platformy jest panelem wydawcy

Workspace platformy dostawał panel zwykłej firmy: baner „Nie wybrano planu”, listę „Na
start” z krokami nie do wykonania, kalendarz, magazyn i abonament w menu oraz ekrany,
które w tle pytały o rezerwacje i dostawały 403. Od PB3c powłoka panelu zna rodzaj
workspace'u.

**Po czym poznaje.** Po `workspace_kind === "platform"` z `OrganizationSummary` (pole
już jest w API), nie po typie organizacji: workspace platformy nosi domyślny typ
deploymentu jak każda firma. `panelAccess()` zwraca wtedy `publisher: true`. Backend się
nie zmienia — odmowy z pkt 2 zostają, jakie były; panel tylko przestaje do nich
prowadzić.

**Co oferuje.** Z modułów `shared.*` — wyłącznie listę `PUBLISHER_MODULES`
(`apps/frontend/src/lib/panel-navigation.ts`): `shared.sites`, `shared.media`,
`shared.translation`, `shared.model-port`, `shared.image-generation`. Moduły `core.*`
i `vertical.*` zostają. Każdy inny moduł wspólny wymaga planu, którego ten workspace nie
kupi, więc API i tak by odmówiło; nowy moduł wspólny nie jest wydawcy oferowany, dopóki
ktoś go do listy nie dopisze. Ponieważ zawężenie siedzi w `panelAccess()`, idą za nim
wszystkie bramki panelu, które pytają o moduł — menu, zakładki, strony.

**Menu** (`PUBLISHER` zamiast `WORK` i `COMPANY`):

| Grupa | Wpisy |
| --- | --- |
| Praca | Dziś · Strona internetowa (Podstrony, Menu, Blog, Tłumaczenia, Publikacja, Adres i domeny, Integracje) · wpisy produktu |
| Firma | Wiadomości (same „Zapytania ze strony”) · wpisy produktu · Ustawienia (Dane firmy, obszary rejestru, Języki, Historia zmian, Twoje konto, zakładki produktu) |
| Platforma | Ustawienia platformy — operatorowi, jak dotąd |

Strona stoi pod „Pracą”, bo jest codzienną pracą wydawcy — dzięki temu trafia też na
dolny pasek telefonu, który bierze pierwsze trzy wpisy „Pracy”. Nie ma Zespołu ani
„Mojej karty” (nikt nie jest tu zapraszany; redaktor to operator dopisany komendą, pkt
2), Abonamentu i Kredytów (tłumaczenia tego workspace'u idą z budżetu platformy),
Kalendarza, Magazynu, Zamówień, Asystenta, Wizytówki, „Widoczności w Google”, powiadomień
automatycznych, „API i webhooków”, banera planu ani listy „Na start”.

**Pierwszy ekran.** „Dziś” pokazuje stan strony (`components/panel/site-state.tsx`):
nazwę, adres, stan słowami „Podstron” („Jeszcze nieopublikowana”, „Zmiany
nieopublikowane”, „Opublikowana”), ostatnią publikację, liczbę podstron i ile z nich
czeka, blog, języki oraz własną domenę, która nie przeszła jeszcze weryfikacji. Pod nim
skróty do części strony pod nazwami z menu. Czyta te same adresy API co „Podstrony” —
żadnego, którego wydawcy się odmawia. Pulpit produktu (slot `product/dashboard.tsx`) ma
pierwszeństwo tak jak w firmie.

**Ustawienia.** Rejestr ustawień (ADR-078) wymienia też grupy modułów spoza listy;
`panelSettings()` zostawia wydawcy grupy jego modułów i obszary, w których coś zostało
— w menu „Ustawień”, na stronie obszaru i w „Szukaj w ustawieniach”.

**Adres wpisany ręcznie.** Ekran firmy, którego nie zamyka bramka modułu — Zespół,
Kalendarz, Plan i płatności, Kredyty — odpowiada w workspace platformy „Nie ma takiej
strony” (`lib/company-only.ts`), zamiast pokazać ekran, którego każde zapytanie
kończy się odmową.

**Produkt.** Wpisy menu, zakładki ustawień i pulpit produktu działają u wydawcy jak
w firmie: moduł, uprawnienie, typ organizacji. Wydawcy pokaże się wpis stojący za
modułem `vertical.*` (albo modułem z listy); wpis produktu za innym modułem wspólnym
zostaje przy firmach.

**Firmy.** Nic się nie zmienia: `panelAccess()` organizacji o rodzaju innym niż
`platform` jest tym samym obiektem co dotąd. Pilnują tego
`lib/panel-navigation.companies.test.ts` (bez atrap — typy i menu bierze z profilu
i slotu produktu, więc po `core:update` sprawdza to samo w składzie produktu),
`lib/panel-navigation.publisher.test.ts` (menu firmy w składzie o dwóch typach
z modułem produktu, zgodne z kodem sprzed zmiany) i
`app/[locale]/panel/page.test.tsx` (ekran „Dziś” firmy).

## Granice i dług

- **Słowa firmy w panelu wydawcy.** Grupa menu nazywa się „Firma”, a strona danych
  „Dane firmy”, także w workspace platformy; nakładka słów zależna od rodzaju
  workspace'u (jak `organization-messages.ts` dla typu) nie istnieje.
- **Lista modułów wydawcy jest listą rdzenia.** Produkt jej nie rozszerza; gdyby
  wydawca jakiegoś produktu potrzebował modułu wspólnego spoza listy, trzeba go
  dopisać w rdzeniu i nadać workspace'owi właściwy entitlement.
- **„Twoje konto” nadal pozwala założyć firmę.** To operacja konta, nie workspace'u:
  operator może mieć własną firmę obok workspace'u platformy.
- **Adres z kropką nie dociera do strony.** Proxy przepuszcza pliki statyczne bez
  rozstrzygania (`matcher`), więc stary adres typu `/strona.html` nie dostanie ani
  308, ani 410. Wczytanie go wypisuje; zmiana matchera to osobna decyzja.
- **Mapa nie ma ekranu ani polecenia asystenta.** To narzędzie operatora na czas
  przenosin; logika jest w `old_addresses.py` (`read_rows`, `check_against_site`,
  `apply_rows`), więc drzwi w API są do dopisania, gdy mapy zechce klient.
- **Mapa należy do strony, nie do domeny.** Zmiana domeny kanonicznej jej nie rusza;
  całą mapę usuwa `--replace` z pustym plikiem.
- **`robots.txt` hosta platformy** przy wyłączonym marketingu zostaje, jaki był:
  wskazuje (pustą) sitemapę i nie zamyka hosta przed robotami.
- **Formularz bloku modułu składa się z rodzajów pól rdzenia.** Własnej kontrolki —
  wyboru jednego rekordu modułu — moduł nie wniesie; nowy rodzaj pola dodaje rdzeń.
- **Bramką typów bloków jest skład deploymentu.** W deploymencie z kilkoma typami
  organizacji biblioteka pokaże sekcje modułu także firmie, której typ tego modułu nie
  ma; jej strona nic nie narysuje, bo źródło modułu nie odpowie.
- **Blok budowany przez moduł nie jest walidowany przy odczycie strony.** Strona podaje
  go rendererowi tak, jak go dostała; kształtu pilnują testy modułu.
- **Sekcje modułu w bibliotece** nie mają zdjęć przykładowych ani filtra branży,
  a styl bloku to klasy Tailwind w komponencie — import własnego pliku CSS nie jest
  objęty testami rdzenia.

## Odrzucone

- **Wydawca jako osobny typ organizacji.** Typ wybiera profil produktu i idą za nim
  plany, role i rejestracja; workspace platformy jest bytem operatora, a rodzaj
  workspace'u już go nazywa — w modelu, w odmowach i w API.
- **Menu wydawcy liczone z migawki entitlementów.** Firmie brak cechy planu panel
  pokazuje jako zaproszenie do zmiany planu (`PlanGate`); wydawcy nie ma czego kupić,
  więc i tak trzeba by znać rodzaj workspace'u, a każdy ekran płaciłby dodatkowym
  zapytaniem.
- **Wycinanie grup ustawień w API schematu.** Byłaby to zmiana zachowania backendu
  dla jednego ekranu; reguła „co panel oferuje” zostaje w panelu, obok menu.
- **Przekierowanie `/panel` → `/panel/sites`.** Pierwszy ekran ma powiedzieć, gdzie
  jest strona i w jakim jest stanie; „Podstrony” mówią o podstronach.
- **Mapa w `SiteRedirect`.** Tamte wiersze wchodzą do migawki publikacji i każda
  publikacja niosłaby kilka tysięcy reguł w JSON-ie czytanym przy każdej wizycie;
  nie mają też wyniku „usunięty”.
- **Cel reguły zapisany jako adres końcowy i przepisywany przy każdej zmianie
  adresu.** Wymaga, żeby każda operacja zmieniająca adres znała mapę; pytanie
  resolvera przy wizycie daje to samo bez tej zależności.
- **410 jako strona 404 z innym tekstem.** Wyszukiwarka traktuje 404 jako „może
  wróci”; przy przenosinach chodzi o to, żeby adres zniknął z indeksu.
- **Pytanie backendu o 410 przy każdej wizycie każdej strony** — stąd `rules` i
  minuta ciszy; **lista adresów `gone` trzymana w proxy** — dublowałaby w TypeScripcie
  reguły porównywania adresów.
- **Przekierowanie do celu, który nie odpowiada** — 308 prowadzące do 404 jest gorsze
  od 404.
- **Typy produktu dopisywane do manifestu rdzenia** (jak `core.stay_*`). Rdzeń znałby
  produkt z nazwy, a typ istniałby w każdym deploymencie.
- **Rejestracja typów bloków w `AppConfig.ready`.** Frontend i test kontraktów nie mają
  jak jej przeczytać, a schematy i tak muszą być plikami wspólnymi dla obu stron.
- **Pole z blokami w deskryptorze modułu.** Deskryptor opisuje skład (aplikacja,
  uprawnienia, cechy planu); bloki mają własny katalog kontraktów, własne wersje
  i własny test, a katalog nazwany identyfikatorem modułu wystarcza za powiązanie.
- **Wykrywanie zestawów frontendu po konwencji plików.** Zależy od bundlera (Turbopack
  i Vitest robią to inaczej); slot produktu jest wzorcem już sprawdzonym na pulpicie
  i kalendarzu.

## Relacje

ADR-048 (wyjątek), ADR-035 (workspace platformy, operacje tylko dla człowieka),
ADR-028 (routing hostów i domeny), ADR-039/041 (RLS nowej tabeli; renderer czyta ją
w tenancie nazwanym przez host), ADR-049 (profil produktu, punkty rozszerzenia),
ADR-070 pkt 15 i ADR-071 pkt 9, 12, 14 z uzupełnieniem 2026-10-07 (adresy i odnośniki
per język), ADR-074 uzupełnienie 2026-10-07 (kto składa adres strony rekordu; źródła
publiczne wypełniają bloki modułów), ADR-031 (kategorie sekcji i formularz studia),
ADR-070 (fragmenty tłumaczeń z danych bloków), ADR-057 (szablon strony i menu panelu),
ADR-050 (typ organizacji a rodzaj workspace'u), ADR-078 (rejestr ustawień).
