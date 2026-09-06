# Integracja SEO — kontrakt koordynacyjny I0 v1

Stan rozpoznania: 2026-09-06. Obowiązuje [ADR-043](../adr/ADR-043-Integracja-SaaS-Core-SCR-i-SSA.md).
Dokument rozdziela wymagania od istniejących możliwości. Nowe nazwy logiczne
nie oznaczają wdrożonych pól modeli, endpointów ani migracji w pozostałych repozytoriach.

## Właściciel danych i odpowiedzialności

| Obszar | Właściciel | Kontrakt z pozostałymi usługami |
| --- | --- | --- |
| Konta, członkostwa, saldo klienta | Produkt, w którym klient kupuje usługę | Jawne mapowanie organizacji; bez wspólnej bazy kont i sald |
| Witryna SaaS Core, bloki, domena, draft, publikacja | Właściwe wdrożenie SaaS Core | Grantowane API treści; renderer czyta zatwierdzoną publikację |
| Brief, strategia i propozycja treści | SCR | Referencje do dowodów SSA oraz bazowej wersji celu |
| Crawl, SEO/GEO, moduły analityczne i dane dostawców | SSA | Tenantowe API wyników z zakresem i czasem pomiaru |
| Połączenie Google i pobrane dane prywatne | SSA w zakresie organizacji połączenia | Przyszła delegacja z I3; tokeny nie opuszczają magazynu |
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

To lista znaczeń, nie schema publicznego API ani istniejące narzędzie runtime.
Dokładny format konfiguracji zostanie przypięty przy wykonaniu pilota. Po zatwierdzeniu nie zmieniamy
tożsamości ani celu tego dokumentu: nowe przypisanie otrzymuje nową rewizję
i dowód zatwierdzenia. Digest kopii to dowód spójności, nie uwierzytelnienie.

Logiczna referencja ma `installation_id`, `organization_id` i `project_id`
lub `site_id`, osobno dla produktu źródłowego, SSA, SCR i celu SaaS Core.
UUID organizacji w różnych usługach nie muszą być równe.
Każdy identyfikator jest interpretowany we wskazanej instancji i organizacji.
Ten sam UUID z innego wdrożenia nie nazywa tego samego zasobu. URL, domena,
nazwa projektu i e-mail służą weryfikacji pomocniczej, nigdy wyborowi właściciela.
Logiczny projekt SCR jest wymaganiem I0, a nie istniejącym modelem SCR.
Do I1 operator mapuje istniejące zasoby; automatyczny resolver inventory pozostaje otwarty.

API każdej strony samodzielnie egzekwuje dostęp. Binding nie może zastąpić
tenant context, grantu ani kontroli zgodności `audit.project` z projektem powiązania.
Propozycja przenosi dokładną referencję do audytu, strony i reguły oraz do
bazowej wersji celu. Nie wyprowadzamy target ID przez podobieństwo URL.

## Uwierzytelnianie i obecne ograniczenia

| Kierunek | Obecna możliwość | Bramka przed rozszerzeniem |
| --- | --- | --- |
| Integracja → SSA | Bearer `ssa_live_*`, jedna organizacja, scopes | Brak grantu per projekt i delegacji wielu organizacji |
| SCR → SaaS Core | Klucz API, tenant i `ContentAutomationGrant` | Podgląd ma egzekwować permission, entitlement i grant także w serwisie |
| Klient → własny panel | Sesja danego produktu | Brak automatycznej sesji lub dostępu do innych produktów |
| SSA BFF → SSA Django | Zaufany service JWT | Klucz prywatny BFF nie jest poświadczeniem dla SCR ani SaaS Core |

W bazie SCR `b42e284` połączenia i generacja nie miały właściciela. Pakiet I0
gałęzi `codex/seo-integration-i0-i1` dodaje workspace połączenia i wywołania generacji;
serwisy change setów sprawdzają właściciela przez połączenie. Wysyłka odczytuje
aktualne cofnięcie i capabilities, sprawdza zapisany tryb oraz skrót wiążący payload
z celem. Adapter HTTP musi odpowiadać wybranemu połączeniu. Dawne nieprzypisane
rekordy pozostają nieaktywne. Przyszła warstwa A4 nadal musi powiązać właściciela
kandydata, neutralnej propozycji, generacji i celu; scoped helper nie zastępuje A4.

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

Obecny planner porównuje `base.version` z wersją Page/ContentEntry. Nie jest to
`publication.sequence` ani wersja tłumaczenia. Schema wymaga `snapshot_hash`,
ale planner go obecnie nie porównuje. Hash publikacji całej witryny i hash draftu
mają różne znaczenie: przed automatyzacją zapisu trzeba uzgodnić bazę i jej
weryfikację w SCR oraz SaaS Core. Pozostałe odczyty draftów i cykl zatwierdzania
propozycji także wymagają osobnego przeglądu; poprawka preview nie zamyka ich bramek.

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

Identyfikator operacji łączy produkty. SSA przyjmuje `X-Client-Reference`
(maksymalnie 64 znaki; obecnie obcina dłuższe wartości). Nie daje on idempotencji.
Jej zakres, hash payloadu i odczyt statusu muszą być określone przez endpoint;
SSA nie oferuje globalnej gwarancji `Idempotency-Key` dla wszystkich modułów.

Produkt sprzedający usługę rezerwuje i rozlicza kredyty raz. SSA rejestruje koszt
dostawcy i wynik w `ModuleRun`; `delivered=true` obejmuje completed i partial.
Sposób rozliczenia wyniku częściowego wymaga jawnej polityki oferty.
`GET /module-runs/` wymaga `billing:manage`; I1 nie rozszerza o niego klucza odczytowego.

Callback `module_run.finished` zawiera run ID, `run_reference`, `project_id`,
organization UUID, zewnętrzny `tenant_id`, `client_reference`, status i koszt.
Ma podpis oraz stabilne event ID dla pary przebieg/status. Odbiorca sprawdza
podpis, właściciela i deduplikuje skutki. Obecna konfiguracja SSA ma tylko jeden
`MODULE_RUN_WEBHOOK_URL` i sekret: routing do różnych produktów jest bramką I2.
Nie podmieniamy odbiorcy SSA BFF na SaaS Core, bo odebrałoby to BFF rozliczenia.

## Historia, GSC i retencja

Wewnętrzny projekt SSA nadal ma właściciela; brak konta klienta w panelu SSA
nie tworzy danych publicznych. Późniejsze połączenie kont wymaga jawnego grantu
do wybranego zbioru historii, ustalenia odbiorcy i zakresu oraz audytu decyzji.
Rejestracja, e-mail i obecne posiadanie domeny nie ujawniają raportów innych osób.
Prywatne dane GSC nie przechodzą automatycznie wraz z raportem publicznej witryny.

I3 zaprojektuje inicjowanie OAuth z SCR/SaaS Core i delegację wykonania w SSA.
Obecnie SSA ma jedno połączenie GSC na organizację, wiele property połączenia
i najwyżej jedną property przypisaną do projektu. Serializer nie zwraca tokenów.
Hosting strony nie oznacza automatycznie dostępu do jej prywatnych statystyk.
Osobne użycie GSC w panelu SSA wymaga osobnego połączenia zgodnie z wybranym zakresem usługi.

Obecne `apps/search_console/tenancy.py::disconnect` usuwa połączenie, property
i zsynchronizowane dane przez kaskadę. Nie obiecujemy zachowania metryk po
odłączeniu. W I3 odbiorcy muszą przestać pobierać i udostępniać dane w cofniętym
zakresie, a polityka usunięcia ich kopii, okresy retencji i minimalna historia
rozliczeń wymagają osobnego kontraktu. Nie tworzymy bezterminowego archiwum
prywatnych danych pod nazwą „historia audytów”.

## Przypięcie zgodności i dowody

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
