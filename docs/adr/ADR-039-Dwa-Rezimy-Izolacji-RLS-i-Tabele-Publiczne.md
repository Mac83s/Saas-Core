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

### 4. Klasyfikacja Sites

Klasyfikacja wykonana 2026-09-02 z rzeczywistych zapytań renderera
(`publication_routing.py`, `public_feeds.py`, `public_media.py`), nie z nazw.
Renderer czyta bez kontekstu tenanta dokładnie sześć tabel: `sites_domain`
(routing hosta), `sites_site` i `sites_publication` (przez `select_related`
z domeny do bieżącej publikacji), `sites_contentcollection`,
`sites_contententry` i `sites_contententrypublication` (wpisy publikują się
niezależnie od witryny). Te sześć jest zadeklarowane w `publicTables`.
`Site` i `ContentEntry` niosą obok tożsamości także wskaźniki stanu roboczego
(polityka edycji, blokada, wersja robocza), ale sama treść robocza żyje w
`PageVersion`/`ContentEntryVersion`, które są prywatne — to jest świadomy
kompromis: rozbicie tych dwóch tabel na część publiczną i prywatną nie jest
warte migracji, dopóki nie pojawi się w nich kolumna z treścią.

Prywatne, z RLS od migracji `sites.0024`: `DomainMutation`,
`SiteOnboardingDraft`, `SiteOnboardingMutation`, `Page`, `PageTranslation`,
`PageTranslationMutation`, `SiteRedirect` (przekierowanie widziane przez
odwiedzającego pochodzi ze snapshotu publikacji, nie z tabeli), `PageVersion`,
`PageBlock`, `ContentEntryVersion` i `ContentAutomationGrant`. RLS miały już
`NavigationItem`, `SiteOutboxEvent`, `ContentProposal`, `ContentTag` i
`ContentEntryTag`.

Konsekwencja dla komend operatorskich: `issue_content_grant` i
`revoke_content_grant` wymagają teraz `--organization`, bo bez ustawionego
tenanta nie da się odczytać klucza ani grantu — a odczyt „nieoznaczony" przed
`SET LOCAL` zwracałby pusty wynik zamiast błędu.

### 5. Stan wdrożenia i znany dług

Test kontraktowy ujawnił, że `shared.billing` nie ma RLS na żadnej z 11 tabel
tenantowych — moduł powstał przed listą RLS z ADR-022 i nie ma helpera
kontekstu; lifecycle, procesor webhooków i rekonsyliacja czytają przez
wszystkie organizacje. Zamiast dopisać migrację obok testu, dług jest zapisany
w `KNOWN_OPEN_PRIVATE_TABLES` (lista może tylko maleć: tabela, która dostanie
RLS, musi z niej zniknąć, inaczej test pada) i ma osobną pozycję w P1: najpierw
przepisanie ścieżek cross-tenant na iterację po organizacjach z `SET LOCAL`,
potem migracja.

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
