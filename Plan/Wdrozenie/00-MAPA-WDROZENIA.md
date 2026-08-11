# SaaS Core — mapa wdrożenia

**Wersja:** 0.1  
**Status:** plan wykonawczy  
**Data:** 2026-08-10  
**Zakres pilota:** MedPlano, bez dokumentacji klinicznej i EDM

## 1. Cel

Ten dokument zamienia roadmapę produktową na kolejkę małych, weryfikowalnych
fal wdrożeniowych. Każda fala ma dostarczyć działający przyrost, przejść własną
bramkę jakości i pozostawić repozytorium w stanie możliwym do wdrożenia.

Dokumenty bazowe w `Plan/` pozostają źródłem decyzji domenowych. Plany w tym
katalogu opisują sposób realizacji i nie zmieniają statusu żadnego ADR-u.

## 2. Zasady prowadzenia prac

1. Najpierw kontrakty i ryzyka przekrojowe, potem funkcje produktowe.
2. Backend egzekwuje tenant scope, permissions i entitlementy; frontend jedynie
   odzwierciedla wynik tych kontroli.
3. Każda fala kończy się demonstracją ścieżki użytkownika oraz automatycznymi
   testami jej najważniejszych gwarancji.
4. Migracje są kompatybilne z wdrożeniem i mają opisaną ścieżkę wycofania.
5. Sekrety, dane kart i niepotrzebne dane medyczne nie trafiają do repozytorium,
   logów ani dokumentacji.
6. Funkcja nie jest ukończona bez obserwowalności, dokumentacji operacyjnej i
   kryteriów odbioru.
7. Decyzja ze statusem `Proposed` wymaga jawnego zatwierdzenia przed pracą,
   której późniejsza zmiana byłaby kosztowna.

## 3. Kolejność fal

| Fala | Nazwa | Szacunek | Zależności | Główny rezultat |
| --- | --- | ---: | --- | --- |
| W0 | [Decyzje i kontrakty](01-W0-Decyzje-i-Kontrakty.md) | 1 tydzień | — | zamknięte decyzje blokujące i kontrakty architektury |
| W1 | [Szkielet monorepo](02-W1-Szkielet-Monorepo.md) | 1 tydzień | W0 | uruchamialny szkielet Django, Next.js i pakietów wspólnych |
| W2 | [Runtime local i staging](03-W2-Runtime-Local-i-Staging.md) | 1–2 tygodnie | W1 | powtarzalne środowisko oraz pierwszy deploy na staging |
| W3 | [Identity i sesje](04-W3-Identity-i-Sesje.md) | 1,5–2 tygodnie | W1, W2 | bezpieczna rejestracja, logowanie i zarządzanie sesją |
| W4 | [Organizations, RBAC i i18n](05-W4-Organizations-RBAC-i-I18n.md) | 1,5–2 tygodnie | W3 | izolowane organizacje, członkostwa, role i dwa języki |
| W5 | [Billing i Entitlements](06-W5-Billing-i-Entitlements.md) | 2–3 tygodnie | W4 | lokalny model dostępu zsynchronizowany ze Stripe |
| W6 | [Sites, Content i Media](07-W6-Sites-Content-i-Media.md) | 2–3 tygodnie | W4 | wersjonowana, wielojęzyczna strona organizacji |
| W7 | [Domains i publikacja](08-W7-Domains-i-Publikacja.md) | 1–2 tygodnie | W2, W6 | subdomeny, własne domeny i bezpieczny TLS |
| W8 | [Notifications, Integrations i Support](09-W8-Notifications-Integrations-i-Support.md) | 2 tygodnie | W3, W4 | niezawodna komunikacja i narzędzia operatora |
| W9 | [Booking](10-W9-Booking.md) | 3–5 tygodni | W4, W8 | neutralny branżowo, bezpieczny system rezerwacji |
| W10 | [Vertical Medical i pilot](11-W10-Vertical-Medical-i-Pilot.md) | 2–3 tygodnie | W5–W9 | pierwszy gabinet MedPlano przechodzi pełną ścieżkę |
| W11 | [Hardening i uruchomienie](12-W11-Hardening-i-Go-Live.md) | 1–2 tygodnie | W0–W10 | audyt, odtworzenie, testy obciążeniowe i decyzja go-live |

Szacunki dotyczą 1–2 doświadczonych programistów i zostaną skorygowane po W0.
W5 i W6 mogą częściowo biec równolegle dopiero wtedy, gdy W4 jest stabilne.

## 4. Kamienie milowe

| Milestone | Fale | Warunek osiągnięcia |
| --- | --- | --- |
| M1 — szkielet na stagingu | W0–W2 | jedna komenda lokalnie, automatyczny deploy i smoke test |
| M2 — bezpieczne konta | W3–W4 | pełna ścieżka użytkownik → organizacja → uprawnienie |
| M3 — płatny SaaS | W5 | plan, trial, webhooki, grace period i audytowane override |
| M4 — publikowane strony | W6–W7 | wersjonowana treść na subdomenie i własnej domenie |
| M5 — komunikacja | W8 | asynchroniczne wiadomości, webhooki i obsługa błędów |
| M6 — rezerwacje | W9 | odporna na wyścigi rezerwacja z przypomnieniami |
| M7 — pilot MedPlano | W10–W11 | onboarding gabinetu, migracja, rollback i zgoda go-live |

## 5. Bramka wejścia do fali

Fala może przejść do `in progress`, gdy:

- zależności mają zaliczone bramki wyjścia;
- decyzje oznaczone jako blokujące są zatwierdzone;
- scenariusz demonstracyjny i kryteria odbioru są jednoznaczne;
- właściciel, szacunek i lista ryzyk są zapisane;
- wymagane środowisko oraz dane testowe są dostępne.

## 6. Wspólna definicja ukończenia

- [ ] kod przeszedł formatowanie, lint, testy typów i testy automatyczne;
- [ ] nowe API jest w OpenAPI, a klient TypeScript został wygenerowany;
- [ ] testy negatywne obejmują brak uprawnień i próbę cross-tenant;
- [ ] migracja została sprawdzona na kopii danych testowych;
- [ ] logi i metryki nie ujawniają sekretów ani danych wrażliwych;
- [ ] healthcheck i smoke test pokrywają nowy przyrost;
- [ ] dokumentacja uruchomienia, rollbacku i ograniczeń jest aktualna;
- [ ] funkcja działa na stagingu w konfiguracji MedPlano;
- [ ] wszystkie nowe decyzje zostały dopisane do rejestru ADR.

## 7. Decyzje i termin ich podjęcia

| Najpóźniej przed | Decyzje |
| --- | --- |
| W1 | wersje runtime, package manager, UUID, układ monorepo, kontrakt modułu |
| W2 | strategia sekretów, monitoring, storage dla stagingu, RPO/RTO stagingu |
| W3 | ADR-013 sesje cookie, polityka CSRF, provider transakcyjnego e-maila dla auth |
| W4 | ADR-012 model tenantów, tenant context, zakres początkowego RLS, biblioteka i18n |
| W5 | model triala, karta w trialu, plany pilota, grace period, fakturowanie/KSeF |
| W6 | ADR-017 kontrolowane bloki, wersjonowanie treści i tłumaczeń |
| W7 | DNS, storage produkcyjny, CDN/WAF i polityka certyfikatów |
| W8 | provider e-mail/SMS, format webhooków i retencja komunikacji |
| W9 | ADR-018 Booking, model blokad i zasady stref czasowych |
| W10 | zakres danych MedPlano, DPA, retencja i wymagania RODO pilota |
| W11 | produkcyjne RPO/RTO, parametry VPS i kryteria go-live |

## 8. Bieżący ruch

W0 i W1 są ukończone. Lokalna część W2 oraz lokalne implementacje W3-W7 są
zakończone; bramki wymagające prawdziwego stagingu/VPS pozostają świadomie
odłożone. W7 dostarcza subdomeny platformy, workflow domen własnych i DNS,
fail-closed Caddy On-Demand TLS oraz publiczny routing snapshotów z canonical i
locale. Politykę potwierdzają testy, build Node 24, Playwright i smoke Compose;
zewnętrzne issuance ACME wymaga prawdziwego stagingu. Następną lokalną falą jest
W8.
