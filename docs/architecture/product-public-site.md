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
| same strony, układ (nagłówek, stopka), 404 | nowe pliki w `app/[locale]/product-site/` | Next |

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

- **Klucz** to ścieżka pliku strony pod `app/[locale]/product-site`, zapisana jak
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
| nazwa działu z innego języka (`/en/rasy-psow/…`), inna pisownia, adres spoza tabeli | 404 — własna strona 404 produktu, w języku z prefiksu adresu |
| folder plików stron wprost (`/product-site/…`) | 404 — także w profilu, w którym tabela jest zadeklarowana, ale nieczynna |
| `/`, gdy tabela nie ma strony `/` | 307 do logowania, jak dotąd |
| strony zespołu i gości (`/panel`, `/login`, `/book`, …), `/sitemap.xml`, `/robots.txt` | bez zmian |

## 4. Pliki stron — `app/[locale]/product-site/`

- `layout.tsx` — układ wszystkich publicznych stron produktu: nagłówek, stopka,
  czcionka. `page.tsx` — strona główna. `not-found.tsx` i `[...rest]/page.tsx`
  (wywołuje `notFound()`) — własna strona 404; bez nich adres spoza tabeli dostaje
  404 bez układu produktu.
- Strony leżą pod układem rdzenia `app/[locale]/layout.tsx` i dziedziczą po nim:
  `<html lang>` z języka adresu, `NextIntlClientProvider`, `@saas-core/ui/globals.css`
  (Tailwind skanuje `apps/**`, więc klasy z plików produktu działają), zmienną
  `--font-geist` i skrypt trybu ciemnego (klasa `.dark` na `<html>` z ustawienia
  czytelnika — układ produktu sam decyduje, czy go honoruje).
- Język: proxy ustawia go z adresu, więc `getTranslations`/`useTranslations` działają
  bez dodatkowych kroków; stronie generowanej statycznie nadal potrzebne jest
  `setRequestLocale(locale)` z `params`.
- **Strona z parametrem odpowiada `notFound()` na wartość, której nie zna.** Tabela
  sprawdza tylko kształt adresu; czy rasa istnieje, wie strona.
- Kodowanych adresów nie pisze się ręcznie (§5). Odnośnik do panelu to zwykłe
  `/panel` albo `Link` z `#i18n/navigation`.

## 5. Linki, przełącznik języka, canonical i hreflang

Wszystko liczy ta sama skompilowana tabela, która rozstrzyga w proxy:

```tsx
import { SiteLink } from "#components/site-link";
import { siteMetadata } from "#lib/product-site/seo";
import { productSite, siteHref } from "#lib/product-site/site";

<SiteLink route="/breeds/[slug]" params={{ slug }}>…</SiteLink>   // język czytelnika
<SiteLink route="/" locale="en">English</SiteLink>                 // inny język
siteHref("/breeds/[slug]", locale, { slug });                      // sam adres

export async function generateMetadata({ params }) {
  return siteMetadata({ route: "/breeds/[slug]", locale, params: versions, title, description });
}

productSite.versions("/breeds/[slug]", versions);   // [{ locale, path }] — przełącznik języka
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
  `Accept-Language` ani ciasteczka.

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
- Źródło to cała ścieżka starego serwisu, razem z jego prefiksem języka. Reguły są
  sprawdzane **przed** obsługą języka, końcowego ukośnika i tabelą stron.
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
  - źródło równe adresowi strony bez parametru albo stronie głównej dowolnego języka;
  - źródło pod segmentem zarezerwowanym (§9), z zapytaniem albo fragmentem;
  - źródło z kropką w segmencie (`/strona.html`, `/feed.xml`): takie adresy są
    serwowane jako pliki i do reguł nie docierają — przekieruj je w serwerze przed
    aplikacją.
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
- `NextIntlClientProvider` przekazuje komunikaty do przeglądarki na każdej stronie,
  także w panelu (pl/en) — trzymaj tu słowa interfejsu, nie treść stron.
- Czcionka z cyrylicą: układ produktu ładuje własną przez `next/font` z podzbiorami
  `latin`, `latin-ext`, `cyrillic` i nadaje jej klasę swojemu kontenerowi. Czcionka
  panelu (Geist, `latin` i `latin-ext`) zostaje, jaka była.

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

## 10. Bramka: kto odrzuca złą tabelę

`lib/product-site/slot.test.ts` (test rdzenia, uruchamiany w bramce produktu) kompiluje
tabelę i reguły **z tego repozytorium** i sprawdza: języki z rejestru, każdy adres
tabeli wraca do swojej strony, każdy stary adres daje przez prawdziwe proxy jedno 308,
a jego cel stronę (nie kolejne przekierowanie i nie 404), każdy `gone` daje 410.
`next build` złej tabeli nie odrzuca.

W działającej aplikacji tabela, której nie da się obsłużyć, **wyłącza publiczne strony
produktu** (`productSiteProblem`, wpis w logu), a panel działa dalej; reguły, których
nie da się obsłużyć, wyłączają tylko reguły (`productOldAddressesProblem`).

## 11. Granice

- Parametr obejmuje jeden segment; nie ma parametru „reszta ścieżki”.
- Strona 410 jest rdzenia — mała, bez nagłówka produktu.
- Adres z kropką nie trafia do proxy (zasada dopasowania proxy, bez zmian): nie da
  się go przekierować regułą, a plik strony z parametrem zapytany wprost pod
  `/<język>/product-site/…/<wartość.z.kropką>` omija tabelę — dlatego strona
  z parametrem musi odpowiadać `notFound()` na nieznaną wartość (§4).
- Profil z `publicBooking: false` odrzuca adresy zawierające `/book/` albo
  `/booking/` wcześniej niż tabela; test z §10 to wykrywa.
- Odczyt opublikowanych wpisów systemu treści dla stron produktu i `/media` na hoście
  platformy to osobne pakiety (ADR-079); tabela zostawia im `media` i `api`.

## 12. Przeniesienie istniejącego serwisu — kolejność

1. Profil: `features.marketingSite: false`, języki w `supportedLocales`.
2. `public-site.ts`: strona główna i działy z nazwami per język.
3. `app/[locale]/product-site/`: `layout.tsx`, `page.tsx`, strony działów,
   `not-found.tsx`, `[...rest]/page.tsx`.
4. `site-messages.ts`: słowa w każdym języku; linki przez `SiteLink`.
5. `old-addresses.ts` (+ `.json`): stare adresy; `pnpm test` pokaże każdą odmowę.
6. `site-sitemap.ts`: lista stron z parametrami per język.
