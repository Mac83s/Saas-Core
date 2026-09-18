# Development na Windows + WSL

## Wymagania

- Windows 11 z WSL2;
- dystrybucja Ubuntu uruchamiająca Node.js 24 LTS;
- pnpm 11 (wersja projektu jest zapisana w `packageManager`);
- `uv`; Python 3.14 jest instalowany przez `uv`, nie globalnie;
- Docker Desktop z integracją dla używanej dystrybucji WSL;
- Git z końcami linii LF wewnątrz repozytorium.

Repozytorium może znajdować się na dysku Windows pod `/mnt/...`, lecz przy
problemach z wydajnością Next.js zalecany jest filesystem WSL. Nie uruchamiaj
jednocześnie procesu Node z Windows i WSL na tym samym `node_modules`.

## Bootstrap

```bash
corepack pnpm bootstrap --profile core-only
```

Skrypt weryfikuje Node 24, instaluje oba ekosystemy z lockfile, uruchamia
PostgreSQL i Redis, waliduje profil, wykonuje migracje oraz generuje OpenAPI i
klienta TypeScript. Bez `--profile` bootstrap bierze główny profil z `product.json` (w repozytorium produktu — ten produkt).

Pełny runtime uruchamia jedna komenda:

```bash
pnpm runtime:up
pnpm runtime:smoke
```

Panel oraz API są dostępne wyłącznie przez Caddy pod
`http://localhost:8080`. PostgreSQL i Redis są wiązane tylko do
`127.0.0.1`, aby nadal obsługiwać testy uruchamiane z WSL.

Do pracy z hot reloadem można uruchomić procesy w dwóch terminalach:

```bash
uv run --project apps/backend python apps/backend/manage.py migrate
uv run --project apps/backend python apps/backend/manage.py runserver
```

```bash
pnpm dev
```

W tym wariancie panel jest dostępny pod `http://localhost:3000`, a API pod
`http://localhost:8000/api/v1/health/`. Next.js proxy przekazuje `/api/*` do
backendu, więc przeglądarka pozostaje same-origin również bez Caddy.

## Kontrole

```bash
pnpm deployment:check:all
pnpm api:check
pnpm check
pnpm backend:check
```

Pytest używa przechwytywania `sys` zamiast domyślnego `fd`. Zapobiega to utracie
pliku tymczasowego runnera podczas testów integracyjnych korzystających z
Docker Desktop, gdy repozytorium znajduje się na montowanym dysku Windows.

Zmiana komponentów shadcn jest wykonywana z katalogu aplikacji. CLI umieści kod
w `packages/ui` dzięki obu plikom `components.json`:

```bash
pnpm dlx shadcn@latest add select combobox -c apps/frontend
```

Wartości sekretne kopiujemy z `.env.example` do lokalnego `.env`; pliku `.env`
nie commitujemy. Hasła w `compose.yaml` są wyłącznie lokalnymi danymi developerskimi.

## Reset lokalnych danych

Poniższa komenda nie jest częścią zwykłego restartu. Usuwa wyłącznie lokalne
wolumeny Compose z bazą i Redisem, a następny bootstrap tworzy je od zera:

```bash
docker compose down --volumes
corepack pnpm bootstrap --profile core-only
```
