# Plan 14 — integracja SaaS Core, SCR i SSA

Data: 2026-09-06. I0–I5 odebrano lokalnie; następnym zakresem jest I6, opisany
niżej. Maciej rozszerzył zgodę poleceniem „ok pracuje az skonczysz calość”;
kolejne przyrosty nie wymagają osobnego pytania o kontynuację. Weryfikacja
lokalna i dowód wdrożenia są osobne.
Podstawa: [ADR-043](../../docs/adr/ADR-043-Integracja-SaaS-Core-SCR-i-SSA.md)
i [kontrakt I0 v1](../../docs/architecture/seo-ecosystem-integration.md).
Plan nie zastępuje kolejności P0–P3 z planu 13 ani nie otwiera verticali.

### Bieżący odbiór wykonawczy, 2026-09-06

- [x] I2 Core backend/rozliczenia i panel audytów: `65a931b`, `463f2c5`;
  654 PostgreSQL, 120 frontend, build, następnie 29 testów SEO po ograniczeniu listy.
  Pilot HTTP potwierdza pojedyncze rozliczenie completed i zwolnienie partial.
- [x] I3 SSA/SCR: `c05919e`, `c7ffc84`, granty/OAuth/revocation/private copies;
  543 PostgreSQL SSA i 280 PostgreSQL/104 frontend SCR. Realna zgoda Google osobno.
- [x] I3 Core: `186157d`, panel i powiązanie zgody z dokładną sesją,
  blokada erasure przed disconnect; 690 PostgreSQL, 128 frontend,
  RLS czterech tabel bez tenanta/dla A/dla B: 0/1/1, osobny pilot HTTP.
- [x] I4 Core: kontrolowany katalog i przyjęcie nowego draftu zgodnie z ADR-046;
  16 testów PostgreSQL obejmuje RLS rzeczywistej roli, erasure i guard rollbacku,
  8 testów kolejki; osobny pilot SCR→Core bez wcześniejszego audytu 1 passed / 29,80 s.
- [x] I4 SCR: `6c621de`, ograniczony kosztowo worker, formularz briefu,
  katalog celów/szablonów, przegląd i dostarczenie do Core; pilot bez audytu.
- [x] I5 SSA: `60a84db`, idempotentne zlecenia wszystkich ośmiu modułów,
  560 PostgreSQL + 8 wyścigów worker/broker. Brak tworzenia nowego płatnego run po unknown.
- [x] I5 SCR: `1bc2bcc`, harmonogramy/jednorazowe zlecenia, pomiary i porównanie
  zgodnych danych; SSA `3123ca2` dostarcza wynik konkretnej operacji. Pełne suite:
  SSA 578 PostgreSQL, SCR 359 PostgreSQL + 3 testy zgodności kontraktu,
  frontend SCR 134 testy, lint/typy/build. Początkowy skip vendored contract
  sprawdzony osobno z jawną ścieżką katalogu Core.
- [x] WordPress `e8db148`: opis meta po zatwierdzeniu administratora,
  127 asercji PHP/MariaDB, dwa równoległe procesy z identycznym receiptem,
  26 asercji rzeczywistego HTTP (login, nonce, apply, replay, publiczny HTML).
- [x] Połączone API: osiem testów HTTP, 188,94 s. Granice Google/model/crawl
  syntetyczne; wynik nie jest potwierdzeniem konfiguracji dostawców.
- [x] SCR: `f1d9c95` kontrolowane 503, odseparowany błędny harmonogram i
  strumieniowy limit odpowiedzi; `971acae` jawnie włączane procesy projektów,
  briefów i obserwacji, obraz z kontraktami i obsługa zatrzymania. Końcowy cały
  backend **383 passed PostgreSQL / 19,65 s**. Obraz workerów: 19 asercji bez sieci.
- [x] Core-only: obraz uruchomiony, trzy moduły core, brak tras SEO/Sites i zadań
  okresowych; health backend/frontend zgodny, RLS roli aplikacyjnej poprawne,
  wszystkie pliki Pythona obrazu zgodne z checkoutem. Lokalny profil, bez deployu.
- [x] Końcowy odbiór lokalnych obrazów: Core `0c07d0f`, business i core-only
  zbudowane oraz uruchomione, zgodne profile frontend/backend. Business:
  siedem kontroli HTTP strony/sitemap/obrazu/odmowy/health, 344 pliki backendu
  zgodne z checkoutem, zero oczekujących migracji. Frontend końcowy: 131 testów.
  Naprawione braki wykryte dopiero w runtime: sekrety procesu migrate i route
  publicznych mediów. Konfiguracja produkcyjnych dostawców pozostaje osobną bramką.

Zakres odbioru to pierwsza wersja integracji, nie cały docelowy produkt SEO.
Brief uruchamia się w osobnym SCR dla istniejącej witryny i grantu Core;
asystent rozpoczynający proces z samego konta Core pozostaje dalszą pracą.
Kanał A4/WordPress obsługuje opis meta; nie edytuje artykułów i struktury.
Pełne granice oraz kolejność uruchomienia:
[odbiór integracji](../../docs/development/SEO-INTEGRATION-ACCEPTANCE.md).

## I6 — scalenie i pilot na instancjach

I0–I5 są ukończone i odebrane lokalnie w izolowanych gałęziach. Poniższa lista
jest następnym zakresem wykonawczym; nie jest częścią już odebranej implementacji.

- [ ] Przejrzeć trzy gałęzie integracyjne względem aktualnych głównych gałęzi,
  rozwiązać ewentualne kolizje z pracą równoległą i scalić w kolejności
  SSA → SCR → SaaS Core. Nie przenosić starszych handoffów ponad nowszym kodem.
- [ ] Zbudować i uruchomić osobne środowisko integracyjne każdego produktu:
  oddzielne bazy, sekrety, logi, storage i procesy workerów; zapisać SHA oraz
  digesty rzeczywiście uruchomionych obrazów.
- [ ] Skonfigurować źródła, ograniczone klucze, podpisane callbacki, ceny,
  features, połączenia celów i granty. Utworzyć wyłącznie syntetyczne konta
  testowe oraz jeden kontrolowany projekt.
- [ ] Powtórzyć osiem przepływów HTTP na uruchomionych instancjach, a następnie
  wykonać checklistę ręczną PL/EN z paneli Core i SCR. Instrukcja:
  [test ręczny integracji](../../docs/development/SEO-INTEGRATION-MANUAL-TEST.md).
- [ ] Na kontrolowanej usłudze Google wykonać zgodę GSC, synchronizację,
  cofnięcie pojedynczego grantu i pełne odłączenie. Zapisać wersje runtime,
  zakres property i potwierdzenie, że token nie wrócił do Core ani SCR.
- [ ] Wykonać jeden limitowany kosztowo audyt i jedną generację przez prawdziwych
  dostawców. Przed uruchomieniem ustawić twardy limit stron, kwoty i wywołań;
  po zakończeniu zapisać faktyczny koszt oraz wynik częściowy/pełny.
- [ ] Dopiero po zielonym pilocie przygotować manifest wydania, plan rollbacku,
  monitoring kolejek i stopniowe udostępnienie pierwszym klientom.

## Backlog produktu po pierwszej wersji integracji

Te pozycje są zapisanym kierunkiem, ale nie są jeszcze wdrożone:

- [ ] asystent i onboarding w Core, który zakłada i prowadzi proces SCR bez
  osobnego logowania klienta do SCR;
- [ ] planowanie oraz generowanie wielu podstron i struktury całej witryny;
- [ ] edycja artykułów i innych pól treści przez rozszerzony, wersjonowany
  kontrakt, z osobnym przeglądem i publikacją;
- [ ] pełna strategia SEO/GEO, rekomendacje struktury i koordynacja wielu
  modułów SSA w jednym planie pracy;
- [ ] cykliczne proponowanie lub publikowanie zmian zgodnie z polityką klienta,
  wraz z monitoringiem, budżetem i możliwością zatrzymania;
- [ ] Google Analytics oraz kolejne źródła pomiarów;
- [ ] jawny grant pokazujący klientowi w SSA historię audytów z innych produktów,
  bez ujawniania prywatnych danych GSC;
- [ ] WordPress: edycja szerszej treści i struktury, wielojęzyczność oraz
  testy zgodności na rzeczywistych wersjach Yoast i Rank Math;
- [ ] polityka retencji prywatnych kopii GSC i produktowy sposób opisywania
  zmiany wyników bez przypisywania jej automatycznie pojedynczej edycji.

Poniższe opisy zachowują wcześniejsze bramki i liczby testów jako historię.

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
- [x] **SCR:** trwała neutralna propozycja A4, powiązanie właściciela kandydata
  z generacją i celem, model logicznego projektu oraz resolver zasobów docelowych.
  Propozycja, API decyzji, projekt i resolver ukończone w `455981e`; panel,
  dostarczenie i brief w `c7ffc84`/`6c621de`, wiązanie projektu ze snapshotem
  w `1bc2bcc`. Zakres treści pierwszej wersji opisany w odbiorze, nie dowolny CMS.
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
  Zadanie jest rozwinięte jako I6 powyżej.
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
