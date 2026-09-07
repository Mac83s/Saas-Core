# Integracja SEO — kontrakt koordynacyjny I0 v1

Stan implementacji: 2026-09-06, gałęzie integracyjne trzech repozytoriów.
Obowiązuje [ADR-043](../adr/ADR-043-Integracja-SaaS-Core-SCR-i-SSA.md),
uzupełniony przez ADR-045 (zamówienia audytu), ADR-046 (brief) i ADR-047 (GSC).
Dokument opisuje kontrakty zaimplementowane i sprawdzone lokalnie; nie oznacza
wdrożenia na instancjach klientów. Numery commitów i dowody są w
[planie 14](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md).

## Właściciel danych i odpowiedzialności

| Obszar | Właściciel | Kontrakt z pozostałymi usługami |
| --- | --- | --- |
| Konta, członkostwa, saldo klienta | Produkt, w którym klient kupuje usługę | Jawne mapowanie organizacji; bez wspólnej bazy kont i sald |
| Witryna SaaS Core, bloki, domena, draft, publikacja | Właściwe wdrożenie SaaS Core | Grantowane API treści; renderer czyta zatwierdzoną publikację |
| Brief, strategia i propozycja treści | SCR | Referencje do dowodów SSA oraz bazowej wersji celu |
| Crawl, SEO/GEO, moduły analityczne i dane dostawców | SSA | Tenantowe API wyników z zakresem i czasem pomiaru |
| Połączenie Google i pobrane dane prywatne | SSA w zakresie organizacji połączenia | Delegacja I3 ograniczona do projektu/property i czasu; tokeny nie opuszczają SSA |
| Koszt dostawcy i wykonanie modułu | SSA | Identyfikator przebiegu, status i koszt; bez zastępowania salda produktu |
| Zastosowanie treści na zewnętrznym CMS | Klient lub uprawniony adapter SCR | Osobne potwierdzenie zastosowania i publikacji |

Strona marketingowa platformy i każda witryna klienta są osobnymi projektami
logicznymi. Subdomena nie zmniejsza wymaganej izolacji. SCR standalone może
dostarczać treść w panelu lub przez API bez dostępu do kodu witryny klienta.

## Powiązanie instalacji i zasobów

Binding v1 jest kontrolowanym przez operatora dokumentem pilota. Wskazuje:

- wersję kontraktu, identyfikator powiązania oraz zatwierdzoną rewizję;
- produkt źródłowy, instancję wdrożenia i organizację zamawiającą;
- instancję SSA, organizację SSA, istniejący projekt i wybrany audit run;
- instancję SCR i workspace, logiczny projekt treści oraz wybrany cel;
- instancję SaaS Core, organizację, witrynę i konkretny zasób z locale;
- rodzaj powierzchni i bazową wersję/hash zasobu, tryb oraz dozwoloną komendę;
- referencje konfiguracji poświadczeń; żadnych sekretów ani tokenów.

To lista znaczeń, nie schema publicznego API. Wykonywalny `PilotBinding` v1
żyje w SCR `targets/resolver.py`; sprawdza inwentarz i bazę treści Core.
Po zatwierdzeniu nie zmieniamy
tożsamości ani celu tego dokumentu: nowe przypisanie otrzymuje nową rewizję
i dowód zatwierdzenia. Digest kopii to dowód spójności, nie uwierzytelnienie.

Logiczna referencja ma `installation_id`, `organization_id` i `project_id`
lub `site_id`, osobno dla produktu źródłowego, SSA, SCR i celu SaaS Core.
UUID organizacji w różnych usługach nie muszą być równe.
Każdy identyfikator jest interpretowany we wskazanej instancji i organizacji.
Ten sam UUID z innego wdrożenia nie nazywa tego samego zasobu. URL, domena,
nazwa projektu i e-mail służą weryfikacji pomocniczej, nigdy wyborowi właściciela.
Model `projects.Project` w SCR wiąże workspace, źródło SSA i odrębny projekt SSA.
Provisioning jest trwałą operacją: powtórzenie zachowuje tożsamość, a ten sam URL
u dwóch klientów daje dwa projekty. `observations.ProjectAuditBinding` łączy
projekt z konkretnym snapshotem; nie zastępuje identyfikatora projektu UUID audytu.

API każdej strony samodzielnie egzekwuje dostęp. Binding nie może zastąpić
tenant context, grantu ani kontroli zgodności `audit.project` z projektem powiązania.
Propozycja przenosi dokładną referencję do audytu, strony i reguły oraz do
bazowej wersji celu. Nie wyprowadzamy target ID przez podobieństwo URL.

## Uwierzytelnianie i obecne ograniczenia

| Kierunek | Obecna możliwość | Bramka przed rozszerzeniem |
| --- | --- | --- |
| Integracja → SSA | Operatorski klucz źródła, scopes, `X-External-Tenant-ID` | Źródło jest przypięte do produktu/wdrożenia; każdy zewnętrzny tenant ma osobną organizację SSA |
| SCR → SaaS Core | Klucz API, tenant i `ContentAutomationGrant` | Serwis podglądu i zapisu egzekwuje permission, entitlement, grant oraz bazę treści |
| Klient → własny panel | Sesja danego produktu | Brak automatycznej sesji lub dostępu do innych produktów |
| SSA BFF → SSA Django | Zaufany service JWT | Klucz prywatny BFF nie jest poświadczeniem dla SCR ani SaaS Core |

W bazie SCR `b42e284` połączenia i generacja nie miały właściciela. Pakiet I0
gałęzi `codex/seo-integration-i0-i1` dodaje workspace połączenia i wywołania generacji;
serwisy change setów sprawdzają właściciela przez połączenie. Wysyłka odczytuje
aktualne cofnięcie i capabilities, sprawdza zapisany tryb oraz skrót wiążący payload
z celem. Adapter HTTP musi odpowiadać wybranemu połączeniu. Dawne nieprzypisane
rekordy pozostają nieaktywne. Warstwa A4 zapisuje neutralną propozycję,
snapshot/ustalenie źródłowe, workspace, payload i decyzję człowieka. Dostarczenie
sprawdza zaakceptowany payload oraz aktualne uprawnienia połączenia.

Import SCR identyfikuje kopię audytu przez workspace, kanoniczny adres instancji
SSA i UUID przebiegu oraz sprawdza projekt przekazany operatorowi. Zmiana adresu
wdrożenia nie łączy automatycznie historii. Migracje zachowują dane; rollback
odmawia przy kolizji UUID między źródłami albo nazw połączeń między workspace.

Podgląd SaaS Core, dokładnie `POST /api/v1/sites/changes/`, wykonuje odczyt. Routing `content:read`
musi rozpoznawać tę semantykę. Naprawa pozwala użyć `content:read` i grantu
`suggest_only`, kontrolując uprawnienie, entitlement oraz zakres grantu przed
odczytem prywatnych bloków. Dowód: 14 testów w `test_content_preview_authorization.py`
i istniejące testy operacji; jest to kod gałęzi integracji, nie potwierdzenie deployu.

## Dowody i pierwszy przepływ I1

1. Operator wybiera zakończony audyt jednej strony platformowej i zatwierdza binding.
2. Klucz SSA z `projects:read` odczytuje `GET /api/v1/projects/{id}/` oraz
   `GET /api/v1/audit-runs/{id}/`; pilot odrzuca inny projekt lub niezakończony audit.
3. Pilot pobiera `/audit-runs/{id}/issues/` i `/pages/` z pełną paginacją.
   Odpowiedzi mają `count`, `next`, `previous`, `results`; `page_size` ma maksimum 100.
   `page_id` filtruje issues po stronie, `page` jest numerem strony paginacji.
4. Zachowuje czas pobrania, zakres crawla, `finished_at`, identyfikatory i digest
   kopii dowodów. `completed` nie znaczy `crawl_completeness=complete`.
5. Używa istniejącej propozycji metadanych lub deterministycznie przygotowanej
   propozycji na podstawie zatwierdzonej treści, bez nowego wywołania modelu.
6. Sprawdza capabilities, grant i bazową wersję celu, po czym wywołuje preview.
   Wynik jest podglądem; nie wykonuje apply, publish ani zmiany polityki strony.

Planner porównuje `base.version` z wersją Page/ContentEntry oraz weryfikuje
`base.snapshot_hash` z bieżącą bazą treści. Hash obejmuje również metadane,
więc sam niezmieniony numer draftu nie pozwala ominąć zmiany tłumaczenia.
Token przeglądu wiąże człowieka z dokładną treścią do zaakceptowania; zmiana
treści po podglądzie wymaga ponownego przeglądu. Receipt umożliwia odczyt
wyniku utraconej odpowiedzi bez utworzenia następnej wersji.

Nie uruchamiamy w I1 nowego crawla, GSC sync ani płatnego modułu. GET SSA może
aktualizować `ApiKey.last_used_at` co pięć minut oraz licznik cache: deklaracja
pilota brzmi „bez mutacji biznesowych i bez nowych analiz”, nie „zero zapisów”.

`/audit-runs/{id}/modules/` jest widokiem bieżącym; offsite wybiera ostatni
przebieg całego projektu. Nie jest niezmiennym manifestem źródeł danego audytu.
Status issues także może być zmieniany. Kopia odpowiedzi służy odtwarzalności
pilota, bez obietnicy trwałości danych źródłowych. Raporty zawierające dane
klientów nie są fixture'ami ani plikami do commita.

## Stan operacji i rozliczenia

Rozróżniamy: propozycję utworzoną, zaakceptowaną, dostarczoną, zastosowaną do
draftu, opublikowaną oraz późniejszy pomiar efektu. To semantyka integracji,
nie gotowy wspólny enum API. HTTP 2xx ani akceptacja propozycji nie potwierdzają
publikacji. Tryb nie może zmienić się między budową i wysyłką tego samego payloadu.

Identyfikator operacji łączy produkty. Nowe endpointy SSA
`/api/v1/integration/audits/` i `/integration/modules/` zapisują UUID
`client_reference`, hash żądania, źródło/tenanta i dokładny przebieg. POST
z tym samym żądaniem oraz GET po referencji odzyskują istniejący wynik.
Ta gwarancja dotyczy tych endpointów, nie dowolnego starszego endpointu SSA.
Nieznany wynik płatnego wywołania nie uprawnia do utworzenia nowego przebiegu.

Produkt sprzedający usługę rezerwuje i rozlicza kredyty raz. SSA rejestruje koszt
dostawcy i wynik w `ModuleRun`; `delivered=true` obejmuje completed i partial.
Core rezerwuje skonfigurowaną cenę, pokazuje ją przed zakupem i rozlicza raz
wyłącznie ukończony pełny raport; partial/failed/cancelled zwalniają rezerwację,
a nieznany stan ją zachowuje do uzgodnienia. Jest to polityka oferty Core.
`GET /module-runs/` wymaga `billing:manage`; I1 nie rozszerza o niego klucza odczytowego.

Callback `module_run.finished` zawiera run ID, `run_reference`, `project_id`,
organization UUID, zewnętrzny `tenant_id`, `client_reference`, status i koszt.
Ma podpis oraz stabilne event ID dla pary przebieg/status. Odbiorca sprawdza
podpis, właściciela i deduplikuje skutki. SSA wybiera odbiorcę z operatorskiego
`MODULE_RUN_CALLBACK_RECIPIENTS` przypiętego do źródła. Starszy odbiorca BFF
zachowuje własne zdarzenia. W Core callback budzi uzgodnienie przez API;
sam payload callbacku nie rozlicza kredytów.

## Historia, GSC i retencja

Wewnętrzny projekt SSA nadal ma właściciela; brak konta klienta w panelu SSA
nie tworzy danych publicznych. Późniejsze połączenie kont wymaga jawnego grantu
do wybranego zbioru historii, ustalenia odbiorcy i zakresu oraz audytu decyzji.
Rejestracja, e-mail i obecne posiadanie domeny nie ujawniają raportów innych osób.
Prywatne dane GSC nie przechodzą automatycznie wraz z raportem publicznej witryny.

I3 pozwala rozpocząć OAuth z SCR/SaaS Core i wykonać go w SSA. Core wiąże
jednorazowy stan z dokładną sesją, aktorem i organizacją. SSA przechowuje jedno
połączenie na organizację oraz osobne granty property/projektu z datą końca.
Synchronizacja stosuje zakres URL projektu również do agregatów i ponownie
sprawdza grant przed wywołaniem dostawcy i zapisem. Serializer nie zwraca tokenów.
Hosting strony nie oznacza automatycznie dostępu do jej prywatnych statystyk.
Osobne użycie GSC w panelu SSA wymaga osobnego połączenia zgodnie z wybranym zakresem usługi.

Obecne `apps/search_console/tenancy.py::disconnect` usuwa połączenie, property
i zsynchronizowane dane przez kaskadę. Nie obiecujemy zachowania metryk po
odłączeniu. Cofnięcie grantu usuwa jego prywatne kopie i blokuje kolejne odczyty;
disconnect usuwa połączenie i powiązane kopie. Core blokuje erasure dopóki nie
otrzyma potwierdzenia zdalnego sprzątania, także po utracie funkcji w planie.
Wygaśnięcie grantu od razu blokuje dostęp; operatorski okres fizycznego usuwania
wygasłych kopii wymaga polityki retencji przed uruchomieniem produkcyjnym.

Disconnect obejmuje wspólne połączenie całej organizacji źródłowej, wszystkie
jej granty i oczekujące autoryzacje wszystkich projektów. Revoke jednego grantu
ma węższy zakres. Panel wymaga jawnego potwierdzenia odłączenia workspace.

## Brief, kanały i obserwacje

Core udostępnia wersjonowany katalog kontrolowanych tekstowych pól szablonów.
SCR przyjmuje brief, rezerwuje limit wywołań przed dostawcą i zapisuje wynik do
przeglądu. Po akceptacji Core sam odtwarza szablon i tworzy propozycję nowego
draftu; model nie dostarcza dowolnego kodu ani JSON bloków. Nowa strona nie
wymaga audytu. Pierwszy przepływ obsługuje jedną podstronę na operację.
Startuje w odrębnej sesji/workspace SCR i wymaga istniejącego Core Site,
operatorskiego TargetConnection i grantu. Core nie ma jeszcze klienta SCR
ani formularza/asystenta rozpoczynającego ten brief w sesji klienta Core.

Neutralny kanał A4 obsługuje `set_meta_description`. Connector WordPress został
odłożony decyzją właściciela do osobnego etapu i nie wchodzi do obecnego `main`
ani środowiska testowego. Zachowany prototyp może być później punktem startu,
ale wymaga ponownego przeglądu oraz osobnej bramki kompatybilności.

SCR uruchamia jednorazowe lub ograniczone liczbą powtórzeń harmonogramy dla
ośmiu modułów SSA i crawla onsite. Pobiera wyniki przez `/results/` przypięte
do referencji operacji i zapisuje niezmienne pomiary. Brak wyników oznacza
dalsze pobieranie, nie zlecenie kolejnej płatnej analizy. Porównanie wymaga
zgodnego źródła, projektu, modułu, opcji, lokalizacji, silnika i kompletności.
Zmiana zaobserwowanej pozycji nie jest dowodem, że spowodowała ją zmiana treści.
Limit szczegółowego wyniku wynosi 2000 wierszy. Onsite daje punktację i uwagi,
`rank_keywords`/`serp_monitor` pozycje, pozostałe moduły wybrane agregaty;
`competitors` na tym etapie zwraca wyłącznie informacje o zakresie analizy.

## Przypięcie zgodności i dowody

Końcowe pakiety integracyjne: Core `186157d`, SCR `1bc2bcc` (po `6c621de`,
z pominięciem odłożonego WordPress `e8db148`) i SSA `3123ca2` (po `60a84db`). Osiem testów HTTP
przeszło w 188,94 s. Późniejsze poprawki uruchamiania i dowody obrazów są
zapisywane w planie 14 i HANDOFF, oddzielnie od konfiguracji produkcyjnej.

Poniższa tabela zachowuje **historyczny punkt startu rozpoznania**, nie stan końcowy:

| Repozytorium | Sprawdzony kod | Znaczenie |
| --- | --- | --- |
| SaaS Core | baza `3a5391b`, synchronizacja `9d9f916` | Integracja w osobnym worktree; późniejszy WIP Claude poza tym zakresem |
| SCR | `7dc4604`, baza `b42e284` | Ownership połączeń/generacji i powiązanie wysyłki; A4 i resolver otwarte |
| SSA | `ba197d7f70a7224d6f9d2fa2f73f295ad5a98fe5` | Tenantowe API i ledger; ograniczenia opisane powyżej |

To przypięcie odczytanych źródeł, nie potwierdzenie wdrożenia tych commitów.
Dowód runtime musi osobno wskazać instancje, wersje obrazów, konfigurację bez
sekretów, uruchomione polecenia i wynik. Zestawy SSA `test_api_keys`,
`test_tenancy_api`, `test_search_console_tenancy`, `test_module_callback` oraz
`test_api` pokazują aktualny kontrakt w kodzie testów; odczyt nie oznacza ich wykonania.

Odbiór i zależności: [plan I0–I5](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md).
