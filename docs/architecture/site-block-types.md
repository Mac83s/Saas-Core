# Typy bloków stron: rdzeń i moduły

Blok to jedna sekcja strony klienta: typ, wersja schematu i dane. Typy `core.*`
należą do rdzenia (`packages/contracts/site-blocks/manifest.json`,
`packages/site-blocks/src/core-manifest.ts`). Moduł `shared` albo `vertical` —
w praktyce wertykał produktu — wnosi własne typy **z własnych plików, bez
zmiany pliku rdzenia** (ADR-077, ADR-049). Ten dokument jest kontraktem dla
takiego modułu. Wzorzec, na którym kontrakt jest dowiedziony testami, to
testowy wertykał `vertical.sample` — lista plików w §11.

Blok modułu jest zwykłym blokiem: ta sama walidacja przy zapisie, te same
wersje, ten sam formularz i podgląd w studiu, te same fragmenty do tłumaczenia,
ten sam renderer strony. Różni się tylko tym, że **istnieje tam, gdzie
deployment składa jego moduł** (§8).

## 1. Dwa rodzaje bloków

| Rodzaj | Kto go tworzy | Przykład | W manifeście | W studiu |
|---|---|---|---|---|
| stawiany | osoba (albo automatyzacja) na stronie lub we wpisie | indeks rekordów, quiz | — | formularz, sekcja w bibliotece, „Dodaj pustą sekcję” |
| budowany przez serwer | moduł, dla własnej strony rekordu | profil rekordu na `/rasy-psow/<slug>/` | `"serverBuilt": true` | nigdzie; zapis z takim blokiem dostaje `400 server_built_site_block` |

Blok stawiany, który pokazuje rekordy modułu, niesie tylko wybór (nagłówek,
kolejność); rekordy dopowiada przy każdym odczycie publiczne źródło modułu
(`PublicSource.site_block_types` i `site_blocks`). Stronę rekordu — adres,
tytuł i bloki — też daje źródło (`site_page`, `site_pages`). Pod adresem samego
działu (`/rasy-psow/`) źródło nie odpowiada: listę rekordów stawia się blokiem
na zwykłej podstronie, a podstrona może stanąć pod tym adresem tylko wtedy, gdy
źródło ma `root_page=True` (§7). Protokół źródeł opisuje notatka na górze
`apps/backend/src/saas_core/modules/core/organizations/public_sources.py`;
ten dokument go nie powtarza.

## 2. Pliki, które dokłada moduł

Dla modułu `vertical.<nazwa>` (identyfikator z deskryptora w
`packages/contracts/modules/`):

| Plik (nowy) | Co zawiera |
|---|---|
| `packages/contracts/site-blocks/modules/vertical.<nazwa>/manifest.json` | typy, wersje, wyjątki tłumaczeń, sekcje biblioteki (§3) |
| `packages/contracts/site-blocks/modules/vertical.<nazwa>/<typ>.v<n>.schema.json` | schemat danych każdej wersji (§4) |
| `apps/frontend/src/modules/vertical/<nazwa>/site-blocks.tsx` | komponenty i formularze: `defineModuleSiteBlocks` (§5) |
| `apps/backend/src/saas_core/modules/vertical/<nazwa>/…` | źródło publiczne rejestrowane w `AppConfig.ready` — gdy blok pokazuje rekordy albo rekord ma własną stronę |

Do tego dwa wpisy w slocie produktu (`apps/frontend/src/product/`, jedyne
pliki rdzenia, które produkt zmienia): lista zestawów w `site-blocks.ts` i
słowa panelu w `product.messages` (§5.4).

Backend czyta manifest z dysku, z podkatalogu `modules/` katalogu
`SITE_BLOCK_CONTRACTS_PATH` — obraz kopiuje ten katalog w całości, więc nowa
zmienna środowiskowa ani wpis w `Dockerfile` nie są potrzebne.

## 3. Manifest modułu

Schemat: `packages/contracts/site-blocks/module-manifest.v1.schema.json`.

```json
{
  "schemaVersion": 1,
  "module": "vertical.sample",
  "blocks": [
    {
      "type": "vertical.sample.record_list",
      "latestVersion": 2,
      "schemas": {
        "1": "vertical.sample.record_list.v1.schema.json",
        "2": "vertical.sample.record_list.v2.schema.json"
      },
      "translation": {
        "copied": { "curator": "name" },
        "data": ["reviewed_on"],
        "personal": ["curator_role"]
      },
      "sections": [{ "id": "vertical.sample.record_list_classic", "…": "…" }]
    },
    {
      "type": "vertical.sample.record_profile",
      "latestVersion": 1,
      "schemas": { "1": "vertical.sample.record_profile.v1.schema.json" },
      "serverBuilt": true
    }
  ]
}
```

- **Nazwa typu** to `<id modułu>.<nazwa>`: `vertical.puppily.breed_index`.
  Myślnik w identyfikatorze modułu zapisuje się podkreśleniem
  (`shared.model-port` → `shared.model_port.…`), bo typ bloku nie ma myślników.
  `module` musi być nazwą katalogu.
- **Wersje** tworzą linię od 1 do `latestVersion`. Schemat opublikowanej
  wersji nigdy się nie zmienia; zmiana kształtu danych to nowa wersja z
  migratorem (§9).
- **`serverBuilt`**: blok buduje wyłącznie moduł; nie może mieć `sections`.
- **`translation`** — §4.2. **`sections`** — §6.

## 4. Schemat bloku

JSON Schema 2020-12, obiekt z `additionalProperties: false`. `$id` kończy się
nazwą pliku (`…/vertical.sample.record_list.v2.schema.json`) — po tym frontend
sprawdza, że zaimportował plik wskazany w manifeście.

### 4.1. Nazwy pól, które rdzeń rozumie

- **Odnośnik** to pole o nazwie `href` — zagnieżdżone tam, gdzie trzeba
  (`action.href`, `items[].href`). Po tej nazwie rdzeń pilnuje listy
  dozwolonych hostów automatyzacji i prowadzi odnośnik do strony w języku
  czytelnika; pole o innej nazwie nie dostałoby żadnego z dwojga, więc test
  kontraktów odrzuca schemat modułu, w którym wzorzec przyjmujący ścieżkę
  albo adres stoi pod inną nazwą.
- **Zdjęcie** to obiekt z `asset_id` (i `alt`). Po kluczu `asset_id` rdzeń
  wiąże media ze stroną, liczy rozmiary i dokłada oznaczenie AI; komponent
  rysuje je przez `renderImage` (§5.2).

### 4.2. Co jest tekstem do tłumaczenia

Reguła jest ta sama co dla bloków rdzenia: **string bez `enum`, `pattern`,
`const` i `format` jest prozą** i staje się jednym fragmentem (kluczem jest
pozycja bloku i ścieżka pola); wszystko inne to struktura, taka sama w każdym
języku. Tablica odcinków z `text` i znacznikami (`bold`, `italic`, `href`,
`rel`) jest jednym fragmentem ze znacznikami jako tokenami.

Czego schemat nie umie powiedzieć, mówi `translation` w manifeście. Ścieżki
mają `/` między nazwami i `*` za dowolny indeks tablicy (`items/*/author`),
i obowiązują we wszystkich wersjach:

| Klucz | Znaczenie |
|---|---|
| `copied` | proza taka sama w każdym języku: `"name"` (nazwisko, nazwa własna) albo `"address"`; kopiowana, nigdy nie trafia do modelu |
| `data` | wolny string, który jest daną, nie prozą (wydrukowana data): nie jest fragmentem |
| `personal` | tekst o prawdziwych osobach — ich słowa, role: `true` dla całego bloku albo lista ścieżek |

Ścieżka, której nie ma w żadnej wersji schematu, zatrzymuje `manage.py check`
(`sites.E013`): literówka wysłałaby cudze nazwisko do modelu bez słowa.

Blok budowany przez serwer nie ma fragmentów — nikt go nie zapisuje. Jego
słowa są słowami rekordu: moduł tłumaczy je jako własne źródło tłumaczeń
(`translation-sources.md`) i buduje blok już w języku strony.

## 5. Frontend

### 5.1. Zestaw modułu

```tsx
import contract from "@saas-core/contracts/site-blocks/modules/vertical.sample/manifest.json";
import listV1 from "@saas-core/contracts/site-blocks/modules/vertical.sample/vertical.sample.record_list.v1.schema.json";
import listV2 from "@saas-core/contracts/site-blocks/modules/vertical.sample/vertical.sample.record_list.v2.schema.json";
import profileV1 from "@saas-core/contracts/site-blocks/modules/vertical.sample/vertical.sample.record_profile.v1.schema.json";
import { defineModuleSiteBlocks, type ModuleBlockContract } from "@saas-core/site-blocks";

export const sampleBlocks = defineModuleSiteBlocks(contract as ModuleBlockContract, {
  "vertical.sample.record_list": {
    schemas: [listV1, listV2],
    migrators: { 1: (data) => ({ ...data }) },
    component: RecordList,
    live: true,
    catalog: {
      category: "offer",
      labelKey: "sampleRecordList",
      fields: [
        { path: ["heading"], kind: "text", labelKey: "sampleHeading" },
        { path: ["order"], kind: "choice", labelKey: "sampleOrder", options: ["name", "newest"] },
      ],
    },
  },
  "vertical.sample.record_profile": { schemas: [profileV1], component: RecordProfile },
});
```

`defineModuleSiteBlocks` łączy manifest z kodem i odmawia, gdy się rozchodzą:
typ bez komponentu albo komponent bez typu, inna liczba schematów niż wersji,
schemat z innego pliku, brak migratora, pole formularza, którego nie ma
w schemacie, formularz na bloku `serverBuilt`.

### 5.2. Komponent

- Zwykła funkcja bez hooków, której korzeniem jest element HTML (`<section>`):
  renderer woła ją sam, żeby dołożyć klasy wyglądu sekcji i kotwicę. To, co
  musi działać w przeglądarce gościa (filtry, quiz), jest komponentem
  klienckim zagnieżdżonym **w środku** — nigdy korzeniem.
- Dostaje `data` (już zmigrowane do najnowszej wersji), `options.locale`
  (język strony), `options.preview`, a na opublikowanej stronie `live.data` —
  odpowiedź źródła dla bloku z `live: true`.
- Tekst edytowalny w miejscu rysuje przez `editor?.text(ścieżka, wartość)`
  (albo `plainBlockText`), zdjęcie przez `renderImage(obraz, <img …/>,
  imageRenderer)`. Blok `serverBuilt` niczego z tego nie potrzebuje.
- Blok z `live: true` bez odpowiedzi źródła nie jest na opublikowanej stronie
  żadną sekcją. W studiu i w podglądzie odpowiedzi nie ma nigdy: komponent
  rysuje wtedy szkic (`live === undefined`).
- Nagłówek strony (`<h1>`) należy do strony; blok zaczyna od `<h2>`.
- Wygląd: klasa `site-block` na korzeniu daje odstępy motywu; własne style to
  klasy Tailwind w komponencie (rdzeń skanuje `apps/**`) z tokenami motywu
  (`var(--site-accent)` i pokrewne). Plik CSS importowany z pliku modułu jest
  dla Next dozwolony, ale testy rdzenia go nie obejmują.
- Plik zestawu czyta renderer publiczny na serwerze i studio w przeglądarce:
  nie importuje UI panelu (`@saas-core/ui`), klienta API ani niczego z
  `"use client"` poza własnymi komponentami klienckimi bloków.

### 5.3. Formularz studia

Formularz powstaje z `catalog.fields` — to dane, nie komponent. Rodzaje pól:
`text`, `textarea`, `url`, `choice` (opcje równe `enum` schematu, w tej samej
kolejności), `media` (`aspect` = kadr), `list` (z `item`, opcjonalnie
`maxItems`), `richText` i `table`. `stayOffer`, `stayUnit` i `stayPlace` należą
do rezerwacji.

Własnej kontrolki — na przykład wyboru jednego rekordu modułu — moduł dziś nie
wniesie: to byłby nowy rodzaj pola w rdzeniu. `category` to jedna z kategorii
ADR-031 (`start`, `about`, `offer`, `trust`, `pricing`, `faq`, `contact`,
`booking`, `footer`, `decorative`).

### 5.4. Slot produktu i słowa

```ts
// apps/frontend/src/product/site-blocks.ts
import type { ProductSiteBlocks } from "#lib/product-extension";
import { sampleBlocks } from "../modules/vertical/sample/site-blocks";

export const siteBlocks: ProductSiteBlocks = [sampleBlocks];
```

Nazwę bloku (`labelKey`), etykiety pól i opcje wyboru (`<labelKey>Options.
<wartość>`) studio czyta z przestrzeni `Sites` — produkt dokłada je w
`product.messages` (`{ pl: { Sites: { … } }, en: { Sites: { … } } }`), z
kluczami poprzedzonymi nazwą modułu, żeby nie zderzyły się z rdzeniem.

## 6. Sekcje w bibliotece

Blok stawiany trafia do biblioteki przez `sections` w manifeście:

```json
{
  "id": "vertical.sample.record_list_classic",
  "version": 1,
  "schemaVersion": 2,
  "labels": {
    "pl": { "name": "Lista rekordów", "description": "…", "usage": "…" },
    "en": { "name": "List of records", "description": "…", "usage": "…" }
  },
  "seed": { "pl": { "heading": "Nasze rekordy", "order": "name" }, "en": { "…": "…" } }
}
```

- `id` to `<typ bloku>_<nazwa>` i nie zmienia się przy poprawkach (rośnie
  `version`). `seed` jest poprawny względem schematu wersji `schemaVersion`.
- Blok z kilkoma układami podaje `layout` w sekcji i to samo pole `layout`
  w zalążku; blok bez układów jest swoją jedną sekcją.
- Rodzina sekcji modułu staje w bibliotece po rodzinach rdzenia, pod nazwą
  bloku. Sekcję widzi tylko deployment, który składa moduł.
- Zalążek trzyma się zasad katalogu (`site-section-catalog.md`): bez
  zmyślonych dowodów, miejsca do uzupełnienia jako `[Uzupełnij: …]` /
  `[Fill in: …]`, żadnych odnośników do `#kotwicy`.

Szablony całych stron (recepty), konwersje między typami sekcji i zdjęcia
przykładowe pozostają rdzenia.

## 7. Backend modułu

- **Blok stawiany z rekordami**: źródło rejestruje typ w `site_block_types`
  i odpowiada w `site_blocks(organization_id, locale, blocks, page_base)`;
  odpowiedź wędruje do komponentu jako `live.data`. Adresy stron rekordów
  składa z `page_base`, nigdy sam.
- **Strona rekordu**: `site_page` zwraca `SourcePage(blocks=[…])` z blokiem
  `serverBuilt`. Strona podaje go rendererowi tak, jak go dostała, więc moduł
  sprawdza kształt u siebie: `validate_built_site_block(block_type=…,
  schema_version=…, data=…)` z `saas_core.modules.shared.sites.api` — w
  teście modułu, a tam, gdzie dane są cudze, także przy budowaniu.
- **Lista rekordów pod adresem działu**: źródło deklaruje `root_page=True`, a
  listą jest blok stawiany na podstronie, której slug w języku strony firmy to
  segment źródła w tym języku (`rasy-psow`). Wersja językowa tej podstrony
  dostaje nazwę działu w swoim języku sama (`/en/dog-breeds/`), a okruszki
  stron rekordów prowadzą przez nią. Bez flagi segment jest dla podstron
  zamknięty w każdym języku (`slug_reserved`); dział (blog) nie dostaje go
  nigdy (ADR-074 pkt 7, „Korzeń działu jest podstroną”).
- Zapisu bloków moduł nie obsługuje: `validate_site_block` rdzenia przyjmuje
  jego typy tak samo jak własne.
- **Rekord z treścią z bloków stawianych** (opis rasy jako lista bloków
  rdzenia) tłumaczy się tak jak wersja językowa podstrony — tymi samymi
  funkcjami z `saas_core.modules.shared.sites.api`, czystymi (bez bazy i bez
  tenanta): `extract_units(blocks)` daje fragmenty (`TextUnit`: klucz
  `<pozycja>/<ścieżka>`, rodzaj, klasa danych, limit), `assemble(blocks,
  texts)` składa bloki w innym języku (`AssembledBody`; błędy naraz w
  `LocaleUnitsInvalid.problems` jako `UnitProblem`), a `texts_against(source,
  blocks)` zamienia całe bloki z zewnątrz z powrotem na teksty fragmentów
  (`StructureDiffers`, gdy to nie jest to samo ciało z innym tekstem). Blok
  `serverBuilt` tą drogą nie przechodzi: `assemble` sprawdza bloki jak zapis.
- **Adres strony rekordu poza żądaniem strony** (odnośnik w panelu): z
  `source_page_base(język_strony_firmy, język, source.segment(język))` z tego
  samego `api`, plus slug rekordu. Funkcja tylko składa adres — nie wie, w
  których językach strona firmy jest czytana ani czy rekord ma tam stronę.
- **Witryna budowana kodem produktu** (komenda, która stawia podstrony,
  wygląd i menu z plików produktu): serwisy, które woła panel, z tego samego
  `api`, w kontekście osoby (`activate_tenant_context`) — każdy pyta o to samo
  uprawnienie co panel i tak samo odmawia automatyzacji (`person_required`).
  Obok podstron i szkiców (`create_page`, `save_draft`,
  `save_page_translation`, `publish_site`) są tam:
  - treść wersji językowej: `get_locale_body` (`LocaleBody`, w `units`
    `UnitState`), `save_locale_body`, `rebase_locale_body`;
  - wygląd, nagłówek i stopka: `get_site_appearance`, `save_site_appearance`;
  - menu podstron, zawsze całe naraz: `get_site_navigation`
    (`SiteNavigation`), `save_site_navigation`;
  - dział (blog): `list_collections`, `create_collection`,
    `set_collection_navigation`;
  - teksty witryny w jej innych językach: `list_site_texts` (`SiteTexts`,
    `SiteTextItem`), `save_site_texts`, `publish_site_texts`;
  - rodzaj podstrony i jej usunięcie: `set_page_type`, `delete_page`
    (`PageDeletion`).

  Odmowy, które taki kod łapie, mają tam swoje nazwy (`…VersionConflict`,
  `LocaleUnitInvalid`, `LocaleNotEnabled`, `PageIsHomepage`, `PageIsLast`…).
  Modele (`Site`, `Page`, `ContentCollection`) produkt dostaje w odpowiedziach;
  spod `shared.sites` nie importuje niczego poza `api`.

## 8. Gdzie typ istnieje

Typ modułu istnieje tam, gdzie **profil deploymentu składa moduł**:

| Warstwa | Skład z modułem | Skład bez modułu |
|---|---|---|
| zapis (draft, wpis, szablon firmy, change set) | walidacja schematem | `400 unknown_site_block_type` |
| `GET /api/v1/sites/capabilities/` | typ stawiany na liście `block_schemas` | brak |
| studio | formularz, biblioteka, „Dodaj pustą sekcję” | typu nie ma w rejestrze ani w bibliotece |
| strona publiczna | komponent modułu | typu nie ma w rejestrze |

Pliki modułu mogą leżeć w repozytorium obok profilu, który go nie składa
(jedno repo, kilka profili) — nic z nich nie jest wtedy czytane. Bramką jest
skład deploymentu, nie typ organizacji ani plan: czy dana firma ma rekordy do
pokazania, rozstrzyga moduł — jego źródło nie odpowiada i sekcji na stronie
nie ma.

Automatyzacja (SeoContentRank) widzi typ modułu w `capabilities` i może
zmieniać jego teksty jak każde inne; szablony stron dla blueprintów zostają
przy typach rdzenia.

## 9. Nowa wersja bloku

1. Dołóż plik schematu `…v<n+1>.schema.json`; poprzednich nie ruszaj.
2. W manifeście podnieś `latestVersion` i dopisz plik w `schemas`.
3. W zestawie dopisz schemat do `schemas` i migrator `migrators[n]` (dane
   wersji n → n+1).
4. Zalążki sekcji przepisz na nową wersję (`schemaVersion`, `version` sekcji).

Strony zapisane w starszej wersji zostają poprawne: backend trzyma walidator
każdej wersji, a renderer migruje dane przy rysowaniu.

## 10. Co sprawdza się samo

Produkt nie pisze tych kontroli — dostaje je z rdzeniem i przechodzi je
własną bramką:

| Kontrola | Co łapie |
|---|---|
| `manage.py check` — `sites.E011` | katalog w `modules/`, którego nazwa nie jest modułem katalogu (literówka w id) |
| `sites.E012` | manifest niezgodny ze schematem, typ bez nazwy modułu, dziura w wersjach, powielony typ, sekcja na bloku `serverBuilt` |
| `sites.E013` | ścieżka w `translation`, której nie ma w schemacie |
| `packages/contracts` — `site-block-contracts.test.mjs` | to samo bez Django, `$id` schematów, zalążki sekcji względem schematu |
| `defineModuleSiteBlocks` (przy imporcie zestawu) | rozjazd manifestu i kodu (§5.1) |
| `apps/frontend` — `product-site-blocks.test.tsx` | brak tekstu `Sites.*` dla nazwy bloku, pola albo opcji w pl/en; zalążek, którego schemat nie przyjmuje; axe na podglądzie każdej sekcji |
| testy rdzenia chodzące po wszystkich schematach (`test_site_localized_bodies.py`, reguła nazw odnośników) | u produktu obejmują też schematy jego modułu |

Własne testy modułu: budowany blok przez `validate_built_site_block`,
odpowiedzi źródła, render komponentów z axe.

## 11. Wzorzec: `vertical.sample`

Testowy wertykał, którego nie składa żaden profil; testy składają go same.

| Plik | Rola |
|---|---|
| `packages/contracts/site-blocks/fixtures/modules/vertical.sample/` | manifest i schematy: blok stawiany w dwóch wersjach z wyjątkami tłumaczeń i sekcją, blok strony rekordu |
| `apps/frontend/src/modules/shared/sites/testing/sample-module-blocks.tsx` | zestaw: komponenty, formularz, słowa |
| `apps/backend/tests/test_sites_module_blocks.py` | zapis, wersje, fragmenty, publikacja, odpowiedź źródła, strona rekordu, skład bez modułu, zepsute manifesty |
| `apps/frontend/src/modules/shared/sites/module-blocks.test.tsx`, `module-blocks-absent.test.tsx` | biblioteka, formularz, podgląd, strona opublikowana z axe; skład bez modułu |
| `packages/site-blocks/src/module-blocks.test.ts` | `defineModuleSiteBlocks` i jego odmowy |
