# SaaS Core - roadmapa wdrożenia

## 1. Zasada realizacji

Każdy etap ma zakończyć się działającym przyrostem możliwym do uruchomienia na stagingu. Nie rozpoczynamy kolejnego dużego modułu bez testów i kryteriów odbioru poprzedniego fundamentu.

Szacunki zakładają pracę 1-2 doświadczonych programistów. Zostaną zaktualizowane po rozpisaniu backlogu.

## 2. Etap 0 - kontrakt architektoniczny

**Szacunek:** 1 tydzień

Zakres:

- finalna struktura repozytorium;
- profile deploymentów;
- kontrakt modułów;
- wybór bibliotek bazowych;
- model `User`, `Organization`, `Membership`;
- strategia sesji;
- konwencje API;
- podstawowe ADR-y.

Kryteria odbioru:

- [ ] repozytorium ma zaakceptowaną strukturę;
- [ ] moduł Core nie zależy od verticala;
- [ ] wiadomo, jak MedPlano aktywuje moduł Medical;
- [ ] istnieje opis lokalnego developmentu;
- [ ] wszystkie otwarte decyzje blokujące mają właściciela.

## 3. Etap 1 - fundament techniczny

**Szacunek:** 2-3 tygodnie

Zakres:

- Django i Next.js;
- PostgreSQL i Redis;
- Docker Compose;
- Caddy;
- konfiguracja local/staging/production;
- CI/CD;
- OpenAPI i generowany klient;
- healthchecki;
- podstawowe logowanie i monitoring;
- backup stagingu.

Kryteria odbioru:

- [ ] aplikację można uruchomić jedną udokumentowaną procedurą;
- [ ] frontend komunikuje się z API;
- [ ] obrazy powstają w CI;
- [ ] staging jest oddzielony od production;
- [ ] działają migracje i smoke test;
- [ ] istnieje test odtworzenia bazy.

## 4. Etap 2 - Identity, Organizations i i18n

**Szacunek:** 2-3 tygodnie

Zakres:

- rejestracja;
- weryfikacja e-mail;
- logowanie i reset hasła;
- sesje;
- organizacje;
- membership i zaproszenia;
- role i permissions;
- zmiana aktywnej organizacji;
- język interfejsu;
- audit log podstawowych operacji;
- panel Next.js.

Kryteria odbioru:

- [ ] użytkownik nie widzi Django Admin;
- [ ] jeden użytkownik może należeć do kilku organizacji;
- [ ] zaproszenie ma czas ważności i nie można użyć go ponownie;
- [ ] testy potwierdzają izolację organizacji;
- [ ] wszystkie kontrole są wykonywane w API;
- [ ] panel działa w co najmniej dwóch językach.

## 5. Etap 3 - Billing i Entitlements

**Szacunek:** 2-3 tygodnie

Zakres:

- plan i PlanVersion;
- Feature, Entitlement i Quota;
- Stripe Checkout;
- 3-dniowy, konfigurowalny trial;
- Customer Portal;
- podpisane i idempotentne webhooki;
- zmiana i anulowanie planu;
- okres karencji;
- tryb read-only;
- usage counters;
- adapter fakturowania.

Kryteria odbioru:

- [ ] ponowienie tego samego webhooka nie duplikuje skutków;
- [ ] zmiana planu aktualizuje funkcje organizacji;
- [ ] rola użytkownika i plan są niezależne;
- [ ] trial kończy się zgodnie z konfiguracją;
- [ ] utrata płatności nie usuwa danych;
- [ ] operator może przyznać audytowane nadpisanie planu.

## 6. Etap 4 - Sites, Content, Media i Domains

**Szacunek:** 3-4 tygodnie

Zakres:

- Site i Page;
- PageBlock i schema version;
- draft, preview i publication;
- tłumaczenia treści;
- motyw i design tokens;
- media;
- SEO;
- subdomena platformy;
- własna domena;
- weryfikacja DNS;
- Caddy On-Demand TLS;
- canonical i przekierowania.

Kryteria odbioru:

- [ ] organizacja może edytować tylko swoją stronę;
- [ ] można cofnąć się do poprzedniej publikacji;
- [ ] strona działa na subdomenie;
- [ ] obca domena nie otrzyma certyfikatu;
- [ ] własna domena przechodzi pełny workflow weryfikacji;
- [ ] wielojęzyczne strony posiadają poprawne adresy i SEO.

## 7. Etap 5 - Notifications, Integrations i obsługa

**Szacunek:** 2 tygodnie

Zakres:

- provider poczty transakcyjnej;
- kolejka wiadomości;
- tłumaczone szablony;
- bounce i complaint;
- preferencje powiadomień;
- API keys;
- webhooki wychodzące;
- import/export;
- panel operatora;
- alerty i retry.

Kryteria odbioru:

- [ ] awaria dostawcy poczty nie blokuje operacji użytkownika;
- [ ] retry nie wysyła duplikatów;
- [ ] wiadomość ma widoczny status;
- [ ] webhooki są podpisane;
- [ ] operator może bezpiecznie ponowić nieudaną operację;
- [ ] wszystkie działania wsparcia trafiają do audit logu.

## 8. Etap 6 - wspólny Booking

**Szacunek:** 3-5 tygodni dla pierwszego używalnego zakresu

Zakres:

- lokalizacje;
- pracownicy;
- usługi;
- zasoby;
- harmonogramy;
- nieobecności;
- wyszukiwanie terminów;
- tworzenie, zmiana i anulowanie rezerwacji;
- blokada podwójnego terminu;
- klient końcowy;
- potwierdzenia i przypomnienia.

Kryteria odbioru:

- [ ] równoległe próby nie tworzą dwóch wizyt w tym samym terminie;
- [ ] strefy czasowe są obsługiwane poprawnie;
- [ ] zmiana grafiku nie niszczy istniejących rezerwacji;
- [ ] statusy mają historię;
- [ ] dane klienta są minimalizowane;
- [ ] wiadomości nie ujawniają niepotrzebnych danych.

## 9. Etap 7 - pierwszy Vertical Medical

**Szacunek:** 2-3 tygodnie po gotowym Booking

Zakres:

- DoctorProfile;
- specjalizacje;
- rodzaje wizyt;
- bloki strony lekarza;
- onboarding gabinetu;
- konfiguracja medycznych zasad komunikacji;
- dodatkowy audit;
- pierwsza migracja klienta z WordPressa.

Kryteria odbioru:

- [ ] pierwszy gabinet przechodzi pełny onboarding;
- [ ] strona działa na własnej domenie;
- [ ] gabinet może samodzielnie edytować treści;
- [ ] rezerwacja działa od strony pacjenta i panelu;
- [ ] istnieje procedura migracji oraz rollbacku DNS;
- [ ] zakres danych został sprawdzony pod kątem RODO.

## 10. Kamienie milowe

| Milestone | Rezultat |
| --- | --- |
| M1 | działający szkielet na stagingu |
| M2 | bezpieczne konta i organizacje |
| M3 | płatny SaaS z trialem i planami |
| M4 | generator stron i własne domeny |
| M5 | kompletna komunikacja i obsługa |
| M6 | wspólny moduł rezerwacji |
| M7 | pilot MedPlano z pierwszym gabinetem |

## 11. Ryzyka

| Ryzyko | Odpowiedź |
| --- | --- |
| zbyt ogólny Core | projektować na podstawie MedPlano i beauty, nie hipotetycznych dziesiątek branż |
| forkowanie deploymentów | kontrakty modułów, wspólne testy i brak zmian bezpośrednio w Core |
| błędy izolacji tenantów | automatyczny tenant scope, testy i opcjonalne RLS |
| zbyt rozbudowany page builder | kontrolowane, wersjonowane bloki |
| zależność od Stripe | lokalne entitlementy i adapter billingowy |
| problemy z pocztą | zewnętrzny provider i asynchroniczna wysyłka |
| awaria jednego VPS-a | backup poza VPS-em i procedura odtworzenia |
| zbyt szybkie wejście w dane medyczne | początkowy zakres marketingowo-rezerwacyjny |

## 12. Następna sesja projektowa

Pierwszy szczegółowy dokument wykonawczy powinien objąć Etap 0 i Etap 1:

- konkretne zależności Django i Next.js;
- układ pakietów;
- schemat konfiguracji deploymentu;
- modele Identity i Tenancy;
- strategię auth;
- development Docker Compose;
- środowiska i zarządzanie sekretami;
- pierwsze endpointy i testy.
