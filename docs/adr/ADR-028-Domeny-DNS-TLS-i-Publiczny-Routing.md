# ADR-028 — domeny, DNS, TLS i publiczny routing

**Status:** Accepted
**Data:** 2026-08-12
**Właściciel:** zespół SaaS Core
**Przegląd:** przed pierwszym production i w W11

## Kontekst

ADR-010 przyjął domeny klientów i Caddy On-Demand TLS, ADR-003 przypisał Site
Renderer do Next.js, a ADR-027 zdefiniował niemutowalny snapshot publikacji.
W7 musi połączyć te decyzje bez tworzenia fallbacku tenantowego z nagłówka Host,
bez wydawania certyfikatów dla dowolnej nazwy i bez uzależniania kontroli domeny
od dostępności zewnętrznego panelu DNS.

## Decyzja

### Własność domeny i lifecycle

- `Domain` należy do `shared.sites`, wskazuje dokładnie jeden `Site` i ma globalnie
  unikalny, znormalizowany hostname dla wszystkich stanów innych niż `released`;
- host jest normalizowany do małych liter ASCII/IDNA, bez portu i końcowej kropki;
  adresy IP, wildcardy, userinfo, ścieżki, puste etykiety i niedozwolone znaki są
  odrzucane;
- subdomena `<czytelny-site-slug>-<stabilny-skrót-id>.<platformDomain>` powstaje razem z site, jest typu
  `platform`, zaufana na podstawie konfiguracji deploymentu i dostępna w każdym
  planie;
- domena własna zaczyna w `pending` i wymaga `site.publish` oraz entitlementu
  `custom_domain.enabled`; stany to `pending`, `verified`, `failed`, `disabled`
  i `released`;
- zwolniona domena zachowuje zapis audytowy i przez 7 dni nie może zostać
  przypisana ponownie. Po kwarantannie może powstać nowy rekord z nowym tokenem;
- tylko jedna aktywna domena site jest canonical. Zmiana canonical jest
  transakcyjna, idempotentna i audytowana.

### Dowód DNS

- challenge TXT znajduje się pod `_saas-core.<hostname>` i zawiera identyfikator
  rekordu domeny oraz losowy token o co najmniej 256 bitach entropii;
- worker używa `dnspython`, ograniczonego czasu zapytania i cache respektującego
  TTL. Sprawdza jednocześnie dokładny TXT oraz routing: CNAME do skonfigurowanego
  targetu platformy albo co najmniej jeden oczekiwany rekord A/AAAA;
- NXDOMAIN, brak lub niezgodny rekord są rozstrzygającą porażką. Timeout i
  SERVFAIL są błędem przejściowym: zachowują wcześniejszą weryfikację przez
  ograniczony okres, ale są widoczne i ponawiane z backoffem;
- jednoznaczna zmiana TXT albo routingu po weryfikacji natychmiast usuwa zgodę
  na nowe certyfikaty. Ponowna weryfikacja wymaga nadal tego samego challenge;
- token jest zwracany wyłącznie właścicielowi w tenantowym API i nigdy nie trafia
  do logów, metryk ani publicznego endpointu TLS.

### On-Demand TLS

- Caddy kieruje zapytanie permission bezpośrednio prywatną siecią Compose do
  `/internal/caddy/domains/authorize/`; ścieżka jest blokowana na publicznym
  ingressie;
- endpoint normalizuje dokładnie jeden parametr `domain` i wykonuje indeksowany
  lookup. Nie uruchamia DNS i nie zwraca identyfikatora tenanta ani site;
- odpowiedź `2xx` otrzymuje wyłącznie domena `verified`, niezwolniona,
  nie-disabled, należąca do aktywnej organizacji i site z bieżącą publikacją;
- decyzje pozytywne i negatywne mają osobny krótki cache, aplikacyjny rate limit
  oraz metryki z wynikiem, ale bez hostname. Zmiana lifecycle unieważnia cache;
- brak backendu permission oznacza odmowę handshake. Caddy nie posiada
  fail-open ani statycznej allowlisty domen klientów;
- stan TLS w bazie opisuje kwalifikację i ostatnie żądanie (`pending`,
  `eligible`, `requested`, `disabled`, `failed`). Faktyczne wydanie i odnowienie
  certyfikatu obserwujemy w metrykach/logach Caddy; Caddy nie oferuje wiarygodnego
  callbacku domenowego, więc aplikacja nie pozoruje potwierdzenia issuance.

### Routing, renderer i SEO

- publiczne API Django rozwiązuje site wyłącznie z poprawnego, znormalizowanego
  `Host` i aktywnej domeny. Nieznany host, brak publikacji i nieaktywna organizacja
  zwracają `404`, bez fallbacku do pierwszego site lub tenanta;
- API odczytuje wyłącznie `Site.current_publication`, wybiera ścieżkę i locale ze
  snapshotu oraz zwraca dane bez identyfikatorów tenantowych;
- Next.js rozpoznaje host panelu/platformy, a pozostałe hosty kieruje do
  oddzielnego publicznego route tree. Renderer używa wyłącznie kontrolowanego
  registry `@saas-core/site-blocks`;
- alias domeny otrzymuje stałe przekierowanie na canonical host z zachowaniem
  ścieżki i query. Canonical, `hreflang` i `x-default` są budowane z canonical
  hosta oraz ścieżek zapisanych w publikacji;
- preview pozostaje osobnym, uwierzytelnionym use case'em panelu i nigdy nie jest
  dostępny przez publiczną domenę.

### CDN/WAF

- pilot publikuje Caddy bez zewnętrznego CDN/WAF. Ograniczamy powierzchnię przez
  firewall VPS, Caddy, limity request body, nagłówki bezpieczeństwa i rate limit;
- wybór providera CDN/WAF jest `Deferred` do W11, gdy znane będą wymagania
  produkcyjne, jurysdykcja danych, budżet i profil ruchu. Warstwa CDN nie może
  zmienić źródła prawdy Host ani cache'ować odpowiedzi między hostami.

## Konsekwencje

- dokładny indeks hostname zapewnia stałoczasową decyzję Caddy i resolver site;
- propagation DNS jest asynchroniczne i obserwowalne, a przejściowa awaria
  resolvera nie powoduje natychmiastowego outage istniejącej domeny;
- publiczny renderer nie potrzebuje tenantowej sesji, ale jego jedynym źródłem
  danych pozostaje zatwierdzony snapshot;
- staging nadal wymaga prawdziwej domeny, rekordów DNS i publicznego ACME, aby
  potwierdzić issuance; testy lokalne dowodzą polityki, nie zewnętrznego faktu;
- bez CDN/WAF origin jest widoczny i sam absorbuje ruch; ryzyko jest akceptowane
  wyłącznie dla pilota i wraca jako obowiązkowa decyzja w W11.

## Alternatywy odrzucone

- dynamiczna konfiguracja Caddy per domena — większa powierzchnia operacyjna i
  wyścigi między bazą a ingress;
- weryfikacja tylko po A/CNAME — umożliwia przejęcie osieroconego rekordu;
- DNS wykonywany w endpointcie permission — handshake zależałby od propagacji i
  zewnętrznego resolvera;
- fallback nieznanego hosta do site deploymentu — ryzyko ujawnienia treści
  innego tenanta i cache poisoning;
- wildcard dla domen klientów — klient nie deleguje nam swojej strefy i nadal
  wymagałby polityki issuance;
- wybór CDN/WAF bez środowiska produkcyjnego — kosztowna decyzja bez danych.

## Źródła

- `Plan/SaaS-Core-06-Rejestr-Decyzji.md` — ADR-003 i ADR-010;
- `docs/adr/ADR-025-Runtime-Staging-Sekrety-i-Odtwarzanie.md`;
- `docs/adr/ADR-027-Sites-Tresc-Media-i-Publikacja.md`;
- `docs/architecture/api-and-events.md`;
- https://caddyserver.com/docs/caddyfile/options#on-demand-tls;
- https://caddyserver.com/on-demand-tls;
- https://dnspython.readthedocs.io/en/stable/resolver-class.html;
- https://dnspython.readthedocs.io/en/stable/resolver-caching.html.
