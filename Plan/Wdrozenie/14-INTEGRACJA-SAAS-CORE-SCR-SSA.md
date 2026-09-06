# Plan 14 — integracja SaaS Core, SCR i SSA

Data: 2026-09-06. Aktywny zakres: I0–I5, w kolejności zależności. Maciej rozszerzył
zgodę poleceniem „ok pracuje az skonczysz calość”; kolejne przyrosty nie wymagają
osobnego pytania o kontynuację. Weryfikacja lokalna i dowód wdrożenia są osobne.
Podstawa: [ADR-043](../../docs/adr/ADR-043-Integracja-SaaS-Core-SCR-i-SSA.md)
i [kontrakt I0 v1](../../docs/architecture/seo-ecosystem-integration.md).
Plan nie zastępuje kolejności P0–P3 z planu 13 ani nie otwiera verticali.

## Organizacja pracy

Jedna sesja koordynuje kontrakty, odbiór i Memex. Zadania wykonawcze mają
właściciela repozytorium i jawne ścieżki; agent nie przejmuje zmian równoległych.
Claude zachowuje P3 w głównym SaaS Core. Integracja używa osobnego worktree
na bazie `3a5391b`, zsynchronizowanego z ukończonymi commitami profili `9d9f916`
i usuwania tenanta `4cc8684` (merge `96c4a6a`, migracja łącząca `a43aacf`).
Po scaleniu: 618 testów PostgreSQL. Scalenie wymaga przeglądu diffu względem aktualnego main,
nie odtworzenia starego HANDOFF ponad zmianami Claude.

Po spójnym pakiecie właściciel przekazuje commit, dokładny zakres, testy i
otwarte bramki. Koordynator aktualizuje plan, HANDOFF i jeden worklog Memex.
Praca w SSA/SCR zaczyna się od Memex CLI; same odczyty nie oznaczają wdrożenia.

## I0 — kontrakt i gotowość wykonawcza

- [x] **Koordynator:** zapisać podział odpowiedzialności, tożsamości, historii,
  GSC i rozliczeń. Dowód: ADR-043 oraz kontrakt I0 v1; nowe runtime API pozostają otwarte.
- [x] **Koordynator:** lokalny pilot używa ścisłego `PilotBinding` v1,
  wiążącego workspace, instancje, snapshot/audyt/projekt SSA, URL strony,
  connection i zasób/locale Core. Resolver porównuje inventory i content-base;
  nie dopasowuje właściciela po samym URL. SCR `455981e`.
- [x] **SCR:** przypisać `TargetConnection` i `GenerationCall` do workspace;
  serwisy `ContentChangeSet` sprawdzają właściciela przez połączenie. Dawne rekordy
  bez właściciela/powiązania zachowane i nieaktywne. Dowód: migracje i testy
  `test_target_workspace`, `test_target_workspace_migration`, `test_generation_workspace`.
- [ ] **SCR:** trwała neutralna propozycja A4, powiązanie właściciela kandydata
  z generacją i celem, model logicznego projektu oraz resolver zasobów docelowych.
  Propozycja, API decyzji, projekt i resolver ukończone w `455981e`; pozostaje
  pełny przepływ generacji i dostarczenia z panelu oraz połączenie projektu ze snapshotami.
- [x] **SCR:** deduplikacja audytu obejmuje workspace, kanoniczny adres instancji
  SSA i audit ID. `pull_audit --run` oraz serwis importu potwierdzają zgodność
  audytu z przekazanym projektem. Dowód: migracja audit0003 i `test_audit_source_binding`.
- [x] **SCR:** tryb zapisany razem z payloadem i skrótem powiązania; dostarczenie
  sprawdza aktualne połączenie, cofnięcie, capabilities oraz adapter HTTP.
  Parametr deliver nie rozszerza trybu build. Dowód: `test_target_workspace`
  i `test_saas_core_delivery`; brak żądań HTTP w przypadkach odmowy.
- [x] **SSA:** zewnętrzne powiązania i ograniczone granty historyczne:
  `d8d12f2`, 517 testów PostgreSQL. Źródło produktu/wdrożenia jest operatorskie,
  każdy zewnętrzny tenant ma osobną organizację; historia nie otwiera GSC.

I0 ma gotowy kierunek architektoniczny. Powyższe bramki wykonawcze nie są
zamknięte samym powstaniem dokumentacji lub istniejącego connectora.

## I1 — jedna propozycja metadanych i podgląd

- [x] **SaaS Core:** naprawić serwerową kontrolę permission, entitlement
  i grantu podglądu oraz klasyfikację POST preview jako `content:read`.
  Dowód: `preview_change_set`, dokładny wyjątek middleware oraz testy poniżej;
  zmiana w izolowanej gałęzi, bez deployu.
- [x] **SaaS Core:** testy właściwego i obcego tenanta, braku uprawnienia,
  entitlementu i kontekstu, zawieszenia organizacji, cofniętego lub obcego
  grantu, niezgodnej bazowej wersji oraz braku mutacji domenowych przy preview.
  Dowód: 14 nowych testów autoryzacji, istniejące testy content operations
  (w tym stale base), pełny backend 570 passed na świeżej bazie PostgreSQL.
  Asercja kolejności zapytań dowodzi ustawienia tenanta przed odczytem bloków;
  nie jest odbiorem izolacji RLS uruchomionego produktu.
- [x] **Koordynator:** artefakt pilota z przypiętym projektem/audytem SSA,
  docelowym zasobem SaaS Core, pełną paginacją, zakresem pomiaru i digestami.
- [x] **SCR:** deterministyczna propozycja na syntetycznym istniejącym audycie;
  A4 zapisuje payload, źródło, skróty i decyzję. Bez nowego modelu lub analizy.
- [ ] **Właściciele instancji:** wykonać pilot na uruchomionych API z właściwymi
  kluczami; zapisać wersje runtime osobno od SHA odczytanych repozytoriów.
- [x] **Koordynator:** potwierdzić brak apply/publish i nowych analiz; porównać
  wersję draftu/publication przed i po. Aktualizacja użycia klucza SSA jest dopuszczalna.

Odbiór I1 wymaga działającego podglądu jednej strony i przypadków odmowy,
nie samego sukcesu mocków. Testy na kontrolowanym lokalnym stacku można
ukończyć niezależnie: pilot trzech procesów przeszedł lokalnie (101 ustaleń,
HTTP 201/200/403, bez zmiany bazy). Pilot na skonfigurowanych instancjach
produktowych pozostaje otwarty; lokalne syntetyczne klucze go nie zastępują.
Publikacja całej witryny nadal należy do człowieka zgodnie z ADR-035.

## Kolejne etapy — autoryzowane, wykonywane po spełnieniu zależności

| Etap | Właściciele | Wynik i warunek rozpoczęcia |
| --- | --- | --- |
| I2 — audyt kupowany w produkcie | SaaS Core/SCR billing + SSA | Rezerwacja i pojedyncze rozliczenie, retry i partial; najpierw routing callbacków bez odebrania zdarzeń SSA BFF |
| I3 — delegacja GSC | SSA połączenia + panele SCR/SaaS Core | OAuth rozpoczęty z produktu, ograniczony grant, odwołanie i usunięcie kopii; bez przekazywania refresh tokenów |
| I4 — strona z briefu | SaaS Core assistant/sites + SCR | Aktywny katalog szablonów, treść do kontrolowanych bloków i zwykły draft/preview; nowa strona nie wymaga wcześniejszego crawla |
| I5 — kanały i cykle | SCR + SSA pomiary | Panel, API, CMS i harmonogram; osobno potwierdzone zastosowanie, publikacja oraz pomiar efektu; struktura CMS w późniejszym zakresie |

Przed skalowaniem na klientów wymagane są bramki izolacji SCR i powiązań SSA
z I0, trwała propozycja A4 oraz odbiór rozliczeń. Jednorazowa usługa i abonament
używają tej samej kontroli dostępu; harmonogram nie poszerza uprawnień.
Przed automatyzacją zapisu trzeba dodatkowo uzgodnić i egzekwować znaczenie
`base.snapshot_hash`, sprawdzić granty pozostałych odczytów draftów oraz cykl
zatwierdzania propozycji. Samo zabezpieczenie podglądu nie zamyka tych tematów.

## Dowody odbioru

Najnowszy pakiet: SCR `455981e` — 251 testów PostgreSQL (w tym rzeczywista
współbieżność propozycji i projektów), 91 testów frontendu, TypeScript, ESLint
i produkcyjny build. SSA `d8d12f2` — 517 PostgreSQL i osobny test stabilnej
paginacji. Core `b284533` — baza/digest/token i przegląd metadanych;
po scaleniu usuwania tenanta `a43aacf`: 618 PostgreSQL. Osobny test rzeczywistej
roli bez BYPASSRLS daje 0/1/1 widocznych propozycji bez tenanta/dla A/dla B.
Drugi pilot HTTP: SCR zakłada dwa projekty dla różnych klientów na tym samym
URL; SSA zachowuje odrębność i odmawia odczytu cudzego projektu (1 passed / 18,01 s).
Odtworzenie i granice dowodu: [pilot lokalny](../../docs/development/SEO-INTEGRATION-LOCAL-PILOT.md).

Kontynuacja: SCR `7dc4604` — 170 testów SQLite i 170 PostgreSQL, 69 frontendu,
lint/typy bez błędów i brak driftu API. Migracje od pustej bazy oraz rzeczywiste
cofnięcia i odmowy przy kolizjach sprawdzone na obu silnikach. Core po włączeniu
`9d9f916`: 579 testów backendu, 301 plików mypy, 1 kontrakt importów, 154 testy JS;
lint/typy/formatowanie i regeneracja API zgodne. Dokładne komendy/ograniczenia są
w HANDOFF. Główne katalogi repozytoriów i runtime pozostają poza tym pakietem.

Odbiór kodu gałęzi I0/I1, 2026-09-06: 570 testów backendu, 111 frontendu,
8 UI, 14 bloków stron i 21 kontraktów. Mypy: 288 plików; import-linter:
1 kontrakt zachowany. Node 24.13.0: lint i TypeScript bez błędów; oba profile
i artefakty aktualne. OpenAPI oraz klient zregenerowane bez driftu; migracje
bez zmian. Cztery nieaktualne testy deploymentu z bazy naprawione bez zmiany
implementacji. Dokładne ograniczenia i odtworzenie testów: [HANDOFF](../../docs/development/HANDOFF.md).

Każdy wynik wskazuje repo/commit, komendę, liczbę testów lub artefakt i granicę
wniosku. Lokalny zielony test nie dowodzi RLS, Caddy, konfiguracji połączeń
ani zgodności faktycznie uruchomionych obrazów. SaaS Core przechodzi właściwe
bramki `verify-saas-core-release`; testy kontraktowe pozostałych repozytoriów
uruchamiają ich właściciele. Wycofanie I1 polega na wyłączeniu pilota i cofnięciu
jego grantów/kluczy; nie wymaga kompensacji publikacji, bo I1 jej nie wykonuje.
