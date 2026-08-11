# ADR-027 — Sites, treść, media i atomowa publikacja

**Status:** Accepted
**Data:** 2026-08-11

## Kontekst

ADR-017 przyjął kontrolowane, wersjonowane bloki zamiast dowolnego page buildera
i zabronił wykonywania JavaScriptu klienta. W6 wymaga doprecyzowania granic
draftu, publikacji, tłumaczeń, renderera i mediów tak, aby implementacja nie
tworzyła ukrytego drugiego źródła prawdy ani nie osłabiła izolacji tenantów.

`shared.sites` i `shared.media` są niezależnymi modułami Shared. Oba korzystają z
organizacji, audytu oraz lokalnych entitlementów, ale nie mogą zależeć od
verticala MedPlano. Publiczny renderer musi odtwarzać dokładnie zatwierdzoną
publikację, nawet gdy draft jest już nowszy.

## Decyzja

### Model edycji i publikacji

- `Site` i `Page` są stabilnymi korzeniami tenantowymi. `Page` przechowuje
  rosnący numer wersji używany jako optimistic lock oraz wskaźnik bieżącego
  draftu.
- Każdy zaakceptowany zapis draftu tworzy nową, niemutowalną `PageVersion` wraz
  z niemutowalnymi `PageBlock`. Nie aktualizujemy treści istniejącej wersji.
- Zapis wymaga oczekiwanej wersji `Page`; konflikt zwraca Problem Details `409`
  i nie nadpisuje pracy drugiego edytora.
- `Publication` jest append-only. Zawiera kanoniczny snapshot całej strony,
  wersję schematu snapshotu i SHA-256 jego kanonicznej reprezentacji JSON.
- Publikacja wszystkich stron, nawigacji, tłumaczeń, motywu i referencji do
  mediów odbywa się w jednej transakcji. Dopiero po zapisie `Site` wskazuje nową
  bieżącą publikację, a zdarzenie outbox `sites.site.published.v1` powstaje w tej
  samej transakcji.
- Rollback nie zmienia draftu ani historycznej publikacji. Tworzy nowy rekord
  `Publication` z wybranym historycznym snapshotem, nowym autorem, czasem i
  audytem.
- Preview renderuje jawnie wskazaną wersję draftu i jest chroniony sesją panelu;
  publiczny renderer odczytuje wyłącznie bieżącą publikację.

### Kontrakt kontrolowanych bloków

- Stabilny identyfikator bloku ma postać `<namespace>.<name>`, a każdy rekord ma
  dodatni `schema_version`.
- Kanoniczne kontrakty danych bloków są JSON Schema przechowywanymi w
  `packages/contracts/site-blocks`. Backend i `@saas-core/site-blocks` walidują
  ten sam artefakt; formularze panelu mogą dodawać walidację Zod, ale nie tworzą
  równoległego kontraktu.
- Migratory są czystymi funkcjami `vN -> vN+1`, nie pomijają wersji i mają testy
  kompatybilności wstecznej. Odczyt starej publikacji może migrować dane w
  pamięci, lecz nie modyfikuje snapshotu.
- Renderer wybiera komponent wyłącznie z allowlistowanego registry aktywnych
  modułów. Dane bloku nigdy nie są interpretowane jako HTML, JavaScript, CSS ani
  nazwa dynamicznego importu.
- Vertical może rejestrować własny blok przez publiczny manifest i schemat, ale
  `shared.sites` nie importuje kodu verticala.

### Tłumaczenia, adresy i SEO

- Tłumaczenia są osobnymi rekordami z locale z profilu deploymentu; nie używamy
  kolumn `title_pl`, `title_en` ani dowolnych kodów języka z requestu.
- Każdy site ma locale bazowe. Publikacja wymaga kompletnej wersji bazowej;
  brakujące pole drugiego locale korzysta z jawnego fallbacku do bazowego tylko
  wtedy, gdy polityka pola na to pozwala.
- Domyślne locale używa adresu bez prefiksu, pozostałe locale prefiksu
  `/<locale>/`. Slug jest unikalny w obrębie `(site, locale)` i po pierwszej
  publikacji nie zmienia się przez zwykłą edycję.
- Każdy opublikowany wariant ma własny canonical, komplet `hreflang` dla
  dostępnych tłumaczeń i `x-default` wskazujący locale bazowe.

### Media i storage

- `shared.media` jest właścicielem `MediaAsset`. Prywatne rekordy i ich
  rozszerzenia otrzymują PostgreSQL RLS od pierwszej migracji zgodnie z ADR-022.
- Klucz obiektu zawiera identyfikator organizacji i losowy UUID; oryginalna nazwa
  pliku jest wyłącznie metadanymi po normalizacji i nigdy nie steruje ścieżką.
- Upload przechodzi stany `pending -> uploaded -> scanning -> ready` albo
  `rejected`. Tylko `ready` może wejść do publikacji.
- Backend wydaje krótkotrwałe, zakresowe signed uploady. Po uploadzie weryfikuje
  rozmiar, deklarowany MIME, magic bytes, dekodowanie obrazu i wynik skanera;
  usuwa EXIF przed utworzeniem wariantów. HTML, JavaScript i SVG są odrzucane w
  pierwszej wersji.
- Zapis assetu i naliczenie `storage.bytes` są idempotentne. Usuwanie jest
  dwuetapowe: najpierw tombstone i blokada nowych użyć, potem asynchroniczne
  usunięcie obiektu, gdy żadna publikacja go nie referencjonuje.
- Staging i production używają zewnętrznego S3 zgodnie z ADR-025. Lokalny Docker
  Desktop używa wyłącznie testowego SeaweedFS `4.41` w trybie `weed mini`, z
  przypiętym obrazem, prywatną siecią, losowymi sekretami plikowymi i
  preutworzonym bucketem. Emulator nie jest profilem stagingowym ani
  produkcyjnym.

### Autoryzacja i UI

- Każdy use case wymaga jawnego `TenantContext`. API osobno sprawdza permission
  `site.content.edit` albo `site.publish` oraz entitlement `sites.enabled`;
  media analogicznie sprawdzają `media.read`/`media.manage` i `storage.enabled`.
- Mutacje mają audyt, idempotency key oraz transakcję/outbox, jeśli emitują
  zdarzenie. Frontend nie jest granicą bezpieczeństwa.
- Panel korzysta wyłącznie z publicznego API `@saas-core/ui`. Krótkie locale
  używa `Select`, a wyszukiwalne zbiory stron, bloków i mediów używają
  `Combobox`. Formularze używają React Hook Form, Zod i Problem Details.

## Konsekwencje

- Historia draftów i publikacji rośnie append-only; retencja wersji wymaga
  osobnej, bezpiecznej polityki i nie jest częścią W6.1.
- Atomowy snapshot duplikuje część danych, ale usuwa zależność renderera od
  zmiennego draftu i pozwala jednoznacznie zweryfikować rollback.
- JSON Schema jest kontraktem między Pythonem i TypeScriptem; zmiana danych
  bloku wymaga nowej wersji i migratora.
- Lokalny emulator dowodzi kompatybilności protokołu S3, ale nie zastępuje testu
  wybranego zewnętrznego providera przed stagingiem.

## Alternatywy odrzucone

- mutowalna publikacja — uniemożliwia wiarygodny rollback i audyt;
- renderowanie bezpośrednio z draftu — grozi publikacją niezatwierdzonych zmian;
- dowolny HTML/JavaScript lub dynamiczny import z danych — rozszerza powierzchnię
  XSS i łamie ADR-017;
- JSON z tłumaczeniami w jednym rekordzie — utrudnia unikalność adresów, fallback
  i niezależną kompletność locale;
- MinIO lub otwarty LocalStack jako nowy lokalny standard — ich wcześniejsze
  dystrybucje zostały zarchiwizowane w 2026 roku; nie przyjmujemy
  nieutrzymywanego obrazu jako fundamentu nowej fali.

## Źródła

- `Plan/SaaS-Core-06-Rejestr-Decyzji.md` — ADR-017;
- `docs/adr/ADR-020-Frontend-i-System-UI.md`;
- `docs/adr/ADR-022-Identyfikatory-Tenancy-i-RLS.md`;
- `docs/adr/ADR-025-Runtime-Staging-Sekrety-i-Odtwarzanie.md`;
- `docs/architecture/api-and-events.md`;
- `docs/architecture/testing-strategy.md`;
- https://github.com/seaweedfs/seaweedfs/releases/tag/4.41;
- https://github.com/seaweedfs/seaweedfs#quick-start-with-weed-mini.
