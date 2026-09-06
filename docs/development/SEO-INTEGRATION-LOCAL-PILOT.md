# Lokalny pilot trzech usług

Aktualny zestaw zawiera sześć przypadków: podgląd bez zapisu; dostarczenie do
szkicu z przeglądem w Core; dwa niezależne projekty na tym samym URL; zamówienie
audytu completed; zamówienie partial; nowa strona z briefu bez istniejącego audytu.
W audytach rzeczywisty sender SSA wysyła dwukrotnie podpisany callback, a Core
uzgadnia status i pobiera 101 ustaleń; ledger kredytów zmienia się dokładnie raz.
Końcowy status audytu jest kontrolowanym fixture, nie pracą crawlera.

W briefie SCR pobiera rzeczywisty katalog Core i rezerwuje wywołanie przed modelem.
Tylko odpowiedź modelu jest zastąpiona syntetycznymi tekstami; create, accept,
deliver, katalog i receipt przechodzą przez właściwe API. Nie powstaje snapshot
wcześniejszego audytu. Core tworzy jeden draft i propozycję, człowiek akceptuje
jej podgląd, a powtórzenie dostawy nie tworzy kolejnej wersji ani publikacji.

Uruchomienie zawsze dostaje `--create-db` oraz własny `--basetemp=.runtime/<run>`.
Testy transakcyjne czyszczą również dane migracji; lokalny harness odtwarza ich
początkowy zapis pomiędzy przypadkami, bez aktualizacji niemutowalnych ról.

Test `apps/backend/integration_tests/test_seo_pilot_live.py` uruchamia osobne
procesy Django SSA i SCR oraz serwer HTTP Core z pytest. Każdy proces importuje
wyłącznie własną aplikację. SSA i SCR otrzymują nowe pliki SQLite; Core używa
osobnej bazy testowej PostgreSQL. Nie są uruchamiane crawl, modele AI, OAuth,
DataForSEO ani publikacja. Wszystkie dane i klucze są syntetyczne.

Przebieg tworzy zakończony audyt z 101 ustaleniami oraz jedną stroną. SCR czyta
go przez API SSA z pełną paginacją, weryfikuje projekt, zapisuje snapshot,
wykonuje handshake Core i pobiera rzeczywistą bazę treści. Następnie publiczne
API SCR zapisuje neutralną propozycję, a connector wywołuje podgląd Core.
Test porównuje hash i wersję treści oraz liczbę draftów i publikacji przed/po.
Cofnięcie grantu musi od razu zmienić odpowiedź odczytu bazy na 403.

Drugi test (`test_scr_provisions_independent_projects_in_ssa`) tworzy dwa
workspace SCR i operatorskie źródło SSA. Obaj klienci podają ten sam URL
i ten sam klucz idempotencji. API SCR zwraca 202, worker rozmawia przez HTTP
z SSA, a odczyt projektu potwierdza stan `ready`. Powtórzenie nie tworzy nowego
projektu; różni właściciele dostają różne projekty SSA. Odczyt własnego projektu
zwraca 200, cudzego 404. Liczba audytów pozostaje zerowa.

Przykład PowerShell, uruchomiony z katalogu roboczego Core (ścieżki interpreterów
trzeba wskazać dla własnego środowiska):

```powershell
$env:PYTHONPATH = '<Core>/apps/backend/src'
$env:POSTGRES_DB = 'saas_core_livepilot_20260906'
$env:POSTGRES_PASSWORD_FILE = '<private>/postgres_password'
$env:SCR_PILOT_REPO = '<SCR worktree>'
$env:SCR_PILOT_PYTHON = '<SCR python.exe>'
$env:SSA_PILOT_REPO = '<SSA worktree>'
$env:SSA_PILOT_PYTHON = '<SSA python.exe>'
& '<Core python.exe>' -m pytest -c apps/backend/pyproject.toml `
  apps/backend/integration_tests/test_seo_pilot_live.py -q `
  --reuse-db --create-db --tb=short --basetemp=.runtime/pytest-livepilot-unique
```

Przy powtórzeniu należy użyć nowego `--basetemp`. `--create-db` przywraca także
role katalogowe po testach transakcyjnych. Test nie jest automatycznie dołączony
do zwykłego suite Core: wymaga jawnych ścieżek dwóch innych repozytoriów i ich
środowisk. Brak ścieżek powoduje skip, a nie potwierdzenie integracji.

Wynik `evidence.json` jest prywatnym artefaktem w katalogu testu. Sąsiadujący
`private-context.json` zawiera wyłącznie testowe klucze, ale również nie trafia
do Git. Wynik wskazuje źródło, projekt, audyt, propozycję, zmianę, czas obserwacji,
kompletność crawla oraz wersję/hash bazy. `accepted` oznacza udany podgląd.

Pierwszy udany odbiór 2026-09-06: **1 passed / 25,16 s**, artefakt w
`.runtime/pytest-livepilot-05`. Sprawdzono 101 ustaleń, jedną stronę, zapis
propozycji HTTP 201, podgląd HTTP 200 i odmowę po cofnięciu grantu HTTP 403.
Kod był wtedy niezatwierdzonym przyrostem trzech gałęzi integracyjnych.

Provisioning: **1 passed / 18,01 s**, `.runtime/pytest-provision-live-01`.
Sprawdzony kod SCR zapisano następnie jako `455981e`, SSA jako `d8d12f2`.
Nie są to numery wdrożonych obrazów: test uruchamia checkouty przez wskazane
interpretery. Każde odtworzenie wymaga zapisania faktycznych HEAD i diffów.

Ten test potwierdza współpracę API na kontrolowanym lokalnym środowisku.
Nie potwierdza konfiguracji produkcyjnej, Caddy/TLS, wdrożonych obrazów,
rzeczywistego audytu klienta ani izolacji RLS: Core łączy się właścicielem bazy
testowej. Izolacja RLS ma osobny dowód pod rolą bez BYPASSRLS.
