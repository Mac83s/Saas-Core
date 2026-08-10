# SaaS Core - katalog modułów

## 1. Podział modułów

Moduły dzielą się na trzy grupy:

1. Core - obowiązkowy fundament każdego produktu.
2. Shared - funkcje wielokrotnego użycia, ale nieobowiązkowe w każdym produkcie.
3. Vertical - funkcje charakterystyczne dla konkretnej branży.

## 2. Moduły Core

### 2.1 Identity

Odpowiedzialności:

- rejestracja użytkownika;
- logowanie i wylogowanie;
- weryfikacja adresu e-mail;
- reset hasła;
- sesje i urządzenia;
- 2FA;
- ustawienia bezpieczeństwa konta;
- preferowany język użytkownika.

Poza zakresem:

- role organizacyjne;
- plany abonamentowe;
- pacjenci i klienci końcowi.

### 2.2 Tenancy / Organizations

Odpowiedzialności:

- organizacje/workspace'y;
- konto prywatne i firmowe jako wariant organizacji;
- członkostwa;
- zaproszenia;
- zmiana aktywnej organizacji;
- profil rozliczeniowy;
- ustawienia organizacji;
- izolacja tenantów.

### 2.3 Permissions

Odpowiedzialności:

- role Owner, Admin, Manager, Staff i Viewer;
- szczegółowe permissions;
- polityki dostępu do zasobów;
- kontrola operacji w API i panelu;
- obowiązkowe kontrole tenant scope.

Role określają, kto może wykonać operację. Nie określają, czy organizacja kupiła daną funkcję.

### 2.4 Billing

Odpowiedzialności:

- klienci Stripe;
- subskrypcje;
- trial;
- zmiana i anulowanie planu;
- płatności zaległe;
- okres karencji;
- kupony;
- Customer Portal;
- synchronizacja przez webhooki;
- adapter fakturowania/KSeF.

### 2.5 Entitlements i Usage

Odpowiedzialności:

- katalog funkcji;
- wersje planów;
- funkcje logiczne;
- limity liczbowe;
- bieżące zużycie;
- ręczne nadpisania;
- plany partnerskie i administracyjne;
- centralna funkcja autoryzacji `can()` / `limit()`.

### 2.6 Sites i Content

Odpowiedzialności:

- strony klienta;
- strony i podstrony;
- wersje robocze i publikacje;
- wersjonowane bloki;
- motywy i design tokens;
- nawigacja;
- SEO;
- tłumaczenia treści;
- podgląd zmian;
- historia publikacji.

### 2.7 Domains

Odpowiedzialności:

- subdomena platformy;
- własna domena;
- weryfikacja DNS;
- status certyfikatu;
- canonical;
- przekierowania;
- bezpieczna autoryzacja On-Demand TLS.

### 2.8 Files / Media

Odpowiedzialności:

- upload;
- prywatne i publiczne pliki;
- limity planów;
- metadane;
- miniatury;
- walidacja MIME i rozszerzeń;
- skanowanie;
- podpisane adresy URL;
- retencja i usuwanie.

### 2.9 Notifications

Odpowiedzialności:

- e-mail;
- SMS w przyszłości;
- powiadomienia in-app;
- wielojęzyczne szablony;
- kolejki i retry;
- preferencje odbiorcy;
- bounce, complaint i suppressions;
- historia statusów bez niepotrzebnej retencji treści.

### 2.10 Audit i Compliance

Odpowiedzialności:

- audyt zmian;
- wersje regulaminów i polityk;
- rejestrowanie zgód;
- eksport danych;
- anonimizacja i usunięcie;
- polityki retencji;
- bezpieczna impersonacja operatora;
- historia operacji administracyjnych.

### 2.11 Integrations

Odpowiedzialności:

- API keys;
- webhooki wychodzące;
- odbiorniki webhooków;
- podpisy payloadów;
- retry i log prób;
- OAuth dla zewnętrznych integracji;
- adaptery dostawców płatności, poczty i faktur.

### 2.12 Jobs i Events

Odpowiedzialności:

- Celery tasks;
- harmonogram;
- idempotency;
- retry;
- dead-letter workflow;
- transaction outbox;
- zdarzenia domenowe;
- monitoring błędów zadań.

### 2.13 Settings i Feature Flags

Odpowiedzialności:

- ustawienia platformy;
- ustawienia deploymentu;
- ustawienia organizacji;
- preferencje użytkownika;
- bezpieczne stopniowe wdrażanie funkcji;
- włączanie modułów dla wybranych tenantów.

### 2.14 Support i Observability

Odpowiedzialności:

- panel operatorski;
- healthchecki;
- logi i korelacja requestów;
- metryki;
- alerty;
- historia deploymentów;
- status integracji;
- ponawianie bezpiecznych operacji.

## 3. Wspólny moduł Booking

Booking jest modułem wielokrotnego użycia, niezależnym od branży.

Podstawowe funkcje:

- lokalizacje;
- pracownicy/usługodawcy;
- usługi;
- zasoby, np. gabinet lub stanowisko;
- harmonogramy i reguły dostępności;
- przerwy i nieobecności;
- rezerwacje;
- anulowanie i zmiana terminu;
- przypomnienia;
- ochrona przed podwójną rezerwacją;
- opcjonalna zaliczka/płatność;
- statusy rezerwacji;
- klient końcowy/contact.

Booking nie przechowuje dokumentacji medycznej ani danych typowych wyłącznie dla jednej branży.

## 4. Vertical Medical

Przykładowy zakres:

- profil lekarza;
- specjalizacje;
- numery uprawnień zawodowych, jeśli wymagane;
- rodzaje wizyt;
- informacje o przygotowaniu do wizyty;
- bezpieczne ustawienia komunikacji;
- reguły minimalizacji danych medycznych;
- rozszerzenie rezerwacji o dane właściwe dla gabinetu;
- w przyszłości asystent wyszukiwania evidence dla lekarza.

Funkcje diagnostyczne, EDM i dane kliniczne wymagają osobnego projektu regulacyjnego i nie są częścią początkowego Core.

## 5. Vertical Beauty

Przykładowy zakres:

- profil specjalisty;
- zabiegi i kategorie;
- czas, cena i warianty;
- stanowiska i urządzenia;
- galerie przed/po;
- pakiety usług;
- rozszerzenia zgód i przeciwwskazań;
- branżowe bloki strony.

## 6. Kontrakt rozszerzenia

Każdy moduł powinien określać:

- nazwę i wersję;
- zależności;
- modele i migracje;
- endpointy;
- permissions;
- entitlementy;
- wpisy menu;
- strony panelu;
- bloki Site Renderera;
- tłumaczenia;
- zdarzenia publikowane i obsługiwane;
- zadania cykliczne;
- politykę retencji;
- testy kontraktowe.

## 7. Kryteria gotowości modułu

- [ ] posiada właściciela domeny biznesowej;
- [ ] nie odwołuje się bezpośrednio do konkretnego deploymentu;
- [ ] posiada migracje;
- [ ] posiada testy izolacji tenantów;
- [ ] posiada testy permissions i entitlements;
- [ ] dokumentuje dane osobowe;
- [ ] dokumentuje zdarzenia;
- [ ] posiada przynajmniej podstawowe metryki;
- [ ] można go wyłączyć bez uszkodzenia Core;
- [ ] jego frontend nie jest widoczny, gdy moduł jest wyłączony.
