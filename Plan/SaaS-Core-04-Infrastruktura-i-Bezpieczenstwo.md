# SaaS Core - infrastruktura i bezpieczeństwo

## 1. Środowiska

Każdy produkt posiada co najmniej:

- local development;
- staging;
- production.

Staging i production mają osobne:

- bazy danych;
- sekrety;
- domeny;
- konta/test mode Stripe;
- storage;
- konfiguracje poczty.

## 2. Kontenery

Minimalny zestaw usług:

```text
caddy
frontend
backend
worker
scheduler
postgres
redis
object-storage lub adapter zewnętrznego S3
monitoring
```

Wymagania:

- healthchecki;
- limity CPU i RAM;
- kontenery uruchamiane bez roota;
- obrazy wersjonowane i niemodyfikowane na serwerze;
- trwałe wolumeny tylko tam, gdzie są wymagane;
- brak dostępu aplikacji do Docker socket;
- sekrety poza repozytorium;
- kontrolowana kolejność migracji i deploymentu.

## 3. Deployment

Proponowany przepływ:

1. testy i lint;
2. budowa obrazów;
3. skan zależności i obrazów;
4. publikacja obrazu z numerem wersji;
5. backup przed ryzykowną migracją;
6. uruchomienie migracji;
7. aktualizacja kontenerów;
8. healthcheck;
9. smoke tests;
10. możliwość szybkiego rollbacku aplikacji.

Migracja bazy musi być kompatybilna z poprzednią i nową wersją aplikacji, jeśli deployment nie jest wykonywany atomowo.

## 4. Własne domeny i TLS

Przepływ domeny:

1. Klient dodaje domenę w panelu.
2. System generuje token i instrukcję DNS.
3. Worker sprawdza TXT/CNAME/A/AAAA.
4. Backend oznacza domenę jako zweryfikowaną.
5. Endpoint autoryzacyjny Caddy zwraca zgodę tylko dla aktywnej domeny z bazy.
6. Caddy pobiera i odnawia certyfikat.
7. Site Renderer rozpoznaje stronę na podstawie nagłówka Host.
8. System ustawia canonical i ewentualne przekierowania.

Zabezpieczenia:

- normalizacja hostname;
- unikalność domeny;
- ochrona przed domain takeover;
- powtórna weryfikacja po zmianie DNS;
- allowlista dla wystawiania certyfikatów;
- rate limiting endpointu weryfikującego;
- usunięcie powiązania po zakończeniu retencji.

Dokumentacja: [Caddy On-Demand TLS](https://caddyserver.com/on-demand-tls).

## 5. Poczta transakcyjna

Poczta aplikacyjna obejmuje:

- weryfikację konta;
- reset hasła;
- zaproszenia;
- informacje o subskrypcji;
- rezerwacje i przypomnienia;
- alerty operatora.

Wymagany interfejs dostawcy:

```text
EmailProvider
  send(message, idempotency_key)
  get_status(provider_message_id)
  handle_webhook(payload)
```

Mechanizmy obowiązkowe:

- wysyłka wyłącznie przez worker;
- retry z backoff;
- idempotency;
- DKIM, SPF i DMARC;
- bounce i complaint handling;
- suppression list;
- podpisywane webhooki;
- wielojęzyczne i wersjonowane szablony;
- ograniczona retencja treści;
- brak wrażliwych informacji w temacie wiadomości.

Domyślna decyzja: dostawca zewnętrzny. Konkretnego dostawcę wybierzemy po porównaniu DPA, lokalizacji danych, dostarczalności, API, webhooków i kosztów.

## 6. Skrzynki pocztowe klientów

Skrzynki `kontakt@domena-klienta.pl` są osobnym produktem od poczty transakcyjnej.

Opcje:

1. zewnętrzny operator skrzynek - wariant rekomendowany;
2. własny mailcow - wariant wymagający osobnego VPS-a i IP.

Wariant lokalny wymaga:

- PTR/rDNS;
- SPF, DKIM i DMARC;
- ochrony antyspamowej i antywirusowej;
- 2FA;
- monitorowania kolejek i blacklist;
- limitów wysyłki;
- szyfrowanych backupów;
- procesu aktualizacji bezpieczeństwa;
- planu odzyskania poczty.

Dokumentacja: [mailcow dockerized](https://docs.mailcow.email/).

Serwer pocztowy nie powinien działać na tym samym VPS-ie i IP co główna aplikacja.

## 7. Płatności i faktury

Stripe odpowiada za:

- Checkout;
- metodę płatności;
- subskrypcję;
- trial;
- ponowienia płatności;
- Customer Portal;
- zdarzenia webhook.

Backend:

- weryfikuje podpis webhooka;
- zapisuje nieprzetworzony identyfikator zdarzenia;
- zapewnia idempotency;
- przetwarza zdarzenie w workerze;
- aktualizuje lokalny snapshot subskrypcji i entitlementów;
- uruchamia adapter fakturowania.

Dokumentacja:

- [Stripe subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks)
- [Stripe Customer Portal](https://docs.stripe.com/customer-management)
- [KSeF - etapy wdrożenia](https://ksef.podatki.gov.pl/etapy-wdrozenia-ksef/)

## 8. Uwierzytelnianie

Założenia początkowe:

- panel działa na stałej domenie aplikacji;
- bezpieczne cookie HttpOnly i Secure;
- ochrona CSRF;
- brak tokenów sesyjnych w localStorage;
- rate limiting logowania;
- potwierdzenie e-mail;
- 2FA obowiązkowe dla operatorów i rekomendowane dla właścicieli;
- możliwość unieważnienia sesji;
- logowanie prób i zmian zabezpieczeń.

Django Admin:

- tylko operatorzy platformy;
- osobny adres;
- 2FA;
- audyt działań;
- ograniczenie sieciowe lub VPN, jeśli wykonalne;
- brak używania jako panel klienta.

## 9. Izolacja danych

- Każdy request API rozwiązuje aktywną organizację z sesji i membership.
- `organization_id` przesłane przez frontend nie jest samodzielną podstawą dostępu.
- QuerySety tenantowe wymagają jawnego tenant context.
- Testy próbują odczytać i zmienić zasoby innej organizacji.
- Operacje operatora są audytowane.
- Dla wybranych tabel można zastosować PostgreSQL RLS jako drugą warstwę.
- Każdy vertical posiada oddzielną bazę produkcyjną.

## 10. Pliki i upload

- allowlista MIME i rozszerzeń;
- limit rozmiaru;
- skan plików;
- generowanie losowych nazw obiektów;
- prywatne pliki przez krótkotrwałe signed URL;
- brak wykonywania uploadowanego HTML/JS;
- usuwanie metadanych EXIF, gdy nie są potrzebne;
- limit storage per organizacja;
- lifecycle i retencja obiektów.

## 11. Logi i monitoring

Każde żądanie i zadanie otrzymuje correlation ID.

Monitorujemy:

- błędy aplikacji;
- czas odpowiedzi API;
- kolejkę zadań;
- nieudane webhooki;
- opóźnione wiadomości;
- status certyfikatów;
- miejsce na dysku;
- PostgreSQL i Redis;
- wyniki backupu;
- błędy logowania i podejrzany ruch.

Logi nie powinny zawierać haseł, kluczy, pełnych tokenów, danych kart ani niepotrzebnych danych medycznych.

## 12. Backup i odtwarzanie

Minimum:

- codzienny pełny backup PostgreSQL;
- częstszy backup/WAL zależnie od RPO;
- backup storage;
- kopia poza VPS-em i poza jednym dostawcą awarii;
- szyfrowanie;
- retencja kilku przedziałów czasu;
- automatyczny raport powodzenia;
- regularny test odtworzenia.

Do ustalenia:

- RPO - dopuszczalna utrata danych;
- RTO - maksymalny czas przywrócenia usługi;
- częstotliwość prób odtworzenia;
- procedura awarii całego VPS-a.

## 13. Dodatkowe wymagania dla MedPlano

- minimalizacja danych zdrowotnych;
- ogólna treść e-maili i SMS-ów;
- silniejsza polityka 2FA;
- rozszerzony audit log;
- przegląd dostawców i umów powierzenia;
- krótsza retencja diagnostycznych logów;
- zakaz wysyłania danych pacjenta do modeli AI bez osobno zatwierdzonego procesu.

## 14. Otwarte decyzje infrastrukturalne

- [ ] dostawca VPS i parametry pierwszej instancji;
- [ ] zewnętrzny storage czy MinIO;
- [ ] konkretny dostawca poczty transakcyjnej;
- [ ] operator skrzynek klientów;
- [ ] narzędzie monitoringu i agregacji logów;
- [ ] strategia sekretów;
- [ ] narzędzie backupu PostgreSQL;
- [ ] RPO i RTO;
- [ ] zakres WAF/CDN;
- [ ] integracja z systemem faktur/KSeF.
