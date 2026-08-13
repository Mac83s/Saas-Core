# Profil deploymentu

## 1. Rola profilu

Profil opisuje niesekretną kompozycję produktu. Jest wersjonowany razem z kodem,
walidowany przed uruchomieniem i stanowi jedyne źródło aktywacji modułów. Sekrety
i dane zależne od środowiska nie trafiają do profilu ani do wygenerowanego
katalogu frontendowego.

## 2. Minimalny profil MedPlano

Plik `deployments/medplano/deployment.json`:

```json
{
  "$schema": "../../packages/contracts/deployment.schema.json",
  "schemaVersion": 1,
  "id": "medplano",
  "product": {
    "name": "MedPlano",
    "defaultLocale": "pl",
    "supportedLocales": ["pl", "en"],
    "platformDomain": "medplano.pl"
  },
  "modules": [
    "core.identity",
    "core.organizations",
    "core.audit",
    "shared.billing",
    "shared.sites",
    "shared.media",
    "shared.notifications",
    "shared.booking",
    "vertical.medical",
    "config.medplano"
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

Profil `deployments/core-only/deployment.json` pomija wszystkie verticale i służy
do udowodnienia, że Core oraz Shared działają bez MedPlano.

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
- backendowy i frontendowy deskryptor tego samego modułu są niespójne.

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
pnpm deployment:check --profile medplano
pnpm module-catalog:check --profile medplano
pnpm deployment:render --profile medplano
```

Komendy są podłączone do wspólnego runnera, a ich nazwy stanowią część
kontraktu CI.
