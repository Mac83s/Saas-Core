# W7 — Domains i publikacja

**Status:** blocked by W2 and W6  
**Szacunek:** 1–2 tygodnie  
**Poprzednicy:** W2, W6  
**Rezultat:** publikacja na subdomenie i zweryfikowanej domenie klienta

## 1. Scenariusz demonstracyjny

Organizacja otrzymuje subdomenę platformy, dodaje własną domenę, wykonuje
instrukcję DNS i po automatycznej weryfikacji publikuje stronę przez TLS. Obca
lub niezweryfikowana domena nie uzyskuje certyfikatu ani treści innego tenanta.

## 2. Pakiety pracy

### W7.1 — model domeny

- wdrożyć `Domain` ze znormalizowanym hostname i jednoznaczną unikalnością;
- rozdzielić subdomenę platformy i domenę własną;
- zapisać token, status weryfikacji, TLS, canonical i daty kontroli;
- modelować lifecycle pending/verified/failed/disabled/released;
- określić okres kwarantanny przed ponownym przypisaniem domeny.

### W7.2 — weryfikacja DNS

- generować trudny do odgadnięcia token TXT;
- sprawdzać TXT oraz wymagane rekordy A/AAAA/CNAME w workerze;
- uwzględnić cache, propagację i tymczasowe błędy resolvera;
- ponownie weryfikować domenę po istotnej zmianie DNS;
- chronić przed domain takeover i przypisaniem domeny należącej do innego site.

### W7.3 — Caddy On-Demand TLS

- wystawić minimalny endpoint autoryzacyjny bez danych tenantowych;
- odpowiadać pozytywnie wyłącznie dla aktywnej, zweryfikowanej domeny;
- dodać cache krótkoterminowy, rate limiting i monitoring decyzji;
- ograniczyć zakres certyfikatów i przetestować awarie backendu autoryzacji;
- nie wydawać certyfikatu w stanie pending, disabled ani released.

### W7.4 — routing i SEO

- rozwiązywać `Site` wyłącznie z normalizowanego nagłówka Host;
- odrzucać nieznane hosty bez fallbacku do przypadkowego tenanta;
- wymuszać canonical i kontrolowane przekierowania;
- obsłużyć locale oraz preview poza publiczną domeną;
- przygotować bezpieczne zachowanie przy wyłączeniu organizacji.

## 3. Testy obowiązkowe

- hostname z portem, wielkością liter, Unicode/punycode i końcową kropką;
- domena przypisana do innej organizacji;
- token TXT zły, stary albo skopiowany;
- DNS timeout, NXDOMAIN i zmiana po wcześniejszej weryfikacji;
- próba uzyskania certyfikatu dla dowolnego hosta;
- Host header injection oraz cache poisoning;
- rollback DNS podczas migracji klienta.

## 4. Bramka wyjścia

- [ ] subdomena platformy działa po publikacji strony;
- [ ] własna domena przechodzi udokumentowany workflow DNS;
- [ ] niezweryfikowany host nie uzyskuje certyfikatu;
- [ ] Site Renderer nigdy nie wybiera site spoza resolved host;
- [ ] canonical, przekierowania i locale są testowane;
- [ ] status domeny oraz certyfikatu jest obserwowalny dla supportu;
- [ ] istnieje procedura wycofania DNS i zwolnienia domeny.

