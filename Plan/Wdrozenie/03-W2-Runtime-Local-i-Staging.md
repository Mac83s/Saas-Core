# W2 — runtime local i staging

**Status:** in progress  
**Szacunek:** 1–2 tygodnie  
**Poprzednik:** W1  
**Rezultat:** powtarzalne środowisko lokalne i pierwszy automatyczny staging

## 1. Scenariusz demonstracyjny

Jedna komenda uruchamia Caddy, frontend, backend, worker, scheduler, PostgreSQL i
Redis. Commit spełniający bramki buduje wersjonowane obrazy, wdraża je na
staging, wykonuje migracje i smoke test, a operator potrafi przywrócić bazę z
testowej kopii.

## 2. Pakiety pracy

### W2.0 — decyzje i kontrakty operacyjne

- [x] zatwierdzić topologię pojedynczego VPS-a i granice sieci;
- [x] wybrać dystrybucję obrazów oraz sposób wersjonowania i rollbacku;
- [x] zatwierdzić strategię sekretów i niesekretnej konfiguracji;
- [x] wybrać stagingowy storage oraz stos obserwowalności;
- [x] zatwierdzić stagingowe RPO/RTO i metodę restore drill;
- [x] zapisać decyzje w ADR-025 oraz rejestrze decyzji.

### W2.1 — obrazy i Compose

- [x] utworzyć wieloetapowe obrazy backendu i frontendu;
- [x] uruchamiać procesy jako użytkownik bez roota i bez zbędnych capabilities;
- [x] zdefiniować migrator, web, worker i scheduler z jednego obrazu backendu;
- [x] dodać healthchecki, limity, restart policy i zależności gotowości;
- [x] nie publikować portów aplikacji i danych poza lokalną pętlę zwrotną;
- [x] przygotować wolumeny wyłącznie dla PostgreSQL, Redis, Caddy i monitoringu;
- [x] sprawdzić oba obrazy jako `linux/amd64` i zapisać użytkownika procesu.

### W2.2 — konfiguracja i sekrety

- [x] wdrożyć wspólny odczyt `<NAZWA>_FILE` i walidację ustawień przy starcie;
- [x] rozdzielić przykładową konfigurację local i staging od wartości runtime;
- [x] ograniczyć sekrety per usługa i zabronić ich jako build args;
- [x] zapewnić, że publiczna konfiguracja frontendu nie ujawnia sekretów;
- [x] opisać tworzenie, rotację i awaryjne unieważnienie sekretów;
- [x] dodać skan repozytorium, historii, obrazów i logów testowych.

### W2.3 — Caddy i routing

- [x] uruchomić lokalny ingress na `http://localhost:8080`;
- [x] kierować `/api/*` do Django, a pozostałe ścieżki do Next.js;
- [x] ufać nagłówkom proxy wyłącznie od wewnętrznego Caddy;
- [x] przekazywać/generować correlation ID i ustawić limity request body;
- [x] dodać HSTS tylko dla staging HTTPS i bazowe security headers;
- [x] przygotować stałe hosty stagingu bez On-Demand TLS klientów;
- [x] przetestować routing, same-origin i niedostępność każdego upstreamu.

### Dowody W2.1 — 2026-08-10

- obrazy backendu, frontendu i Caddy zbudowane z attestation dla `linux/amd64`;
- procesy aplikacyjne oraz Caddy działają jako UID/GID `10001`, z
  `no-new-privileges` i `cap_drop: ALL`;
- siedem długowiecznych usług osiąga stan `healthy`, a migrator kończy kodem 0;
- smoke przez Caddy potwierdza panel, liveness, readiness PostgreSQL/Redis i
  spójny correlation ID;
- odizolowany projekt `saas-core-clean` przeszedł start od pustych wolumenów,
  pełny smoke, restart z zachowaniem danych i ponowny smoke;
- świeże zasoby `saas-core-clean` zostały usunięte po teście; główny runtime
  pozostał uruchomiony.

### W2.4 — pipeline wdrożenia

- [x] budować `linux/amd64` i tagować obrazy `sha-<commit>`;
- [x] publikować obrazy i attestations do GHCR bez sekretów build-time;
- [x] skanować obrazy przed dopuszczeniem do rollout;
- [x] serializować staging przez GitHub Environment i concurrency group;
- [x] wykonać migrację jako pojedynczy job, rollout i smoke przez Caddy;
- [x] zapisać digesty, poprzednią wersję i wynik healthchecków;
- [x] opisać rollback obrazu i expand/contract dla migracji.

Powyższy pipeline jest zaimplementowany i lokalnie zwalidowany składniowo. Jego
faktyczne wykonanie pozostaje częścią bramki wyjścia i wymaga repozytorium GHCR,
VPS-a, domeny oraz GitHub Environment `staging`.

### W2.5 — obserwowalność i odtwarzanie

- [x] włączyć strukturalne logi JSON z correlation ID dla HTTP i Celery;
- [x] dodać metryki Caddy/Django/Celery/PostgreSQL/Redis bez wysokiej kardynalności;
- [x] skonfigurować Prometheus, Loki, Alloy i Grafana bez Docker socketu;
- [ ] wysłać syntetyczny alert poza VPS bez danych wrażliwych;
- [ ] wykonywać `pg_dump -Fc`, szyfrowanie i kopię do osobnego bucketa;
- [x] walidować checksumę i możliwość odczytu katalogu archiwum;
- [x] odtworzyć backup do izolowanej bazy, wykonać migracje i integrity check;
- [x] zapisać lokalny czas i raport restore drill; pomiar RPO/RTO stagingu wymaga hosta.

## 3. Kolejność wykonania i dowody

| Etap | Zależność | Dowód zakończenia |
| --- | --- | --- |
| W2.0 decyzje | W1 | ADR-025 i zamknięte pozycje rejestru |
| W2.1 obrazy | W2.0 | build, inspect non-root, skan bez critical |
| W2.2 config | W2.1 | start z secret files i test braku każdego wymaganego ustawienia |
| W2.3 ingress | W2.1–W2.2 | smoke przez Caddy i test awarii upstreamu |
| W2.5 telemetry | W2.3 | metryki/logi po wspólnym correlation ID |
| W2.5 restore | W2.1–W2.2 | raport backup → restore z czasem i checksumą |
| W2.4 staging | wszystkie lokalne | digest GHCR, migracja i smoke na osobnym hoście |

## 4. Testy obowiązkowe

- start od pustych wolumenów i ponowny start z danymi;
- healthchecki w stanach healthy, starting i dependency unavailable;
- migracja forward oraz uruchomienie poprzedniej wersji aplikacji, gdy wspierane;
- smoke test przez Caddy, nie bezpośrednio do kontenera;
- awaria workera nie blokuje operacji synchronicznej;
- backup → usunięcie danych testowych → restore → kontrola integralności.

## 5. Bramka wyjścia

- [x] lokalne środowisko uruchamia się jedną udokumentowaną komendą;
- [ ] staging nie współdzieli bazy, sekretów ani storage z innym środowiskiem;
- [x] obrazy są wersjonowane i uruchamiane bez roota;
- [ ] pipeline wykonał na prawdziwym stagingu migrację, smoke test i próbę rollbacku;
- [x] lokalny restore drill zakończył się poprawnie i ma zapisany czas 6 s;
- [ ] logi i metryki pozwalają powiązać request z zadaniem Celery;
- [ ] W3 może bezpiecznie dodać migracje Identity.

### Dowody W2.2–W2.5 — 2026-08-10

- konfiguracja stagingu renderuje się bez publikowania portów bazy, Redis,
  backendu ani frontendu; jedynym ingress pozostaje Caddy 80/443;
- CI skanuje pełną historię przez Gitleaks, zależności JS/Python, a workflow
  obrazów generuje SBOM/provenance i blokuje High/Critical przez Trivy;
- failure smoke potwierdził odrębne zachowanie liveness/readiness oraz awarie
  Redis, backendu, frontendu i workera, po czym odtworzył wszystkie usługi;
- lokalny `pg_dump -Fc` ma checksumę SHA-256; restore do bazy
  `saas_core_restore_*` odtworzył 18 migracji, przeszedł Django check w 6 s i
  usunął bazę testową;
- workflow stagingu zapisuje dokładne referencje `repo@sha256`, poprzedni
  release i manifest, a rollback nie cofa automatycznie schematu danych;
- smoke obserwowalności potwierdził 7 aktywnych targetów Prometheus, dokładnie
  jednego workera Celery, logi aplikacji w Loki i zdrową Grafanę z
  provisionowanym dashboardem; Alloy czyta wyłącznie pliki JSONL i nie ma
  dostępu do Docker socketu.
