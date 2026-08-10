# SaaS Core - architektura aplikacji

## 1. Założenia

- Jeden wspólny kod dla wielu produktów.
- Osobny deployment i baza danych dla każdego produktu.
- Wewnątrz produktu wielu tenantów/organizacji.
- Modularny monolit z jasno określonymi granicami modułów.
- API-first: Next.js komunikuje się z Django przez wersjonowane API.
- Zadania asynchroniczne są wykonywane poza procesem HTTP.
- Moduły branżowe rozszerzają Core bez jego forkowania.

## 2. Topologia aplikacji

| Element | Przeznaczenie | Przykładowy adres |
| --- | --- | --- |
| Landing produktu | marketing i oferta operatora | `medplano.pl` |
| Panel klienta | zarządzanie organizacją i stroną | `app.medplano.pl` |
| Public Site Renderer | strony i wizytówki klientów | własne domeny i subdomeny |
| API | logika biznesowa | `api.medplano.pl` |
| Django Admin | wewnętrzne zaplecze techniczne | adres wewnętrzny |
| Status page | dostępność usług | `status.medplano.pl` |

## 3. Stos technologiczny

### Frontend

- Next.js;
- TypeScript;
- Tailwind CSS;
- wspólny system komponentów UI;
- biblioteka tłumaczeń obsługująca routing locale;
- generowany klient API z dokumentacji OpenAPI;
- formularze z walidacją po stronie klienta i serwera.

### Backend

- Django w wersji LTS;
- Django REST Framework;
- PostgreSQL;
- Redis;
- Celery i Celery Beat;
- OpenAPI;
- wewnętrzny Django Admin.

### Infrastruktura

- Docker Compose;
- Caddy;
- storage zgodny z S3;
- zewnętrzny dostawca poczty transakcyjnej;
- monitoring błędów, metryk i logów;
- zewnętrzny backup bazy i plików.

## 4. Przepływy żądań

### Panel klienta

```text
Przeglądarka
  -> Caddy
  -> Next.js Panel
  -> Django REST API
  -> PostgreSQL / Redis / Worker
```

### Strona klienta

```text
Domena klienta
  -> Caddy
  -> Next.js Site Renderer
  -> rozpoznanie Site po hostname
  -> pobranie opublikowanej treści
```

### Zadanie asynchroniczne

```text
Zmiana stanu w API
  -> zapis danych
  -> zapis zdarzenia w outbox
  -> Celery Worker
  -> e-mail / webhook / generowanie strony
```

## 5. Proponowana struktura repozytorium

```text
apps/
  backend/
    config/
    modules/
      identity/
      tenancy/
      permissions/
      billing/
      entitlements/
      sites/
      domains/
      content/
      files/
      notifications/
      audit/
      integrations/
      jobs/
    shared/
    verticals/
      medical/
      beauty/

  frontend/
    src/
      app/
      core/
      modules/
      verticals/
      components/
      generated-api/

packages/
  ui/
  site-blocks/
  contracts/

deployments/
  medplano/
  beauty/

infra/
  docker/
  caddy/
  monitoring/
  scripts/

docs/
```

## 6. Profile deploymentów

Deployment określa:

- nazwę i markę produktu;
- aktywne moduły;
- domyślne języki;
- motyw panelu;
- dostępne bloki stron;
- katalog planów;
- integracje;
- polityki retencji;
- ustawienia poczty;
- domeny systemowe.

Przykład koncepcyjny:

```python
ENABLED_MODULES = [
    "core.identity",
    "core.tenancy",
    "core.billing",
    "core.sites",
    "core.domains",
    "core.notifications",
    "modules.booking",
    "verticals.medical",
]
```

Frontend korzysta z analogicznego manifestu:

```ts
export const deploymentConfig = {
  product: "medplano",
  modules: [
    coreModule,
    sitesModule,
    billingModule,
    bookingModule,
    medicalModule,
  ],
};
```

## 7. Kontrakt modułu

Backendowy moduł może rejestrować:

- modele i migracje;
- endpointy API;
- uprawnienia;
- entitlementy i limity;
- zadania asynchroniczne;
- zdarzenia i ich handlery;
- integracje;
- wpisy administracyjne.

Frontendowy moduł może rejestrować:

- strony panelu;
- pozycje menu;
- formularze;
- widgety dashboardu;
- bloki publicznej strony;
- elementy onboardingu;
- tłumaczenia.

Moduły są aktywowane na etapie budowania/deploymentu. W pierwszej wersji nie przewiduje się instalowania niezweryfikowanego kodu modułów przez klientów.

## 8. Nadpisywanie konfiguracji

Kolejność rozstrzygania ustawień:

```text
Core defaults
  -> Vertical defaults
    -> Deployment defaults
      -> Plan entitlements
        -> Organization settings
          -> User preferences
```

Nadpisywanie dotyczy ustawień i prezentacji, a nie omijania reguł bezpieczeństwa.

## 9. API i kompatybilność

- Publiczne endpointy posiadają wersję, np. `/api/v1`.
- OpenAPI jest źródłem generowanego klienta TypeScript.
- Zmiana niekompatybilna wymaga nowej wersji lub okresu migracji.
- Webhooki posiadają wersję payloadu.
- Bloki stron mają `schema_version` oraz migratory treści.
- Każdy moduł posiada własne migracje bazy.

## 10. Granice architektury

Na pierwszym etapie nie wprowadzamy:

- Kubernetes;
- niezależnych mikroserwisów dla każdego modułu;
- osobnej bazy dla każdego tenanta;
- dynamicznego wykonywania kodu dostarczonego przez klienta;
- dowolnego page buildera uruchamiającego JavaScript klienta;
- współdzielonej bazy dla różnych produktów branżowych.

## 11. Zadania do dalszego rozpisania

- [x] dokładny mechanizm rejestracji modułów Django — `docs/architecture/module-contract.md`;
- [x] kontrakt rejestru tras i menu Next.js — `docs/architecture/module-contract.md`;
- [x] strategia sesji pomiędzy Next.js i Django — `docs/architecture/auth-and-tenant-context.md`;
- [x] generowanie i publikowanie klienta OpenAPI — `docs/architecture/api-and-events.md`;
- [x] zasady komunikacji modułów przez zdarzenia — `docs/architecture/api-and-events.md`;
- [x] strategia testów kontraktowych — `docs/architecture/testing-strategy.md`;
- [ ] strategia migracji treści `PageBlock`.
