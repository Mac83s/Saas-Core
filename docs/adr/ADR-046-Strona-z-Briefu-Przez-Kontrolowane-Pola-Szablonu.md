# ADR-046 — strona z briefu przez kontrolowane pola szablonu

Status: Accepted. Data: 2026-09-06. Zakres: I4 planu integracji 14.

Nowa strona nie wymaga audytu nieistniejącej jeszcze domeny. SCR przechowuje
osobną generację z briefu, jej właściciela, połączenie do Core, budżet wywołań,
katalog i wynik przeglądu. Nie dopisuje sztucznego audytu jako źródła treści.

Core wystawia katalog dla jawnej witryny po sprawdzeniu tenanta, uprawnienia,
entitlementu i grantu. Katalog zawiera najnowsze zatwierdzone wersje recept oraz
wyłącznie dozwolone pola tekstowe. Klucze pól są wskaźnikami JSON do istniejących
liści recepty. Model nie wybiera kodu, nowych typów bloków, adresów, mediów,
cenników ani danych kontaktowych. Katalog jest związany z witryną i skrótem
SHA-256 kanonicznego JSON UTF-8 (posortowane klucze, bez spacji, ensure_ascii=False,
bez pola catalog_hash). Wersja recepty pozostaje liczbą całkowitą.

SCR czyta katalog przez istniejące połączenie należące do workspace. Generacja
ma trwały klucz zamiaru, zamrożony brief/katalog/wybrany szablon i limit wejścia,
wyjścia oraz liczby prób z polityki operatora. Liczba znaków i tokenów nie jest
udawanym limitem USD. Nieznany koszt pozostaje nieznany. Nieznany wynik płatnego
wywołania nie powoduje automatycznego uruchomienia kolejnego modelu.

Core przyjmuje zaakceptowany wynik przez osobny endpoint blueprint-draft.
Uwierzytelnia klienta i sprawdza grant zapisu całej witryny. Weryfikuje własny
aktualny katalog, identyczny zbiór pól i ograniczenia tekstu; sam odtwarza bloki.
Tworzy wyłącznie nową stronę landing i zwykły draft z polityką proposed.
Zapis używa istniejących usług stron, mediów i draftów. Nie podmienia istniejącej
strony, nie zmienia nawigacji/domen i nie publikuje. Zwykła kolejka propozycji
Core wymaga przeglądu człowieka przed publikacją nowego szkicu.

Trwałe potwierdzenie w Core wiąże tenant, osobę, credential, witrynę, generację,
cały payload i klucz zamiaru. Odczyt potwierdzenia jest bez skutków ubocznych.
Ponowienie tego samego zamiaru zwraca tę samą stronę; inne dane z tym samym
kluczem dają konflikt. Źródło generacji jest oświadczeniem uwierzytelnionej
integracji, nie kryptograficznym dowodem zgody użytkownika w SCR. Uprawnienia
Core i jego przegląd pozostają samodzielnymi granicami.

Recepty mogą zawierać przykładowe kontakty i odnośniki. Model ich nie wymyśla
ani nie zastępuje; użytkownik widzi konieczność ich sprawdzenia w zwykłym
edytorze. Ten przyrost dostarcza mechanizm przygotowania i przeglądu strony,
nie pełnego asystenta z dowolnymi narzędziami. Przyszły asystent może używać
wyłącznie wersjonowanej komendy tej aplikacji z TenantContext i zgodą,
bez dostępu modelu do repozytorium, ORM lub powłoki.
