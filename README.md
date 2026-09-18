# SaaS Core

Modularny monolit Django + Next.js dla wielu osobnych produktów i deploymentów.
Profile dowodowe to `core-only` i generyczny `business`; produkty branżowe
(HoofCare, MedPlano i kolejne) żyją w osobnych repozytoriach wyprowadzonych z
Saas-Core i aktualizują rdzeń przez merge (ADR-049). Fala W1 oraz lokalna część W2 są
ukończone; uruchomienie pipeline'u na prawdziwym stagingu wymaga docelowego VPS-a,
domeny i konfiguracji GitHub Environment.

## Szybki start

Wymagane są Node.js 24 LTS, pnpm 11, `uv` oraz uruchomiony Docker Desktop z
integracją WSL. Po sklonowaniu repozytorium:

```bash
corepack pnpm bootstrap --profile core-only
```

Pełny runtime kontenerowy (Caddy, frontend, backend, worker, scheduler,
PostgreSQL i Redis) uruchamia jedna komenda:

```bash
pnpm runtime:up
pnpm runtime:smoke
```

Testy operacyjne i bezpieczna lokalna próba odtworzenia:

```bash
pnpm runtime:smoke:failures
pnpm runtime:smoke:observability
pnpm runtime:backup
pnpm runtime:restore-drill
```

- panel: `http://localhost:8080`;
- Grafana: `http://localhost:3001` (hasło w `.runtime/secrets/grafana_admin_password`);
- health API: `http://localhost:8080/api/v1/health/`;
- dokumentacja API: `http://localhost:8080/internal/api-docs/`.

Do pracy z hot reloadem można nadal uruchomić procesy bezpośrednio:

```bash
uv run --project apps/backend python apps/backend/manage.py runserver
pnpm dev
```

Pełna instrukcja dla Windows znajduje się w
[docs/development/windows-wsl.md](docs/development/windows-wsl.md). Decyzje
techniczne są w [docs/adr](docs/adr/README.md), a kolejność prac w
[Plan/Wdrozenie](Plan/Wdrozenie/00-MAPA-WDROZENIA.md).
Runbook stagingu, obserwowalności, sekretów i odtwarzania znajduje się w
[docs/operations](docs/operations/README.md).

## System UI

Panel korzysta z shadcn/ui v4 w wariancie Base UI / Nova. Kod komponentów należy
do `packages/ui`; aplikacje nie tworzą własnych kopii. Wspólny pakiet zawiera już
m.in. `Button`, `Card`, `Field`, `Input`, `Select` i `Combobox`.
