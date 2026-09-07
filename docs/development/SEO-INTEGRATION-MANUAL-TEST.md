# Ręczny test integracji SaaS Core, SCR i SSA

## Co można sprawdzić od razu

Kod pierwszej wersji I0–I5 jest zatwierdzony w trzech izolowanych worktrees:

| Produkt | Ścieżka | Commit odbiorczy |
| --- | --- | --- |
| SaaS Core | `.runtime/worktrees/seo-integration-i0-i1` | `33238e4` |
| SeoContentRank | `.runtime/worktrees/scr-integration-i0-i1` | `971acae` |
| SEOSiteAudit | `.runtime/worktrees/ssa-ecosystem-integration` | `3123ca2` |

Można już powtórzyć automatyczny test współpracy trzech API. Nie wymaga on
klucza Google, modelu AI, DataForSEO ani płatnego crawla. Tworzy syntetyczne dane,
uruchamia osobne procesy SCR i SSA oraz sprawdza osiem przepływów przez HTTP.
Pełna komenda i wymagane zmienne są w
[SEO-INTEGRATION-LOCAL-PILOT.md](SEO-INTEGRATION-LOCAL-PILOT.md).

Przed uruchomieniem:

1. uruchom Docker Desktop i sprawdź `docker ps`;
2. uruchom PostgreSQL używany przez testy Core;
3. wskaż interpretery Python z trzech worktrees w zmiennych opisanych w pilocie;
4. nadaj nową nazwę bazy i nowy katalog `--basetemp` dla każdego przebiegu;
5. sprawdź, czy pytest kończy się wynikiem `8 passed`, a nie `skipped`.

Ten test jest obecnie najlepszym dowodem działania integracji jako całości.
Sprawdza prawdziwe endpointy i podpisy, idempotencję, kredyty, granty i odmowy,
ale zastępuje zewnętrznych dostawców kontrolowanymi odpowiedziami.

Można też odtworzyć publiczną stronę profilu `business`, jej sitemapę i obraz
przez skrypt opisany w [runtime/README.md](runtime/README.md). Wymaga on lokalnego
stosu Compose oraz fixture i nie jest testem onboardingu prawdziwego klienta.

## Co trzeba przygotować przed testem w przeglądarce

Nie ma jeszcze jednego gotowego adresu lokalnego, pod którym można zalogować się
i przeklikać wszystkie trzy produkty. Integracyjne commity nie są scalone do
głównych gałęzi, a zaakceptowany obraz workerów SCR nie zawiera serwera HTTP ani
frontendu. Obecny Docker nie działa, więc zachowane wcześniej stosy na portach
8896/8897 nie są teraz dostępne.

Przed testem użytkowym trzeba wykonać I6 z planu 14:

1. przejrzeć i scalić trzy gałęzie integracyjne z aktualnym kodem;
2. uruchomić osobne instancje SSA, SCR i Core z osobnymi bazami i sekretami;
3. wdrożyć migracje, API i frontend SCR/Core oraz trzy procesy workerów SCR;
4. utworzyć testowe konta, workspace, witrynę Core, projekt SCR i źródło SSA;
5. skonfigurować ograniczone klucze, callbacki, cenę audytu, features,
   połączenie do Core i granty;
6. dla GSC dodać klienta OAuth i kontrolowane konto Google; dla płatnego testu
   ustawić mały, twardy limit stron i kosztu.

To jest konfiguracja środowiska i scalenie odebranego kodu. Nie wymaga nowego
projektu architektury. Bez tych kroków można rzetelnie testować kontrakty, lecz
nie cały proces jako klient korzystający z paneli.

## Checklista testu użytkowego na wspólnym środowisku

Przy każdym scenariuszu zapisz adres środowiska, SHA i digest obrazów, użyte
konto testowe, czas rozpoczęcia, wynik oraz identyfikatory operacji. Wykonaj
scenariusze raz po polsku i podstawową nawigację ponownie po angielsku.

### 1. Audyt kupowany w SaaS Core

1. Zaloguj się do Core i otwórz `/pl/panel/seo`.
2. Wybierz witrynę, zobacz cenę i potwierdź audyt.
3. Sprawdź, że saldo ma rezerwację tylko raz, również po odświeżeniu strony.
4. Poczekaj na worker/SSA i otwórz raport w tym samym panelu.
5. Dla wyniku pełnego sprawdź pojedyncze rozliczenie. Dla wyniku częściowego
   sprawdź zwolnienie rezerwacji. Ponowiony callback nie może naliczyć drugi raz.

### 2. Projekt SCR i izolacja klienta

1. W SCR otwórz `/pl/dashboard/projects` i utwórz projekt dla domeny testowej.
2. Poczekaj, aż worker `projects` utworzy powiązany wewnętrzny projekt SSA.
3. Utwórz drugi workspace z tym samym URL-em.
4. Sprawdź, że powstaje inny projekt SSA oraz że konto drugiego workspace nie
   widzi projektu, audytu, propozycji ani pomiarów pierwszego.

### 3. Nowa podstrona z briefu

1. W SCR otwórz `/pl/dashboard/site-blueprints`.
2. Wybierz zatwierdzone połączenie do Core, istniejącą witrynę i szablon.
3. Wpisz brief, zleć generację i poczekaj na worker `blueprints`.
4. Otwórz wynik, przejrzyj teksty, zaakceptuj i dostarcz do Core.
5. W Core otwórz `/pl/panel/sites`, przejrzyj różnicę i zaakceptuj propozycję.
6. Sprawdź, że powstał jeden szkic nowej podstrony. Nie może zostać opublikowany
   automatycznie, a ponowienie dostawy nie może utworzyć drugiej wersji.

### 4. Poprawa opisu istniejącej strony

1. W SCR otwórz propozycję na `/pl/dashboard/proposals` i sprawdź ustalenie
   audytu, aktualny opis, proponowany opis oraz docelowy zasób.
2. Zaakceptuj propozycję i dostarcz ją do Core w trybie `preview` lub
   `draft_write`, zgodnie z grantem.
3. W Core na `/pl/panel/sites` sprawdź podgląd i zaakceptuj propozycję do szkicu.
4. Zmień stronę po przygotowaniu podglądu i potwierdź, że stara propozycja jest
   odrzucona jako oparta na nieaktualnej bazie.
5. Cofnij grant połączenia i potwierdź natychmiastową odmowę kolejnego odczytu.

### 5. Search Console

1. W Core otwórz `/pl/panel/seo/search-console` i rozpocznij połączenie.
2. Zaloguj się kontrolowanym kontem Google, wybierz właściwą property i wróć do
   panelu. Sprawdź, że Core widzi status/grant, ale nie otrzymuje refresh tokenu.
3. W SCR otwórz projekt, następnie jego ekran `search-console`, i nadaj grant
   tylko temu projektowi.
4. Uruchom ograniczoną synchronizację i sprawdź dane projektu.
5. Cofnij grant projektu, a potem wykonaj pełne odłączenie w produkcie źródłowym.
   Potwierdź usunięcie prywatnych kopii i zniknięcie blokady usunięcia konta.

### 6. Jednorazowa i cykliczna obserwacja

1. W SCR otwórz `/pl/dashboard/observations`.
2. Wybierz projekt, moduł oraz jednorazowy albo ograniczony harmonogram.
3. Poczekaj na worker `observations`, otwórz operację i wynik.
4. Ponów uzgodnienie tej samej operacji i sprawdź, że nie powstał drugi płatny
   run ani drugi snapshot.
5. Dla dwóch zgodnych pełnych pomiarów sprawdź porównanie. Traktuj je jako
   obserwowaną zmianę, bez automatycznego przypisania wyniku jednej edycji.

### 7. WordPress

1. Zainstaluj connector zgodnie z instrukcją w repo SCR:
   `connectors/wordpress/README.md`.
2. Pobierz bazę konkretnego wpisu przez `GET /wp-json/scr/v1/posts/{id}/base`
   i utwórz w SCR propozycję dla dokładnie tego targetu oraz hasha.
3. Zaakceptuj ją w SCR. W WordPress otwórz **Narzędzia → SeoContentRank**,
   podaj ID wpisu i propozycji, a następnie wczytaj podgląd.
4. Potwierdź zmianę. Sprawdź w publicznym HTML jeden opis meta oraz brak zmiany
   tytułu, treści, slugu i statusu publikacji.
5. Powtórz operację i sprawdź ten sam receipt. Zmień treść wpisu i potwierdź,
   że wcześniejsza baza jest odrzucona jako nieaktualna.

## Kryterium zakończenia pilota

Pilot można uznać za zakończony, gdy wszystkie scenariusze objęte wdrożeniem
mają dowód sukcesu i odpowiadający przypadek odmowy, kolejki nie mają starych
rekordów w stanie `running`, rozliczenia i receipty nie dublują się, a logi nie
zawierają sekretów ani prywatnej treści. Osobno trzeba zapisać ograniczenia:
wynik testu syntetycznego nie potwierdza dostawcy, a pojedynczy test płatny nie
potwierdza jeszcze gotowości do szerokiego ruchu produkcyjnego.
