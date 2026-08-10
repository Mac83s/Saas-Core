# W11 — hardening i go-live

**Status:** blocked by W0–W10  
**Szacunek:** 1–2 tygodnie  
**Poprzednicy:** wszystkie fale funkcjonalne  
**Rezultat:** udokumentowana decyzja go/no-go dla pierwszego pilota

## 1. Cel

Fala nie dodaje dużych funkcji. Zamienia działający staging w system, którego
ryzyka są zmierzone, procedury przećwiczone, a właściciele świadomie akceptują
pozostałe ograniczenia.

## 2. Pakiety pracy

### W11.1 — bezpieczeństwo

- przeprowadzić threat modeling auth, tenantów, billing, upload, domen i Booking;
- wykonać testy OWASP oraz test zależności i obrazów;
- przejrzeć permissions, endpointy operatora i dane w logach;
- zweryfikować rotację sekretów, nagłówki, TLS i rate limiting;
- zamknąć krytyczne i wysokie findings albo formalnie zablokować go-live.

### W11.2 — niezawodność i wydajność

- ustalić SLO dla kluczowych ścieżek;
- wykonać test obciążenia API, renderera i wyszukiwania terminów;
- sprawdzić wyczerpanie puli DB, zaległość Celery i awarię Redis;
- przetestować timeouty, retry, circuit breaking i degradację zależności;
- ustalić limity oraz capacity plan pierwszego VPS-a.

### W11.3 — backup i disaster recovery

- zatwierdzić produkcyjne RPO i RTO;
- wykonać restore PostgreSQL oraz storage w odizolowanym środowisku;
- przećwiczyć utratę całego VPS-a i odbudowę z kodu + backupu;
- zweryfikować szyfrowanie, retencję i kopię poza dostawcą awarii;
- zapisać czasy, problemy i właścicieli usprawnień.

### W11.4 — operacje i support

- przygotować dashboardy, alerty i status page;
- stworzyć runbooki auth, płatności, domen, poczty, kolejek i backupu;
- ustalić dyżur, eskalację i komunikację incydentu;
- przygotować bezpieczne procedury supportu i impersonacji;
- zweryfikować monitoring certyfikatów, dysku i wyników backupu.

### W11.5 — release i pilot

- zamrozić zakres oraz przygotować wersjonowane obrazy release candidate;
- wykonać migrację próbną i checklistę DNS;
- ustalić kryteria rollbacku aplikacji, bazy i domeny;
- uzyskać podpisy właścicieli produktu, techniki i privacy;
- uruchomić pilota etapowo i obserwować zdefiniowane metryki.

## 3. Minimalna bramka go-live

- [ ] brak otwartych podatności krytycznych i wysokich;
- [ ] testy izolacji tenantów oraz współbieżności Booking przechodzą;
- [ ] restore drill mieści się w zatwierdzonym RPO/RTO;
- [ ] alerty zostały wywołane testowo i mają odbiorcę;
- [ ] rollback aplikacji i DNS został przećwiczony;
- [ ] DPA, polityki prywatności, retencja i rejestr danych są gotowe;
- [ ] support ma runbooki i minimalne dostępy;
- [ ] właściciele podpisali decyzję go-live.

## 4. Kryteria no-go

Go-live jest wstrzymany, jeśli:

- istnieje możliwość cross-tenant access;
- nie można odtworzyć danych z backupu;
- płatność albo webhook może nieodwracalnie zdublować skutek;
- system może wystawić certyfikat dla nieautoryzowanej domeny;
- Booking dopuszcza podwójną rezerwację;
- brakuje podstawy prawnej lub umowy dla przetwarzanych danych;
- nie istnieje działający rollback albo osoba zdolna go wykonać.

## 5. Po uruchomieniu

- codzienny przegląd błędów i kolejek w pierwszym tygodniu;
- przegląd metryk produktu i supportu po 7 oraz 30 dniach;
- test restore zgodnie z zatwierdzoną częstotliwością;
- retro pilota i aktualizacja ADR-ów, limitów oraz roadmapy;
- osobna decyzja przed przyjęciem kolejnych gabinetów lub verticala Beauty.

