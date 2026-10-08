# Treść własna platformy na stronach produktu — kontrakt odczytu

Wykonywalna połowa [ADR-079](../adr/ADR-079-Typy-Tresci-Taksonomie-i-Tresc-Wlasna-Platformy.md)
pkt 29–33 (sekcja „Uzupełnienie CT3”). Uzupełnia
[`product-public-site.md`](product-public-site.md) (ADR-080): tamten kontrakt mówi, jak
produkt stawia własne strony na hoście platformy, ten — skąd te strony biorą wpisy
poradnika albo bloga.

Platforma pisze własną treść **w panelu workspace'u platformy** — tym samym edytorem,
z tymi samymi tłumaczeniami i publikacją co klient. Strony publiczne rysuje **produkt**:
własne trasy, nagłówek, stopka i szablony. Rdzeń daje odczyt „co jest opublikowane”
i komponent, który rysuje treść wpisu. Produkt używa tego **wyłącznie nowymi plikami**;
żadnego pliku rdzenia nie zmienia. Ścieżki poniżej są względem `apps/frontend/src/`.

## 1. W sześciu zdaniach

1. Produkt importuje `#lib/product-site/content` (odczyt, tylko serwer)
   i `#components/site-entry-body` (treść wpisu z bloków rdzenia).
2. Pyta o **typ treści po kluczu**, **język** i **slug** — nigdy o adres.
3. Dostaje wpis, listę, pozycje (tagi, później kategorie) i wykaz do sitemapy jako
   **części adresu**: klucz typu, język, slug. Adresy składa sam, swoją tabelą
   (`siteHref`, `siteMetadata`, `siteVersions`).
4. Zdjęcia treści odpowiadają pod `/media/<id>` na hoście platformy — tam, gdzie
   szukają ich komponenty bloków.
5. Wpis, który odpowiada dziś gdzie indziej, wraca jako `moved` z dzisiejszymi
   częściami adresu; strona robi z nich jedno 308.
6. Czego nie ma opublikowanego, tego dla odczytu nie ma wcale: szkic, wycofany wpis,
   wyłączony typ i adres, którego nikt nie miał, odpowiadają tak samo.

## 2. Skąd bierze się treść

- Operator platformy wchodzi do workspace'u platformy (ADR-077 pkt 2 i 9) i w „Strona
  internetowa → Treści” zakłada **typ treści** (np. „Poradnik”). Typ ma **klucz**
  (`poradnik`) — stały, nadawany przy utworzeniu, ten sam we wszystkich językach.
  **Produkt pyta zawsze po kluczu.**
- Wpis jest w jednym języku; jego wersje w innych językach to osobne wpisy tej samej
  grupy tłumaczeń, każdy z własnym slugiem i własną publikacją.
- Odczyt widzi wpis od chwili publikacji i przestaje go widzieć przy wycofaniu —
  od razu, bez żadnej publikacji strony.
- Języki: odczyt oddaje wpisy w językach workspace'u (i w języku jego strony). Profil
  produktu z pięcioma językami wymaga, żeby workspace miał te języki włączone — nowy
  workspace dostaje wszystkie języki profilu, a założony przed dodaniem języka do
  profilu sam go nie dostaje (języki firmy w ustawieniach panelu).
- Workspace ma jedną stronę. Odczyt czyta **tylko workspace platformy tego wdrożenia**
  — nie przyjmuje hosta, strony ani firmy i niczym nie da się go skierować gdzie indziej.

## 3. Co produkt importuje

```ts
import {
  contentEntry,          // wpis po (typ, język, slug)
  contentEntries,        // strona listy typu albo jednej pozycji
  contentTypes,          // typy, które mają coś opublikowanego
  contentTerms,          // pozycje typu w języku, z licznikami
  contentSitemap,        // wykaz do sitemapy (części adresu)
  contentSitemapEntries, // ten wykaz jako linie `site-sitemap.ts`
  contentVersions,       // wersje językowe → `params` tabeli
  type ContentEntryResult,
  type ContentListResult,
  type ContentRoutes,
} from "#lib/product-site/content";
import { SiteEntryBody } from "#components/site-entry-body";
```

Typy odpowiedzi pochodzą z `@saas-core/api-client` (`PublicContentEntry`,
`PublicContentList`, `PublicContentListItem`, `PublicContentTerm`, `PublicContentTerms`,
`PublicContentType`, `PublicContentSitemap`, `PublicContentImage`) — generowane
z OpenAPI, nie przepisuj ich ręcznie.

`#lib/product-site/content` jest **tylko dla serwera** (`import "server-only"`): import
z komponentu klienckiego jest błędem budowania. Komponent kliencki dostaje gotowe dane
przez propsy.

## 4. Wywołania i odpowiedzi

Wszystkie pytają backend bezpośrednio, przy żądaniu, bez pamięci podręcznej. Awaria
backendu to wyjątek (strona odpowiada 500), nie „brak wpisu”.

### 4.1 Wpis

```ts
const result = await contentEntry({ type: "poradnik", locale, slug, canonicalUrl });
// { kind: "entry", entry } | { kind: "moved", to: { type, locale, slug } } | { kind: "not-found" }
```

| Pole `entry` | Co to jest |
|---|---|
| `type`, `locale`, `slug` | części adresu tego wpisu |
| `title`, `excerpt`, `author_name` | jak opublikowano |
| `published_at`, `updated_at` | ISO 8601; `updated_at` to chwila zmiany treści — ponowna publikacja tego samego tekstu jej nie rusza |
| `timezone` | strefa wydawcy (IANA): dzień, który widzi czytelnik, liczy się w niej |
| `blocks` | treść jako bloki rdzenia — rysuje je `SiteEntryBody` (§6) |
| `image` | pierwsze zdjęcie treści `{ asset_id, alt }` albo `null` |
| `image_sizes`, `ai_media_ids` | fakty o zdjęciach, których potrzebuje `SiteEntryBody` |
| `terms` | pozycje wpisu `{ taxonomy, slug, name }`, nazwa w języku wpisu |
| `versions` | opublikowane wersje językowe `{ locale, slug }`, **ta wersja też**, język strony pierwszy |
| `noindex` | wpis prosi o nieindeksowanie: strona ustawia `robots: noindex`; takiego wpisu nie ma na żadnej liście |
| `machine_text` | `null` dla tekstu człowieka; inaczej znacznik tekstu AI (`notice`: pokaż czytelnikowi notę — robi to `SiteEntryBody`) |
| `schema_type` | czym wpis jest dla wyszukiwarek (`BlogPosting`, `NewsArticle`, `Article`, `WebPage`) |
| `structured_data` | tylko z `canonicalUrl`: węzły JSON-LD wpisu (§8); inaczej `null` |

### 4.2 Lista

```ts
const result = await contentEntries({ type: "poradnik", locale, page, pageSize });
const tagged = await contentEntries({ type: "poradnik", locale, taxonomy: "tag", term: "porady" });
// { kind: "list", list } | { kind: "moved", to: { type, locale, taxonomy, term } } | { kind: "not-found" }
```

| Pole `list` | Co to jest |
|---|---|
| `type`, `locale`, `name` | klucz typu, język i nazwa typu w tym języku |
| `term` | pozycja, której lista dotyczy (`{ taxonomy, slug, name }`), albo `null` |
| `items` | wpisy strony, od najnowszego: `locale`, `slug`, `title`, `excerpt`, `author_name`, `published_at`, `updated_at`, `image`, `terms` |
| `page`, `pages`, `total` | bieżąca strona, liczba stron, liczba wpisów na całej liście w tym języku |
| `languages` | języki, w których ta lista odpowiada — do `hreflang` listy |
| `indexable` | `false` dla listy pozycji z mniej niż trzema wpisami: strona ustawia `noindex` i pomija ją w sitemapie. Regułę ma rdzeń, produkt ją tylko stosuje |

- `pageSize` od 1 do 100; pominięte — rozmiar indeksu wdrożenia (domyślnie 10).
- Strona za ostatnią to `not-found`, nie pusta lista.
- Lista typu w języku strony workspace'u odpowiada także wtedy, gdy wszystkie wpisy
  typu są w innym języku (wtedy `items` jest puste); w każdym innym języku — tylko gdy
  ma tam wpis. Lista pozycji odpowiada tylko tam, gdzie pozycja ma wpis.
- `moved` dla listy jest zarezerwowane na pozycję, o którą zapytano dawnym adresem;
  do czasu kategorii (§10) zawsze przychodzi lista albo `not-found`.

### 4.3 Typy i pozycje

```ts
const types = await contentTypes();
// [{ key, schema_type, languages, names: { pl, en }, segments: { pl, en } }]
const terms = await contentTerms({ type: "poradnik", locale });
// { type, locale, taxonomies: [{ key: "tag", hierarchical, segment, terms: [
//     { taxonomy, slug, name, count, indexable, parent_slug } ] }] } | null
```

- Typ jest na liście dopiero, gdy ma wpis na jakiejś liście; `names` i `segments` tylko
  w językach, w których ma taki wpis.
- `segments` to nazwa działu typu w adresach **w panelu** — informacja, nie adres.
  Sekcje swojej strony produkt nazywa we własnej tabeli (§5).
- Pozycja istnieje dla odczytu tylko tam, gdzie nosi ją **opublikowany wpis, który nie
  prosi o nieindeksowanie**, w danym języku. `count` liczy tylko takie wpisy.
- `parent_slug` to slug pozycji nadrzędnej w taksonomii hierarchicznej; dla tagów `null`.
  Drzewo składa produkt z tych wskazań.

### 4.4 Sitemapa

```ts
// product/site-sitemap.ts
import { contentSitemapEntries } from "#lib/product-site/content";

export async function siteSitemap() {
  return [
    { route: "/" },
    ...(await contentSitemapEntries({
      poradnik: {
        entry: "/guide/[slug]",
        list: "/guide",
        terms: { tag: "/guide/tag/[term]" },   // tylko jeśli produkt ma taką stronę
      },
    })),
  ];
}
```

Produkt mówi, która strona tabeli pokazuje który typ; rdzeń zwraca linie
`{ route, params per język, lastModified }` i sam pisze adresy z tabeli (ADR-080 §7).
Typ, lista albo taksonomia bez strony są pomijane. W wykazie są tylko wpisy z list,
lista każdego typu w językach, w których ma wpis, i listy pozycji warte indeksowania.
Surowy wykaz: `contentSitemap()`.

## 5. Jak części adresu stają się adresami

Produkt deklaruje sekcję w **swojej** tabeli — z nazwą per język, jaką sam wybierze:

```ts
// product/public-site.ts
routes: {
  "/guide": { pl: "/poradnik", en: "/guide", de: "/ratgeber" },
  "/guide/[slug]": { pl: "/poradnik/[slug]", en: "/guide/[slug]", de: "/ratgeber/[slug]" },
}
```

Strona wpisu:

```tsx
// app/product-site/[locale]/guide/[slug]/page.tsx
import { notFound, permanentRedirect } from "next/navigation";
import { cache } from "react";

import { JsonLd } from "#components/json-ld";
import { SiteEntryBody } from "#components/site-entry-body";
import { contentEntry, contentVersions } from "#lib/product-site/content";
import { siteAlternates, siteMetadata } from "#lib/product-site/seo";
import { siteHref } from "#lib/product-site/site";

const TYPE = "poradnik"; // klucz typu z panelu
const ROUTE = "/guide/[slug]"; // klucz tabeli

// Odczyt przy żądaniu: obraz buduje się bez backendu.
export const dynamic = "force-dynamic";

// Metadane i strona pytają raz.
const read = cache((locale: string, slug: string) =>
  contentEntry({
    type: TYPE,
    locale,
    slug,
    canonicalUrl: siteAlternates({ route: ROUTE, locale, params: { slug } }).canonical,
  }),
);

export async function generateMetadata({ params }) {
  const { locale, slug } = await params;
  const result = await read(locale, slug);
  if (result.kind !== "entry") return {};
  const { entry } = result;
  return {
    ...siteMetadata({
      route: ROUTE,
      locale,
      params: contentVersions(entry.versions), // hreflang = opublikowane wersje
      title: entry.title,
      description: entry.excerpt,
    }),
    ...(entry.noindex ? { robots: { index: false, follow: true } } : {}),
  };
}

export default async function Page({ params }) {
  const { locale, slug } = await params;
  const result = await read(locale, slug);
  if (result.kind === "not-found") notFound();
  if (result.kind === "moved") {
    permanentRedirect(siteHref(ROUTE, result.to.locale, { slug: result.to.slug }));
  }
  const { entry } = result;
  return (
    <article>
      <h1>{entry.title}</h1>
      <SiteEntryBody entry={entry} />
      {entry.structured_data ? <JsonLd data={graph(entry.structured_data)} /> : null}
    </article>
  );
}
```

- `contentVersions(entry.versions)` daje `{ pl: { slug: "…" }, en: { slug: "…" } }` —
  dokładnie to, co biorą `siteMetadata` i `siteVersions` (przełącznik języka). Język
  bez opublikowanej wersji nie trafia do `hreflang` ani do przełącznika. Drugi argument
  to nazwa parametru pliku strony, gdy nie jest nim `slug`.
- Link do wpisu z listy: `<SiteLink route="/guide/[slug]" params={{ slug: item.slug }}>`.
- Link do listy pozycji: `siteHref("/guide/tag/[term]", locale, { term: term.slug })`.
- `SiteLink` i `siteHref` rzucają błąd dla języka, którego tabela nie ma. Wpis w języku
  spoza tabeli produktu po prostu nie ma u niego strony — filtruj `versions` przez
  `siteVersions`, nie pisz adresu ręcznie.
- Slug z adresu, który nie jest slugiem rdzenia, kończy jako `not-found`; tabela
  i tak wpuszcza tylko `a–z`, `0–9` i łączniki.

## 6. Treść wpisu — `SiteEntryBody`

```tsx
<SiteEntryBody entry={entry} className="guide-body" />
```

- Rysuje **same bloki** komponentami rdzenia (`@saas-core/site-blocks`): tekst, tabele,
  FAQ, cytaty, zdjęcia. Bez nagłówka strony, menu, stopki, `<main>` i bez tytułu wpisu —
  to daje strona produktu.
- Zdjęcia dostają zapisany rozmiar (`width`, `height`), znacznik obrazu AI i ładowanie
  pierwszych dwóch razem ze stroną. Nota „przetłumaczono maszynowo” pojawia się nad
  tekstem, gdy serwer tak mówi (`machine_text.notice`).
- **Pomija** formularz kontaktowy i bloki rekordów na żywo (noclegi): za tą stroną nie
  stoi strona firmy, do której formularz by pisał.
- Style bloków są częścią `@saas-core/ui/globals.css` (importuje go układ produktu,
  ADR-080 §4) i są pisane pod `.site-theme`. Opakowanie to
  `.site-theme.site-theme--embedded`: wysokość, tło, kolor tekstu i czcionkę bierze ze
  strony, w której stoi. Szerokość treści to `--site-content-width` (domyślnie `72rem`),
  kolor akcentu `--site-accent` — ustaw je we własnym arkuszu pod własną klasą
  (`className`).
- `designTokens` (paleta, typografia, promień, odstępy rdzenia) — opcjonalnie;
  domyślnie motyw neutralny.
- Komponent serwerowy; nie potrzebuje dostawcy komunikatów.
- **Odnośniki w treści są takie, jak je napisał autor.** Rdzeń ich nie przepisuje,
  bo nie zna adresów produktu: w treści platformy pisz adresy strony produktu.
- Teksty treści są niezaufane. Nie wstawiaj `blocks` do HTML inaczej niż przez
  `SiteEntryBody`.

## 7. Zdjęcia — `/media/…` na hoście platformy

| Adres | Odpowiedź |
|---|---|
| `/media/<asset_id>` | oryginał (JPEG, PNG albo WebP) |
| `/media/<asset_id>/thumbnail`, `/media/<asset_id>/preview` | kopie WebP 320 px i 1280 px |
| cokolwiek innego pod `/media` | jak dotąd (404) |

- Odpowiada **zdjęcie, które pokazuje bieżąca publikacja wpisu workspace'u
  platformy** we włączonym typie i w języku, który workspace ma włączony — zdjęcie
  odpowiada tam, gdzie jego wpis. Zdjęcie ze szkicu, z wycofanego wpisu, ze strony
  kreatora workspace'u, cudze i nieistniejące dają to samo 404.
- Druga reguła nie dotyczy treści: **kopię** (nigdy oryginał) zdjęcia, które własny
  moduł produktu zadeklarował jako pokazywane gościowi (rekord na żywo — np. rasa),
  opisuje [`product-public-site.md` §13](product-public-site.md) (ADR-080,
  „Uzupełnienie PR1c”). Zdjęcie wpisu odpowiada jak dotąd, w oryginale i w kopiach.
- Adresy pisze `SiteEntryBody`. Własną miniaturę na liście napisz z `image.asset_id`:
  `<img src={`/media/${image.asset_id}/thumbnail`} alt={image.alt} />`.
- Odpowiedź ma `Cache-Control: public, max-age=31536000, immutable` (nowe zdjęcie to
  nowy identyfikator), `X-Content-Type-Options: nosniff` i `Content-Security-Policy:
  default-src 'none'; sandbox` — to origin panelu, więc bajty są obrazem i niczym więcej.
- Strona firmy na własnym hoście ma swoje `/media/…`, bez zmian.

## 8. JSON-LD

Z `canonicalUrl` wpis niesie `structured_data`: **własne węzły wpisu**, zbudowane tą
samą funkcją co na stronach firm — `WebPage` (także `FAQPage`, gdy treść ma pytania)
pod `<canonical>#webpage` i, o ile typ nie jest zwykłą stroną, artykuł pod
`<canonical>#article`. Węzły wskazują `<origin>/#website` i `<origin>/#organization`;
**te dwa węzły pisze produkt**:

```ts
const graph = (nodes: object[]) => ({
  "@context": "https://schema.org",
  "@graph": [
    { "@type": "WebSite", "@id": `${origin}/#website`, url: `${origin}/`, name: "…" },
    { "@type": "Organization", "@id": `${origin}/#organization`, name: "…", url: `${origin}/` },
    ...nodes,
  ],
});
```

Drukuj przez `<JsonLd>` (`#components/json-ld`), który zabezpiecza teksty.
`canonical_url` to pełny adres `http(s)` **na hoście platformy** (`platformDomain`
profilu — tym, pod którym `siteAlternates` pisze adres kanoniczny), bez zapytania,
fragmentu i znaków `<`, `>`, `"`, `'`, `` ` `` i `\`; każdy inny daje 400. Służy tylko
do złożenia identyfikatorów — nie jest pobierany ani zapisywany. Węzeł nie niesie
`translationOfWork` (rdzeń nie zna adresu wersji źródłowej u produktu).

## 9. „Przeniesione”

`{ kind: "moved", to: { type, locale, slug } }` znaczy: pod tymi częściami adresu wpis
odpowiada dziś. Strona robi **jedno 308** pod adres, który jej tabela z nich składa
(`permanentRedirect(siteHref(…))`), i nic więcej.

Dziś `moved` przychodzi w jednym przypadku: wpis jest w języku, który workspace
wyłączył — wtedy prowadzi do wersji w języku strony workspace'u (albo pierwszej, jaką
ma), a bez żadnej wersji jest `not-found`. Dojdą: dawny slug wpisu (ADR-079 pkt 16,
pakiet CT4) i dawny adres pozycji (pkt 11, pakiet CT2) — bez zmiany kształtu odpowiedzi.

## 10. Kategorie — co dojdzie

Pozycje są zaprojektowane tak, żeby kategorie były dodatkiem:

- `terms[].taxonomy` dostanie kolejne wartości obok `tag` (klucz taksonomii kategorii
  typu); `contentTerms` zwróci dodatkową taksonomię z `hierarchical: true`,
  a `parent_slug` zacznie wskazywać pozycję nadrzędną;
- `contentEntries({ taxonomy, term })` przyjmie tę taksonomię; lista kategorii
  nadrzędnej obejmie wpisy podrzędnych;
- slug pozycji stanie się adresem **per język**, a dawny adres da `moved`;
- `contentSitemapEntries` już przyjmuje stronę per taksonomia (`terms: { … }`).

Strona produktu, która traktuje `taxonomy` jako napis i ignoruje taksonomie, których
nie zna, nie wymaga zmiany.

## 11. Czego produkt nie może zakładać

- **Że część adresu jest adresem.** `segments` typu, `slug` i `segment` taksonomii to
  części; adres powstaje wyłącznie z tabeli produktu.
- **Że typ, pozycja albo lista istnieje, zanim coś opublikowano.** Pusty typ i typ,
  którego nie ma, to to samo `not-found`. Strona listy decyduje, czy pokazać pusty
  stan, czy `notFound()`.
- **Że każdy wpis ma każdy język** — mówi to `versions`.
- **Że pozycja ma listę wartą indeksowania** — mówi to `indexable`.
- **Że slug jest na zawsze** — obsłuż `moved`.
- **Że zbiór pól i taksonomii jest zamknięty.** Dochodzą pola i taksonomie; nieznane
  ignoruj.
- **Że odczyt da się wołać z przeglądarki, z innego hosta albo przy budowaniu.** Trasa
  `GET /api/v1/public/content/…` jest technicznie publiczna (oddaje tylko to, co
  opublikowane), ale nie jest produktem: bez CORS, kluczy i obietnicy stabilności dla
  obcych; odpowiada tylko na hostach platformy. Strony czytające treść mają
  `export const dynamic = "force-dynamic"`.
- **Że odpowiedź jest pamiętana.** Każde wywołanie pyta backend; lista i sitemapa
  czytają wszystkie opublikowane wpisy strony (bez treści). Pamięć podręczna po stronie
  produktu jest jego decyzją i jego ryzykiem (wycofany wpis ma zniknąć od razu).
- **Że `/media/…` odda oryginał zdjęcia spoza opublikowanego wpisu** albo cokolwiek
  innego niż obraz. Poza wpisami odpowiadają wyłącznie kopie (`thumbnail`, `preview`)
  zdjęć zadeklarowanych przez źródło publiczne workspace'u (§7).
- **Że strona workspace'u platformy z kreatora gdziekolwiek odpowiada.** Jej host
  (`<etykieta>.<platformDomain>` i domeny własne) odpowiada 404 na wszystkim — strony,
  wpisy, listy, kanały, sitemapa, media (ADR-079 pkt 29). Wiersze zostają w bazie,
  a panel wydawcy nie pokazuje adresu tej witryny i do niej nie prowadzi.

## 12. Kto czego pilnuje

- **Rdzeń (testy w bramce rdzenia i produktu):**
  `apps/backend/tests/test_sites_content_reads.py` — nic nieopublikowanego nie da się
  odczytać ani zgadnąć; czytany jest tylko workspace platformy (firma z tym samym
  kluczem typu, slugiem, tagiem i zdjęciem nie trafia do żadnej odpowiedzi; każde
  zapytanie do tabel bez RLS nazywa workspace; `SET LOCAL` stoi przed każdym odczytem
  tabeli z RLS); `/media/` tylko dla pokazanych zdjęć; strona workspace'u 404.
  `apps/backend/tests/test_sites_content_media_sources.py` — zdjęcie rekordu na żywo:
  tylko kopia, tylko zadeklarowane, cudze i niczyje dają to samo 404, `SET LOCAL` stoi
  przed pytaniem do źródła.
  `apps/backend/tests/test_pre_tenant_door.py` — lista wywołujących odnalezienie
  workspace'u przez drzwi sprzed tenanta; nowy wywołujący psuje test.
  `lib/product-site/content.test.ts`, `components/site-entry-body.test.tsx`,
  `lib/product-site/media.test.ts`, `proxy.platform-media.test.ts` — klient, treść,
  zdjęcia i reguła proxy, na testowym produkcie z testów ADR-080.
- **Tego testy nie wiedzą:** baza testowa łączy się właścicielem tabel i omija RLS.
  Że rola aplikacji widzi dokładnie te wiersze, sprawdza się na uruchomionym stosie
  (ADR-079, „Uzupełnienie CT3”).
- **Produkt:** test własnych stron z podstawionym `fetch` oraz — po przebudowie stosu —
  `product-site:check` (ADR-080 §10): każda linia sitemapy odpowiada 200.
