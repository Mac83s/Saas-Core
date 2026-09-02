# Profil deploymentu

## 1. Rola profilu

Profil opisuje niesekretną kompozycję produktu. Jest wersjonowany razem z kodem,
walidowany przed uruchomieniem i stanowi jedyne źródło aktywacji modułów. Sekrety
i dane zależne od środowiska nie trafiają do profilu ani do wygenerowanego
katalogu frontendowego.

## 2. Profil generyczny `business`

Plik `deployments/business/deployment.json`:

```json
{
  "$schema": "../../packages/contracts/deployment.schema.json",
  "schemaVersion": 1,
  "id": "business",
  "product": {
    "name": "SaaS Core Business",
    "defaultLocale": "pl",
    "supportedLocales": ["pl", "en"],
    "platformDomain": "business.localhost"
  },
  "modules": [
    "core.health",
    "core.identity",
    "core.organizations",
    "shared.billing",
    "shared.sites",
    "shared.media",
    "shared.notifications",
    "shared.booking"
  ],
  "billing": {
    "planKeys": ["profile", "starter", "pro"]
  },
  "features": {
    "customDomains": true,
    "publicBooking": true
  }
}
```

Profil `deployments/core-only/deployment.json` zawiera wyłącznie moduły Core i
służy do udowodnienia, że Core działa bez żadnego modułu Shared. Serwisy
branżowe (np. MedPlano) dostaną własne profile, gdy powstanie ich kod; do tego
czasu profil `deployments/_planned/medplano/deployment.json` jest poza
katalogiem i nie jest walidowany — deklarowałby moduły, których nie ma.

## 3. Walidacja

Walidator kończy proces kodem różnym od zera, gdy:

- dokument nie spełnia JSON Schema albo używa nieznanej wersji;
- identyfikator modułu nie istnieje lub pojawia się dwukrotnie;
- brakuje zależności bezpośredniej lub przechodniej;
- graf zawiera cykl albo import w niedozwolonym kierunku;
- locale domyślne nie należy do listy obsługiwanych;
- profil z aktywnym `shared.billing` nie zawiera dokładnie trzech unikalnych
  kluczy `billing.planKeys`;
- profil zawiera klucz oznaczony jako sekret;
- deskryptor deklaruje `backend.djangoApp`, którego pakiet nie istnieje w
  `apps/backend/src` — katalog ma opisywać kod, który jest;
- deskryptor deklaruje w `backend.publicTables` tabelę spoza własnej aplikacji
  (ADR-039);
- backendowy i frontendowy deskryptor tego samego modułu są niespójne.

Drugi kierunek — każda aplikacja `saas_core.modules.*` w `INSTALLED_APPS` ma
deskryptor — sprawdza test backendu `tests/test_module_catalog.py`.

Lista modułów po rozwiązaniu zależności jest sortowana topologicznie i zapisywana
do artefaktu builda razem z hashem profilu. Runtime odmawia startu, jeżeli hash
profilu i obrazu są różne.

## 4. Moment konfiguracji

| Moment | Przykłady | Źródło |
| --- | --- | --- |
| build-time | moduły, locale, identyfikator produktu | `deployment.json` |
| deploy-time | hosty, nazwa bazy, adres Redis, bucket | zmienne środowiska |
| runtime | plan organizacji, feature override, aktywna domena | PostgreSQL |
| secret | hasła, klucze API, signing keys | secret store / plik poza repo |

Zmiana build-time wymaga nowego obrazu. Zmiana deploy-time wymaga ponownego
uruchomienia kontenera. Runtime jest zmieniany przez kontrolowane use case'y i
zapisywany w audycie.

`billing.planKeys` jest build-time'ową listą publicznego katalogu konkretnego
deploymentu. Dla obecnej oferty zawiera dokładnie trzy stabilne klucze. Profil
bez `shared.billing`, taki jak `core-only`, nie wymaga sekcji `billing`.

## 5. Komendy

```text
pnpm deployment:check --profile business
pnpm module-catalog:check --profile business
pnpm deployment:render --profile business
```

Komendy są podłączone do wspólnego runnera, a ich nazwy stanowią część
kontraktu CI.
