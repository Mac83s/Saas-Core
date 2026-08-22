# ADR-035 — publikacja systemowa i integracja z SeoContentRank

**Status:** Proposed
**Data:** 2026-08-21
**Właściciel:** zespół SaaS Core
**Wymaga zatwierdzenia przed:** W9.6.1

## Kontekst

ADR-027 ustanowił tenantowy `Site`, niemutowalne wersje stron, atomową
publikację całego serwisu i renderer kontrolowanych bloków. Ten kontrakt dobrze
obsługuje niewielkie strony firmowe. Nie opisuje jednak dwóch nowych potrzeb:

1. platforma musi publikować własne strony marketingowe i blogi bez tworzenia
   globalnego fallbacku omijającego `TenantContext`;
2. osobny system SeoContentRank ma analizować oraz proponować zmiany w treści
   klientów i treści platformowych, ale nie może otrzymać dostępu do bazy,
   dowolnego HTML ani nieograniczonego prawa publikacji.

Blog może docelowo zawierać setki lub tysiące wpisów. Dopisywanie każdego wpisu
do atomowego snapshotu całego `Site` powodowałoby rosnący koszt zapisu, odczytu i
rollbacku. Potrzebna jest osobna granica publikacji dla powtarzalnych wpisów,
przy zachowaniu wspólnych kontraktów bloków, tłumaczeń, mediów i SEO.

## Proponowana decyzja

### 1. Dwa rodzaje powierzchni treści

SaaS Core obsługuje dwa jawne rodzaje powierzchni:

- **site pages** — skończone, hierarchiczne strony i podstrony serwisu,
  publikowane nadal jako atomowy snapshot `Site` zgodnie z ADR-027;
- **content collections** — kolekcje powtarzalnych wpisów, np. blog, aktualności
  albo poradniki, w których każdy wpis ma własny niemutowalny draft, publikację
  i rollback, a indeks, RSS i sitemap są odtwarzalnymi projekcjami.

Oba rodzaje używają tych samych allowlistowanych bloków, wersjonowanych JSON
Schema, zasad PL/EN, mediów `ready`, canonical/hreflang oraz publicznego
renderera. Kolekcja nie interpretuje HTML, CSS ani JavaScriptu z danych.

### 2. Jawny właściciel treści systemowych

Treści marketingowe i blogowe samej platformy należą do chronionej organizacji
platformowej tworzonej idempotentnie dla konkretnego deploymentu. Organizacja
ma wyróżniony `workspace_kind=platform`, ale nadal korzysta z pełnego
`TenantContext`, permissionów, entitlementów, audytu i RLS tam, gdzie obowiązuje.

- nie istnieje globalny tenant ani fallback wybierany z `Host`, requestu lub
  braku kontekstu;
- użytkownik klienta nie może dołączyć do organizacji platformowej przez zwykły
  onboarding lub zaproszenie;
- operator zarządza członkostwem przez oddzielną ścieżkę z MFA i audytem;
- wewnętrzne entitlementy są nadawane jawnie przez konfigurację deploymentu,
  a nie przez pominięcie kontroli billingowej;
- domeny i routing nadal podlegają ADR-028 i ADR-031.

Ten sam mechanizm może później obsłużyć chronione strony platform pomocniczych,
ale każda z nich otrzymuje własną organizację i osobne granty integracyjne.

### 3. SaaS Core jest źródłem prawdy publikacji

SaaS Core pozostaje właścicielem:

- bieżącego draftu, immutable versions i optimistic locka;
- walidacji bloków, tłumaczeń, adresów, mediów i nawigacji;
- podglądu, diffu, approval digestu, publikacji i rollbacku;
- publicznego renderera, domen, sitemap, RSS i zdarzeń publikacyjnych;
- permissionów, entitlementów, grantów automatyzacji i audytu.

SeoContentRank pozostaje właścicielem analizy SEO/GEO, mapy tematów i fraz,
wykrywania kanibalizacji, rekomendacji, kampanii zmian, kosztów modeli oraz
pomiaru efektu. Nie zapisuje bezpośrednio modeli domenowych SaaS Core.

### 4. Grant automatyzacji zamiast szerokiego klucza

Klucz API z ADR-029 uwierzytelnia integrację i ustanawia dokładny tenant. Osobny,
odwoływalny `ContentAutomationGrant` ogranicza go dodatkowo do wskazanych
site'ów, stron, kolekcji lub wpisów oraz do dozwolonych komend.

Grant ma jawnie wybrany tryb:

- `suggest_only` — wyłącznie odczyt i propozycje;
- `draft_write` — propozycja może utworzyć nową wersję draftu;
- `publish_with_approval` — publikacja wymaga jednorazowego approval digestu;
- `auto_publish_limited` — automatyczna publikacja wyłącznie dla allowlisty
  niskiego ryzyka, z limitami częstotliwości i objętości.

Domyślny tryb to `suggest_only`. `auto_publish_limited` jest wyborem operatora,
ma termin ważności, emergency revoke i początkowo może być używany wyłącznie na
wewnętrznych powierzchniach platformowych. Zmiana domeny, nawigacji głównej,
stron prawnych, cennika, publikacja masowa i usunięcie treści zawsze wymagają
osobnego potwierdzenia niezależnie od trybu.

### 5. Wersjonowany kontrakt zmian

SeoContentRank wysyła `ContentChangeSet`, a nie dowolny JSON Patch. Dokument
zawiera wersję kontraktu, docelowy zasób, bazowy numer wersji i hash snapshotu,
klucz idempotencji, uzasadnienie oraz listę allowlistowanych komend, np.:

- utworzenie strony albo wpisu;
- zmiana metadanych SEO i kontrolowanych pól tłumaczenia;
- dodanie, aktualizacja, usunięcie lub zmiana kolejności kontrolowanego bloku;
- dodanie linku wewnętrznego do istniejącego, kanonicznego celu;
- zaplanowanie publikacji w dozwolonym oknie.

SaaS Core waliduje grant i aktualną wersję, buduje deterministyczny diff oraz
preview, wylicza approval digest i dopiero po spełnieniu polityki tworzy nowy
draft. Publikacja jest osobną komendą. Konflikt wersji zwraca `409`; SeoContentRank
musi pobrać nowy stan i jawnie przeliczyć propozycję zamiast nadpisywać zmianę.

### 6. Synchronizacja i niezawodność

- API jest wersjonowane w OpenAPI i używa Problem Details;
- każda mutacja ma `Idempotency-Key`, audyt i transakcję/outbox;
- zdarzenia publikacji są transformowane do podpisanych webhooków z delivery ID;
- retry jest at-least-once, a obie strony deduplikują skutki;
- odwołany grant lub klucz zatrzymuje nowe operacje natychmiast;
- niejednoznaczny timeout jest rozstrzygany przez odczyt statusu operacji, nie
  przez ślepe ponowienie;
- payloady i logi nie zawierają sekretów, pełnych promptów ani niepotrzebnych
  danych osobowych.

## Konsekwencje

- istniejące tenantowe modele `Site` i `Page` nie tracą obowiązkowego
  `organization_id` i nie otrzymują globalnej ścieżki dostępu;
- systemowe strony mogą korzystać z istniejącego renderera, domen i publikacji
  bez duplikowania całej platformy CMS;
- blog wymaga nowego modelu kolekcji i publikacji per wpis zamiast rozszerzania
  snapshotu całego site bez granic;
- integracja z SeoContentRank jest odwracalna i może rozpocząć się read-only,
  następnie przejść przez drafty i approval do ograniczonej automatyzacji;
- SaaS Core nie przejmuje crawlera, Search Console, analizy konkurencji ani
  generowania strategii treści.

## Alternatywy odrzucone

- globalne strony bez `TenantContext` — tworzą drugi, słabiej chroniony tor;
- sztuczny fallback tenant wybierany automatycznie — umożliwia pomyłkę zakresu;
- osobny CMS dla stron systemowych — duplikuje renderer, media, domeny i audyt;
- pełny blog w snapshotcie całego `Site` — koszt rośnie z każdym wpisem;
- bezpośredni dostęp SeoContentRank do bazy lub ORM — omija kontrakty domenowe;
- dowolny HTML/JavaScript albo ogólny JSON Patch — rozszerza powierzchnię XSS i
  utrudnia stabilną walidację ryzyka;
- jeden przełącznik „auto” dla całej organizacji — ma zbyt szeroki blast radius.

## Relacje

- rozszerza ADR-022, ADR-024, ADR-027, ADR-028, ADR-029, ADR-031 i ADR-033;
- wykonanie opisuje fala W9.6;
- zatwierdzenie ADR-u nie uruchamia automatycznej publikacji — każdy grant nadal
  wymaga jawnej konfiguracji i dowodu odbioru.
