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
| same strony, własny układ główny (dokument), 404 | nowe pliki w `app/product-site/[locale]/` | Next |
| otoczka strony: nagłówek z przełącznikiem języka, stopka | własny komponent produktu, renderowany przez każdą stronę (§4) | Next |
| dane i zdjęcia własnego modułu w workspace platformy | moduł wertykału produktu — przez blok rdzenia (§13) | backend |

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
| `/`, gdy tabela nie ma strony `/` | 307 do logowania, jak dotąd (`/login`; spod `/en` i każdego innego języka — `/en/login`) |
| strony zespołu i gości (`/panel`, `/login`, `/book`, …), `/sitemap.xml`, `/robots.txt` | bez zmian — należą do rdzenia w każdym języku, także pod prefiksem języka (niżej) |

**Logowanie i strony zespołu mówią po polsku i angielsku, w każdym profilu.** Języki
treści produktu ich nie zmieniają (sprawdzone zapisem `proxy.golden.json`, profil
z pięcioma językami bez marketingu):

| Adres | Odpowiedź |
|---|---|
| `/login`, `/panel`, `/register`, `/password-reset` | 200, po polsku |
| `/en/login`, `/en/panel` | 200, po angielsku |
| `/pl/login` | 308 do `/login` |
| `/de/login`, `/es/login`, `/ru/login` (język treści spoza pl/en) | 308 do `/en/login` |

Te same adresy odpowiadają więc także wtedy, gdy zastępowany serwis miał pod nimi
własne logowanie albo rejestrację: nie da się ich objąć regułą starych adresów (§6)
ani uczynić adresem tabeli (§9) — pierwszy segment jest rdzenia.

## 4. Pliki stron — `app/product-site/[locale]/`

Folder stoi **obok** `app/[locale]`, nie pod nim: strony produktu mają własny układ
główny i nie dziedziczą dokumentu panelu. Powód jest mierzalny (§8): pod `[locale]`
każda strona niesie cały katalog komunikatów języka.

- `layout.tsx` — **układ główny** produktu: sam dokument. `page.tsx` — strona główna.
  `not-found.tsx` i `[...rest]/page.tsx` (wywołuje `notFound()`) — własna strona 404
  dla adresu spoza tabeli. `layout.tsx`, `not-found.tsx` i `[...rest]/page.tsx` są
  **wymagane**, gdy produkt deklaruje tabelę: proxy oddaje im wizyty, a test z §10
  (`slot.test.ts`) nie przechodzi bez nich.
- **Nagłówek i stopkę renderuje każda strona, nie układ.** Przełącznik języka
  w nagłówku prowadzi do *tej* strony w innym języku, a którą stroną jest i z jakimi
  parametrami, wie tylko ona — układ Next nie dostaje trasy strony, którą otacza,
  i nie renderuje się ponownie przy przejściu między stronami. Produkt pisze więc
  jedną otoczkę (niżej `SitePage`) i każda strona podaje jej swój klucz tabeli
  i parametry.

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
      {children}
    </SiteDocument>
  );
}

// product/site/site-page.tsx — otoczka, plik produktu
import { siteVersions } from "#lib/product-site/seo";

export function SitePage({ locale, route, params, children }) {
  // Strona bez własnego adresu (404) przełącza język na stronie głównej.
  const versions = siteVersions(route ?? "/", route ? params : undefined);
  return (
    <>
      <Header locale={locale} versions={versions} />
      <main>{children}</main>
      <Footer locale={locale} />
    </>
  );
}

// app/product-site/[locale]/breeds/[slug]/page.tsx
export default async function Page({ params }) {
  const { locale, slug } = await params;
  // … odczyt rasy; nieznana → notFound()
  return (
    <SitePage locale={locale} route="/breeds/[slug]" params={slugs}>
      …
    </SitePage>
  );
}

// app/product-site/[locale]/not-found.tsx — nie dostaje parametrów
import { getLocale } from "next-intl/server";

export default async function NotFound() {
  const locale = await getLocale();   // język adresu, o który zapytano
  return <SitePage locale={locale} route={null}>…</SitePage>;
}
```

**Strona 404 i jej język.** `not-found.tsx` nie dostaje od Next ani parametrów, ani
adresu. Język bierze z `getLocale()` (`next-intl/server`): proxy ustawia go z prefiksu
adresu, o który zapytano, i nigdy z nagłówka ani ciasteczka gościa (test
`answers.test.ts`: „gives … the product's own 404, in that language”). Otoczkę
renderuje jak każda strona; nie ma własnych wersji językowych, więc przełącznik
prowadzi do strony głównej w każdym języku (`siteVersions("/")`). Strona
z parametrem, która nie zna wartości, woła `notFound()` tak samo jak `[...rest]`
i dostaje tę samą stronę 404.

Sprawdzone na zbudowanym stosie pierwszego produktu (2026-10-09, Next 16.2,
przeglądarka): `/de/nichts`, `/nic-takiego` i `/en/…` odpowiadają **statusem 404**,
a czytelnik widzi nagłówek, stopkę i słowa 404 produktu w języku adresu, z `<html
lang>` w tym języku. **Granica, której ten kontrakt nie zdejmuje:** tę stronę rysuje
przeglądarka. Dokument, który serwer wysyła z `notFound()`, jest pusty (`<html
id="__next_error__">`, bez `lang` i bez treści) i niesie stronę 404 jako dane — tak
Next odpowiada na `notFound()` strony renderowanej przy żądaniu, także na stronach
rdzenia. Status jest poprawny dla wyszukiwarek; czytelnik bez skryptów widzi pustą
stronę.

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
- **`generateStaticParams`** (`siteStaticParams`);
- opcjonalnie skrypt trybu ciemnego (`COLOR_SCHEME_SCRIPT` z `#lib/color-scheme` jako
  pierwsze dziecko `SiteDocument`), jeśli serwis ma ciemny wygląd. Skrypt zapisuje
  atrybut na `<html>`, zanim React go hydratyzuje; `SiteDocument` oznacza `<html>`
  jako `suppressHydrationWarning` (jak dokument panelu), więc różnica nie jest
  zgłaszana — obejmuje to tylko atrybuty samego `<html>`, nie strony pod nim;
- metadane i ikony — jak w każdej aplikacji Next (`metadata`, `siteMetadata` z §5).

Nagłówek, stopka i treść należą do stron (otoczka wyżej), nie do układu.

Pozostałe zasady:

- **`setRequestLocale(locale)` w ciele układu głównego** (jak w przykładzie) jest
  tym, co pozwala stronom bez parametru budować się statycznie: sprawdzone na
  zbudowanej aplikacji — bez tej linii strona główna i lista działu renderują się przy
  każdym żądaniu (`ƒ`), z nią są statyczne (`●`). `SiteDocument` też ustawia język, ale
  jako komponent potomny robi to za późno dla strony, która czyta tłumaczenia.
  Bez tej linii strony nadal odpowiadają poprawnie, w języku z adresu — tylko wolniej.
- Układ główny renderuje `SiteDocument` i nic wokół stron; otoczkę z nagłówkiem
  i stopką renderuje strona (wyżej).
- **Strona z parametrem odpowiada `notFound()` na wartość, której nie zna.** Tabela
  sprawdza tylko kształt adresu; czy rasa istnieje, wie strona.
- Kodowanych adresów nie pisze się ręcznie (§5). Odnośnik do panelu albo logowania
  to `Link` z `#i18n/navigation` (lint rdzenia odrzuca `<a href="/panel">`
  i `<a href="/login">`, w każdym języku). Panel mówi po polsku i angielsku (§3): na
  stronie w języku spoza pl/en podaj odnośnikowi `locale="en"`
  (`isPanelLocale(locale) ? undefined : "en"` z `#i18n/routing`), inaczej pisze
  `/de/login` i prowadzi przez jedno 308. Podaj mu też `prefetch={false}`: strona
  logowania należy do zespołu, a bez tego przeglądarka każdego czytelnika pobiera ją
  z wyprzedzeniem na każdej stronie serwisu. Przejście między stronami produktu
  a panelem to pełne załadowanie dokumentu (dwa układy główne); między stronami
  produktu — przejście po stronie klienta.

## 5. Linki, przełącznik języka, canonical i hreflang

Wszystko liczy ta sama skompilowana tabela, która rozstrzyga w proxy:

```tsx
import { SiteLink } from "#components/site-link";
import { siteMetadata, siteVersions } from "#lib/product-site/seo";   // tylko serwer
import { siteHas, siteHref } from "#lib/product-site/site";

<SiteLink route="/breeds/[slug]" params={{ slug }}>…</SiteLink>   // język czytelnika
<SiteLink route="/" locale="en">English</SiteLink>                 // inny język
siteHref("/breeds/[slug]", locale, { slug });                      // sam adres

export async function generateMetadata({ params }) {
  return siteMetadata({ route: "/breeds/[slug]", locale, params: versions, title, description });
}

siteVersions("/breeds/[slug]", versions);   // [{ locale, path }] — przełącznik języka

siteHas("/breeds", locale);                  // czy strona jest w tym języku — nie rzuca
siteHas("/breeds");                          // …w jakimkolwiek języku wdrożenia
```

- `params` to parametry wspólne dla wszystkich języków (`{ slug: "labrador" }`) albo
  per język, gdy nazwa wpisu jest tłumaczona: `{ pl: { slug: "owczarek-niemiecki" },
  en: { slug: "german-shepherd" } }`. Język pominięty nie trafia do hreflang ani do
  przełącznika.
- `siteMetadata` daje `canonical`, `hreflang` wszystkich wersji i `x-default` (wersja
  języka domyślnego, a gdy jej nie ma — pierwsza) oraz Open Graph.
- `SiteLink` i `siteHref` rzucają błąd dla strony, języka albo parametru, których
  tabela nie obsłuży — błąd widać tam, gdzie link napisano, nie tam, gdzie go kliknięto.
  Tak samo rzucają pytania skompilowanej tabeli o stronę, której tabela nie nazywa:
  `languages(route)`, `hasParams(route)`, `href(…)`, `versions(…)`.
- **Pytanie, które nie rzuca: `siteHas(route, locale?)`** (na skompilowanej tabeli
  `has(route, locale?)`). Wpis menu albo przycisk do strony, którą przyniesie dopiero
  kolejna zmiana, albo która nie istnieje w każdym języku, pyta o nią przed napisaniem
  odnośnika. Odpowiada `false` także tam, gdzie wdrożenie nie serwuje stron produktu
  (profil z marketingiem rdzenia, brak tabeli). Bez języka pyta o jakikolwiek język
  wdrożenia.
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
- **Stare logowanie, rejestracja i panel zastępowanego serwisu nie są regułami.**
  `/pl/login`, `/en/login`, `/de/register` leżą pod segmentami rdzenia (§9) — także
  pod prefiksem języka — i odpowiadają jego stronami tak, jak mówi §3: stare
  `/pl/login` to jedno 308 do `/login`, stare `/de/login` — jedno 308 do `/en/login`.
  Źródło pod takim segmentem jest odmową przy kompilacji. Stary adres logowania
  o innej nazwie (`/logowanie`) może być tylko `gone`: cel `moved` musi być adresem
  tabeli, a stron zespołu w tabeli nie ma.
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
- Opublikowane wpisy systemu treści (poradnik, blog platformy) strony produktu czytają
  przez osobny kontrakt: [`product-content-read.md`](product-content-read.md)
  (ADR-079). Zdjęcia tej treści odpowiadają pod `/media/<id>` na hoście platformy —
  stąd `media` i `api` wśród segmentów zarezerwowanych. Zdjęcia rekordów własnego
  modułu produktu odpowiadają tam jako kopie (§13).
- Arkusz `@saas-core/ui/globals.css` niesie cały Tailwind panelu i style kreatora
  stron (ok. 322 kB, 47 kB po gzip, blokuje rysowanie). Lżejszego wejścia — same
  tokeny i podstawa — rdzeń dziś nie ma (ADR-080, „Uzupełnienie PR1c”, pkt 5).

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

## 13. Moduł produktu w workspace platformy: dane i zdjęcia własne

Publiczne strony produktu stoją na hoście platformy, który nie jest domeną żadnej
strony — host nie nazwie tenanta. To, co własny moduł produktu (`modules/vertical/…`)
pokazuje i zapisuje dla gościa (rasy, zapis na listę, formularz), należy do
**workspace'u platformy** tego wdrożenia i leży w tabelach z wymuszonym RLS. ADR-080,
„Uzupełnienie PR1c”.

**Trzy linie dla autora modułu:**

1. **Zdjęcie rekordu:** `/media/<asset id>/thumbnail` (WebP 320 px) albo
   `/media/<asset id>/preview` (WebP 1280 px) na hoście platformy — gdy identyfikator
   zwraca `served_media` źródła publicznego, które moduł rejestruje
   (`register_public_source`). Nigdy oryginał (`/media/<asset id>` to 404, chyba że
   zdjęcie pokazuje też opublikowany wpis treści).
2. **Dostęp do workspace'u platformy bez hosta:**

   ```python
   from saas_core.modules.core.organizations.api import (
       PlatformWorkspaceMissing,
       in_platform_workspace,
   )

   with in_platform_workspace() as organization_id:
       Breed.all_objects.filter(organization_id=organization_id, …)
   ```

   Moduł produktu **nigdy nie nazywa** `platform_workspace`, `platform_workspace_id`
   ani `ensure_platform_workspace` — test rdzenia `tests/test_pre_tenant_door.py`
   (produkt dostaje go z rdzeniem i go nie edytuje) pada wtedy z komunikatem, który
   podaje ten import. Workspace zakłada komenda rdzenia `provision_platform_workspace`.
3. **Komendy operatora idą tą samą drogą, bez wyjątku:** komenda otwiera blok, czyta
   w nim wiersz workspace'u (`Organization.objects.get(pk=organization_id)`), wychodzi
   i dalej prowadzi własne transakcje jak dotąd.

### 13.1. Blok `in_platform_workspace()`

- Jest **jedną transakcją z ustawionym tenantem workspace'u**: tabele z wymuszonym RLS
  odpowiadają w nim — i tylko wierszami workspace'u. Oddaje jego identyfikator.
- Workspace odnajduje stałym pytaniem przez drzwi sprzed tenanta: po rodzaju **i** po
  nazwie wyliczonej z wdrożenia (`platform-<DEPLOYMENT>`), sama kolumna `id`. Żadna
  dana od gościa do tego pytania nie trafia.
- **Wdrożenie bez workspace'u mówi to wprost:** `PlatformWorkspaceMissing`
  (`APIException`, 503, kod `platform_workspace_missing`). Widok może ją przepuścić
  albo zamienić na własną odpowiedź; komenda zamienia ją na `CommandError`.
- **Wywołany w czyjejś otwartej transakcji** jest jej punktem zapisu. Ustawienie
  tenanta przeżywa zwolnienie punktu zapisu, więc blok przy wyjściu przywraca
  ustawienie, które zastał — następne zapytanie wywołującego nie idzie jako platforma.
  Blok zakończony wyjątkiem jest wycofywany do punktu zapisu razem z ustawieniem.
- **Zalogowany gość jest w bloku nadal gościem.** Sesja panelu jedzie z każdym
  żądaniem tego samego originu, więc gość zalogowany do własnej firmy ma na stronach
  produktu jej kontekst. W bloku kontekst cudzej firmy jest ukryty
  (`require_tenant_context()` odmawia jak anonimowemu); kontekst członka samego
  workspace'u zostaje.
- **Identyfikator może wyjść z bloku.** Czytnik, który sam ustawia tenant dla podanego
  identyfikatora, i komenda z własnymi transakcjami (jedna na rekord, przebieg próbny
  z wycofaniem) biorą go z bloku i pracują dalej po swojemu — nie trzeba zamykać
  całej pracy w jednej transakcji bloku.
- Nie zastępuje kontekstu tenanta w panelu: żądanie, które ma już swoją firmę,
  czyta ją jak dotąd.

Funkcja, która ma oddać sam identyfikator albo `None` (kształt „wydawca serwisu”):

```python
def site_publisher_id() -> UUID | None:
    try:
        with in_platform_workspace() as organization_id:
            return organization_id
    except PlatformWorkspaceMissing:
        return None
```

Komenda operatora:

```python
try:
    with in_platform_workspace() as organization_id:
        organization = Organization.objects.get(pk=organization_id)
except PlatformWorkspaceMissing as error:
    raise CommandError(str(error.detail)) from error
with workspace_scope(organization=organization, operator_email=…):   # jak dotąd
    …
```

### 13.2. Zdjęcia rekordów modułu

- Moduł rejestruje źródło publiczne (`PublicSource(key, shown_media,
  served_media=…)`, w `AppConfig.ready`). `served_media(organization_id)` zwraca
  identyfikatory zdjęć, które gość ma prawo zobaczyć — to, co moduł sam by mu pokazał
  (rasy opublikowane), nigdy wszystko, co trzyma.
- Rdzeń pyta źródło **w tenancie workspace'u** (po `SET LOCAL`, w tej samej
  transakcji), więc `served_media` czyta własne tabele z RLS zwyczajnie, bez
  ustawiania czegokolwiek.
- Odpowiada wyłącznie kopia (`thumbnail`, `preview`) zdjęcia gotowego, należącego do
  workspace'u i zwróconego przez źródło. Zdjęcie niezadeklarowane, cudze i nieistniejące
  dają **to samo 404**; oryginał — 404.
- Źródło jest pytane przy każdym żądaniu zdjęcia (rekord na żywo: wycofana rasa znika
  od razu). Zmierzone na stosie z 374 zdjęciami pod rolą aplikacji: pytanie do źródła
  0,9 ms z 9,5 ms całego żądania miniatury (mediana) — rejestr nie potrzebuje
  tańszego pytania „czy ten jeden”. Odpowiedź ma `Cache-Control: public,
  max-age=31536000, immutable`, więc przeglądarka pyta o dane zdjęcie raz.
- Strona firmy na własnym hoście serwuje zdjęcia swoich rekordów tą samą regułą, jak
  dotąd (`public_media`).

### 13.3. Kto czego pilnuje

- `tests/test_pre_tenant_door.py` — moduł wertykału woła blok bez deklaracji i pada za
  nazwanie odnalezienia (także w komendzie); moduł `core` albo `shared` pada za jedno
  i drugie, dopóki nie zostanie zadeklarowany w rdzeniu z powodem; pięć plików
  publicznego renderera nie może nazwać niczego z tego.
- `tests/test_platform_workspace_block.py` — kolejność zapytań bloku, przywrócenie
  ustawienia, ukrycie cudzego kontekstu, brak workspace'u.
- `tests/test_sites_content_media_sources.py` — reguła zdjęć i `SET LOCAL` przed
  pytaniem do źródła.
- **Tego testy nie wiedzą:** baza testowa łączy się właścicielem tabel i omija RLS —
  test trzyma kolejność zapytań, nie to, że rola aplikacji widzi wiersze. To pokazuje
  uruchomiony stos: `/media/<id zdjęcia opublikowanego rekordu>/thumbnail` na hoście
  platformy odpowiada 200 `image/webp`, a ten sam adres bez wariantu — 404.
