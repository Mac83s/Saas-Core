# Źródła tłumaczeń — protokół treści i silnika tłumaczeń

Wykonywalna połowa [ADR-069](../adr/ADR-069-Tlumaczenia-AI-Tresci.md): jak moduł z
treścią (strony, wizytówka, rezerwacje, produkt) oddaje ją silnikowi `shared.translation`
do tłumaczenia i przyjmuje wynik — własnymi serwisami, z własną publikacją. Prymitywy
(żetony, pochodzenie, skrót fragmentu, fakty) są w `main` od TL8a; rejestr, typy źródła
i polityki dopisuje TL5. Adaptery powstają w TL11 (strony firm), TL12 (wizytówka i
rezerwacje) i PU5 (Puppily). Normą są typy i reguły z §2–§9; przykład w §10 to
ilustracja. Ścieżki `content_protocol/…` to `apps/backend/src/saas_core/content_protocol/…`.

## 1. Gdzie leży i dlaczego

Protokół leży w neutralnym pakiecie `saas_core/content_protocol/`, nie w module
(decyzja memex `the-translation-source-registry-and-protocol-liv`):

- to pojęcia treści, nie organizacji — `core.organizations` stałby się workiem na
  wszystko;
- kontrakt warstw porządkuje tylko `saas_core.modules.*`, więc pakiet najwyższego
  poziomu (jak `saas_core/http`) importują `core`, `shared` i `vertical`; neutralność
  trzyma kontrakt `content-protocol-pure` w `apps/backend/.importlinter` (pakiet nie
  importuje `saas_core.modules` ani `saas_core.config`). Pakiet używa tylko biblioteki
  standardowej: nie dotyka bazy i nie czyta aktywnego tenanta — dostaje kontekst w
  argumencie;
- moduły treści nie zależą od silnika: profil musi składać każdą zależność modułu
  (`config/composition.py:296-310`), więc `shared.sites` importujący silnik ciągnąłby go
  do każdego profilu ze stronami. Bez silnika ręczne tłumaczenie działa, polityka mówi
  „wyłączone”, a zgłoszenia zmian nic nie robią.

Rejestry wypełniane w `AppConfig.ready` to wzorzec rdzenia
(`register_resource_reference_handler`, `register_erasure_rows`,
`register_email_template`).

## 2. Podział odpowiedzialności

| Kto | Co robi | Czego nie robi |
| --- | --- | --- |
| Moduł (adapter źródła) | wylicza obiekty i fragmenty z klasą danych i limitami; przenosi tłumaczenia na nową strukturę źródła; zapisuje tekst z pochodzeniem własnymi serwisami (blokady, audyt, idempotencja); bramka zapisu (fakty, tokeny, limity, terminy chronione); publikacja własną ścieżką; przegląd przez osobę | nie woła modelu, nie liczy kredytów, nie zna trybu firmy poza polityką |
| Silnik (`shared.translation`) | wycena, zlecenia, segmentacja, maski, glosariusz, kontrola jakości, wywołanie portu modeli, rozliczenie, popyt automatu, polityka publikacji | nie pisze tabel modułów, nie publikuje sam |
| `content_protocol` | typy, rejestr, gramatyka żetonów, pochodzenie, skróty, fakty, reguła decyzji publikacji | nie ma stanu poza rejestrami w pamięci |

## 3. Fragmenty

### 3.1. Rodzaje

Fragment to tekst jednego tłumaczalnego miejsca. Klucz jest stały **tylko w obrębie
bieżącej struktury źródła** (strony: pozycja bloku i ścieżka JSON); między wersjami
tłumaczenia przenosi adapter po skrócie tekstu (§6.2).

| Rodzaj | Co to jest | Co widzi model | Przykłady |
| --- | --- | --- | --- |
| `text` | zwykły tekst | cały tekst jako segment | tytuł, nagłówek i bio wizytówki, alt, etykieta |
| `inline` | bieg `core.rich_text` (akapit, nagłówek, punkt listy) z pogrubieniem, kursywą i linkiem jako `⟦n⟧…⟦/n⟧` | jeden segment z żetonami; kolejność par może się zmienić | akapit bloku tekstu |
| `name` | imię i nazwisko osoby | nic — kod kopiuje, do cyrylicy transliteruje | autor opinii i cytatu |
| `address` | adres pocztowy | nic — kod kopiuje | adres w `core.contact` |

Cztery rodzaje są w kodzie (`shared/sites/localized_bodies.py`, stałe `UNIT_*`); TL5
przenosi stałe rodzajów i klas danych do `content_protocol/units.py`, a `sites` je
importuje. Puppily dołoży `list`, `template` (zmienne jak `{breed}` maskowane) i
`document` (długi rich text, kontrakt PU2) — nowy rodzaj to zmiana tego dokumentu, bo
rodzaj wchodzi do skrótu. Slug nie jest fragmentem: liczy go moduł kodem z
przetłumaczonego tytułu (ADR-070 pkt 18). Adresy linków, kotwice, zdjęcia i `rel` to
struktura przepisywana ze źródła; liczby, daty i dane kontaktowe w osobnych polach nie
są fragmentami.

### 3.2. Klasy danych i znaczniki braków

| Klasa | Co oznacza | Kiedy wolno wysłać |
| --- | --- | --- |
| `public` | tekst marketingowy firmy | przy fladze `model_port.processor_listed` (obszar platformy zwolniony) |
| `public_personal` | tekst publiczny nazywający osoby: opinie, cytaty, rola autora, bio | dodatkowo, gdy profil wymienia ją w `ai.sendableDataClasses` (domyślnie tak, MedPlano nie) |
| `health` | dane o zdrowiu ludzi | nigdy |

Klasę deklaruje adapter per fragment, bo jeden obiekt miesza klasy (strona z opinią
klienta). Fragment, którego klasy nie wolno wysłać, zostaje do tłumaczenia ręcznego z
kodem `not_sendable`. Fragment ze znacznikiem „[Uzupełnij: …]” (`placeholder=True`)
nigdy nie idzie do modelu i blokuje kompletność, dopóki właściciel nie uzupełni źródła.

### 3.3. Skrót

`content_protocol.provenance.unit_hash(kind, text)` to sha256 z rodzaju, nowej linii i
tekstu po NFC ze zwiniętymi białymi znakami. Rodzaj wchodzi do skrótu, bo te same słowa
jako tytuł i jako etykietę linku tłumaczy się inaczej; ten sam tekst ma ten sam skrót w
każdym obiekcie i module — na tym stoi pamięć tłumaczeń niezależna od pozycji. Zmiana
samych odstępów nie czyni fragmentu nieaktualnym (świadomy kompromis). Postać
kanoniczna jest częścią kontraktu: jej zmiana wymaga ADR i migracji zapisanych skrótów.

## 4. Pochodzenie i stan fragmentu

Pochodzenie zapisuje adapter **obok tekstu celu, w tym samym wierszu i tej samej
transakcji** (strony: `PageLocaleVersion.units`; wizytówka i rezerwacje: wiersz
tłumaczenia; Puppily: wiersz języka). Typ jest jeden:
`content_protocol.provenance.Provenance(origin, source_hash, written_hash, model, at)`,
zapisywany jako `as_dict()`.

| `origin` | Kto pisze | Chroniony przed automatem | Liczy się jako |
| --- | --- | --- | --- |
| `ai` | silnik (`model` = model rozwiązany przez port) | nie, chyba że tekst różni się od `written_hash` | tłumaczenie |
| `human` | osoba w panelu, także „Zostaw bez zmian” i poprawka w przeglądzie | tak | tłumaczenie |
| `integration` | SCR albo inna integracja (`translation.update` zestawu zmian) | tak | tłumaczenie |
| `template` | nasiona szablonu w tym języku | nie | tłumaczenie |
| `import` | import o nieznanym autorstwie | nie | tłumaczenie |
| `copy` | tekst źródła wstawiony do ręcznego tłumaczenia | nie | brak |
| `untranslated` | tekst źródła stojący w miejscu tłumaczenia | nie | brak |

Import ze znanym autorstwem (Puppily, PU4) zapisuje `ai` albo `human`, a `source_hash`
liczy z bieżącego źródła — świadome założenie, że importowane tłumaczenia są aktualne.
Cel bez pochodzenia (zapisany przed protokołem, np. dzisiejsze metadane EN) jest
chroniony i niezweryfikowany.

Stan liczy `content_protocol.units.unit_states(units, targets)` (TL5):

| Stan | Znaczenie | Automat | Kliknięcie | Kliknięcie z „nadpisz poprawki” |
| --- | --- | --- | --- | --- |
| `missing` | brak celu, pusty cel, `copy` albo `untranslated` | wysyła | wysyła | wysyła |
| `fresh` | `source_hash` celu równy skrótowi bieżącego źródła | nic | nic | nic |
| `stale`, niechroniony | źródło zmieniło się od zapisu celu | wysyła | wysyła | wysyła |
| `stale`, chroniony | jak wyżej, ale cel napisała osoba albo integracja | wysyła jako propozycję: wynik zawsze `pending` z `overwrites_human` | jak automat; wycena liczy propozycje osobno, osoba może je pominąć | wysyła i nadpisuje |
| `unverified` | cel bez pochodzenia | nigdy | jako propozycja, tylko z opcją „także niezweryfikowane” | nadpisuje |
| `blocked` | źródło ma znacznik braku | nigdy | nigdy | nigdy |
| `copied` | `name` albo `address` | nigdy | nigdy | nigdy |

`content_protocol.units.sendable_units(units, targets, *, sendable, protected,
include_unverified)` składa tę tabelę z klasami danych; tę samą funkcję wołają wycena,
planowanie automatu i zestaw testów, więc „co kosztuje” i „co idzie do modelu” nie mogą
się rozjechać.

```python
# content_protocol/units.py — TL5
type UnitKind = Literal["text", "inline", "name", "address"]
type DataClass = Literal["public", "public_personal", "health"]
type UnitStatus = Literal["missing", "fresh", "stale", "unverified", "blocked", "copied"]
type ProtectedMode = Literal["skip", "propose", "overwrite"]


@dataclass(frozen=True, slots=True)
class Unit:
    key: str                 # stable within the current source structure only
    kind: UnitKind
    text: str                # the source text; inline marks as tokens
    data_class: DataClass
    max_length: int | None   # hard limit in code points
    required: bool = True    # a publishable target needs it
    placeholder: bool = False

    @property
    def source_hash(self) -> str:
        return unit_hash(self.kind, self.text)


@dataclass(frozen=True, slots=True)
class Target:
    text: str
    provenance: Provenance | None  # None: written before provenance existed


@dataclass(frozen=True, slots=True)
class UnitState:
    status: UnitStatus
    protected: bool
```

`TextUnit` stron (`shared/sites/localized_bodies.py`) ma te same pola — adapter stron
mapuje je jeden do jednego.

## 5. Rejestr

```python
# content_protocol/registry.py — TL5
class TranslationRegistryError(RuntimeError): ...  # raised from AppConfig.ready: stops the start

def register_translation_source(source: TranslationSource) -> None: ...  # same object again: no-op
def translation_source(key: str) -> TranslationSource: ...
def translation_sources() -> tuple[TranslationSource, ...]: ...       # sorted by key

def register_translation_policy(provider: TranslationPolicyProvider) -> None: ...  # the engine, once
def translation_policy(*, organization_id: UUID) -> TranslationPolicy: ...  # POLICY_OFF without it

def register_source_change_listener(listener: Callable[[SourceChangeNotice], None]) -> None: ...
def notify_source_changed(*, context: ContentContext, source_key: str,
                          object_ids: Iterable[UUID], change: SourceChange = "changed",
                          cause: str) -> None: ...
```

Rejestracja sprawdza deklarację od razu, więc zepsuty adapter zatrzymuje start, a nie
zlecenie klienta: klucz `<etykieta aplikacji>.<rzecz>` (prefiks `testing.` tylko ze
ścieżki testowej, §11); etykiety `pl` i `en`; rekord na żywo ma tylko podstawę
`published` i zapis `live`; źródło wersjonowane zapisuje co najmniej `pending` i `live`,
`draft` wtedy i tylko wtedy, gdy ma podstawę `working`; inny obiekt pod zajętym kluczem
to błąd.

| Klucz | Moduł | Rodzaj | Podstawy | Zapis | Dokument prawny | Faza |
| --- | --- | --- | --- | --- | --- | --- |
| `sites.page` | `shared.sites` | wersjonowane | `published`, `working` | `draft`, `pending`, `live` | podstrona `PageType.LEGAL` | TL11 |
| `sites.entry` | `shared.sites` | wersjonowane, osobna publikacja języka (rodzeństwo) | `published`, `working` | `draft`, `pending`, `live` | nie | TL11 |
| `sites.site_texts` | `shared.sites` | wersjonowane (`SiteTextTranslation`) | `published` | `pending`, `live` | nie | TL11 |
| `profiles.public_profile` | `shared.profiles` | rekord na żywo | `published` | `live` | nie | TL12 |
| `booking.service`, `booking.location`, `booking.team`, `booking.resource` | `shared.booking` | rekord na żywo | `published` | `live` | nie | TL12 |
| `puppily.*` (rasa, wpis, kategoria, dokument) | `vertical.puppily` | wersjonowane | `published` (`working` od PU10) | `pending`, `live` | dokument prawny | PU5 |

## 6. Adapter

```python
# content_protocol/sources.py — TL5
type Basis = Literal["published", "working"]   # what visitors see / the editor's draft
type Staging = Literal["live_record", "versioned"]
type SourceAction = Literal["read", "translate", "publish", "withdraw"]
type ReviewAction = Literal["accept", "discard", "withdraw"]
type OutcomeState = Literal["live", "pending", "draft", "conflict", "refused"]


class ContentContext(Protocol):
    """TenantContext fits as it is; acting_* come with A1a (ADR-076)."""
    organization_id: UUID
    membership_id: UUID | None
    actor_id: UUID | None
    principal_kind: str
    credential_id: UUID | None
    acting_via: str          # "" | "assistant" | "ai_translation"
    acting_ref: str
    acting_trigger: str
    def has_permission(self, permission: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ObjectRef:
    object_id: UUID
    label: str                     # customer text: data, never an instruction
    scope: str                     # publication scope, e.g. the site
    priority: int                  # 0 goes first (the home page)
    public: bool                   # has a public surface now; automation plans only these
    published_version: str | None  # opaque tokens, compared for equality only
    working_version: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class SourceRead:
    object_id: UUID
    locale: str
    basis: Basis
    scope: str
    source_locale: str
    basis_version: str             # opaque: the source version the units come from
    target_version: str | None     # opaque: the target version the targets come from
    units: tuple[Unit, ...]
    targets: Mapping[str, Target]  # by unit key, realigned to this structure
    facts: PublicationFacts
    excluded: str | None = None    # deleted, withdrawn, source_unpublished,
                                   # locale_is_source, locale_not_enabled


@dataclass(frozen=True, slots=True)
class WriteItem:
    object_id: UUID
    locale: str
    basis: Basis
    basis_version: str
    target_version: str | None
    texts: Mapping[str, tuple[str, Provenance]]  # delivered, past the engine's hard checks
    requested: WriteTarget
    reason: str | None = None                     # e.g. qa_flagged when requested == "pending"


@dataclass(frozen=True, slots=True)
class WriteBatch:
    source_key: str
    scope: str
    trigger: Trigger
    protected: ProtectedMode
    items: tuple[WriteItem, ...]   # in priority order
    idempotency_key: str           # stable per (job, batch, scope)
    published_in_job: frozenset[UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    object_id: UUID
    locale: str
    state: OutcomeState
    keys: tuple[str, ...]          # one item may give two outcomes
    reason: str | None = None
    errors: tuple[FieldError, ...] = ()   # A1a format, field = units.<key>
    target_version: str | None = None


class TranslationSource(Protocol):
    key: str
    module_id: str                 # gated per organization type
    labels: Mapping[str, str]      # {"pl": ..., "en": ...}
    staging: Staging
    bases: frozenset[Basis]
    write_targets: frozenset[WriteTarget]
    translations_publish_separately: bool

    def authorize(self, *, context: ContentContext, action: SourceAction,
                  object_ids: Sequence[UUID]) -> None: ...
    def list_objects(self, *, context: ContentContext, cursor: str | None, limit: int,
                     changed_since: datetime | None = None) -> ObjectPage: ...
    def read(self, *, context: ContentContext, object_id: UUID, locale: str,
             basis: Basis) -> SourceRead: ...
    def write(self, *, context: ContentContext, batch: WriteBatch) -> tuple[WriteOutcome, ...]: ...
    def publish(self, *, context: ContentContext, scope: str, job_ref: str,
                idempotency_key: str) -> str | None: ...   # publication id; no-op for live records
    def completeness(self, *, context: ContentContext, object_id: UUID,
                     locale: str) -> Completeness: ...
    def protected_terms(self, *, context: ContentContext,
                        object_id: UUID) -> tuple[ProtectedTerm, ...]: ...
    def review(self, *, context: ContentContext, action: ReviewAction,
               items: Sequence[ReviewItem], idempotency_key: str) -> tuple[WriteOutcome, ...]: ...
    def revert(self, *, context: ContentContext, job_ref: str,
               idempotency_key: str) -> tuple[WriteOutcome, ...]: ...

# Plain frozen dataclasses as well: ObjectPage(items, next_cursor),
# Completeness(complete, publishable, untranslated, reasons),
# ReviewItem(object_id, locale, expected_version), ProtectedTerm(text, rule: "keep" | "name"),
# FieldError(field, code, message).
```

### 6.1. `list_objects`

Stronami (`limit` do 200, kolejność stała) każdy obiekt z publicznym tekstem źródłowym
albo szkicem, bez usuniętych i wycofanych. `public` mówi, czy obiekt ma dziś publiczną
powierzchnię (strony: podstrona w bieżącej migawce; wizytówka: wpis w katalogu) —
automat planuje tylko takie, kliknięcie także niepubliczne. `priority` 0 idzie pierwsze
(strona główna: język wchodzi na witrynę dopiero z nią, ADR-070 pkt 7). `changed_since`
służy dobowej naprawie zgłoszeń (§8.4).

### 6.2. `read`

Jedno wywołanie zwraca fragmenty źródła i cele dla trójki (obiekt, język, podstawa) —
razem, bo muszą pochodzić z tych samych wersji; tokeny wersji wracają przy zapisie.

- **Podstawa.** `published` widzą goście; automat tłumaczy zawsze ją, nigdy szkicu
  (ADR-070 pkt 6 i 9). Obiekt bez wersji publicznej zwraca dla `published`
  `excluded="source_unpublished"`.
- **Wyrównanie.** `targets` są podane dla bieżących fragmentów: po wstawieniu,
  przesunięciu albo usunięciu adapter przenosi cele z pochodzeniem po skrócie (strony:
  pamięć tłumaczeń, ADR-070 pkt 4–5; wizytówka i Puppily: stałe nazwy pól). Cel
  usuniętego fragmentu nie jest zgłaszany.
- **Fakty** (`PublicationFacts`, §7) opisują obiekt w języku celu dla czytającego
  kontekstu. `locale_live` dotyczy zakresu publikacji: strony — język jest w
  `live_locales` witryny; rekord na żywo — obiekt zakresu był już publiczny w tym
  języku. Nowa usługa w firmie, której widget mówi już po niemiecku, tłumaczy się więc
  sama, a pierwsze wejście języka wymaga kliknięcia.
- **Wartości** to tekst klienta (opinie, import, zestawy zmian SCR); adapter ich nie
  „czyści” — silnik podaje je modelowi jako dane i sprawdza wynik.

### 6.3. `write`

Silnik woła `write` raz na partię i zakres, wewnątrz własnej transakcji, w której
oznacza pozycje jako zapisane — zapis w module i stan zlecenia zatwierdzają się razem
albo wcale; adapter używa tylko zagnieżdżonego `transaction.atomic()`. Dla każdej
pozycji, w tej kolejności:

1. **Idempotencja.** Pozycja zapisana już pod tym kluczem z tym samym skrótem treści
   zwraca te same wyniki bez drugiego zapisu; z innym — `conflict` /
   `idempotency_conflict`. Sprawdzenie idzie przed porównaniem wersji, bo powtórka po
   udanym zapisie zobaczyłaby własną nową wersję.
2. **Blokady** własnych wierszy we własnej kolejności (strony: podstrona → strona www →
   `PageTranslation`). Wierszy silnika moduł nie blokuje.
3. **Wersje.** Inne `basis_version` — `conflict` / `source_changed`; inne
   `target_version` — `conflict` / `target_changed` (strony: `body_version`, ADR-070
   pkt 2). Silnik czyta wtedy ponownie i używa dostarczonych tłumaczeń po skrócie, bez
   nowego wywołania modelu.
4. **Decyzja.** `decide_publication` z polityką przeczytaną teraz i faktami policzonymi
   teraz (§7). Odmowa daje `refused` i niczego nie zapisuje.
5. **Bramka zapisu.** Fakty wyniku równe faktom źródła (`content_protocol.facts`; „120
   zł” przechodzi, „120 PLN” i „150 zł” nie), tokeny jak w źródle, limity, terminy
   chronione i reguły modułu. Niezgodne fragmenty dostają `pending` z `gate_failed` i
   błędami pól; silnik ich nie rozlicza.
6. **Ochrona.** Fragmenty o chronionym celu przy `propose` dają osobny wynik `pending` z
   `overwrites_human`; przy `overwrite` (tylko kliknięcie) idą według decyzji.
7. **Zapis** tekstu z pochodzeniem — dostarczone fragmenty plus przeniesione
   wyrównaniem — w jednym wierszu, z audytem modułu w kontekście zlecenia (kanał to
   principal, `acting_via="ai_translation"`, ADR-069 pkt 15). Slug liczy moduł kodem
   i nigdy nie zmienia zamrożonego (ADR-070 pkt 18).

`pending` w źródle wersjonowanym trafia tam, czego zwykła publikacja nie czyta (strony:
`body_pending` z `pending_reason`); w rekordzie na żywo nie jest zapisywany — trzyma go
kolejka przeglądu silnika. `draft` to cel szkicu. Zapis tłumaczenia nigdy nie zmienia
tekstu źródłowego ani `Page.version`, nie zgłasza zmiany (§8.4) i nie publikuje.

### 6.4. `publish`

Wyniki `live` źródła wersjonowanego wychodzą jedną publikacją na zakres i partię
(ADR-069 pkt 21): strony — pochodna publikacja `translation_job` opublikowanej migawki
z wersjami związanymi z opublikowanym źródłem (ADR-070 pkt 11), nigdy `publish_site`.
Rekord na żywo jest publiczny po commicie zapisu (wizytówka odświeża przy tym katalog),
więc `publish` nic nie robi. Linki wewnętrzne lokalizuje przy odczycie ładunek
publiczny modułu (ADR-070 pkt 15) — adapter ich nie przepisuje.

### 6.5. `completeness`

`complete` — każdy wymagany fragment ma tłumaczenie (`fresh`, `stale`, `unverified`,
`copied`); `missing` i `blocked` ją psują. `publishable` — kompletny i spełnia reguły
modułu, a `reasons` podaje jego kody (strony: ADR-070 pkt 6 — `metadata_incomplete`,
`untranslated_units`, `source_placeholder`, `locale_home_missing`,
`media_unavailable`, `source_unpublished`, `source_outdated`). Nieaktualny fragment nie
psuje kompletności, ale wersja stron, której źródło zmieniło fakt, jest wstrzymana z 307
(ADR-070 pkt 10). O widoczności decyduje moduł, nie silnik.

### 6.6. `review` i `revert`

Akceptacja, odrzucenie i zdjęcie tłumaczeń to decyzje osoby z prawem publikacji źródła
(ADR-070 pkt 12): `review` idzie przez `assert_person_required`, więc kontekst zlecenia
(`acting_via="ai_translation"`) dostaje `person_required` (pusta lista dozwolonych,
ADR-069 pkt 15), a asystent przechodzi tylko według tabeli A1a i z tokenem zgody
(ADR-076). Jedno wywołanie obejmuje wiele pozycji jednego zakresu i daje jedną
publikację — tak działa akceptacja zbiorcza i zatwierdzenie `mass_publication`. Rekord
na żywo przyjmuje akceptację jako `write` z wyzwalaczem `acceptance` i tymi samymi
warunkami osoby. Poprawki przed akceptacją mają pochodzenie `human`. `revert` przywraca
stan sprzed zlecenia (strony: pochodna publikacja `translation_revert`; rekord na żywo:
poprzedni tekst i pochodzenie) z audytem.

### 6.7. Uprawnienia i terminy chronione

`authorize(action)` sprawdza prawa modułu i entitlement dla `read`, `translate` (zapis
wersji celu), `publish` (wynik `live`, akceptacja) i `withdraw`; silnik osobno sprawdza
`translation.request` i `translation.manage`. Wycena nie woła `authorize(publish)`:
menedżer może zlecić tłumaczenie, a jego wyniki czekają z `publisher_required`. Serwisy
modułu sprawdzają prawa jeszcze raz przy zapisie, bo kontekst zlecenia odtwarza się z
członkostwa, które mogło je stracić. Silnik woła adapter tylko z kontekstem równym
aktywnemu. `protected_terms` podaje nazwę strony i marki (`keep`) oraz imiona i
nazwiska w tekście (`name`); silnik łączy je z glosariuszem firmy.

## 7. Polityka publikacji

```python
# content_protocol/policy.py — TL5
type WriteTarget = Literal["draft", "pending", "live"]
type TriggerKind = Literal["click", "automatic", "acceptance"]
type PolicyMode = Literal["off", "review", "automatic"]


@dataclass(frozen=True, slots=True)
class Trigger:
    kind: TriggerKind
    job_ref: str | None   # "translation_job:<uuid>"
    cause: str            # user | api_key | schedule | conversation:<uuid> (A1a acting_trigger)


@dataclass(frozen=True, slots=True)
class PublicationFacts:
    legal_document: bool           # waits for a person in every mode
    locale_live: bool              # the language is already public in the object's scope
    actor_may_publish: bool        # the acting person holds the module's publish right
    object_published_in_job: bool = False
    published_in_job: int = 0      # other objects this job made public


@dataclass(frozen=True, slots=True)
class TranslationPolicy:
    mode: PolicyMode               # strictest of company mode, operator override and ceiling
    reason: str | None             # engine_absent, kill_switch, organization_paused,
                                   # processor_not_listed, operator_forced_review
    mass_publication_cap: int      # operator setting, default 20


POLICY_OFF = TranslationPolicy(mode="off", reason="engine_absent", mass_publication_cap=0)


def decide_publication(*, policy: TranslationPolicy, requested: WriteTarget,
                       requested_reason: str | None, trigger: Trigger,
                       facts: PublicationFacts) -> PublicationDecision: ...
```

Politykę rejestruje silnik (z ustawień firmy, nadpisań operatora, sufitu wdrożenia i
profilu), a czyta moduł przy każdym zapisie AI — surowszy tryb obejmuje też zlecenia już
w kolejce. Bez silnika `POLICY_OFF`: zapisy AI są odrzucane, ręczne tłumaczenie działa,
bo zapisy osób i integracji polityki nie czytają. `decide_publication` to jedna
implementacja reguł ADR-069; pierwsza pasująca wygrywa:

1. **Akceptacja** (`acceptance`) → `requested` (`live`, dla podstawy `working` —
   `draft`). Wyłącznik zatrzymuje model i publikacje automatu, nie decyzje ludzi.
2. **Wyłączone** (`mode == "off"`) → odmowa z powodem polityki.
3. **Dokument prawny** → `pending` / `legal_document`, w każdym trybie i przy każdym
   wyzwalaczu — przed regułą szkicu, więc przetłumaczony szkic strony prawnej nie wyjdzie
   z najbliższym `publish_site` bez akceptacji.
4. **Szkic** (`requested == "draft"`) → `draft`: wychodzi z publikacją szkicu przez osobę.
5. **Przegląd na prośbę silnika** (`requested == "pending"`) → `pending` z powodem
   silnika (np. `qa_flagged`).
6. **Tryb „po akceptacji”** → `pending` / `review_mode` albo `operator_forced_review`.
7. **Osoba bez prawa publikacji** → `pending` / `publisher_required`.
8. **Pierwsze wejście języka** (`automatic` i `not locale_live`) → `pending` /
   `locale_first_appearance`. Samo „Dodaj język” niczego nie tłumaczy; zgodą jest
   kliknięcie „Przetłumacz” z wyceną.
9. **Publikacja masowa** (`automatic`, obiekt jeszcze nie wyszedł w tym zleceniu, a
   `published_in_job >= mass_publication_cap`) → `pending` / `mass_publication`. N liczy
   obiekty, nie pary (obiekt, język); kliknięcie z wyceną limitu nie ma.
10. W pozostałych przypadkach → `live`.

Moduł może decyzję tylko zaostrzyć (bramka `gate_failed`, `overwrites_human`, reguły
publikowalności), nigdy złagodzić. Silnik liczy te same reguły wcześniej, żeby nie
wydawać pieniędzy na darmo i uprzedzić osobę w wycenie; wyniki `mass_publication`
jednego zlecenia składa w jedną pozycję przeglądu.

## 8. Zgłoszenia zmian i popyt

```python
type SourceChange = Literal["changed", "withdrawn", "deleted"]

@dataclass(frozen=True, slots=True)
class SourceChangeNotice:
    organization_id: UUID
    source_key: str
    object_ids: tuple[UUID, ...]
    change: SourceChange
    cause: str               # user | api_key | schedule
    actor_id: UUID | None
    at: datetime
```

### 8.1. Kto zgłasza

Moduł zgłasza zmianę **publicznego tekstu źródłowego** z serwisu, który ją robi —
nigdy zapis szkicu.

| Moduł | Serwis | Zmiana |
| --- | --- | --- |
| `shared.sites` | `publish_site` — podstrony, których wersja źródła w nowej migawce się zmieniła, i teksty witryny | `changed` |
| `shared.sites` | `publish_entry` (osoba, grant SCR, harmonogram), z pominięciem rodzeństwa AI — ono nigdy nie jest źródłem | `changed` |
| `shared.sites` | `delete_page`; wycofanie wpisu | `deleted`; `withdrawn` |
| `shared.sites` | nie zgłaszają: publikacje pochodne (każdy powód) i `rollback_site` | — |
| `shared.profiles` | zmiana nagłówka, bio albo etykiety linku opublikowanej karty; `publish_profile` | `changed` |
| `shared.profiles` | `withdraw_profile`; `delete_profile` | `withdrawn`; `deleted` |
| `shared.booking` | utworzenie i zmiana nazwy usługi, miejsca, zespołu albo zasobu; ponowne włączenie | `changed` |
| `shared.booking` | wyłączenie; usunięcie | `withdrawn`; `deleted` |
| `vertical.puppily` | publikacja, wycofanie i usunięcie w serwisie redakcyjnym | wszystkie trzy |

### 8.2. Kontrakt wywołania

1. Moduł woła `notify_source_changed` w transakcji, która zmienia tekst, po zapisie i
   przed commitem, ze swoim kontekstem.
2. Funkcja nie wykonuje zapytań i nigdy nie rzuca. Bez odbiorcy wraca od razu; zły
   argument i wyjątek odbiorcy to wpisy w logu bez treści
   (`translation_source_change_rejected`, `…_failed`). Błąd zgłoszenia nie zatrzyma zapisu
   firmy.
3. Odbiorca silnika robi tylko `transaction.on_commit(…, robust=True)`: wycofana
   transakcja nie zostawia popytu, a wyjątek po commicie jest logowany (wzorzec kolejki
   indeksu katalogu, `shared/profiles/search_index.py`).
4. Moduł, który zgłasza z obsługi zdarzenia domenowego, nie pisze nic w transakcji
   dostarczenia — wyjątek obsługi zatrzymałby outbox stron i webhooki SCR.

### 8.3. Po stronie silnika (TL21)

1. Typ organizacji musi składać `shared.translation` i moduł źródła (pomocnik
   wydzielony do `core.organizations` z bramki modułów); inaczej zgłoszenie przepada.
2. `changed` przy włączonym automacie zapisuje albo odświeża jeden `TranslationDemand`
   na (firma, źródło, obiekt) z terminem „teraz + 5 minut”; kolejne zgłoszenia przesuwają
   termin najwyżej do 30 minut od pierwszego, więc ciągłe publikacje nie odkładają pracy
   bez końca. Bez zgody wiersza nie ma — panel pokazuje „Nieaktualne” i „Przetłumacz
   nieaktualne”.
3. `withdrawn` i `deleted` kasują popyt obiektu; dla źródła z osobną publikacją języka
   silnik zakłada pozycję przeglądu „wycofaj tłumaczenia”.
4. Co minutę silnik bierze dojrzały popyt, sprawdza zgodę w chwili uruchomienia
   (członkostwo osoby od zgody aktywne, z `translation.manage`, `authorize(publish)`
   źródła przechodzi), czyta tylko obiekty publiczne w podstawie `published` i tylko w
   językach żywych w zakresie, liczy `sendable_units` z `propose` i zakłada jedno
   zlecenie na zakres dla wszystkich języków, w kolejności `priority`, w miesięcznym
   limicie automatu i w saldzie.
5. Brak zgody, praw, limitu, salda albo dostawcy — popyt czeka z powodem, a osoby z
   `translation.manage` dostają jedno powiadomienie na okres.

### 8.4. Pętle i zgubione zgłoszenia

Zapis tłumaczenia zmienia cel, nie źródło, więc nie jest zgłaszany; publikacje pochodne
i rodzeństwo AI też nie. Callback po commicie może przepaść (proces zginie między
commitem a callbackiem): nikt nie płaci, nic nie wychodzi, a stan liczony na żywo
pokazuje tłumaczenie jako nieaktualne. Dlatego raz na dobę
`reconcile_translation_demand` przegląda `list_objects(changed_since=…)` firm z
włączonym automatem i zapisuje brakujący popyt tą samą drogą.

## 9. Przebieg zlecenia

1. **Wycena.** `translation.request`, `authorize(translate)`, `read` każdej pary
   (podstawa `published`, a dla szkicu otwartego w edytorze `working`), znaki z
   `sendable_units`; digest obejmuje skróty fragmentów, języki, cenę, tryb i opcje;
   wycena mówi, ile wyników poczeka i dlaczego (§7).
2. **Zlecenie.** Jedna pozycja na (obiekt, język), w kolejności `priority`; kontekst
   odtworzony z członkostwa osoby (klikającej albo od zgody) z
   `acting_via="ai_translation"`, `acting_ref="translation_job:<id>"` i
   `acting_trigger`.
3. **Praca.** Przed wysłaniem silnik czyta ponownie; terminy chronione i glosariusz idą
   do modelu jako dane, maski i kontrolę jakości robi silnik, wywołanie — port (ADR-068).
   Fragment po kontroli dostaje `Provenance(origin="ai", source_hash=<odczytany>,
   written_hash=<skrót wyniku>, model=<resolved_model>, at=…)`.
4. **Zapis** partiami: `write` na zakres, `requested` = `draft` dla podstawy `working`,
   inaczej `live` (albo `pending` z powodem silnika). Partia zamyka się na końcu części
   zlecenia albo gdy zlecenie czeka na pulę portu dłużej niż 30 minut — wtedy gotowe
   pozycje wychodzą jedną publikacją (`publish`), a zlecenie trwa dalej.
5. **Rozliczenie.** Silnik rozlicza znaki fragmentów zapisanych jako `live`, `pending`
   (poza `gate_failed`) i `draft` — także później odrzuconych w przeglądzie (ADR-069 pkt
   24); po konflikcie rozlicza tylko fragmenty ostatecznie zapisane.

Automat różni się tym, że kontekst to członkostwo osoby od zgody, podstawa jest zawsze
`published`, planowanie pomija obiekty niepubliczne i pierwsze wejście języka, a limit
publikacji masowej obowiązuje.

## 10. Przykład: wizytówka (`profiles.public_profile`)

Obiektem jest karta firmy (`PublicProfile` z `subject_kind=organization`); publiczna
jest tylko karta z wpisem w katalogu, a każdy jej zapis jest od razu publiczny — to
**rekord na żywo**. Fragmenty: `headline` (`text`, 200), `bio` (`text`, 4000) i
etykiety linków (`text`, 80, klucz od skrótu adresu, nie od pozycji); klasa `public`.
Nazwa firmy to termin chroniony `keep`; kontakt, miasto i adresy linków to struktura.
Tokeny wersji: `PublicProfile.version` i wersja wiersza tłumaczenia. TL12 dodaje do
`PublicProfileTranslation` pochodzenie per pole, klucz idempotencji ze skrótem i
blokadę wersji w `save_translation`.

Przebieg: salon dodaje niemiecki — nic się nie tłumaczy (ADR-071 pkt 5). Właścicielka
klika „Przetłumacz”: 1 215 znaków na jeden język to 2 jednostki po X kredytów; zlecenie
działa jako ona, `write` z `live` zapisuje wiersz `de` z pochodzeniem `ai` i odświeża
katalog. Poprawia ręcznie niemiecki nagłówek (`human`, chroniony). Później zmienia
polskie bio: `update_profile` zgłasza `changed`, po 5 minutach automat tłumaczy tylko
bio i zapisuje je `live` (język jest już żywy). Gdy zmieni też polski nagłówek, automat
wysyła go jako propozycję, a `write` daje dla niego osobny wynik `pending` z
`overwrites_human` — jej tekst zostaje publiczny do jej decyzji.

## 11. Zestaw testów kontraktu

Każdy adapter przechodzi ten sam zestaw, bez silnika: zestaw gra jego rolę
deterministyczną atrapą tłumacza i liczy stany funkcjami protokołu.
`apps/backend/src/saas_core/testing/translation_sources.py` (TL5, tylko dla testów)
daje klasę bazową `TranslationSourceContract`, protokół `SourceDriver` (moduł
implementuje go na prawdziwych tabelach: `create`, `insert`, `move`, `edit`, `delete`,
`publish`, `write_as_person`, `write_as_integration`, `copy_source`, `public_texts`),
atrapy `FakeDraftSource` i `FakeLiveRecordSource` oraz menedżery
`registered_translation_source`, `translation_policy_override` i
`captured_source_changes`, które przywracają globalne rejestry po teście. Kontrakty
`.importlinter`: moduły nie importują `saas_core.testing`, a `shared.sites`,
`shared.profiles`, `shared.booking` i warstwa `vertical` nie importują
`shared.translation`.

Scenariusze — punkt wyjścia: obiekt z fragmentami [A, B, C], opublikowany i
przetłumaczony na `de`:

| Scenariusz | Wymagany wynik |
| --- | --- |
| Wstawienie X między A i B | A, B, C `fresh` z niezmienionym pochodzeniem, X `missing`; do wysłania tylko X |
| Przesunięcie C przed A | wszystkie `fresh`, nic do wysłania; publicznie de(C), de(A), de(B) bez zapisu tłumaczenia |
| Edycja B → B′ | B `stale`, do wysłania tylko B′; wariant z poprawką osoby: B chroniony, automat daje osobny wynik `pending` / `overwrites_human`, tekst osoby zostaje publiczny |
| Usunięcie A | cel A nie występuje w `read`, kompletność bez zmian, nic do wysłania |
| Kopia zastępcza | cele `copy` są `missing`, wersja nie jest publiczna, zapis AI nadpisuje kopie |
| Edycja integracji B | pochodzenie `integration`, chroniony; po zmianie źródła kliknięcie bez „nadpisz poprawki” daje propozycję, nie nadpisanie |

Sprawdzenia dodatkowe: powtórka `write` z tym samym kluczem i treścią nic nie zmienia,
inna treść to `idempotency_conflict`, nieaktualne tokeny — `source_changed` i
`target_changed`; wyniki `pending` nie wychodzą zwykłą publikacją; reguły z §7 (dokument
prawny także dla `working`, `locale_first_appearance`, `publisher_required`,
`mass_publication` liczone po obiektach, `POLICY_OFF` → `refused`); bramka faktów w
każdym źródle; znacznik braku, `name` i `address` nigdy w `sendable_units`; `health`
nigdy, a przy `sendable={"public"}` znika `public_personal`; `notify_source_changed`
wykonuje zero zapytań, a odbiorca dostaje zgłoszenie dokładnie raz po commicie i żadne
po wycofaniu; skróty źródła po zapisie tłumaczenia są niezmienione; `review` z
kontekstem `acting_via="ai_translation"` daje `person_required`.

`test_every_registered_source_has_a_contract_test` pilnuje, że każde zarejestrowane
źródło (poza `testing.*`) ma podklasę `TranslationSourceContract` z tym kluczem, a
pierwszy segment klucza to etykieta aplikacji modułu, który je zarejestrował — nowe
źródło bez testu zatrzymuje CI, także w produktach.

## 12. Utrzymanie

- Nowe źródło to w jednym commicie: adapter, rejestracja w `AppConfig.ready`, zgłoszenia
  w serwisach modułu i test kontraktu ze sterownikiem.
- Zmiana protokołu (typ, pole, znaczenie metody, nowy rodzaj fragmentu) aktualizuje ten
  dokument w tym samym commicie, a gdy zmienia decyzję — także ADR-069.
- Produkty dokładają źródła nowymi plikami (ADR-049); brakujący punkt rozszerzenia
  dodaje się w Saas-Core.
