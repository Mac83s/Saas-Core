# ADR-039 — dwa reżimy izolacji: RLS domyślnie, tabele publiczne z deklaracji

**Status:** Accepted
**Data:** 2026-09-02
**Zatwierdzono:** 2026-09-02 (decyzja właściciela)
**Doprecyzowuje:** ADR-022 § RLS — nie usuwa RLS z żadnej tabeli, która je ma;
określa, które tabele tenantowe mogą go nie mieć, jak to jest deklarowane i
jak jest sprawdzane

## Kontekst

ADR-022 przyjął RLS jako drugą warstwę izolacji dla tabel z danymi osobowymi
lub prywatnymi i pozwolił rozszerzać je bez nowego ADR-u. W praktyce moduły
rozjechały się: `shared.booking`, `shared.media` i `shared.notifications` mają
wymuszone RLS na wszystkich tabelach tenantowych, a `shared.sites` tylko na
części (outbox, elementy nawigacji). Reszta tabel Sites polega na tenant scope
w serwisach i wyzwalaczach cross-tenant, bo publiczny renderer obsługuje
odwiedzającego bez kontekstu tenanta — wymuszone RLS na tabelach kolekcji
zablokowało publikację i migracja `0009` je zdjęła. HANDOFF zostawił pytanie,
która strona ma rację.

Dwa incydenty (klucz API, publiczne media) pokazały koszt drugiego wariantu:
odczyt tabeli z wymuszonym RLS przed `SET LOCAL` zwraca pusty wynik, a test z
rolą właściciela tabel tego nie wykrywa. Wymuszanie RLS wszędzie, łącznie z
rendererem, wymagałoby kontekstu serwisowego per host i mnożyło tę klasę
błędu. Zdjęcie RLS z całego Sites zostawiłoby drafty klientów pod ochroną
wyłącznie kodu aplikacji.

## Decyzja

### 1. Reżim domyślny: RLS

Każda tabela tenantowa (`TenantScopedModel`) ma `FORCE ROW LEVEL SECURITY`,
politykę na `app.organization_id` i wyzwalacz cross-tenant. Nowa tabela
tenantowa bez RLS jest błędem testu kontraktowego, nie decyzją do podjęcia
w migracji.

### 2. Reżim publiczny: z deklaracji w deskryptorze

Tabela może nie mieć RLS wyłącznie wtedy, gdy jest wymieniona w deskryptorze
swojego modułu w polu `backend.publicTables` (nazwy tabel bazy). Na listę
trafiają tylko tabele, które publiczny renderer czyta bez kontekstu tenanta i
które z definicji zawierają stan opublikowany albo routing: opublikowane
snapshoty i publikacje, routing domen, przekierowania widziane przez
odwiedzającego, publikacje wpisów. Drafty, wersje robocze, granty, klucze,
mutacje i outbox nigdy nie są publiczne.

Lista jest częścią kontraktu katalogu modułów (`module.schema.json`, P1), więc
widzi ją walidator deskryptorów, backend i frontend. Dodanie tabeli do listy
nie wymaga nowego ADR-u, ale wymaga uzasadnienia w opisie migracji i przejścia
testu z punktu 3.

### 3. Test kontraktowy na prawdziwym PostgreSQL

Jeden test dla wszystkich zainstalowanych modułów:

- każda tabela tenantowa spoza `publicTables` ma
  `pg_class.relforcerowsecurity = true` i politykę;
- każda tabela z `publicTables` istnieje, jest tenantowa (ma
  `organization_id` i wyzwalacz cross-tenant) i nie ma RLS — bo RLS na tabeli
  czytanej bez kontekstu daje puste odpowiedzi zamiast błędu, co jest gorszym
  trybem awarii niż jawny brak;
- odczyt tabeli publicznej bez kontekstu tenanta jest dozwolony wyłącznie w
  jawnie publicznych ścieżkach modułu (`public_views`, `publication_routing`,
  `public_feeds`, `public_media` w Sites); API panelu czyta wszystko w
  kontekście tenanta. Test kolejności zapytań (`SET LOCAL` przed pierwszym
  odczytem tabeli z RLS) obowiązuje dla każdej ścieżki poza request/task.

### 4. Klasyfikacja Sites (P1)

P1 klasyfikuje 22 tabele `shared.sites` na podstawie rzeczywistych zapytań
renderera, nie na podstawie nazw. Punkt wyjścia: prywatne są
`SiteOnboardingDraft`, `SiteOnboardingMutation`, `PageVersion`, `PageBlock`,
`PageTranslation`, `PageTranslationMutation`, `ContentProposal`,
`ContentEntryVersion`, `ContentAutomationGrant`, `DomainMutation`,
`NavigationItem` i `SiteOutboxEvent` (dwie ostatnie mają już RLS). Kandydaci
na publiczne to `Domain` (routing hosta), `Publication` i
`ContentEntryPublication` (opublikowany stan) oraz `SiteRedirect`. `Site`,
`Page`, `ContentCollection`, `ContentEntry` i tagi rozstrzyga analiza zapytań:
jeśli renderer czyta je bezpośrednio, są publiczne i muszą przestać nieść pola
robocze; jeśli czyta wyłącznie snapshot, dostają RLS.

## Konsekwencje

- Sites dostaje migrację z RLS na tabelach prywatnych; renderer nie zmienia
  ścieżki odczytu, bo czyta tylko tabele publiczne;
- deskryptor modułu zyskuje pole `publicTables`; walidator katalogu sprawdza,
  że wymienione tabele należą do modułu;
- dwa reżimy są jawne: nowy endpoint albo działa w kontekście tenanta, albo
  czyta wyłącznie tabele z listy — trzeciej możliwości test nie przepuszcza;
- koszt: jedna migracja Sites, rozszerzenie schematu deskryptora i jeden test
  kontraktowy; szacunek 3–4 dni w P1;
- ADR-022 pozostaje w mocy; ten dokument tylko nazywa wyjątek, który praktyka
  już stosowała, i zamyka go testem.

## Alternatywy odrzucone

- wymuszone RLS na całym Sites z kontekstem serwisowym w rendererze — spójne
  z literą ADR-022, ale każdy publiczny odczyt musiałby najpierw rozwiązać host
  do organizacji i ustawić `SET LOCAL`; ta sama klasa błędu, która dwa razy
  wyłączyła produkt przy zielonych testach;
- cały moduł Sites bez RLS, zalegalizowany ADR-em — najtańsze, ale drafty
  klientów chroni wyłącznie kod aplikacji;
- lista tabel publicznych w kodzie Pythona zamiast w deskryptorze — niewidoczna
  dla walidatora katalogu i frontendu, łatwa do rozjechania z migracjami;
- klasyfikacja po nazwach tabel bez analizy zapytań renderera — zgadywanie.

## Relacje

- doprecyzowuje ADR-022; korzysta z kontraktu modułów ADR-021;
- realizowane w P1 planu poaudytowego razem z uzgodnieniem katalogu modułów;
- decyzje Memex „Odczyt tabeli z wymuszonym RLS wymaga SET LOCAL przed
  zapytaniem" i „Zaplanowana publikacja odtwarza kontekst tenanta" opisują
  tryb awarii, który ten ADR ogranicza do jawnych ścieżek.
