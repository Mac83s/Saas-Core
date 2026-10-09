# ADR-077 — Strona treści produktu w kreatorze: droga wycofana; co po niej zostało

**Status:** Wycofany w części, która otwierała kreator stron dla publicznej strony
produktu — decyzja właściciela z 2026-10-08 (memex, projekt `puppily`:
`puppily-s-public-site-is-dedicated-coded-views-o`). **Pkt 2, 4, 6 i 9 obowiązują.**
Pkt 2 i 9 zostają na stałe z osobnej decyzji właściciela z tego samego dnia: własny
blog produktu jest pisany w systemie treści rdzenia, w workspace platformy,
a pokazują go kodowane widoki produktu. Numeracja punktów jest zachowana, bo kod
i inne dokumenty wskazują je po numerze.
**Data:** 2026-10-07; wycofanie 2026-10-08 (pakiet PC1 planu memex
`saas-core-wielojezycznosc-i-tlumaczenia-ai`).

**Nie zmienia:** ADR-048 — obowiązuje bez wyjątku: publiczna strona produktu to
dedykowane, kodowane widoki w aplikacji produktu, na hoście produktu; kreator stron
służy stronom klientów. Kontrakt modułów §6 (ADR-049) — bloki stron należą do rdzenia.
**Rozszerza (w części, która została):** ADR-035 §1–2 (workspace platformy jest
wydawcą, pkt 2), ADR-057 pkt 5 (menu panelu ma drugi skład — wydawcy, pkt 9),
ADR-071 „Świadome granice” (odnośnik do działu w treści, pkt 6), ADR-049
(przełącznik profilu `features.marketingSite`, pkt 4).

## Co było próbowane

ADR-048 rozstrzygnął, że strony marketingowe produktów to dedykowane trasy Next.js, a
kreator stron służy klientom. Puppily wyglądało na inny przypadek: nie strona
sprzedażowa, tylko serwis treści — 374 strony ras i 91 wpisów w pięciu językach — czyli
to, co kreator umie (podstrony, działy z wpisami, wersje językowe z własnymi adresami,
hreflang, sitemapa, tłumaczenia). Właściciel zdecydował 2026-10-07, na rekomendację
agenta, że pierwszy etap Puppily powstaje w kreatorze jako strona workspace'u platformy
(memex `puppily-s-first-stage-runs-on-the-site-builder-w`).

W dniach 07–08.10 siedem pakietów (PB3a–PB3e, PB1, PB2) dołożyło do rdzenia dwie grupy
zmian: takie, z których korzystają strony klientów, oraz punkty rozszerzenia istniejące
tylko po to, żeby produkt mógł zbudować kreatorem własną stronę — własne typy bloków
modułu, mapę starych adresów z odpowiedzią 410, podstronę w korzeniu działu źródła
rekordów i eksport serwisów stron dla komendy, która stawia witrynę z plików produktu.
Nic z tego nie zostało wypchnięte ani wdrożone.

## Dlaczego droga została wycofana

Po obejrzeniu wyniku na lokalnym stacku właściciel odrzucił ją 2026-10-08:

- strony produktu mają dedykowane, jednorazowe moduły (quiz doboru rasy), własny
  nagłówek i własną stopkę — to kod produktu, nie sekcje biblioteki;
- panel użytkownika produktu jest tym samym panelem rdzenia na tym samym hoście, co
  w HoofCare i MedPlano, a nie panelem na subdomenie obok strony z kreatora;
- przekierowania własnych podstron produktu nie należą do kreatora stron klientów:
  kreator ma być dla klientów dokładnie tym, czym był.

Widoki Puppily powstają od nowa jako kodowane strony w aplikacji produktu (ADR-048).
Z rdzenia wycięto to, co służyło wyłącznie odrzuconej drodze (pakiet PC1); zostało to,
z czego korzystają strony klientów, i to, o co właściciel prosił sam.

Tego samego dnia właściciel rozstrzygnął pytanie, które po wycofaniu zostało otwarte:
własna treść platformy — blog produktu — jest redagowana w systemie treści rdzenia,
w workspace platformy, a czytelnikowi pokazują ją kodowane widoki produktu. Dlatego
workspace platformy jako wydawca (pkt 2) i jego panel (pkt 9) zostają w rdzeniu na
stałe: to tam operator redaguje treść platformy. Rodzaje tej treści i sposób, w jaki
widoki produktu ją czytają, opisze osobny ADR o typach treści (w przygotowaniu
w innym pakiecie); będzie wskazywał pkt 2 i 9 tego dokumentu.

## Punkty decyzji i ich stan

### 1. Wyjątek od ADR-048 — wycofany

Nie ma wyjątku: produkt nie buduje swojej publicznej strony w `shared.sites`.

### 2. Workspace platformy jako wydawca — obowiązuje

W workspace platformy operator redaguje własną treść platformy (blog produktu); to,
co poniżej, daje mu do tego stronę, miejsce na pliki i domenę bez planu. Publiczną
stroną produktu ta treść nie jest — pokazują ją kodowane widoki produktu (pkt 1).

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

### 3. Strona na domenie produktu, panel na subdomenie platformy — wycofany

Układ zakładał stronę z kreatora na domenie produktu i panel na subdomenie
(`app.<domena>`). Odpadł razem z pkt 1: panel produktu stoi na hoście produktu, obok
jego kodowanych widoków. Kodu własnego ten punkt nie miał; opisane w nim zachowanie
domen własnych klientów (ADR-028) nie zmieniło się ani wtedy, ani teraz.

### 4. Host platformy bez marketingu: `features.marketingSite` — obowiązuje

Przełącznik nie zależy od tego, czym produkt zastępuje marketing rdzenia: wyłącza go
produkt, który przynosi własne publiczne strony.

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

### 5. Mapa starych adresów strony i odpowiedź 410 — wycofane, kod usunięty

Usunięte w PC1: model `SiteOldAddress` z migracją `sites` 0053 (nigdy niewypchniętą
i niewdrożoną — na lokalnym stacku cofniętą, zanim plik zniknął), moduł
`old_addresses.py`, komenda `load_old_addresses`, adres
`GET /api/v1/public/site/gone/`, strona `app/site-gone/` i pytanie proxy frontendu
przed każdą wizytą strony klienta. Proxy jest znów synchroniczne i nie pyta backendu
o nic przed przekazaniem wizyty rendererowi; nieistniejący adres strony klienta
odpowiada 404 jak przed 07.10. Przekierowania własnych adresów strony — `SiteRedirect`
po zmianie adresu podstrony i dawne nazwy działów (ADR-071) — nie były częścią mapy
i działają bez zmian.

Stare adresy serwisu, który produkt zastępuje, obsługuje kod produktu albo serwer
przed nim, nie kreator.

### 6. Odnośnik do działu w treści idzie za językiem czytelnika — obowiązuje

Domknięcie granicy zostawionej przez PB1 (ADR-071 pkt 14): odnośnik w treści strony albo w wyglądzie
(stopka) prowadzący do działu w języku strony (`/blog/`) w wersji językowej prowadzi
pod nazwę działu w języku czytelnika (`/en/journal/`), jeśli dział ma tam choć jeden
wpis na liście; inaczej zostaje, jak go napisano. Adres składa wyłącznie
`collection_index_path` (`section_link_targets`).

### 7. Czcionki z cyrylicą — stwierdzenie, bez kodu

Sprawdzone przy okazji i nadal prawdziwe: `packages/ui/src/styles/site-fonts.css` ma
dla Inter, Manrope, Nunito, Lora i Playfair Display osobny plik `cyrillic` pobierany
tylko przez stronę z cyrylicą; DM Sans cyrylicy nie ma i jego zestawy schodzą do
Inter; zestawy systemowe mają ją same.

### 8. Typy bloków produktu — wycofane, kod usunięty

Usunięte w PC1: manifest modułu w `packages/contracts/site-blocks/modules/`
i jego schemat, `defineModuleSiteBlocks`, slot `apps/frontend/src/product/site-blocks.ts`,
wspólny rejestr bloków deploymentu we frontendzie, czytanie manifestów modułów
w backendzie z kontrolami `sites.E011`–`E013`, `validate_built_site_block`, testowy
wertykał `vertical.sample` i kontrakt `docs/architecture/site-block-types.md`.
Zdanie kontraktu modułów (§6) obowiązuje znów w całości: szablony stron i bloki stron
należą do rdzenia, a produkt, który potrzebuje nowego bloku **dla stron klientów**,
dodaje go w Saas-Core. Rekordy modułu w blokach rdzenia i własne strony rekordów
na stronie klienta idą jak dotąd protokołem źródeł publicznych (ADR-074 pkt 7).

### 9. Panel workspace'u platformy jest panelem wydawcy — obowiązuje

Panel, w którym operator redaguje treść platformy (pkt 2). Dla firm nic się nie
zmieniło — patrz „Firmy” niżej.

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
`shared.translation`, `shared.model-port`. Moduły `core.*` i `vertical.*` zostają. Każdy
inny moduł wspólny — rezerwacje, asystent, obrazy AI — wymaga cechy planu, której ten
workspace nie ma i nie kupi, więc API i tak by odmówiło; nowy moduł wspólny nie jest
wydawcy oferowany, dopóki ktoś go do listy nie dopisze. Ponieważ zawężenie siedzi
w `panelAccess()`, idą za nim wszystkie bramki panelu, które pytają o moduł — menu,
zakładki, strony.

**Pytania w tle.** Ekran, który sam pyta API innego modułu — edytor strony i wpisu
o ofertę obrazów AI i o oferty pobytów — w workspace platformy nie pyta o moduł spoza
listy (`useAsksModule` w `components/panel/panel-access.tsx`; dostęp podaje układ
panelu przez `PanelAccessProvider`). W firmie pyta jak dotąd: tam odpowiada plan,
a ekran mówi, co odpowiedział.

**Menu** (`PUBLISHER` zamiast `WORK` i `COMPANY`) — od 2026-10-09 bez ekranów kreatora
stron (pakiet PW1, ADR-079 pkt 29: strona workspace'u nie odpowiada pod żadnym hostem):

| Grupa | Wpisy |
| --- | --- |
| Praca | Dziś · Treści platformy (Treści, Tłumaczenia, Integracje) · wpisy produktu |
| Firma | wpisy produktu · Ustawienia (Dane firmy, obszary rejestru, Języki, Historia zmian, Twoje konto, zakładki produktu) |
| Platforma | Ustawienia platformy — operatorowi, jak dotąd |

„Treści platformy” to wpis „Strona internetowa” firmy bez ekranów kreatora (znacznik
`builder` w `PANEL_SECTIONS.website`) i pod nazwą tego, co zostało. Stoi pod „Pracą”,
bo pisanie jest codzienną pracą wydawcy — dzięki temu trafia też na dolny pasek
telefonu, który bierze pierwsze trzy wpisy „Pracy”. Nie ma „Podstron” z ich edytorem
(a z nim wyglądu, szablonów i biblioteki sekcji), „Menu”, „Publikacji” witryny ani
„Adresu i domen”: niczego, co się tam ustawia, nikt by nie zobaczył. Nie ma
„Wiadomości”: zapytanie przychodzi z formularza na podstronie kreatora, a żaden host
tej strony nie serwuje. Nie ma Zespołu ani „Mojej karty” (nikt nie jest tu zapraszany;
redaktor to operator dopisany komendą, pkt 2), Abonamentu i Kredytów (tłumaczenia tego
workspace'u idą z budżetu platformy), Kalendarza, Magazynu, Zamówień, Asystenta,
Wizytówki, „Widoczności w Google”, powiadomień automatycznych, „API i webhooków”,
banera planu ani listy „Na start”.

**Pierwszy ekran.** „Dziś” pokazuje, co platforma napisała
(`components/panel/site-state.tsx`): typy treści, liczbę wpisów i ile z nich jest
opublikowanych, języki — oraz zdanie o tym, gdzie opublikowane wpisy widać (host
produktu, jeśli produkt ma własne strony). Ani słowa o podstronach, publikacji witryny
i domenach. Pod nim skróty: „Treści”, „Tłumaczenia” i „Języki” (ustawienie workspace'u,
nie ekran strony). Czyta to, co czyta „Treści” — nic, czego wydawcy się odmawia. Pulpit
produktu (slot `product/dashboard.tsx`) ma pierwszeństwo tak jak w firmie.

**Pierwsze wejście.** Treść wisi na rekordzie strony (jeden na workspace, `sites.max`),
więc zanim powstanie pierwszy typ, wydawca go zakłada — ale nie kreatorem firmy, który
pyta o subdomenę i nazwę. Ekran „Treści” pyta tylko o język, w którym platforma pisze
(`publisher-start.tsx`): to jedyna rzecz z tego rekordu, od której treść zależy, i nie
da się jej potem zmienić. Adres na platformie rekord dostaje od API sam; nikt go nie
zobaczy.

**Ustawienia.** Rejestr ustawień (ADR-078) wymienia też grupy modułów spoza listy;
`panelSettings()` zostawia wydawcy grupy jego modułów i obszary, w których coś zostało
— w menu „Ustawień”, na stronie obszaru i w „Szukaj w ustawieniach”. Z grup modułu
stron odpadają dwie o formularzu kontaktowym kreatora: „Odbiorcy zapytań”
(`sites.inquiries`) i czas przechowywania zapytań (`sites.retention`).

**Adres wpisany ręcznie.** Ekran firmy, którego nie zamyka bramka modułu — Zespół,
Kalendarz, Plan i płatności, Kredyty — odpowiada w workspace platformy „Nie ma takiej
strony” (`lib/company-only.ts`), zamiast pokazać ekran, którego każde zapytanie
kończy się odmową. Tak samo odpowiadają ekrany kreatora: `/panel/sites` („Podstrony”),
`/panel/sites/pages/<id>`, `/panel/sites/menu`, `/panel/sites/publication`,
`/panel/sites/address` oraz `/panel/notifications` — choć ich API zostaje otwarte
(ADR-079 pkt 29, akapit o API).

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

## Co jeszcze zostało z tych pakietów, a co z nimi odeszło

Zostało, bo służy stronom klientów albo właściciel prosił o to sam:

- nazwa działu w adresach per język i jej zmiana, także segment i slug per język dla
  źródeł rekordów (PB1, `sites` 0052; ADR-071 i ADR-074, uzupełnienia 2026-10-07);
- jedna reguła sluga podstrony we wszystkich językach: nazwa działu źródła rekordów
  jest zamknięta dla podstron w każdym języku (ADR-074 pkt 7);
- blok tabeli i konwerter HTML → bloki (PB2);
- pierwsza sekcja na pustej stronie rysowana od razu; nagłówek strony na indeksie
  działu; początek okruszków strony rekordu w języku czytelnika;
- brak rejestracji tam, gdzie żaden typ organizacji nie ma `selfSignup`; kontrola
  tekstów gości liczona ze składu profilu; testy rdzenia niezależne od składu;
- z `shared.sites.api`: `convert_html` oraz funkcje fragmentów tekstu
  (`extract_units`, `assemble`, `texts_against` z ich typami i odmowami) — moduł
  tłumaczy nimi rekord, którego treść jest listą bloków rdzenia.

Odeszło razem z pkt 1, 5 i 8:

- `PublicSource.root_page` — podstrona kreatora w korzeniu działu źródła rekordów,
  z okruszkami prowadzącymi przez nią i podpowiedzią w odmowie `slug_reserved`, która
  istniała tylko dla takiego źródła (ADR-074, „Korzeń działu” — wycofane);
- eksport z `shared.sites.api` serwisów, którymi kod produktu stawiał całą witrynę
  (wygląd, menu, działy, teksty witryny, treść wersji językowej, `set_page_type`,
  `delete_page` z ich odmowami) oraz `source_page_base`. Serwisy istnieją jak dotąd
  i woła je panel; nie są publicznym API modułu dla innych modułów.

## Granice i dług

Dotyczą punktów, które stoją (2, 4, 9):

- **Słowa firmy w panelu wydawcy.** Grupa menu nazywa się „Firma”, a strona danych
  „Dane firmy”, także w workspace platformy; nakładka słów zależna od rodzaju
  workspace'u (jak `organization-messages.ts` dla typu) nie istnieje.
- **Lista modułów wydawcy jest listą rdzenia.** Produkt jej nie rozszerza; gdyby
  wydawca jakiegoś produktu potrzebował modułu wspólnego spoza listy, trzeba go
  dopisać w rdzeniu i nadać workspace'owi właściwy entitlement.
- **„Twoje konto” nadal pozwala założyć firmę.** To operacja konta, nie workspace'u:
  operator może mieć własną firmę obok workspace'u platformy.
- **`robots.txt` hosta platformy** przy wyłączonym marketingu zostaje, jaki był:
  wskazuje (pustą) sitemapę i nie zamyka hosta przed robotami.
- **Treść platformy nie ma jeszcze opisanych typów.** Pkt 2 i 9 dają workspace
  i panel; czym jest wpis bloga produktu i jak czytają go widoki produktu,
  rozstrzyga ADR o typach treści, a nie ten dokument.

## Odrzucone (dla pkt 9)

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

Alternatywy rozważane dla punktów wycofanych (mapa adresów, 410, typy bloków modułu)
zostały w historii repozytorium razem z ich kodem (commity z 2026-10-07).

## Relacje

ADR-048 (obowiązuje bez wyjątku), ADR-035 (workspace platformy, operacje tylko dla
człowieka), ADR-028 (routing hostów i domeny — bez zmian), ADR-049 (profil produktu,
punkty rozszerzenia), ADR-070 pkt 15 i ADR-071 pkt 9, 12, 14 z uzupełnieniem
2026-10-07 (adresy i odnośniki per język), ADR-074 uzupełnienie 2026-10-07 (kto składa
adres strony rekordu), ADR-057 (szablon strony i menu panelu), ADR-050 (typ
organizacji a rodzaj workspace'u), ADR-078 (rejestr ustawień).
