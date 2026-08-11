# Staging — provisioning, deploy i rollback

## Kontrakt hosta

Staging wymaga osobnego VPS-a `linux/amd64` z Docker Engine, pluginem Compose,
`curl`, stałą domeną skierowaną na host oraz otwartymi portami 80/443. Konto
deploymentu musi móc uruchamiać Docker, ale nie powinno przyjmować logowania
hasłem. Host musi być wcześniej zalogowany do GHCR tokenem tylko do odczytu.
Pipeline mediów uruchamia oficjalny ClamAV w prywatnej sieci Compose. Zaplanuj
co najmniej 4 GiB RAM dla samego skanera oraz zasoby pozostałych usług; port
`3310` nie może być publikowany na hoście ani w Internecie.

Domyślna struktura poza checkoutem:

```text
/opt/saas-core/
├── staging.env
├── secrets/
├── releases/
└── state/
```

Skopiuj `deployments/staging/.env.example` jako `/opt/saas-core/staging.env`,
ustaw prawdziwą domenę, prefix GHCR i wartości niesekretne. Utwórz sekrety
według [secrets.md](secrets.md). Katalog główny i `secrets` mają należeć do
operatora deploymentu; pliki sekretów wymagają trybu `0600`.

Staging wymaga jawnego zewnętrznego storage S3: ustaw osobny bucket, prywatny
endpoint API, publiczny endpoint signed uploadów, region i właściwą politykę
path-style. Lokalny SeaweedFS jest wyłączony w stagingowym override. Poświadczenia
S3 mają być ograniczone do jednego bucketa i nie mogą być współdzielone z
backupami. Procesy backendowe korzystają z jawnej sieci `egress` do S3 i innych
zewnętrznych integracji; ClamAV pozostaje wyłącznie w prywatnej sieci `scanner`.

## GitHub Environment `staging`

Zmienne:

- `DEPLOY_PATH` — zwykle `/opt/saas-core`;
- `STAGING_URL` — pełny publiczny URL HTTPS bez końcowego znaczenia slasha.

Sekrety:

- `STAGING_HOST` — adres SSH hosta;
- `STAGING_USER` — dedykowany użytkownik deploymentu;
- `STAGING_SSH_KEY` — prywatny klucz Ed25519;
- `STAGING_KNOWN_HOSTS` — wcześniej zweryfikowany wpis host key, nie wynik
  pobrany bez weryfikacji w trakcie workflow.

Environment powinien wymagać akceptacji operatora dla pierwszych wdrożeń.
Sekrety Django, PostgreSQL i Redis pozostają wyłącznie na hoście — workflow ich
nie przesyła.

## Automatyczny deploy

Sekwencja `CI` → `Images` → `Deploy staging` działa wyłącznie dla `main`:

1. quality i skany repozytorium;
2. obrazy `linux/amd64`, SBOM, provenance, skan Trivy i tag `sha-<commit>`;
3. pull danych i usług, pojedyncza migracja, rollout bez publikowania ich portów;
4. fail-closed start workera sprawdzający bazę oraz połączenie z ClamAV;
5. smoke HTTPS przez Caddy;
6. zapis tagu, SHA, listy obrazów oraz dokładnych `repo@sha256` w `state/`.

Niepowodzenie smoke zatrzymuje workflow i zachowuje logi ostatnich 100 wpisów.
Migracje muszą używać expand/contract, ponieważ rollback aplikacji nie cofa
schematu ani danych.

## Rollback

Na hoście, po analizie błędu:

```bash
DEPLOY_PATH=/opt/saas-core \
STAGING_URL=https://staging.example.com \
sh /opt/saas-core/current/infra/deploy/staging-rollback.sh
```

Skrypt odtwarza poprzedni release i obrazy po zapisanych digestach, nie przez
`latest`, a następnie wykonuje readiness przez Caddy. Jeżeli poprzedni manifest
nie istnieje (pierwszy deploy), skrypt kończy się bez zmiany usług.

Rollback nie może przekroczyć granicy bezpieczeństwa sprzed rozdzielenia ról
PostgreSQL. Skrypt odrzuca release, którego Compose nie używa osobnej roli
aplikacyjnej `NOBYPASSRLS`; po rollbacku ponownie sprawdza backend, worker i
scheduler poleceniem `check_database_role`. Odrzucany jest również release,
który nie wymaga zewnętrznego S3. Worker po rollbacku musi przejść
`check_malware_scanner` przed wznowieniem przetwarzania mediów.
