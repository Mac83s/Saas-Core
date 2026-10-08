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

3. **Pliki stron leżą pod `app/[locale]/product-site/`.** Segment jest wewnętrzny:
   czytelnik go nie widzi, a zapytany wprost odpowiada 404. Pod `[locale]`, a nie obok
   niego z własnym układem głównym, bo strony dziedziczą wtedy `<html lang>`, dostawcę
   komunikatów i style rdzenia, a produkt pisze tylko swój układ (nagłówek, stopka,
   czcionka). Osobny folder, a nie grupa tras, bo dwie strony pod jednym adresem
   (`/` rdzenia i `/` produktu) to błąd budowania Next — przepisanie w proxy jest
   jedynym sposobem, żeby produkt miał własną stronę główną bez zmiany pliku rdzenia.
   Rdzeń nie umieszcza w tym folderze żadnego pliku (plik rdzenia zmieniony przez
   produkt łamie `core:check`). Dopasowanie proxy obejmuje ten folder w całości, także
   adresy z kropką, które inaczej omijają proxy: gdy tabela jest zadeklarowana, każdy
   adres pod nim — w każdej pisowni, którą router odczytałby jako jego nazwę —
   odpowiada 404; gdy nie jest, taki adres idzie dalej nietknięty, jak dotąd.

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
    `cyrillic` na jego kontenerze). Czcionka panelu się nie zmienia: dołożenie podzbioru
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
- **Każda strona pod `[locale]` niesie cały katalog komunikatów języka.** Zmierzone
  na zbudowanej aplikacji: dokument strony produktu to ok. 360 KB (100 KB po gzip),
  z czego ok. 342 KB (96 KB po gzip) to katalog panelu przekazywany przez dostawcę
  w układzie rdzenia. To cecha rdzenia sprzed tego pakietu (tak samo ważą strony
  marketingowe i rezerwacji), ale dla serwisu treści z kilkuset stronami ma inną wagę,
  a produkt nie zdejmie tego ładunku nowymi plikami. Dwie drogi, obie poza tym
  pakietem: (a) folder stron produktu pod własnym układem głównym
  (`app/product-site/[locale]/` — zmienia się cel przepisania w proxy i kontrakt §4,
  produkt pisze `<html>` i dostawcę z samymi swoimi słowami; rdzeń może dać do tego
  gotowy komponent), (b) dostawcy per obszar w rdzeniu z wyborem przestrzeni nazw
  (pomaga też stronom marketingowym i rezerwacji wszystkich produktów). Decyzja przed
  przeniesieniem pierwszych stron produktu — po niej zmiana (a) to przeniesienie plików.

## Odrzucone

- **`pathnames` next-intl** — pkt 2.
- **Własny układ główny produktu obok `[locale]`** — produkt powtarzałby `<html>`,
  dostawcę komunikatów i kontrolę języka; więcej do pomylenia przy każdym produkcie.
- **Przekierowania w `next.config` albo w Caddy** — reguły żyłyby poza repozytorium
  produktu albo poza jego testami, bez kontroli łańcuchów względem tabeli; ADR-077
  pkt 5 mówi, że to kod produktu.
- **Błąd przy imporcie dla złej tabeli** — zatrzymałby panel razem z publiczną stroną.
- **Domyślne 308 z nazwy działu w innym języku** — przekierowania, których nikt nie
  zadeklarował; duplikaty adresów w oczach wyszukiwarek do czasu ich wygaśnięcia.

## Relacje

ADR-048, ADR-049, ADR-071 (języki, adresy, pkt 13), ADR-077 (pkt 4 i 5), ADR-079
(`/media`, odczyt treści platformy — później), ADR-028 (routing hostów — bez zmian).
