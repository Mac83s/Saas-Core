# ADR-036 — tożsamość: `User`, `Organization`, `PublicProfile` i konto klienta

**Status:** Proposed — wymaga decyzji właściciela przed P3 planu poaudytowego
**Data:** 2026-09-02
**Właściciel:** zespół SaaS Core
**Rozszerza:** ADR-023 (sesje), ADR-030 (`Customer` niezależny od `User`),
ADR-031 (panel klienta) — żadnej z tych decyzji nie zastępuje

## Kontekst

Audyt z 2026-09-02 wykazał, że produkt ma trzy pojęcia osoby, które nie są od
siebie odróżnione ani jawnie połączone:

- `User` w `core.identity` jest kontem uwierzytelniającym: e-mail, status,
  locale, strefa czasowa, MFA. Nie ma żadnych danych publicznych i tak ma zostać;
- `Organization` w `core.organizations` jest tenantem; `Membership` z `Role`
  wiąże `User` z organizacją. Rodzaje workspace'u to `personal`, `business`
  i `platform`;
- `Customer` w `shared.booking` jest tenantową encją klienta końcowego,
  niezależną od `User` (ADR-030): kontakt, `contact_hash`, anonimizacja,
  self-service przez token przypięty do jednej wizyty. `StaffMember` jest osobną
  tenantową encją pracownika z `public_slug`, bez powiązania z kontem.

Brakuje: publicznego profilu osoby albo organizacji jako danych
ustrukturyzowanych (dziś to tylko bloki strony), konta klienta z historią wizyt
oraz reguł, kiedy i jak `Customer` może zostać połączony z `User`. Plan
poaudytowy (P0, P3) wymaga rozstrzygnięcia tych trzech rzeczy przed zmianą
modeli. Dodatkowo nierozstrzygnięte jest, czy konta są per platforma.

## Proponowana decyzja

### 1. `User` pozostaje wyłącznie kontem

`User` nie dostaje pól publicznych, opisu, zdjęcia ani specjalizacji. Wszystko,
co ktoś ma zobaczyć na stronie, żyje w `PublicProfile`. Operator platformy to
nadal `User.is_staff` z potwierdzonym MFA — nie jest to rola tenantowa.

### 2. Konta są per platforma

Każdy deployment ma własną tabelę `User`; osoba korzystająca z dwóch platform ma
dwa konta. Wspólne logowanie (SSO) między platformami pozostaje poza zakresem,
dopóki nie powstanie osobny ADR kontraktu tożsamości; nie wolno go realizować
przez współdzieloną bazę ani replikację użytkowników.

### 3. `PublicProfile` w nowym module `shared.profiles`

- nowy moduł `shared.profiles` z deskryptorem `dependsOn: ["core.organizations",
  "core.audit", "shared.media"]`, `urlPrefix: /api/v1/profiles`, permission
  `profiles.manage`, bez własnego entitlementu (publikację ogranicza plan przez
  `sites.enabled`);
- `PublicProfile` jest `TenantScopedModel` z RLS: `subject_kind` ∈
  `organization | person`, `display_name`, `headline`, `bio` (tekst z
  ograniczonym formatowaniem, bez HTML), `photo` (FK do `MediaAsset`),
  `contact` (telefon, e-mail publiczny, adres — pola jawne, nie blob),
  `links`, `languages`, `specializations` (lista kluczy słownika), `locale`
  i tłumaczenia pól tekstowych w tym samym mechanizmie co treść stron;
- organizacja ma dokładnie jeden profil `organization` (indeks częściowy
  unikalny); profili `person` może mieć dowolnie wiele;
- profil `person` może, ale nie musi, wskazywać `Membership` (osoba ma konto i
  edytuje własny profil) — pracownik bez konta panelowego również ma profil;
- dlaczego nie w `shared.sites`: `shared.booking` musi wskazać profil
  specjalisty, a Booking nie powinien zależeć od Sites; dlaczego nie w
  `core.organizations`: zdjęcie jest `MediaAsset`, a Core nie importuje Shared.

### 4. Powiązania profilu z Booking, Sites i verticalami

- `StaffMember` dostaje nullable FK `profile` do `PublicProfile` typu `person`
  w tej samej organizacji (wyzwalacz cross-tenant jak w innych relacjach);
- strona renderuje profil **przez odwołanie**: blok `core.profile` (dziś
  recepta `core.profile.v1`) i blok zespołu przechowują `profile_id`, a nie
  kopię pól. Snapshot publikacji (ADR-027) zawiera zrzut wskazanych profili w
  chwili publikacji, więc renderer publiczny nigdy nie czyta tabeli na żywo, a
  zmiana profilu jest widoczna po następnej publikacji — tak samo jak zmiana
  nawigacji;
- „profil prosty bez strony" z planu poaudytowego jest pakietem planu
  `profile` (ADR-032): jednostronicowa witryna z recepty `core.profile.v1` na
  subdomenie platformy. Nie powstaje drugi renderer ani druga ścieżka
  publikacji; „profil rozszerzony" to ta sama witryna z większą liczbą stron;
- vertical (np. medical) rozszerza profil własnymi polami we własnym modelu
  wskazującym `PublicProfile`, nie kolumnami w `shared.profiles`.

### 5. `Customer` pozostaje tenantowy; konto klienta jest dobrowolne

- `Customer` zostaje w `shared.booking` jako encja tenantowa (ADR-030) i
  dostaje nullable FK `user` do `User` (kierunek Shared → Core jest dozwolony);
- rezerwacja gościnna pozostaje domyślna i pełnoprawna; konto nie jest
  warunkiem żadnej operacji self-service;
- **łączenie jest zawsze per organizacja i zawsze z dowodem własności**:
  następuje wyłącznie wtedy, gdy zalogowany `User` z potwierdzonym adresem
  otwiera self-service link wizyty (token dowodzi dostępu do tej wizyty) albo
  rezerwuje będąc zalogowanym, a `contact_hash` klienta odpowiada potwierdzonemu
  adresowi konta. System nie skanuje wszystkich organizacji w poszukiwaniu
  pasujących adresów; personel organizacji nie może połączyć klienta z kontem;
- połączenie jest audytowane i odwracalne (klient może odpiąć konto), a jego
  zerwanie nie usuwa historii biznesowej organizacji.

### 6. Klient jako osobny rodzaj principala

Klient nie jest członkiem organizacji — ADR-030 odrzucił fikcyjne membership i
to obowiązuje. Panel klienta działa w `TenantContext` z
`principal_kind="customer"`, zakresem `customer_id` i organizacją tej
konkretnej wizyty; wszystkie odczyty przechodzą przez RLS i serwisy tak samo jak
dla tokenu self-service. Widok „moje wizyty" dla wielu organizacji jest
agregacją per organizacja, każda we własnym kontekście — bez globalnego
fallbacku i bez zapytania cross-tenant.

Panel klienta (ADR-031) obejmuje: przyszłe i historyczne wizyty, przełożenie i
anulowanie tymi samymi komendami co self-service, płatności (po ADR-037),
eksport i usunięcie konta.

### 7. Role

- `Membership` nadal ma jedną rolę; istniejące globalne szablony ról (dziś
  `owner` i `admin`) uzupełniamy o `staff`, `specialist` i `reception` jako
  szablony globalne z jawnymi zbiorami permission; vertical może dodać własne
  role tylko przez ten sam mechanizm;
- `customer` i `operator` **nie są rolami** `Membership`: pierwszy to principal
  z §6, drugi to `User.is_staff` z MFA;
- każda rola ma negatywne testy exact-tenant: rola w organizacji A nie daje
  żadnego odczytu w organizacji B, a `reception` nie edytuje profilu ani
  cennika.

### 8. Zgody, eksport i usunięcie

- `PolicyAcknowledgement(user, policy_key ∈ terms|privacy, version, locale,
  accepted_at)` w `core.identity`; obowiązujące wersje są konfiguracją
  deploymentu. Brak akceptacji nowej wersji blokuje tylko nowe operacje
  biznesowe — nigdy anulowania wizyty, eksportu ani usunięcia konta;
- eksport zwraca dane konta i, per połączona organizacja, dane klienta i wizyt
  w formacie maszynowym; generowany asynchronicznie przez kolejkę W8;
- usunięcie konta: unieważnienie sesji, tombstone `User` (e-mail zastąpiony
  identyfikatorem, status `deleted`), odpięcie i anonimizacja połączonych
  `Customer` zgodnie z ADR-030 — chyba że organizacja ma niewygasły obowiązek
  retencji (dokumenty sprzedaży po ADR-037); wtedy dane kontaktowe są
  anonimizowane natychmiast, a rekord biznesowy czeka do końca okresu;
- przyszłe wizyty muszą być anulowane przed usunięciem konta; system pokazuje
  to jawnie, nie usuwa ich po cichu.

## Decyzje wymagające właściciela

1. **Konta per platforma w pierwszym wydaniu** — rekomendacja: tak; SSO dopiero
   z osobnym kontraktem.
2. **Profile osób w pierwszym wydaniu** — czy pilot potrzebuje profili
   specjalistów (MedPlano: lekarze), czy wystarczy profil organizacji.
   Rekomendacja: oba, bo katalog lekarzy jest rdzeniem MedPlano.
3. **Domyślny okres retencji danych klienta** po ostatniej wizycie, gdy klient
   nie żąda usunięcia. Rekomendacja: 24 miesiące, konfigurowalne per
   deployment; dokumenty sprzedaży według osobnych przepisów (ADR-037).
4. **Czy aktywacja konta klienta wchodzi do zakresu pilota**, czy pilot działa
   wyłącznie na rezerwacji gościnnej. Rekomendacja: gościnna w pilocie,
   konto klienta w P3 zgodnie z planem — to nie zmienia modeli, tylko kolejność.
5. **Zbiory permission dla nowych ról** — do zatwierdzenia jako tabela w
   `docs/architecture/auth-and-tenant-context.md` przed migracją.

## Konsekwencje

- powstaje nowy moduł `shared.profiles` i migracje w `shared.booking`
  (`StaffMember.profile`, `Customer.user`) oraz `core.identity`
  (`PolicyAcknowledgement`, tombstone); żadna z nich nie jest wykonywana przed
  zatwierdzeniem tego ADR-u;
- pojawia się trzeci rodzaj principala obok `membership` i `service`; każdy
  endpoint klienta musi jawnie deklarować, który principal przyjmuje;
- snapshot publikacji rośnie o zrzut profili, ale renderer pozostaje jeden;
- konto klienta nie tworzy nowej ścieżki dostępu do cudzych wizyt: łączenie
  wymaga tokenu wizyty albo zalogowanej rezerwacji, więc znajomość adresu
  e-mail nie wystarcza.

## Alternatywy odrzucone

- pola publiczne na `User` — miesza konto z treścią i łamie „konto jest
  wyłącznie uwierzytelnianiem";
- `PublicProfile` w `shared.sites` — wymusza zależność Booking → Sites;
- `PublicProfile` w `core.organizations` — Core nie może wskazać `MediaAsset`;
- globalne dopasowanie `Customer` po e-mailu we wszystkich organizacjach —
  zapytanie cross-tenant i wektor przejęcia historii przez znajomość adresu;
- klient jako `Membership` z rolą `customer` — odrzucone już w ADR-030; dałoby
  klientowi tenantowe permission i widoczność w zespole;
- wspólna baza użytkowników wielu platform — sprzeczne z ADR-021 i decyzją
  planu poaudytowego o rozdziale danych produktów.

## Relacje

- realizuje P0 i P3 planu poaudytowego;
- rozszerza ADR-030 (Booking) i ADR-031 (panel klienta), korzysta z ADR-022
  (RLS, `TenantContext`), ADR-027 (snapshot publikacji), ADR-032 (plan
  `profile`);
- ADR-037 dostarcza płatności do panelu klienta i obowiązki retencji.
