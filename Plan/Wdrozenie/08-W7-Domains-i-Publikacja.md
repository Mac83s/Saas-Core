# W7 — Domains i publikacja

**Status:** zakończone lokalnie (2026-08-12)
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

- [x] subdomena platformy działa po publikacji strony;
- [x] własna domena przechodzi udokumentowany workflow DNS;
- [x] niezweryfikowany host nie uzyskuje certyfikatu;
- [x] Site Renderer nigdy nie wybiera site spoza resolved host;
- [x] canonical, przekierowania i locale są testowane;
- [x] status domeny oraz certyfikatu jest obserwowalny dla supportu;
- [x] istnieje procedura wycofania DNS i zwolnienia domeny.

## 5. Dowody zamknięcia

- 268 testów backendu, w tym normalizacja Host/IDNA, izolacja tenantów,
  lifecycle, DNS, TLS, canonical, locale i publiczny resolver;
- testy frontendowe i axe dla panelu domen oraz renderera, 8 testów parsera
  oryginalnego `Host` i zielony Playwright całego workflow Sites;
- produkcyjny build Next.js na Node 24 zawiera dynamiczną trasę
  `/site-renderer/[[...path]]`, a migracja `sites.0004` działa w Compose;
- smoke realnego ingressu potwierdza prywatność endpointu Caddy, `404` dla
  nieprzypisanego hosta i brak zatrucia kolejnego żądania panelu;
- procedura operacyjna znajduje się w `docs/operations/domains.md`, a decyzje
  własności, DNS, TLS, routingu i CDN/WAF w ADR-028.

Faktyczne issuance przez publiczny urząd ACME pozostaje dowodem stagingowym:
wymaga delegowanej domeny i publicznego DNS. Nie blokuje zamknięcia lokalnej
fali, a procedura jawnie odróżnia sprawdzoną politykę od zewnętrznego issuance.
