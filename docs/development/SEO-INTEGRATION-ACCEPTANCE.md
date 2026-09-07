# Odbiór integracji SaaS Core, SCR i SSA — 2026-09-06

Jedna sesja koordynuje kontrakty i testy, a wykonawcy pracują w osobnych
repozytoriach i jawnych ścieżkach. Nie trzeba ręcznie przenosić ustaleń między
sesjami. Główne katalogi używane równolegle przez Claude pozostają nietknięte.
Ten dokument rozdziela dostarczoną pierwszą wersję integracji od pełnego
produktu SEO i jego uruchomienia komercyjnego.

## Dostarczone przepływy

| Potrzeba | Działający zakres pierwszej wersji |
| --- | --- |
| Marketing platformy i niezależne witryny klientów | Osobne projekty SCR i powiązane wewnętrzne projekty SSA. Ten sam URL nie łączy właścicieli ani historii. |
| Audyt kupowany w Core | Cena przed potwierdzeniem, rezerwacja kredytów, trwałe zlecenie SSA, raport w panelu Core, pojedyncze rozliczenie pełnego wyniku. Partial zwalnia rezerwację; nieznany wynik czeka na uzgodnienie. |
| Propozycja poprawy treści | Snapshot audytu, źródłowe ustalenie, neutralny payload, decyzja człowieka i aktualna baza treści celu. Pierwsza komenda to opis meta. |
| Dostarczenie do Core | Podgląd lub proponowany draft zgodnie z grantem. Ponowienie odczytuje potwierdzenie, a zmiana treści po podglądzie wymaga nowego przeglądu. |
| Nowa strona bez wcześniejszego audytu | Brief w SCR, kontrolowany katalog Core, limitowane wywołanie modelu, przegląd tekstów i dostarczenie jednej nowej podstrony jako szkicu. |
| Search Console w produktach | OAuth inicjowany z panelu, tokeny przechowywane tylko w SSA, grant property/projektu z terminem, ograniczona synchronizacja, odwołanie i usuwanie prywatnych kopii. |
| Niezależny klient zewnętrzny | Panel propozycji SCR i neutralne API treści. Klient integrujący własny system odpowiada za zastosowanie i potwierdzenie efektu. |
| WordPress | Administrator pobiera zaakceptowaną propozycję, przegląda ją i zapisuje wyłącznie opis meta. Kontrola wpisu, instalacji, aktualnej treści, nonce i trwałego potwierdzenia operacji. |
| Jednorazowa lub cykliczna obserwacja | Ograniczone harmonogramy ośmiu modułów SSA i onsite, niezmienne wyniki, historia oraz porównania wyłącznie zgodnych pełnych pomiarów. |

SCR nie otrzymuje dostępu do bazy, kodu ani powłoki Core. SSA nie publikuje
treści. Akceptacja w SCR nie zastępuje przeglądu i publikacji w Core.
W WordPressie administrator jawnie stosuje opis na istniejącym wpisie;
status publikacji wpisu i jego treść nie są zmieniane.

Brief rozpoczyna się obecnie w osobnej sesji/workspace SCR i wymaga istniejącej
witryny Core oraz skonfigurowanego przez operatora połączenia i grantu. Sama
rejestracja w Core nie otwiera konta SCR ani nie uruchamia generacji. Włączenie
tego przepływu do asystenta i onboardingu klienta wyłącznie w Core jest dalszą
pracą produktową, opartą na dostarczonych kontraktach.

Pomiary przenoszą najwyżej 2000 szczegółowych wierszy. Onsite daje punktację
i ustalenia, `rank_keywords`/`serp_monitor` pozycje fraz; pozostałe moduły
dają wybrane podsumowania, a `competitors` obecnie wyłącznie zakres analizy.
Odłączenie GSC dotyczy całej organizacji źródłowej i wszystkich jej projektów;
cofnięcie pojedynczego grantu ogranicza się do jego zakresu.

## Co oznacza lokalna weryfikacja

Osiem testów przez rzeczywiste procesy HTTP przeszło w **188,94 s**.
Sprawdzają podgląd, zapis proponowanego draftu, rozdzielenie projektów,
pełny/częściowy audyt i kredyty, brief bez audytu, delegację GSC oraz odbiór
wyników obserwacji. Źródłowy audyt zawiera 101 ustaleń, więc przepływ przechodzi
przez granicę paginacji. Powtórzenia i odmowy są częścią testów.

Osobne suite PostgreSQL sprawdzają transakcje i współbieżność. RLS Core ma
dowód na rzeczywistej roli bez BYPASSRLS, nie tylko na właścicielu tabel.
WordPress był sprawdzany na PHP 8.3, WordPress 6.9.1 i MariaDB 11.4:
127 asercji usług, zgodne wyniki dwóch równoległych procesów oraz 26 asercji
HTTP obejmujących także publiczny HTML i odrzucenie błędnego nonce.

Google, model AI i zakończenie analizy są kontrolowanymi granicami testowymi.
Nie wykonano płatnych wywołań, rzeczywistej zgody Google ani analizy klienta.
Szczegóły odtworzenia: [pilot HTTP](SEO-INTEGRATION-LOCAL-PILOT.md).
Końcowe liczby suite, commity i obrazy: [plan 14](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md)
oraz [HANDOFF](HANDOFF.md). Praktyczny podział na test możliwy od razu i test
po przygotowaniu wspólnego środowiska zawiera
[checklista ręczna](SEO-INTEGRATION-MANUAL-TEST.md).

## Konfiguracja przed uruchomieniem na instancjach

1. Wdrożyć zgodne gałęzie do osobnych środowisk każdego produktu. Każde ma
   własną bazę, sekret, logi i procesy. Najpierw SSA z rozszerzonymi kontraktami,
   następnie klientów Core/SCR. Migracje zachowują istniejącą historię.
2. W SSA utworzyć operatorskie źródło dla konkretnego produktu i wdrożenia,
   plan, ograniczony klucz, odbiorcę podpisanego callbacku i dokładny adres
   powrotu OAuth. Klucze nie trafiają do przeglądarki ani repozytorium.
3. W Core ustawić źródło SSA, cenę operacji oraz jawne features oferty;
   w SCR źródło SSA i zatwierdzone połączenia do Core z ograniczonym grantem.
   Brak konfiguracji nie oznacza darmowej usługi ani nieograniczonego planu.
4. Włączyć workery oraz operatorowi ustalić limity płatnych wywołań i modeli.
   Ręczne uruchomienie komendy nie zastępuje procesu obsługującego kolejkę.
5. Skonfigurować własnego klienta OAuth Google i wykonać rzeczywistą zgodę,
   synchronizację oraz cofnięcie na kontrolowanym koncie. Hosting domeny sam
   nie nadaje dostępu do jej Search Console.
6. Sprawdzić pojedynczy autoryzowany projekt na rzeczywistych instancjach,
   zapisać digesty obrazów, wynik i koszt, a następnie rozszerzać dostęp.

Nie należy cofać tabel receiptów po rozpoczęciu użycia integracji: utrata
historii idempotencji może powtórzyć wykonanie. Rollback aplikacji zachowuje
rozszerzony schemat i cofa backend/frontend danego profilu razem.

## Granice następnych prac produktowych

Pełny asystent rozmowy z klientem, autonomiczny wybór wielu podstron i ich
struktury, kompleksowa strategia SEO, edycja całych artykułów, automatyczne
publikowanie cyklicznych zmian oraz GA i kolejne narzędzia pozostają rozwojem
produktu. Obecny brief tworzy jedną podstronę przez zatwierdzony szablon.
Obecny neutralny kanał treści i WordPress obsługują opis meta.

WordPress v0.1 nie obejmuje edycji struktury ani wielojęzycznych wtyczek.
Rzeczywiste wersje Yoast i Rank Math wymagają osobnej kontroli zgodności.
Udostępnienie historii audytów publicznej witryny w SSA po późniejszej rejestracji wymaga jawnego grantu;
sam e-mail lub posiadanie domeny nie ujawniają danych. GSC wymaga osobnego
uprawnienia, a retencja fizycznych kopii wygasłych grantów wymaga polityki
operatora przed produkcją. Porównanie pozycji pokazuje obserwowaną zmianę,
nie udowadnia skuteczności konkretnej edycji.
