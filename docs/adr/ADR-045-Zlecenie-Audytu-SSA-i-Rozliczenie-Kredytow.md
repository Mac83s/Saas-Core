# ADR-045 — zlecenie audytu SSA i rozliczenie kredytów

**Status:** Accepted — fundament I2 uzgodniony w integracji Core, SCR i SSA.
**Data:** 2026-09-06

## Decyzja

Moduł `shared.seo` należy do profilu business i zależy od organizacji, Sites i
Billing. Core zamawia techniczny audyt istniejącej strony ze zweryfikowaną domeną
kanoniczną przez publiczny interfejs Sites. Adres nie jest dowodem własności:
`Organization.id` jest zewnętrznym tenantem, a `Site.id` zewnętrznym projektem
w jednym jawnie skonfigurowanym źródle SSA. Projekt pozostaje wewnętrzną historią
tego źródła; klient Core otrzymuje wynik w Core, bez konta ani dostępu w SSA.

Trzy tabele tenantowe mają FORCE RLS oraz wyzwalacze zgodności relacji:
`SourceSiteBinding`, `AuditOrder`, `AuditCallbackReceipt`. Żądanie i ustalona cena
są niezmienne; zamknięty wynik i potwierdzenia nie podlegają nadpisaniu.
Usuwanie historii odbywa się wyłącznie przez usunięcie organizacji z ADR-042.

`seo.audit.run` jest domyślnie prawem właściciela, `seo.audit.read` właściciela
i managera. API wymaga również `seo.audit.enabled`. Katalog rejestruje nazwę
funkcji, ale nie zmienia opublikowanych wersji planów. Operator musi jawnie
skonfigurować istniejącą operację kredytową i ofertę albo przyznać uprawnienie.
Nieznany klucz ceny odmawia zlecenia; znana nieaktywna operacja oznacza
świadomie bezpłatny audyt. Nie tworzymy arbitralnego cennika.

## Żądanie i wykonywanie

`GET /api/v1/seo/audit-offer/` pozwala osobie uprawnionej do zamówienia odczytać
cenę i limit stron bez rezerwowania środków. Panel przekazuje wyświetloną cenę
jako `expected_credit_cost` w POST. Billing blokuje wiersz operacji kredytowej
na czas porównania i rezerwacji; zmiana ceny daje 409 `credit_price_changed`
bez zlecenia ani rezerwacji. Pole jest opcjonalne dla istniejących wywołań,
których polityka wcześniej zaakceptowała cenę skonfigurowanej operacji.

`POST /api/v1/seo/audits/` przyjmuje `site_id`, `idempotency_key` (8–120 znaków)
i opcjonalny `max_pages`, ograniczony konfiguracją. Odpowiedź 201 oznacza trwałe
zlecenie, a 200 identyczne wcześniejsze żądanie; inna treść pod tym samym kluczem
daje 409. Transakcja zapisuje rezerwację kredytów, zlecenie i audyt działania.
Nie wykonuje połączenia sieciowego. Sam wiersz zlecenia jest trwałą kolejką,
skanowaną przez zadanie przypisane wyłącznie do aktywnego modułu SEO.

Worker ustawia tenant przed odczytem, przydziela czasową dzierżawę i wychodzi
z transakcji na czas HTTP. Przed nową wysyłką ponownie sprawdza członkostwo,
uprawnienia i bieżącą domenę. Przekazuje stały `client_reference=AuditOrder.id`.
Przed każdym POST audytu wykonuje GET tej operacji; tylko jednoznaczne 404
pozwala wysłać ten sam zamiar ponownie. Utrata odpowiedzi nie oznacza porażki:
stan `reconciling` zachowuje rezerwację bez automatycznego terminu zwolnienia.
Nie ma zgadywania, czy SSA rozpoczęło kosztowną pracę.

Powiadomienie `POST /api/v1/seo/ssa/callback/` weryfikuje standardowy HMAC
`webhook-id.timestamp.raw_body`, źródło i okno 300 sekund przed odczytem danych.
Przechowuje tylko identyfikatory, hash i status; nie kopiuje błędów dostawcy ani
prywatnych danych. Duplikat jest idempotentny. Powiadomienie jedynie przyspiesza
uzgodnienie stanu: samo nigdy nie rozlicza kredytów.

## Wynik i rozliczenie

Worker potwierdza przez GET pełną tożsamość źródła, tenanta, bindingu, projektu,
operacji, joba, audytu i konkretnego ModuleRun. SSA zwraca status oraz koszt
właśnie tego modułu, nie ostatniego modułu projektu. Koszt dostawcy pozostaje
osobnym polem operacyjnym i nie jest ceną klienta.

Potwierdzone ukończenie audytu i modułu pozwala pobrać techniczny raport.
Core zachowuje własny snapshot z hashem i czasem obserwacji, ponieważ bieżące
widoki raportów SSA nie gwarantują historycznej niezmienności. Pobranie ma
limit stron, liczby problemów i łącznych bajtów; sprawdza count, duplikaty oraz
kompletność stronicowania. Nie podąża za adresem `next` od dostawcy. Prywatne
`details` i błędy nie trafiają do kopii raportu. To snapshot techniczny, bez
GSC/GA i bez deklaracji kompletnego eksportu wszystkich danych SSA.

Dopiero zapis kompletnego wyniku `completed` atomowo zatwierdza rezerwację.
`partial` zachowuje dostępny kompletny snapshot technicznego raportu i zwalnia
kredyty; `failed` i `cancelled` również zwalniają. Odwołanie przed uruchomieniem
może nie mieć ModuleRun: zgodne `audit=cancelled` i `job=cancelled` wystarczają.
Niepełny lub niespójny wynik pozostaje do uzgodnienia, bez pobrania opłaty.
Utrata członkostwa po rozpoczęciu nie unieważnia wcześniej autoryzowanego zakupu:
ograniczony kontekst rozliczenia może zamknąć wyłącznie jego istniejącą rezerwację.

GET listy i szczegółu jest prywatny, nie uruchamia audytu ani rozliczenia.
Lista zwraca `items` i `next_cursor`, domyślnie 50 operacji, z limitem do 100;
paginacja po UUID pozwala przejść do starszych zachowanych wyników.
UI i wdrożenie konkretnej oferty są odrębnym zakresem.

## Konfiguracja i wycofanie

Wymagane są `SEO_SSA_BASE_URL` (z `/api/v1`), `SEO_SSA_SOURCE_ID`,
`SEO_SSA_PRODUCT_ID`, `SEO_SSA_DEPLOYMENT_ID`, `SEO_SSA_SERVICE_KEY`,
`SEO_SSA_CALLBACK_SECRET` i `SEO_AUDIT_CREDIT_OPERATION`. Sekrety obsługują
wariant `_FILE`; nie trafiają do artefaktu modułu. Niepełna konfiguracja daje
system check, całkowicie nieustawiona pozwala uruchomić produkt i odmawia audytu.
`SEO_AUDIT_MAX_PAGES` domyślnie wynosi 100, `SEO_REPORT_MAX_ISSUES` 5000;
łączny limit odpowiedzi raportu to 5 MB. HTTP nie śledzi przekierowań.

Migracje są odwracalne. Po przyjęciu zleceń rollback aplikacji musi jednak
zachować nowy schemat, dane i proces uzgadniający istniejące rezerwacje.
Wyłączenie modułu zatrzymuje jego harmonogram; nie jest sposobem na anulowanie
rozpoczętych audytów. Fizyczne cofnięcie tabel po użyciu utraciłoby historię,
dlatego przed takim ruchem potrzebne są zamknięte operacje i świadoma polityka
retencji. Ten przyrost nie wdraża serwisów ani cennika na produkcję.
