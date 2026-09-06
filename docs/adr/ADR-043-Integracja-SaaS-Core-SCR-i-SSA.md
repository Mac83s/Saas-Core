# ADR-043 — integracja SaaS Core, SeoContentRank i SEOSiteAudit

**Status:** Accepted — kierunek i granice I0; dalsze API wymagają implementacji i odbioru.
**Data:** 2026-09-06
**Właściciel:** koordynator integracji i właściciele trzech repozytoriów.
**Podstawa:** opis produktów Macieja i zgoda „ok działaj zatem” na I0 oraz przygotowanie I1.

Numer integracji zmieniono z ADR-042 na ADR-043 przy synchronizacji gałęzi:
ADR-042 jest równolegle użyty dla usunięcia tenanta. Decyzja integracyjna zachowuje treść.

## Kontekst

SCR ma utrzymywać treści platform i ich klientów, a także obsługiwać niezależnych
klientów przez panel, API i przyszłe integracje CMS. SSA jest samodzielnym
produktem audytowym oraz dostawcą pomiarów dla SCR i produktów SaaS Core.
Wspólna domena analizowanej strony nie ustanawia wspólnego właściciela danych.

Istniejące integracje pozwalają przygotować ograniczony pilot, ale nie dowodzą
gotowości obsługi wielu klientów. SCR ma obecnie globalne cele dostarczania
treści, SSA klucze na organizację i jeden adres callbacku na wdrożenie.
Pełny kontrakt i stan implementacji opisuje [kontrakt I0](../architecture/seo-ecosystem-integration.md).

## Decyzja

1. Zachowujemy trzy aplikacje i ich repozytoria. Produkty budowane na SaaS Core
   nadal współdzielą kod zgodnie z ADR-021; każdy produkt ma własne wdrożenie,
   bazy, sekrety i obserwowalność. Integracja używa wersjonowanych API, bez
   bezpośredniego dostępu do cudzych tabel i bez kopiowania tożsamości aktora jako tenanta.
2. SaaS Core posiada strony, drafty, wersje, domeny, podgląd i publikację.
   SCR posiada brief, strategię, propozycje i proces dostarczania treści.
   SSA wykonuje pomiary, analizy SEO/GEO i analityczne wywołania dostawców.
   SCR zamawia analizę w SSA i interpretuje jej wyniki przy planowaniu treści.
3. Powiązanie obejmuje produkt, instancję wdrożenia, organizację i projekt lub
   witrynę każdej strony integracji. URL jest atrybutem zasobu. W I1 powiązanie
   zatwierdza operator w wersjonowanym, niezmiennym dokumencie konfiguracji;
   dokument nie nadaje uprawnień i nie stanowi nowego publicznego endpointu.
4. Historia jest dostępna przez produkt i zakres, w których zamówiono usługę.
   Późniejsze pokazanie jej w innym produkcie wymaga jawnego powiązania kont
   i nadania dostępu do konkretnych danych. Rejestracja, zgodny e-mail oraz
   wykazanie obecnego posiadania domeny nie przenoszą cudzej historii.
5. Planowana delegacja GSC korzysta z istniejącego magazynu połączeń SSA;
   nie kopiujemy refresh tokenów między aplikacjami. I3 musi dopiero dodać
   ograniczone uprawnienie usługi oraz obsługę jego odwołania. Obecny kontrakt
   nie oznacza, że SCR lub SaaS Core mają już taki mechanizm.
6. Produkt sprzedający usługę posiada saldo klienta i rozliczenie zamówienia.
   SSA zapisuje koszt wykonania i dowód dostarczenia. Korelacja operacji nie
   zastępuje idempotencji, a dostarczenie propozycji nie oznacza publikacji.
7. Jedna sesja prowadzi integrację, delegując ograniczone zadania do osobnych
   repozytoriów i katalogów roboczych. Claude zachowuje aktywny zakres P3
   w głównym SaaS Core; integracja powstaje w wydzielonym worktree.

## Zakres pierwszego odbioru

I1 używa istniejącego zakończonego audytu jednej strony platformowej, propozycji
zmiany metadanych i podglądu SaaS Core. Nie uruchamia nowego crawla ani płatnych
dostawców; nie zapisuje draftu ani nie publikuje strony. Dopuszczenie klucza
odczytowego do podglądu wymaga serwerowej kontroli tenant, permission,
entitlement i grantu oraz testów odmowy. Kod tej poprawki i dowód jej odbioru
są osobną bramką planu, nie konsekwencją samego zaakceptowania ADR-u.

## Konsekwencje i kompromisy

Dokument operatorski pozwala sprawdzić jedną integrację przed budową panelu
provisioningu. W zamian wymaga ręcznego ustanowienia powiązań i nie skaluje się
jeszcze na onboarding klientów. Wielu klientów blokują wskazane w planie luki
SCR, brak delegacji projektowej SSA i globalny callback rozliczeń.

Nie przyjmujemy jednej organizacji SSA dla wszystkich klientów, współdzielonego
klucza prywatnego BFF ani automatycznego łączenia po domenie: te skróty
zacierają granice dostępu, rozliczenia i historii. Dane GSC po odłączeniu są
usuwane zgodnie z obecnym SSA; integracja nie obiecuje niezmiennego archiwum.

## Relacje

Doprecyzowuje ADR-035 §3: odpowiedzialność SCR za analizę oznacza jej zamówienie
i wykorzystanie; silnik pomiarów i zaleceń należy do SSA. Pozostałe zasady
ADR-035, w tym operator jako właściciel grantów, pozostają w mocy.
Uzupełnia ADR-021 i ADR-033; nie uruchamia generatora stron z W9.5.7.
Kolejność wykonania: [plan integracji](../../Plan/Wdrozenie/14-INTEGRACJA-SAAS-CORE-SCR-SSA.md).
