# ADR-080 — Publiczne strony produktu na jego hoście: jedna tabela adresów

**Status:** Accepted, 2026-10-08 (pakiet PR1; decyzja właściciela z 2026-10-08, memex
`puppily-s-public-site-is-dedicated-coded-views-o`: publiczna strona produktu to
dedykowane, kodowane widoki na hoście produktu, z tym samym panelem rdzenia).

**Uzupełnia:** ADR-048 (strony produktu to dedykowane trasy Next.js — tu: jak produkt
dostaje własną stronę główną, działy nazwane per język, stare adresy i sitemapę),
ADR-049 pkt 3 i 5 (slot frontendu dostaje cztery nowe pliki), ADR-077 pkt 4
(`features.marketingSite: false` jest warunkiem, pod którym strony produktu odpowiadają)
i pkt 5 (stare adresy serwisu, który produkt zastępuje, obsługuje kod produktu — tu jest
ten kod), ADR-071 pkt 13 (treść nie zależy od `Accept-Language` ani ciasteczka — także
na stronach produktu).
**Nie zmienia:** stron firm i ich renderera (ADR-028, ADR-071), kreatora stron, panelu,
stron marketingowych rdzenia ani zachowania Business, HoofCare i MedPlano.

Kontrakt dla produktów: [`docs/architecture/product-public-site.md`](../architecture/product-public-site.md).

## Kontekst

HoofCare i MedPlano mają stronę produktu złożoną ze stron marketingowych rdzenia
z własnymi słowami (`productCopy`). Produkt treściowy potrzebuje czegoś innego: kilkuset
kodowanych stron w pięciu językach, z własnym nagłówkiem i stopką, na hoście, na którym
stoi też panel. Przed tym pakietem produkt mógł dołożyć pliki tras, ale:

- `/` należało do strony marketingowej rdzenia albo — przy `marketingSite: false` —
  prowadziło do logowania, a każdy adres spoza panelu i stron gości odpowiadał gołym 404;
- jeden plik strony nie mógł odpowiadać pod `/rasy-psow/…`, `/en/dog-breeds/…`
  i `/de/hunderassen/…`;
- nie było gdzie zadeklarować starych adresów zastępowanego serwisu ani dołożyć linii
  do `sitemap.xml`;
- słowa slotu miały typ pl/en.

Wszystko to rozstrzyga `proxy.ts` — najwęższe miejsce aplikacji: przechodzi przez nie
każde żądanie każdego produktu i każdej strony firmy.

## Decyzja

1. **Jedna tabela adresów w slocie.** `apps/frontend/src/product/public-site.ts`
   deklaruje: plik strony → adres per język treści. Tabela jest kompilowana raz
   (`lib/product-site/table.ts`); proxy rozstrzyga wizytę przez `match()`, a link,
   `canonical`, `hreflang`, przełącznik języka i sitemapa są pisane przez `href()`
   i `versions()` tych samych skompilowanych wierszy. Nie ma drugiego miejsca, w którym
   adres dałoby się napisać inaczej, niż jest rozstrzygany; test obiegu (`href` →
   `match` dla każdej strony i języka) pilnuje tego w bramce.

2. **Rozstrzyga własny, mały kod w proxy; next-intl zostaje, jaki był.** Proxy
   przepisuje adres czytelnika na plik strony i samo ustawia nagłówek języka, który
   czyta next-intl. Lokalizowane ścieżki next-intl (`pathnames`) odrzucono: trafiłyby
   do wspólnego `routing`, czyli do `Link` i middleware wszystkich profili, a proxy
   i tak musiałoby samo wiedzieć, czy adres jest adresem produktu (własne 404, profil
   bez marketingu) — byłyby dwa silniki czytające jedną tabelę.

3. **Pliki stron leżą w `app/product-site/[locale]/`, pod własnym układem głównym
   produktu** (od uzupełnienia PR1b, niżej; pierwotnie pod `app/[locale]/product-site/`).
   Segment jest wewnętrzny: czytelnik go nie widzi, a zapytany wprost odpowiada 404.
   Obok `[locale]`, a nie pod nim, bo pod układem rdzenia każda strona dziedziczy
   dostawcę komunikatów, który oddaje przeglądarce cały katalog języka — 342 KB z 360 KB
   dokumentu strony — i produkt nie zdejmie tego nowymi plikami. Żeby własny układ
   główny nie znaczył powtarzania dokumentu przy każdym produkcie, rdzeń daje
   `SiteDocument` (`#components/site-document`): `<html lang dir>`, język żądania dla
   next-intl i dostawcę z samymi wymienionymi przestrzeniami nazw; arkusz stylów,
   czcionkę i skrypt trybu ciemnego układ produktu dobiera sam (kontrakt §4). Osobny
   folder, a nie grupa tras, bo dwie strony pod jednym adresem (`/` rdzenia i `/`
   produktu) to błąd budowania Next — przepisanie w proxy jest jedynym sposobem, żeby
   produkt miał własną stronę główną bez zmiany pliku rdzenia. Rdzeń nie umieszcza
   w tym folderze żadnego pliku (plik rdzenia zmieniony przez produkt łamie
   `core:check`). Dopasowanie proxy obejmuje ten folder w całości, także adresy
   z kropką, które inaczej omijają proxy: gdy tabela jest zadeklarowana, każdy adres
   pod nim — w każdej pisowni, którą router odczytałby jako jego nazwę — odpowiada 404;
   gdy nie jest, taki adres idzie dalej nietknięty, jak dotąd.

4. **Strony produktu odpowiadają tylko tam, gdzie profil wyłącza marketing rdzenia**
   (`features.marketingSite: false`) i tylko na hoście platformy. W profilu
   z marketingiem rdzenia zadeklarowana tabela jest nieczynna (folder plików stron
   odpowiada tam 404 — pliki są w buildzie niezależnie od profilu). Dzięki temu produkt,
   który tabeli nie ma, i profil, który marketingu nie wyłącza, są chronione dwa razy,
   a repozytorium produktu może trzymać obok siebie profile wzorcowe rdzenia.

5. **Jeden adres, jedna odpowiedź.** Adres tabeli odpowiada tylko w dokładnej pisowni
   (małe litery `a–z`, cyfry, łączniki; bez kodowania procentowego). Prefiks języka
   domyślnego to jedno 308. Nazwa działu z innego języka, inna wielkość liter i każdy
   adres spoza tabeli to 404 — własna strona 404 produktu, w języku z prefiksu adresu —
   a nie domyślne przekierowanie: przekierowania są wyłącznie tam, gdzie produkt je
   zadeklarował.

6. **Stare adresy: `product/old-addresses.ts`, sprawdzane przed wszystkim innym na
   hoście platformy.** `moved` → jedno 308 prosto do adresu tabeli; `gone` → 410 z małą
   stroną rdzenia w języku starego adresu. Sprawdzenie stoi w proxy **po** oddaniu
   strony firmy rendererowi (więc strony firmy nie dotyka z konstrukcji, nie z warunku)
   i **przed** regułą końcowego ukośnika i obsługą języka (więc stara pisownia nie
   kosztuje drugiego przekierowania). Porównanie — jedna funkcja dla reguły i wizyty:
   puste segmenty odpadają, dekodowanie procentowe, Unicode NFC, małe litery;
   zapytanie przechodzi na cel.

7. **Łańcuch i pętla są odmową przy kompilacji.** Cel reguły musi być adresem tabeli
   w pisowni kanonicznej (czyli odpowiada stroną, nie przekierowaniem) i nie może sam
   być źródłem reguły. Źródło nie może przykrywać strony bez parametru ani strony
   głównej — w żadnym języku tabeli i także w pisowni z prefiksem języka domyślnego —
   panelu, stron gości, `/media`, `/api` ani mieć kropki (taki adres nie trafia do
   proxy). Reguła na adresie strony z parametrem jest dozwolona — to wpis o zmienionej
   nazwie. Reguły są sprawdzane względem wszystkich języków, które tabela wymienia,
   więc lista jest poprawna albo błędna niezależnie od profilu; profil pomija tylko
   reguły prowadzące do języka, którego nie oferuje.

8. **Kto odrzuca złą tabelę: test w bramce produktu, `/healthz` przy wdrożeniu
   i kontrola na zbudowanym stacku — nie `next build` i nie czytelnik.**
   `lib/product-site/slot.test.ts` kompiluje tabelę i reguły z bieżącego repozytorium
   i przepuszcza każdą regułę przez prawdziwe proxy (jedno 308 pod adres, który proxy
   oddaje plikowi strony). W działającej aplikacji tabela, której nie da się obsłużyć,
   wyłącza publiczne strony produktu i zostawia panel — moduł proxy nie może paść przy
   imporcie, bo padłoby każde żądanie — ale `/healthz` odpowiada wtedy 503, więc
   wdrożenie, które czeka na `/healthz`, nie przechodzi po cichu (tak samo jak przy
   niezgodności profili obrazów). Czy pod celem reguły jest istniejąca strona, wie
   dopiero zbudowana aplikacja: `product-site:check` idzie po każdej regule na
   działającym stacku i wymaga 200 pod celem; to część odbioru produktu.

9. **Sitemapa: produkt wymienia strony, rdzeń pisze adresy.**
   `product/site-sitemap.ts` zwraca klucze tabeli z parametrami (także per język, gdy
   nazwa wpisu jest tłumaczona); rdzeń pisze linie z `hreflang` i pomija adres, na
   który odpowiada reguła starych adresów. Ten sam filtr stoi za `hreflang` w nagłówku
   strony i za przełącznikiem języka (`siteVersions`), więc nagłówek, przełącznik
   i sitemapa wymieniają te same adresy. `robots.txt` się nie zmienia.

10. **Słowa: `product/site-messages.ts`, per język treści, czytane tylko na serwerze.**
    Osobny plik, a nie poszerzone `messages` w `product/index.ts`, bo `product`
    importuje menu panelu w przeglądarce — pięć języków słów serwisu trafiłoby do
    paczki panelu (ten sam powód co `organization-messages.ts`).

11. **Czcionka z cyrylicą należy do układu produktu** (`next/font` z podzbiorem
    `cyrillic`, zmienna w `className` dokumentu). Czcionka panelu się nie zmienia: dołożenie podzbioru
    w układzie rdzenia wstępnie ładowałoby go na każdej stronie każdego produktu.

12. **Segmenty zarezerwowane są jedną listą** (`proxy-segments.ts`), z której czyta
    proxy i kompilacja tabeli: strony zespołu i gości, `media` (opublikowane media
    treści platformy, ADR-079), `internal`, `static`, `site-renderer`, `product-site`
    oraz wszystko, co zaczyna się od `api`, `healthz`, `_next`, `_vercel`.

## Dowód, że istniejące profile się nie zmieniły

`proxy.golden.json` i `metadata.golden.json` zapisano z kodu sprzed zmiany (pierwszy
commit pakietu): odpowiedzi proxy dla 75 adresów hosta platformy i 17 adresów strony
firmy, trzech rodzajów gościa, na czterech kształtach profilu (pl-en; pl-en-de; pl-en
bez rezerwacji; pięć języków bez marketingu), przez prawdziwe middleware next-intl,
oraz sitemapa i robots tych profili. Pliki nie zmieniły się w kolejnych commitach,
a testy porównują z nimi każde uruchomienie. Dodatkowo: tabela czynna zmienia wyłącznie
adresy, które wcześniej odpowiadały 404 albo prowadziły do logowania; tabela
zadeklarowana w profilu z marketingiem rdzenia nie zmienia żadnej odpowiedzi; adresy
strony firmy odpowiadają identycznie także wtedy, gdy są regułą albo stroną produktu.

## Sprawdzone na zbudowanej aplikacji

Testy jednostkowe widzą tylko odpowiedź proxy, nie to, co Next z nią zrobi. Dlatego
2026-10-08 gałąź została zbudowana (`next build`) z jednorazowym, niezacommitowanym
produktem — tabela z działem w trzech językach, 3007 reguł starych adresów, strony
serwerowe i klienckie, własny układ z czcionką z cyrylicą, profil z pięcioma językami
bez marketingu rdzenia — i uruchomiona tak jak w obrazie (serwer `standalone`):

- strona główna i strony działu odpowiadają 200 w języku adresu (`<html lang>`, słowa,
  tytuł z `generateMetadata` bez `setRequestLocale`), także gdy gość przysyła własny
  nagłówek języka i ciasteczko; brak słowa po niemiecku i hiszpańsku daje angielskie;
- `canonical`, `hreflang` i `sitemap.xml` niosą adresy z tabeli, z własną nazwą wpisu
  w każdym języku; wpis objęty regułą nie jest w sitemapie;
- stary adres w każdej pisowni to jedno 308 i strona 200; `gone` to 410 z małą stroną
  w języku adresu; nazwa działu z innego języka i adres spoza tabeli to 404 z nagłówkiem
  i stopką produktu, w języku z prefiksu;
- w prawdziwej przeglądarce: przejścia między stronami produktu są przejściami po
  stronie klienta (bez żądania dokumentu), strona kliencka się hydratyzuje, plik
  czcionki z cyrylicą ładuje się dla rosyjskich słów.

W tym samym składzie (pełny slot, pięć języków, marketing rdzenia wyłączony) przeszedł
cały zestaw vitest frontendu poza kontrolą tekstów gości dla jednorazowego profilu
(es/ru z rezerwacjami — istniejący wymóg ADR-071 pkt 19, nie tego pakietu), `tsc`
i lint plików produktu pisanych według kontraktu.

Strony zespołu i gości nie były częścią tego przebiegu (wymagają backendu): ich
odpowiedzi proxy pilnują pliki `*.golden.json`. Skrypty przebiegu:
`~/DEVELOPMENT/.local-dev/resume/package-pr1/`. Uwaga dla powtarzających: serwer
`standalone` uruchomiony z `HOSTNAME=127.0.0.1` wykonuje każde przepisanie proxy jako
zewnętrzne (drugie przejście przez proxy) — także przepisania next-intl; lokalnie
`HOSTNAME=localhost`, w obrazie `0.0.0.0`, jak dotąd.

## Uzupełnienie po przeglądzie (2026-10-08)

Gałąź przeszła przegląd tylko do odczytu; werdykt: nadaje się do scalenia, nic nie
zmienia adresów Business, HoofCare ani MedPlano. Siedem uwag weszło przed scaleniem
(pkt 3, 7, 8 i 9 powyżej oraz „Granice” są już w ich brzmieniu):

1. złą tabelę albo listę reguł zgłasza `/healthz` (503), nie tylko log;
2. reguły są sprawdzane względem wszystkich języków tabeli, a profil pomija tylko te,
   które prowadzą do języka, którego nie oferuje — wcześniej reguła pod `/de/…`
   w profilu bez niemieckiego wyłączała całą listę;
3. „cel jest stroną” nie wynikało z testu (przepisanie w proxy to zawsze 200):
   doszła kontrola `product-site:check` na zbudowanym stacku, część odbioru produktu;
4. `hreflang`, przełącznik języka i sitemapa czytają jeden filtr reguł;
5. folder plików stron jest w dopasowaniu proxy razem z adresami z kropką i odpowiada
   404 w każdej pisowni; bez zadeklarowanej tabeli taki adres idzie nietknięty;
6. adres tabeli z prefiksem języka domyślnego i końcowym ukośnikiem to jedno 308;
7. źródło reguły na stronie bez parametru jest odmową także w pisowni z prefiksem
   języka domyślnego (`gone` pod `/pl/quiz` odpowiadało 410 zamiast 308 do `/quiz`).

Drugi przebieg na zbudowanej aplikacji (ten sam jednorazowy produkt, 3011 reguł, jedna
celowo z literówką w celu) potwierdził 5 i 6 statusami, a `product-site:check` wskazał
dokładnie tę jedną regułę (308, potem 404 strony); reszta: 308 i 200 pod celem.
Pliki `proxy.golden.json` i `metadata.golden.json` pozostały bez zmian.

## Uzupełnienie 2026-10-08 (PR1b): folder stron pod własnym układem głównym

Rozstrzygnięcie pytania, które PR1 zostawił otwarte po pomiarze z przeglądu (uwaga 8;
wariant „własny układ główny folderu stron”): zanim pierwszy produkt przeniesie strony,
folder jego stron wychodzi spod układu rdzenia. Serwis treści
z kilkuset stronami w pięciu językach nie może nieść na każdej z nich katalogu panelu.

- Proxy oddaje stronę produktu plikowi pod `app/product-site/[locale]/…` (wcześniej
  `app/[locale]/product-site/…`); folder jest odmową po pierwszym segmencie, wpis
  dopasowania pod prefiksem języka znika, bo tam folderu już nie ma.
- `SiteDocument` daje to, czego strona nadal potrzebuje od rdzenia: `<html lang dir>`,
  język żądania i dostawcę z samymi wymienionymi przestrzeniami nazw. Komponenty
  serwerowe czytają dalej każdą przestrzeń nazw języka, także teksty gości rdzenia.
- Ta sama strona jednorazowego produktu, zbudowana aplikacja, przed i po:
  `/en` 359 805 B → 13 178 B (gzip 100 135 B → 3 019 B);
  `/en/dog-breeds/german-shepherd` 359 768 B → 13 362 B (gzip 101 150 B → 3 906 B);
  `/ru/quiz` (strona kliencka) 360 037 B → 10 876 B (gzip 101 558 B → 2 759 B).
  Komunikaty w dokumencie: 342 KB → najwyżej 2,5 KB.
- Ponowny przebieg na zbudowanej aplikacji: strony, 404 produktu, stare adresy, 410,
  przejścia po stronie klienta, hydratacja strony klienckiej, czcionka z cyrylicą
  i `product-site:check` — jak przed zmianą; folder odpowiada 404 w każdej pisowni.
- Dla wdrożenia bez tabeli nic się nie zmienia: `proxy.golden.json`
  i `metadata.golden.json` bez zmian, strony marketingowe rdzenia zachowują swój
  dokument (i jego wagę — „Granice”).
- Koszt: przejście między stronami produktu a panelem to pełne załadowanie dokumentu
  (dwa układy główne). Układ główny produktu woła `setRequestLocale` we własnym ciele
  — bez tego strony bez parametru przestają być statyczne (sprawdzone: `ƒ` zamiast
  `●`), bo `SiteDocument` jako komponent potomny ustawia język za późno; kontrakt §4
  ma tę linię w przykładzie.

## Uzupełnienie 2026-10-09 (PR1c): własny moduł produktu na hoście platformy — zdjęcia, workspace platformy, poprawki kontraktu

Pierwszy produkt na tym kontrakcie (strony informacyjne, potem kilkaset stron rekordów
własnego modułu w pięciu językach, każda ze zdjęciem) pokazał trzy rzeczy, których
rdzeń nie dawał. **Zmienia:** ADR-079 „Uzupełnienie CT3” pkt 10 (zdjęcia rekordów na
żywo odpowiadają na hoście platformy — pkt 1 niżej) i pkt 4 (lista wywołujących
odnalezienie workspace'u dostaje regułę dla modułów produktu — pkt 2). **Uzupełnia:**
ADR-079 pkt 31, ADR-041 (drzwi sprzed tenanta), ADR-049 (produkt nie edytuje pliku
rdzenia), ADR-074 pkt 7 (rejestr źródeł publicznych). Kontrakt: §13
[`product-public-site.md`](../architecture/product-public-site.md).

### 1. Zdjęcia rekordów modułu pod `/media/<id>/<wariant>` na hoście platformy

ADR-079 dał hostowi platformy `/media/<id>` dla zdjęć opublikowanych wpisów treści.
Rekord własnego modułu produktu (rasa) nie jest wpisem: nikt go nie „publikuje”
migawką, więc co z niego widać, wie tylko jego moduł. Strona firmy ma na to od
ADR-074 drugą regułę — źródło publiczne deklaruje zdjęcia, które gość ma prawo
zobaczyć (`served_media`), i host serwuje je **jako kopię, nigdy oryginał**. Host
platformy dostaje tę samą regułę dla źródeł workspace'u platformy
(`serve_content_media`):

- kopia (`thumbnail`, `preview`) odpowiada, gdy zdjęcie nazywa bieżąca publikacja
  wpisu **albo** zwraca je `served_media` któregoś źródła; oryginał — tylko na słowo
  wpisu, jak dotąd. Zdjęcie niezadeklarowane, cudze i nieistniejące dają to samo 404;
- **źródło jest pytane w tenancie workspace'u**: jego tabele mają wymuszone RLS jak
  media, więc pytanie stoi po `SET LOCAL`, w tej samej transakcji (wcześniej kontrola
  wpisu stała przed blokiem transakcji — tabele wpisów nie mają polityki). Zapytane
  przed ustawieniem tenanta, źródło pod rolą aplikacji nie widzi żadnego wiersza
  i każde takie zdjęcie odpowiadałoby 404, podczas gdy testy — właściciel tabel —
  byłyby zielone;
- kopia pyta najpierw źródła (jeden mały odczyt), dopiero potem przeszukuje migawki
  opublikowanych wpisów; oryginał źródeł nie pyta wcale.

**Rejestr nie dostaje tańszego pytania „czy ten jeden identyfikator”.** Zmierzone
2026-10-09 na stosie pierwszego produktu, pod rolą aplikacji (`saas_core_app`, bez
`BYPASSRLS`), z kodem tej gałęzi i źródłem zwracającym 374 identyfikatory: żądanie
miniatury 9,5 ms (mediana z 60 różnych zdjęć, p90 12,7 ms, razem z odczytem z magazynu
plików), z czego pytanie do źródła 0,9 ms; odmowa 5,3 ms. Samo zapytanie o 374 wiersze
to 0,13 ms w bazie, o jeden — 0,08 ms. Tańsze pytanie oszczędziłoby poniżej
milisekundy na żądaniu, które przeglądarka dzięki `immutable` zadaje raz. Liczba
zapytań jednego żądania nie zależy od wielkości odpowiedzi źródła (ma test); rośnie
o jedno z każdym zarejestrowanym źródłem, które serwuje zdjęcia.

### 2. Blok `in_platform_workspace()`: jedyna droga modułu produktu do workspace'u platformy bez hosta

**Dwie rzeczy naraz.** Lista wywołujących `platform_workspace*` (ADR-079, CT3 pkt 4)
istnieje po to, żeby nikt po cichu nie dołożył drugiego publicznego odczytu, który
wybiera tenanta bez hosta — to klasa wycieków rdzenia wielu firm. A produkt nie może
edytować pliku rdzenia (ADR-049), więc lista w teście rdzenia, do której trzeba by
dopisać jego moduły, zamieniłaby każdą aktualizację rdzenia w czerwoną bramkę albo
w edycję cudzego pliku.

**Decyzja.** Według tego ADR moduł wertykału produktu jest właścicielem publicznych
stron hosta platformy. To jedyne miejsce, w którym „workspace platformy, bez hosta”
jest odpowiedzią zaprojektowaną, a nie wyjątkiem. Dlatego:

1. Rdzeń daje **jeden blok**, `in_platform_workspace()` (w `core.organizations`,
   wystawiony przez `core.organizations.api`): pyta drzwi stałym zapytaniem
   `platform_workspace_id()` (rodzaj **i** nazwa wyliczona z wdrożenia, sama kolumna
   `id` — linia drzwi policzona już w `DECLARED_DOOR`, licznik się nie zmienia),
   otwiera transakcję, ustawia tenant workspace'u i oddaje jego identyfikator.
   Wdrożenie bez workspace'u mówi to wprost: `PlatformWorkspaceMissing` (503).
2. **Moduł wertykału (`modules/vertical/**`) woła blok bez deklaracji i nigdy nie
   nazywa odnalezienia.** Test `test_pre_tenant_door.py` pada dla modułu produktu,
   który nazywa `platform_workspace` albo `platform_workspace_id` — importem, atrybutem
   albo napisem — z komunikatem, który podaje import bloku i jego użycie.
3. **Moduł `core`, `shared` i każdy inny poza `modules/vertical/` potrzebuje wpisu
   w `DECLARED_WORKSPACE_LOOKUPS` z powodem — za blok tak samo jak za odnalezienie.**
   Rdzeń zostaje zamknięty: nowy odczyt bez hosta w rdzeniu to nadal zmiana, którą
   ktoś pisze celowo i ktoś inny widzi w przeglądzie. Pięć plików publicznego
   renderera nie może nazwać ani odnalezienia, ani bloku.
4. **Komendy operatora idą tą samą regułą — bez wyjątku po ścieżce.** Komenda otwiera
   blok, czyta w nim wiersz workspace'u i wychodzi; własne transakcje (jedna na
   rekord przy imporcie, przebieg próbny z wycofaniem) prowadzi dalej jak dotąd, każda
   ustawia tenant sama. Powody: (a) jedna reguła i jedna nazwa — wyjątek „plik pod
   `management/commands/`” dawałby miejsce, z którego widok może zaimportować funkcję
   z odnalezieniem; (b) blok pyta po nazwie wdrożenia, a `platform_workspace()` bierze
   pierwszy workspace rodzaju „platforma” w bazie — import operatora ma trafić do
   workspace'u *tego* wdrożenia; (c) wiersz organizacji wczytany w bloku pochodzi
   z połączenia aplikacji, pod polityką, a nie z połączenia drzwi.

**Co blok gwarantuje poza kolejnością** (każde ma test, `test_platform_workspace_block.py`):

- *Nie zostawia ustawienia po sobie.* `SET LOCAL` przeżywa zwolnienie punktu zapisu.
  Blok wywołany w czyjejś otwartej transakcji czyta ustawienie przy wejściu
  i przywraca je przy wyjściu; zakończony wyjątkiem jest wycofany do punktu zapisu
  razem z ustawieniem. Wywołany samodzielnie (widok, komenda) jest jedną transakcją
  i nie płaci tych dwóch zapytań. To pierwszy przełącznik tenanta oddany kodowi
  produktu do wołania skądkolwiek — pozostałe `set_local_organization_id` w rdzeniu
  stoją w miejscach, które rdzeń sam ułożył.
- *Zalogowany gość zostaje gościem.* Sesja panelu jedzie z każdym żądaniem tego
  samego originu, więc gość zalogowany do własnej firmy ma na publicznych stronach
  produktu jej `TenantContext`. W bloku kontekst cudzej firmy jest ukryty: serwis,
  który zapytałby „kto działa”, dostaje odmowę jak dla anonimowego, zamiast działać
  jako firma A przy bazie ustawionej na workspace. Odmowa wejścia do bloku przy
  aktywnym kontekście została odrzucona — formularz publiczny przestałby działać
  każdemu, kto jest zalogowany do panelu.
- *Identyfikator może wyjść z bloku.* Wartość nie jest tajemnicą ani uprawnieniem:
  każdy późniejszy odczyt i tak ustawia tenant sam, a tabele z RLS bez ustawienia nie
  oddają nic.

**Czego reguła nie obiecuje.** Test czyta drzewo źródeł, które produkt składa
(rdzeń + własne moduły), więc pilnuje produktu jego własną bramką — produkt, który
nie uruchamia testów rdzenia, nie jest pilnowany przez nic. Wykrywacz nie zobaczy
nazwy złożonej dopiero w czasie działania ani `ensure_platform_workspace()` użytego
jako odnalezienie (funkcja zakłada workspace, gdy go nie ma — w odczycie byłaby
widocznym błędem). Moduł wertykału może wołać blok także tam, gdzie żądanie ma już
swoją firmę; blok niczego wtedy nie wycieka (czyta workspace wydawcy, do którego
produkt i tak pisze), ale takie użycie jest decyzją produktu, nie tego ADR.

**Odrzucone:**

- *Lista w teście rdzenia z wpisami produktu* — edycja pliku rdzenia przy każdym
  module produktu (ADR-049) albo czerwona bramka po `core:update`.
- *Plik deklaracji po stronie produktu, czytany przez test rdzenia* — produkt sam
  wystawiałby sobie zgodę na odnalezienie; lista przestaje być czymś, co widzi
  przegląd rdzenia.
- *Wystawienie `platform_workspace_id()` modułom wertykału* — ustawienie tenanta
  zostałoby u wywołującego, czyli tam, gdzie się o nim zapomina.
- *Wyjątek dla komend po ścieżce pliku* — pkt 4a.
- *Odmowa w bloku przy aktywnym kontekście innej firmy* — wyżej.

### 3. Poprawki kontraktu po pierwszym produkcie

- `SiteDocument` oznacza `<html>` jako `suppressHydrationWarning`: skrypt trybu
  ciemnego zapisuje na nim atrybut przed hydratacją (jak dokument panelu).
- Skompilowana tabela dostaje `has(route, locale?)`, a strony — `siteHas(…)`: pytanie,
  które nie rzuca. `languages()` i pozostałe pytania o stronę, której tabela nie
  nazywa, rzucają jak dotąd — teraz jest to zapisane.
- **Nagłówek i stopkę renderuje strona, nie układ główny** (zmiana zdań i przykładu
  kontraktu w §1 i §4): przełącznik języka prowadzi do tej samej strony w innym
  języku, a jej klucz i parametry zna tylko strona. Układ główny to sam dokument.
- Strona 404 produktu: `not-found.tsx` nie dostaje parametrów; język adresu daje
  `getLocale()` (proxy ustawia go z prefiksu adresu także dla 404), otoczkę renderuje
  jak każda strona, przełącznik prowadzi do stron głównych.
- Logowanie i strony zespołu: zapisane, co odpowiadają w każdym języku (`/de/login` →
  308 do `/en/login`), że stare adresy logowania zastępowanego serwisu nie mogą być
  regułą ani celem reguły, i że odnośnik do logowania ze strony publicznej dostaje
  `prefetch={false}`.

### 4. Dowód i jego granice

Baza testowa łączy się właścicielem tabel i omija RLS. Testy trzymają więc to, co
widać mimo wszystko: `SET LOCAL` stoi przed pytaniem do źródła i przed każdym odczytem
bloku, w tej samej transakcji; ustawienie wraca po bloku; żadne zapytanie nie nazywa
innej firmy. **Że rola aplikacji widzi wiersze źródła i zdjęcia — i tylko w tym
ustawieniu — pokazuje stos.** Przed scaleniem kod tej gałęzi został uruchomiony
z modułem pierwszego produktu (tylko do odczytu, jednorazowy kontener na obrazie
stosu, baza stosu, rola `saas_core_app`): poza blokiem 0 ras i 0 zdjęć, w bloku 374
i 382; miniatura i podgląd zdjęcia rasy 200 `image/webp`, oryginał 404, osiem zdjęć
workspace'u, których żadna rasa nie pokazuje — 404, obcy identyfikator — 404, host
spoza platformy — 400. Skrypt: `~/DEVELOPMENT/.local-dev/resume/package-pr1c/`.

### 5. Lżejszy arkusz stylów — nie w tym pakiecie

Publiczna strona produktu importuje cały `@saas-core/ui/globals.css` (322 kB, 47 kB po
gzip, blokuje rysowanie), żeby dostać tokeny. Wejście „same tokeny i podstawa” nie
jest małe: tokeny (`:root`), `@theme inline` i `@layer base` są w `globals.css`
przeplecione ze stylami kreatora stron (ok. 190 kB źródeł `site-*.css`), a `@source`
skanuje całe `apps/**`, więc Tailwind emituje każdą klasę panelu. Potrzeba:
wydzielenia tokenów do wspólnego pliku (zmiana kolejności w arkuszu panelu — do
sprawdzenia na ekranach panelu i stronach firm; dwa testy czytają `globals.css`
wprost), wejścia z `@import "tailwindcss" source(none)` i `@source` ograniczonym do
plików stron produktu oraz komponentów, których używają, osobnego importu stylów
treści dla `SiteEntryBody`, i pomiaru na zbudowanej aplikacji. Osobny pakiet.

## Konsekwencje

- Slot frontendu ma cztery nowe pliki; istniejące produkty dostają je puste przez
  `core:update` i nic się u nich nie zmienia.
- `PANEL_SEGMENTS` i `GUEST_SEGMENTS` przeniosły się z `proxy.ts` do
  `proxy-segments.ts`; nowa strona zespołu albo gościa na hoście platformy dopisuje
  się tam i od razu staje się adresem zamkniętym dla tabel produktów.
- Testy rdzenia, które idą przez proxy albo sitemapę, jawnie podstawiają pusty slot —
  w repozytorium produktu slot jest pełny.
- Przekierowania z tabeli są trwałe (308) i przeglądarki je zapamiętują: błędny cel
  poprawia się nową regułą, nie cofnięciem starej.

## Granice

- Parametr adresu obejmuje jeden segment; pierwszy segment adresu jest nazwą.
- Strona 410 jest rdzenia (mała, bez wyglądu produktu); własna strona 410 produktu
  byłaby osobnym punktem rozszerzenia.
- Adres z kropką omija proxy (dopasowanie proxy, bez zmian) i nie da się go objąć
  regułą; stare adresy z kropką albo rozróżniane zapytaniem przekierowuje serwer przed
  aplikacją (kontrakt §6) — rdzeń nie ma dla nich punktu rozszerzenia. Folder plików
  stron jest wyjątkiem: proxy dostaje każdy adres pod nim i odpowiada 404 (pkt 3).
- `/pl/…/` (prefiks języka domyślnego i końcowy ukośnik naraz) to jedno 308 dla
  adresu tabeli; dla pozostałych adresów hosta platformy (strony rdzenia) zostają dwa,
  jak przed tym pakietem — zapis w `proxy.golden.json` się nie zmienił.
- Odczyt opublikowanych wpisów systemu treści przez strony produktu i `/media` na
  hoście platformy to osobne pakiety (ADR-079); tabela zostawia im miejsce.
- **Strony rdzenia pod `[locale]` niosą cały katalog komunikatów języka** — strony
  marketingowe, katalog i strony rezerwacji każdego produktu (Business, HoofCare,
  MedPlano): dokument ma ok. 360 KB, 100 KB po gzip, z czego 96 KB to katalog
  przekazywany przez dostawcę w `app/[locale]/layout.tsx`. Znane i zostawione: to
  osobna, większa sprawa (dostawcy per obszar z wyborem przestrzeni nazw), a te strony
  mają odpowiadać dokładnie jak dotąd. Publiczne strony produktu z tabeli już tego nie
  niosą (uzupełnienie PR1b).

## Odrzucone

- **`pathnames` next-intl** — pkt 2.
- **Strony produktu pod układem rdzenia (`app/[locale]/product-site/`)** — pierwotny
  wybór tego pakietu, żeby produkt nie powtarzał `<html>` i dostawcy komunikatów;
  cofnięty po pomiarze (uzupełnienie PR1b): strona niosła cały katalog panelu.
- **Przekierowania w `next.config` albo w Caddy** — reguły żyłyby poza repozytorium
  produktu albo poza jego testami, bez kontroli łańcuchów względem tabeli; ADR-077
  pkt 5 mówi, że to kod produktu.
- **Błąd przy imporcie dla złej tabeli** — zatrzymałby panel razem z publiczną stroną.
- **Domyślne 308 z nazwy działu w innym języku** — przekierowania, których nikt nie
  zadeklarował; duplikaty adresów w oczach wyszukiwarek do czasu ich wygaśnięcia.

## Relacje

ADR-048, ADR-049, ADR-071 (języki, adresy, pkt 13), ADR-077 (pkt 4 i 5), ADR-079
(`/media`, odczyt treści platformy — później), ADR-028 (routing hostów — bez zmian).
