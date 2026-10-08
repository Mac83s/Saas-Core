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
   produkt łamie `core:check`).

4. **Strony produktu odpowiadają tylko tam, gdzie profil wyłącza marketing rdzenia**
   (`features.marketingSite: false`) i tylko na hoście platformy. W profilu
   z marketingiem rdzenia zadeklarowana tabela jest nieczynna. Dzięki temu produkt,
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
   być źródłem reguły. Źródło nie może przykrywać strony bez parametru, strony głównej,
   panelu, stron gości, `/media`, `/api` ani mieć kropki (taki adres nie trafia do
   proxy). Reguła na adresie strony z parametrem jest dozwolona — to wpis o zmienionej
   nazwie.

8. **Kto odrzuca złą tabelę: test w bramce produktu, nie `next build` i nie
   czytelnik.** `lib/product-site/slot.test.ts` kompiluje tabelę i reguły z bieżącego
   repozytorium i przepuszcza każdą regułę przez prawdziwe proxy (jedno 308, cel
   odpowiada stroną). W działającej aplikacji tabela, której nie da się obsłużyć,
   wyłącza publiczne strony produktu i zostawia panel — moduł proxy nie może paść przy
   imporcie, bo padłoby każde żądanie.

9. **Sitemapa: produkt wymienia strony, rdzeń pisze adresy.**
   `product/site-sitemap.ts` zwraca klucze tabeli z parametrami (także per język, gdy
   nazwa wpisu jest tłumaczona); rdzeń pisze linie z `hreflang` i pomija adres, na
   który odpowiada reguła starych adresów. `robots.txt` się nie zmienia.

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
- Adres z kropką omija proxy (dopasowanie proxy, bez zmian): nie da się go objąć
  regułą, a plik strony z parametrem zapytany wprost pod wewnętrznym adresem z wartością
  z kropką nie przechodzi przez tabelę. Strona z parametrem odpowiada więc `notFound()`
  na nieznaną wartość — kontrakt §4.
- `/pl/…/` (prefiks języka domyślnego i końcowy ukośnik naraz) odpowiada dwoma
  przekierowaniami, jak każdy adres hosta platformy przed tym pakietem.
- Odczyt opublikowanych wpisów systemu treści przez strony produktu i `/media` na
  hoście platformy to osobne pakiety (ADR-079); tabela zostawia im miejsce.

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
