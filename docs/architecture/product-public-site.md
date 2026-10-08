# Publiczne strony produktu na jego hoście — kontrakt

Wykonywalna połowa [ADR-080](../adr/ADR-080-Publiczne-Strony-Produktu-Na-Jego-Hoscie.md).
Produkt (repozytorium z rdzeniem jako `upstream`, ADR-049) stawia własną publiczną
stronę — kodowane widoki z własnym nagłówkiem i stopką, na tym samym hoście co panel
(ADR-048) — **wyłącznie nowymi plikami i plikami slotu `apps/frontend/src/product/`**.
Żadnego pliku rdzenia nie zmienia. Ścieżki poniżej są względem `apps/frontend/src/`.

## 1. Co produkt pisze i gdzie

| Potrzeba | Plik produktu | Kto go czyta |
|---|---|---|
| które adresy odpowiadają i jaką stroną, per język | `product/public-site.ts` (slot) | proxy, serwer, przeglądarka |
| stare adresy: dokąd przeniesione (308) albo usunięte (410) | `product/old-addresses.ts` (slot) | proxy, sitemapa |
| które strony istnieją — do `sitemap.xml` | `product/site-sitemap.ts` (slot) | tylko serwer |
| słowa stron w każdym języku treści | `product/site-messages.ts` (slot) | tylko serwer |
| same strony, własny układ główny (nagłówek, stopka), 404 | nowe pliki w `app/product-site/[locale]/` | Next |

Rdzeń dostarcza cztery pliki slotu puste; produkt je zastępuje. `public-site.ts`
i `old-addresses.ts` to **wyłącznie dane** (mogą importować plik `.json` obok siebie):
czyta je proxy przy każdym żądaniu, więc nie importują Reacta, klienta API ani niczego
z serwera. Stare adresy są w osobnym pliku, żeby kilka tysięcy reguł nie trafiło do
paczki strony w przeglądarce.

## 2. Kiedy te strony odpowiadają

- Tylko na hoście platformy (`product.platformDomain`, `FRONTEND_CONTROL_HOSTS`).
  Stronę firmy na jej hoście proxy oddaje rendererowi wcześniej — tabela produktu
  i jego stare adresy nigdy jej nie dotykają.
- Tylko w profilu, który wyłącza marketing rdzenia: `"features": { "marketingSite":
  false }` (ADR-077 pkt 4). Host ma jedną stronę główną; w profilu z marketingiem
  rdzenia tabela produktu jest nieczynna i wszystko odpowiada jak bez niej — poza
  folderem plików stron, który nie jest adresem w żadnym profilu (404).
- W językach treści profilu (`product.supportedLocales`). Język wymieniony w tabeli,
  którego profil nie oferuje, jest pomijany (tabela jest jedna na repozytorium, profili
  bywa kilka), ale jest sprawdzany tak samo jak pozostałe. Panel zostaje pl/en.
- Język domyślny (`pl`) nie ma prefiksu; pozostałe mają `/<język>` z przodu. Prefiksu
  nie pisze się w tabeli.

## 3. Tabela adresów — `product/public-site.ts`

```ts
import type { ProductPublicSite } from "#lib/product-site/table";

export const publicSite: ProductPublicSite | null = {
  routes: {
    "/": "/",
    "/breeds": { pl: "/rasy-psow", en: "/dog-breeds", de: "/hunderassen" },
    "/breeds/[slug]": {
      pl: "/rasy-psow/[slug]",
      en: "/dog-breeds/[slug]",
      de: "/hunderassen/[slug]",
    },
    "/quiz": "/quiz",
  },
};
```

- **Klucz** to ścieżka pliku strony pod `app/product-site/[locale]`, zapisana jak
  w Next: `/` → `page.tsx`, `/breeds/[slug]` → `breeds/[slug]/page.tsx`. Klucz jest
  też nazwą strony w `SiteLink`, `siteHref`, `siteMetadata` i w sitemapie.
- **Wartość** to adres dla czytelnika: jeden napis — ten sam we wszystkich językach
  treści profilu — albo adres per język; język pominięty nie ma tej strony (404).
- Segment adresu to `a–z`, `0–9` i pojedyncze łączniki między nimi, albo `[parametr]`.
  Adres niesie dokładnie parametry strony. Wartość parametru podlega tej samej regule
  co segment — adres z wielką literą, znakiem spoza `a–z` albo zakodowany procentowo
  nie jest adresem tabeli.
- Pierwszy segment adresu jest nazwą (nie parametrem), nie ma dwóch liter (to prefiks
  języka dziś albo jutro) i nie jest zarezerwowany (§9).
- Adres `/` należy do strony `/` i odwrotnie.
- W jednym języku dwa wpisy nie mogą mieć tego samego kształtu adresu. Nazwa wygrywa
  z parametrem w tym samym miejscu (`/rasy-psow/porownaj` przed `/rasy-psow/[slug]`).

Co odpowiada na hoście platformy, gdy tabela jest czynna:

| Adres | Odpowiedź |
|---|---|
| adres tabeli w swoim języku (`/rasy-psow/labrador`, `/en/dog-breeds/labrador`) | 200, plik strony; język z adresu, bez ciasteczka i bez wykrywania |
| adres tabeli z prefiksem języka domyślnego (`/pl/rasy-psow/labrador`) | jedno 308 do adresu bez prefiksu, z zachowanym zapytaniem |
| adres z końcowym ukośnikiem | jedno 308 do adresu bez ukośnika (reguła hosta platformy, bez zmian) |
| adres tabeli z prefiksem języka domyślnego **i** końcowym ukośnikiem (`/pl/rasy-psow/labrador/`) | jedno 308 prosto do adresu kanonicznego |
| nazwa działu z innego języka (`/en/rasy-psow/…`), inna pisownia, adres spoza tabeli | 404 — własna strona 404 produktu, w języku z prefiksu adresu |
| folder plików stron wprost (`/product-site/…`), także z kropką w adresie i w zapisie procentowym | 404 — także w profilu, w którym tabela jest zadeklarowana, ale nieczynna |
| `/`, gdy tabela nie ma strony `/` | 307 do logowania, jak dotąd |
| strony zespołu i gości (`/panel`, `/login`, `/book`, …), `/sitemap.xml`, `/robots.txt` | bez zmian |

## 4. Pliki stron — `app/product-site/[locale]/`

Folder stoi **obok** `app/[locale]`, nie pod nim: strony produktu mają własny układ
główny i nie dziedziczą dokumentu panelu. Powód jest mierzalny (§8): pod `[locale]`
każda strona niesie cały katalog komunikatów języka.

- `layout.tsx` — **układ główny** produktu. `page.tsx` — strona główna.
  `not-found.tsx` i `[...rest]/page.tsx` (wywołuje `notFound()`) — własna strona 404
  dla adresu spoza tabeli. `layout.tsx`, `not-found.tsx` i `[...rest]/page.tsx` są
  **wymagane**, gdy produkt deklaruje tabelę: proxy oddaje im wizyty, a test z §10
  (`slot.test.ts`) nie przechodzi bez nich.

```tsx
// app/product-site/[locale]/layout.tsx
import "@saas-core/ui/globals.css";                    // jeśli produkt chce stylów rdzenia
import { Inter } from "next/font/google";
import { setRequestLocale } from "next-intl/server";
import { SiteDocument, siteStaticParams } from "#components/site-document";

const font = Inter({ subsets: ["latin", "latin-ext", "cyrillic"], variable: "--font-geist" });
export const generateStaticParams = siteStaticParams;

export default async function Layout({ children, params }) {
  const { locale } = await params;
  setRequestLocale(locale);   // w ciele układu, zanim strona przeczyta tłumaczenie
  return (
    <SiteDocument locale={locale} namespaces={["MojSerwis"]} className={font.variable}>
      <Header />{children}<Footer />
    </SiteDocument>
  );
}
```

**Co daje rdzeń (`SiteDocument`):**

- `<html lang>` z języka adresu i `dir` (`rtl` dla języków pisanych od prawej),
  `<body>`; 404 dla języka, którego wdrożenie nie obsługuje;
- język żądania dla next-intl (`setRequestLocale`) — proxy ustawia go też z adresu,
  bez ciasteczka i bez wykrywania;
- dostawcę komunikatów, który oddaje przeglądarce **tylko wymienione przestrzenie
  nazw** (`namespaces`): własne produktu i dowolne rdzenia, których używają komponenty
  klienckie stron (`Common`, teksty strony gościa). Komponenty serwerowe czytają
  każdą przestrzeń nazw języka (`getTranslations`), także teksty gości rdzenia, bez
  wymieniania ich tutaj i bez kosztu w przeglądarce.

**Co układ produktu musi dać sam** (rdzeń tego nie narzuca, bo publiczny serwis
decyduje o tym po swojemu):

- **arkusz stylów**: `import "@saas-core/ui/globals.css"` daje Tailwind (skanuje
  `apps/**`, więc klasy z plików produktu działają), tokeny i komponenty rdzenia;
  bez tego importu strona nie ma żadnych stylów rdzenia;
- **czcionkę**: `next/font` z podzbiorem `cyrillic`; zmienna o nazwie `--font-geist`
  podana w `className` zasila `font-sans` rdzenia (w `globals.css`), inna nazwa
  wymaga własnego CSS;
- **`generateStaticParams`** (`siteStaticParams`) i treść: nagłówek, stopkę;
- opcjonalnie skrypt trybu ciemnego (`COLOR_SCHEME_SCRIPT` z `#lib/color-scheme` jako
  pierwsze dziecko), jeśli serwis ma ciemny wygląd; metadane i ikony — jak w każdej
  aplikacji Next (`metadata`, `siteMetadata` z §5).

Pozostałe zasady:

- **`setRequestLocale(locale)` w ciele układu głównego** (jak w przykładzie) jest
  tym, co pozwala stronom bez parametru budować się statycznie: sprawdzone na
  zbudowanej aplikacji — bez tej linii strona główna i lista działu renderują się przy
  każdym żądaniu (`ƒ`), z nią są statyczne (`●`). `SiteDocument` też ustawia język, ale
  jako komponent potomny robi to za późno dla strony, która czyta tłumaczenia.
  Bez tej linii strony nadal odpowiadają poprawnie, w języku z adresu — tylko wolniej.
- Nagłówek i stopkę renderuj jako komponenty **wewnątrz** `SiteDocument`.
- **Strona z parametrem odpowiada `notFound()` na wartość, której nie zna.** Tabela
  sprawdza tylko kształt adresu; czy rasa istnieje, wie strona.
- Kodowanych adresów nie pisze się ręcznie (§5). Odnośnik do panelu albo logowania
  to `Link` z `#i18n/navigation` (lint rdzenia odrzuca `<a href="/panel">`); na
  stronie w języku spoza pl/en podaj mu `locale="en"`, inaczej prowadzi przez jedno
  308. Przejście między stronami produktu a panelem to pełne załadowanie dokumentu
  (dwa układy główne); między stronami produktu — przejście po stronie klienta.

## 5. Linki, przełącznik języka, canonical i hreflang

Wszystko liczy ta sama skompilowana tabela, która rozstrzyga w proxy:

```tsx
import { SiteLink } from "#components/site-link";
import { siteMetadata, siteVersions } from "#lib/product-site/seo";   // tylko serwer
import { siteHref } from "#lib/product-site/site";

<SiteLink route="/breeds/[slug]" params={{ slug }}>…</SiteLink>   // język czytelnika
<SiteLink route="/" locale="en">English</SiteLink>                 // inny język
siteHref("/breeds/[slug]", locale, { slug });                      // sam adres

export async function generateMetadata({ params }) {
  return siteMetadata({ route: "/breeds/[slug]", locale, params: versions, title, description });
}

siteVersions("/breeds/[slug]", versions);   // [{ locale, path }] — przełącznik języka
```

- `params` to parametry wspólne dla wszystkich języków (`{ slug: "labrador" }`) albo
  per język, gdy nazwa wpisu jest tłumaczona: `{ pl: { slug: "owczarek-niemiecki" },
  en: { slug: "german-shepherd" } }`. Język pominięty nie trafia do hreflang ani do
  przełącznika.
- `siteMetadata` daje `canonical`, `hreflang` wszystkich wersji i `x-default` (wersja
  języka domyślnego, a gdy jej nie ma — pierwsza) oraz Open Graph.
- `SiteLink` i `siteHref` rzucają błąd dla strony, języka albo parametru, których
  tabela nie obsłuży — błąd widać tam, gdzie link napisano, nie tam, gdzie go kliknięto.
- Przełącznik języka to zwykłe odnośniki (ADR-071 pkt 13): treść nie zależy od
  `Accept-Language` ani ciasteczka. Buduje go `siteVersions` — po stronie serwera;
  komponent kliencki dostaje gotową listę.
- `hreflang`, `siteVersions` i sitemapa czytają jeden filtr: adres, na który dziś
  odpowiada reguła starych adresów, nie jest wymieniany w żadnym z nich. `SiteLink`
  i `siteHref` reguł nie znają (reguły nie trafiają do przeglądarki): link do wpisu
  o starej nazwie zadziała, ale przez jedno 308 — linkuj nową nazwę.

## 6. Stare adresy — `product/old-addresses.ts`

```ts
import type { ProductOldAddresses } from "#lib/product-site/table";
import moved from "./old-addresses.json";

export const oldAddresses: ProductOldAddresses = {
  moved,                         // { "/rasy/labrador-retriever": "/rasy-psow/labrador", … }
  gone: ["/sklep", "/en/shop"],
};
```

- **`moved`**: stary adres → adres tabeli. Odpowiedź to **jedno 308** prosto do celu,
  na hoście i schemacie czytelnika, z zachowanym zapytaniem. **`gone`**: 410 z małą
  stroną w języku starego adresu (pierwszy segment, jeśli jest językiem treści; inaczej
  język domyślny), z odnośnikiem do strony głównej w tym języku. Słowa strony 410 ma
  rdzeń, dla każdego języka rejestru.
- Źródło to cała ścieżka starego serwisu, razem z jego prefiksem języka (także
  `/pl/…`, jeśli stary serwis tak pisał polski). Reguły są sprawdzane **przed** obsługą
  języka, końcowego ukośnika i tabelą stron.
- **Jedna lista dla wszystkich profili.** Reguły są sprawdzane względem wszystkich
  języków, które tabela wymienia, więc lista jest poprawna albo błędna niezależnie od
  profilu. Profil bez niemieckiego pomija reguły prowadzące pod `/de/…` (nie odpowiada
  na nie), a resztę obsługuje.
- **Jak porównujemy** — jedną funkcją (`normalizeOldAddress`) źródło reguły i ścieżkę
  wizyty:
  1. puste segmenty odpadają — końcowy i podwójny ukośnik nie mają znaczenia;
  2. każdy segment jest raz dekodowany z zapisu procentowego (`%C5%BC` = `ż`);
     ścieżka, której nie da się zdekodować, albo z zakodowanym ukośnikiem (`%2F`)
     w segmencie nie pasuje do żadnej reguły;
  3. znaki są sprowadzane do postaci Unicode NFC (litera ze znakiem diakrytycznym
     zapisana jednym albo dwoma znakami to ten sam adres);
  4. wielkość liter nie ma znaczenia (`toLowerCase` po NFC);
  5. zapytanie (`?…`) nie bierze udziału w porównaniu i jest przenoszone na cel.
- **Odmowy przy kompilacji tabeli** (nie u czytelnika):
  - cel, który sam jest starym adresem — łańcuch albo pętla, także jednoelementowa;
  - cel, który nie jest adresem tabeli w pisowni kanonicznej (inny host, końcowy
    ukośnik, prefiks języka domyślnego, wielka litera, adres panelu);
  - ten sam adres dwa razy (po porównaniu z punktów 1–4), także raz w `moved`, raz
    w `gone`;
  - źródło równe adresowi strony bez parametru albo stronie głównej — w dowolnym
    języku tabeli i także w pisowni z prefiksem języka domyślnego (`/pl/quiz`: temu
    adresowi należy się 308 do `/quiz`, nie reguła);
  - źródło pod segmentem zarezerwowanym (§9), z zapytaniem albo fragmentem;
  - źródło z kropką w segmencie (`/strona.html`, `/feed.xml`): takie adresy są
    serwowane jako pliki i do reguł nie docierają.
- **Stare adresy z kropką albo rozróżniane zapytaniem** (`/strona.html`, `/?p=123`)
  nie są regułami tabeli: reguła porównuje samą ścieżkę, a adres z kropką omija proxy.
  Przekierowuje je serwer przed aplikacją (jedno 308 prosto do adresu tabeli); rdzeń
  nie ma dziś dla produktu punktu rozszerzenia na takie reguły — produkt, który ich
  potrzebuje, zgłasza to do rdzenia. Nie obsługuj ich stroną, która sama przekierowuje:
  to drugi krok.
- Reguła **może** leżeć na adresie strony z parametrem (`/rasy-psow/owczarek` →
  `/rasy-psow/owczarek-niemiecki`): tak przenosi się wpis o zmienionej nazwie.
  Reguła odpowiada przed stroną.
- Kilka tysięcy reguł to jedno wyszukanie w mapie na żądanie.

## 7. Sitemapa i robots

```ts
import type { SiteSitemapEntry } from "#lib/product-site/table";

export async function siteSitemap(): Promise<SiteSitemapEntry[]> {
  return [
    { route: "/" },
    { route: "/breeds/[slug]", params: { pl: { slug: "…" }, en: { slug: "…" } }, lastModified },
  ];
}
```

- Produkt wymienia **strony** (klucz tabeli i parametry), nigdy adresy. Rdzeń pisze
  każdy adres z tabeli: jedną linię na język, w którym strona istnieje, każdą
  z `hreflang` wszystkich wersji i `x-default`.
- Adres, na który dziś odpowiada reguła starych adresów, jest pomijany — w sitemapie
  nie ma niczego, co odpowiada 308 albo 410.
- Funkcja jest wołana przy każdym żądaniu `/sitemap.xml`, po stronie serwera, tylko
  gdy tabela jest czynna; może pytać backend. Linia z kluczem, którego tabela nie ma,
  jest pomijana z wpisem w logu — reszta sitemapy odpowiada.
- `robots.txt` hosta platformy zostaje bez zmian: wskazuje `/sitemap.xml`, zamyka
  `/panel`, `/settings` (w każdym języku) i `/api/`.

## 8. Słowa i czcionka

- `product/site-messages.ts`: `{ pl: {…}, en: {…}, de: {…}, es: {…}, ru: {…} }` —
  przestrzenie nazw produktu nakładane na komunikaty danego języka. Język treści spoza
  pl/en czyta katalog angielski, więc angielskie słowa produktu leżą pod jego własnymi:
  brak słowa po niemiecku daje słowo angielskie. Plik czyta tylko serwer; `messages`
  w `product/index.ts` zostają słowami panelu (pl/en).
- Słowa serwisu w pl i en są częścią katalogu języka, więc niesie je też każda strona
  panelu — trzymaj w nich słowa interfejsu, nie treść stron.
- Do przeglądarki trafiają tylko przestrzenie nazw wymienione w `SiteDocument` (§4).
  **Zmierzone na zbudowanej aplikacji (2026-10-08), ta sama strona przed i po
  przeniesieniu folderu spod `[locale]`:**

  | Strona | HTML przed | gzip przed | HTML po | gzip po |
  |---|---|---|---|---|
  | `/en` (strona główna) | 359 805 B | 100 135 B | 13 178 B | 3 019 B |
  | `/en/dog-breeds/german-shepherd` | 359 768 B | 101 150 B | 13 362 B | 3 906 B |
  | `/ru/quiz` (strona kliencka) | 360 037 B | 101 558 B | 10 876 B | 2 759 B |

  Przed: 342 KB dokumentu (96 KB po gzip) to był cały katalog komunikatów języka
  z układu rdzenia. Po: w dokumencie jest jedna przestrzeń nazw produktu (kilkaset
  bajtów do 2,5 KB, zależnie od tego, czy strona jest statyczna).
- Czcionka z cyrylicą: układ główny produktu ładuje ją przez `next/font`
  z podzbiorami `latin`, `latin-ext`, `cyrillic` (§4). Czcionka panelu (Geist, `latin`
  i `latin-ext`) zostaje, jaka była.

## 9. Zarezerwowane pierwsze segmenty

Ani adres tabeli, ani źródło reguły starych adresów nie może zaczynać się (po
ewentualnym prefiksie języka) od:

- stron zespołu i gości: `panel`, `settings`, `invitations`, `login`, `register`,
  `onboarding`, `password-reset`, `reset-password`, `verify-email`, `book`,
  `booking`, `documents`;
- adresów platformy: `media` (opublikowane media treści platformy, ADR-079),
  `internal`, `static`, `site-renderer`, `product-site`;
- niczego, co zaczyna się od `api`, `healthz`, `_next`, `_vercel` — takie ścieżki
  (także `/apiary`) w ogóle nie trafiają do proxy.

Lista żyje w jednym pliku (`proxy-segments.ts`), z którego czyta też proxy.

## 10. Kto odrzuca złą tabelę: test, `/healthz` i kontrola na zbudowanym stacku

Trzy poziomy; każdy widzi coś, czego nie widzi poprzedni.

1. **Test w bramce produktu** — `lib/product-site/slot.test.ts` (test rdzenia)
   kompiluje tabelę i reguły **z tego repozytorium**: języki z rejestru, każdy adres
   tabeli wraca do swojej strony, żadna reguła nie jest łańcuchem, pętlą ani
   przykryciem strony, a przez prawdziwe proxy każdy stary adres daje jedno 308 pod
   adres, który proxy oddaje plikowi strony (nie kolejne przekierowanie i nie 404
   z proxy), każdy `gone` daje 410. **Tego test nie wie:** czy strona pod celem
   istnieje. Tabela sprawdza kształt adresu; literówka w slugu celu
   (`/rasy-psow/labradorr`) przechodzi ten test, odpowiada 308 i kończy na `notFound()`
   strony — a przeglądarki pamiętają 308. `next build` złej tabeli nie odrzuca.
2. **`/healthz`** — tabela, której nie da się obsłużyć, wyłącza publiczne strony
   produktu, a lista reguł, której nie da się obsłużyć, wyłącza reguły; panel działa
   dalej, ale `/healthz` odpowiada wtedy **503** (`product_site_off` albo
   `product_old_addresses_off`, z treścią odmowy), więc przebudowa czekająca na
   `/healthz` (`rebuild-stack`, kontrola na VPS) nie przechodzi po cichu.
3. **Kontrola na zbudowanym stacku — część odbioru produktu** po każdej przebudowie,
   która zmieniła tabelę, reguły albo strony:

   ```
   PRODUCT_SITE_URL=http://127.0.0.1:<port> PRODUCT_SITE_HOST=<host platformy> \
     pnpm --filter @saas-core/frontend product-site:check
   ```

   Idzie po każdej regule z tego repozytorium na działającym stacku: 308 pod cel
   i **200 pod celem** (strona, nie jej 404), 410 dla `gone`; każda linia
   `sitemap.xml` odpowiada 200; strona główna odpowiada w każdym języku; `/healthz`
   jest `ok`. `PRODUCT_SITE_LOCALES=pl,en,de` podaje języki profilu stacku, gdy jest
   inny niż wyrenderowany w repozytorium. W zwykłej bramce ten test jest pomijany.

## 11. Granice

- Parametr obejmuje jeden segment; nie ma parametru „reszta ścieżki”.
- Strona 410 jest rdzenia — mała, bez nagłówka produktu.
- Adres z kropką nie trafia do proxy (zasada dopasowania proxy, bez zmian) i nie da
  się go przekierować regułą (§6). Wyjątkiem jest folder plików stron: proxy dostaje
  każdy adres pod nim, także z kropką, i odpowiada 404.
- Profil z `publicBooking: false` odrzuca adresy zawierające `/book/` albo
  `/booking/` wcześniej niż tabela; test z §10 to wykrywa.
- Odczyt opublikowanych wpisów systemu treści dla stron produktu i `/media` na hoście
  platformy to osobne pakiety (ADR-079); tabela zostawia im `media` i `api`.

## 12. Przeniesienie istniejącego serwisu — kolejność

1. Profil: `features.marketingSite: false`, języki w `supportedLocales`.
2. `public-site.ts`: strona główna i działy z nazwami per język.
3. `app/product-site/[locale]/`: `layout.tsx` (układ główny z `SiteDocument`),
   `page.tsx`, strony działów, `not-found.tsx`, `[...rest]/page.tsx`.
4. `site-messages.ts`: słowa w każdym języku; przestrzenie nazw komponentów
   klienckich w `namespaces` układu; linki przez `SiteLink`.
5. `old-addresses.ts` (+ `.json`): stare adresy; `pnpm test` pokaże każdą odmowę.
6. `site-sitemap.ts`: lista stron z parametrami per język.
7. Po przebudowie stacku: `product-site:check` (§10 pkt 3) — dopiero on mówi, że
   każdy stary adres kończy na istniejącej stronie.
