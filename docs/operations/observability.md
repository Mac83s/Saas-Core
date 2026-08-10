# Obserwowalność

## Lokalny test

Pełny stos uruchamia się razem z aplikacją:

```bash
pnpm runtime:up
pnpm runtime:smoke:observability
```

Test sprawdza endpoint metryk Django, zdrowie Grafany, siedem targetów
Prometheus, widoczność workera Celery oraz obecność logów w Loki. Grafana jest
dostępna pod `http://127.0.0.1:3001`; użytkownik to `admin`, a wygenerowane hasło
znajduje się w `.runtime/secrets/grafana_admin_password`.

Dashboard `SaaS Core / Overview` oraz źródła Prometheus i Loki są provisionowane
z repozytorium, więc nie wymagają ręcznej konfiguracji.

## Przepływ danych

- Caddy, Django, Celery, PostgreSQL, Redis, Loki i Alloy są targetami Prometheus;
- backend, worker i scheduler zapisują strukturalne JSONL do katalogu runtime;
- Alloy ma ten katalog zamontowany tylko do odczytu, dodaje wyłącznie ograniczone
  etykiety `service` i `level`, a następnie wysyła rekordy do Loki;
- Alloy nie ma dostępu do Docker socketu;
- publiczny ingress nie udostępnia Prometheus, Loki ani metryk Django na stagingu.

## Dostęp operatora na stagingu

Grafana jest publikowana wyłącznie na loopback VPS-a. Operator zestawia tunel:

```bash
ssh -L 3001:127.0.0.1:3001 deploy@staging.example.com
```

Następnie otwiera `http://127.0.0.1:3001`. Hasło znajduje się wyłącznie w
`${DEPLOY_PATH}/secrets/grafana_admin_password` na hoście.

## Alerty

Reguły Prometheus obejmują niedostępny target, brak workera Celery i błędy HTTP
5xx. Zewnętrzny odbiorca nie jest jeszcze skonfigurowany: przed zamknięciem W2
trzeba wskazać kanał odbioru dostępny poza VPS-em, wysłać alert syntetyczny i
zarchiwizować potwierdzenie dostarczenia bez danych wrażliwych.
