# ADR-025 — runtime staging, sekrety i odtwarzanie

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core  
**Przegląd:** przed pierwszym production i w W11

## Kontekst

W2 musi zapewnić taki sam kontrakt uruchomienia lokalnie i na stagingu, bez
przenoszenia sekretów do repozytorium ani uzależniania pierwszego wdrożenia od
orkiestratora klasy Kubernetes. Otwarte pozostawały: dystrybucja obrazów,
strategia sekretów, storage, obserwowalność oraz stagingowe RPO i RTO.

## Decyzja

### Runtime i obrazy

- staging działa na osobnym VPS-ie z Docker Engine i Docker Compose;
- Caddy jest jedyną usługą publikującą porty HTTP/HTTPS;
- frontend, backend, worker i scheduler uruchamiają się z niemodyfikowalnych,
  wieloetapowych obrazów jako użytkownik bez roota;
- jeden obraz backendu obsługuje proces HTTP, migracje, worker i scheduler;
- obrazy trafiają do GHCR z niezmiennym tagiem `sha-<commit>` i attestation;
- wdrożenie zapisuje również digest, aby rollback nie zależał od ruchomego tagu;
- początkową architekturą obrazu jest `linux/amd64`; multi-arch zostaje dodany,
  gdy zostanie wybrany host ARM lub drugi typ środowiska.

### Sieć i routing

- PostgreSQL, Redis, backend i frontend nie publikują portów na stagingu;
- Caddy kieruje `/api/*` do Django, a pozostałe żądania do Next.js;
- panel i API przeglądarkowe pozostają same-origin zgodnie z ADR-023;
- lokalny ingress działa na `http://localhost:8080`, bez lokalnego urzędu CA;
- On-Demand TLS dla domen klientów pozostaje wyłączony do W7;
- liveness nie sprawdza zależności, readiness sprawdza PostgreSQL i Redis.

### Konfiguracja i sekrety

- niesekretna konfiguracja jest przekazywana przez jawne zmienne środowiskowe;
- sekrety są montowane per usługa jako pliki Compose w `/run/secrets`;
- aplikacja obsługuje konwencję `<NAZWA>_FILE`, ale nie loguje odczytanej wartości;
- pliki stagingowe znajdują się poza checkoutem, mają prawa `0600` i są
  provisionowane poza procesem budowy obrazu;
- GitHub Environment `staging` przechowuje wyłącznie dane konieczne do deployu;
  workflow nie przekazuje sekretów aplikacji jako argumentów builda;
- pliki `.env` pozostają wyłącznie nośnikiem konfiguracji niesekretnej albo
  lokalnych wartości developerskich.

### Storage

- staging i production użyją zewnętrznego storage zgodnego z S3, z osobnymi
  bucketami i poświadczeniami;
- MinIO nie działa na tym samym VPS-ie co aplikacja, ponieważ nie usuwałby
  wspólnego punktu awarii;
- przed W6 lokalny runtime nie uruchamia sztucznego storage, jeśli żaden moduł
  jeszcze go nie konsumuje; kontrakt adaptera i testowy bucket powstaną w W6.

### Obserwowalność

- aplikacje zapisują strukturalne logi JSON na stdout/stderr z correlation ID;
- Prometheus zbiera metryki Caddy, Django, PostgreSQL, Redis i Celery;
- Loki przyjmuje logi przez Grafana Alloy, a Grafana udostępnia dashboardy;
- stos obserwowalności nie otrzymuje Docker socketu i nie indeksuje sekretów,
  cookie, tokenów ani treści medycznych;
- na stagingu monitoring może współdzielić VPS, ale alert syntetyczny ma trafić
  poza ten VPS; produkcyjna topologia jest ponownie oceniana w W11.

### Backup i odtwarzanie

- stagingowe **RPO wynosi 24 godziny**, a **RTO 4 godziny**;
- codzienny logiczny backup PostgreSQL powstaje przez `pg_dump -Fc` klientem w
  tej samej linii major co serwer;
- backup jest szyfrowany i kopiowany do osobnego bucketa/konta poza VPS-em;
- backup lokalny lub pozostawiony wyłącznie na VPS-ie nie spełnia bramki;
- co najmniej raz na falę wykonywany jest automatyczny restore do odizolowanej
  bazy, migracje, kontrola integralności i pomiar czasu;
- strategia produkcyjna (PITR/WAL, retencja i docelowe RPO/RTO) jest decyzją W11.

### Wdrożenie i rollback

- pipeline wykonuje quality, build, skan, push, migrację, rollout i smoke test;
- na danym stagingu może działać tylko jedna migracja;
- migracje w zwykłym rolloutcie muszą być kompatybilne z poprzednim obrazem;
- rollback aplikacji wskazuje poprzedni digest i nie cofa automatycznie danych;
- migracja destrukcyjna wymaga osobnego planu expand/contract i backupu.

## Konsekwencje

- Compose pozostaje prosty operacyjnie i wystarcza dla pierwszego VPS-a;
- sekrety nie trafiają do historii obrazu ani zwykłego `docker inspect`;
- zewnętrzny S3 i backup poza VPS-em usuwają wspólny punkt awarii danych;
- samohostowany monitoring stagingu nie przeżyje utraty VPS-a, dlatego
  zewnętrzny alert i backup są obowiązkowe, a produkcja wymaga rewizji w W11;
- `pg_dump` spełnia potrzeby małego stagingu, ale nie zastępuje przyszłego PITR;
- faktyczny deploy wymaga utworzonego VPS-a, domeny, repozytorium GHCR i sekretów
  GitHub Environment; kod nie może pozorować wykonania tych operacji.

## Alternatywy odrzucone

- Kubernetes — nieuzasadniona złożoność dla pierwszego, pojedynczego VPS-a;
- sekrety wyłącznie w zmiennych środowiskowych — łatwiejszy przypadkowy wyciek;
- sekrety zaszyfrowane kluczem przechowywanym w tym samym repo/VPS — brak realnej
  separacji materiału deszyfrującego;
- MinIO obok aplikacji — storage współdzieli awarię hosta;
- ruchome tagi `latest` — niejednoznaczny rollout i rollback;
- automatyczne cofanie migracji — ryzyko utraty danych i nieprzewidywalność.

## Źródła

- https://docs.docker.com/compose/how-tos/use-secrets/
- https://docs.docker.com/reference/compose-file/services/#depends_on
- https://docs.docker.com/build/building/best-practices/
- https://docs.astral.sh/uv/guides/integration/docker/
- https://nextjs.org/docs/app/getting-started/deploying
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- https://caddyserver.com/docs/metrics
- https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- https://www.postgresql.org/docs/18/backup.html
- https://www.postgresql.org/docs/18/app-pgdump.html
