# ADR-024 — API, OpenAPI i zdarzenia

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core

## Kontekst

Next.js ma korzystać z wersjonowanego API bez ręcznie utrzymywanych typów.
Moduły potrzebują niezawodnej komunikacji asynchronicznej, lecz projekt nie
powinien wprowadzać brokera zdarzeń ani mikroserwisów przed potrzebą.

## Decyzja

### HTTP API

- publiczny prefiks: `/api/v1/`;
- JSON używa `snake_case`, UUID jako string, Decimal jako string i daty ISO 8601
  z offsetem/UTC;
- mutacje zwracają jawny status i reprezentację albo `204`, bez ukrytych 200;
- błędy stosują `application/problem+json` zgodne z RFC 9457;
- rozszerzenia problemu: `code`, `errors`, `correlation_id`;
- tekst `detail` nie jest kluczem logiki frontendu;
- retry-safe POST akceptuje `Idempotency-Key` i zapisuje wynik w zakresie
  organizacji oraz operacji;
- lista wybiera cursor pagination dla danych rosnących i page-number dla małych,
  stabilnych katalogów; format jest jawny w OpenAPI.

### OpenAPI i klient

- drf-spectacular 0.30 generuje OpenAPI 3.1;
- kanoniczny artefakt: `packages/contracts/openapi/v1.yaml`;
- CI uruchamia generację z `--validate`, porównuje schema diff i blokuje drift;
- `openapi-typescript` generuje typy do `packages/api-client`;
- `openapi-fetch` jest minimalnym transportem współdzielonym przez RSC i klienta;
- TanStack Query hooks są cienkimi, ręcznymi adapterami use-case, nie drugim
  generatorem modeli;
- schema i klient powstają deterministycznie; generated files nie są edytowane.

### Kompatybilność

- dodanie opcjonalnego pola jest kompatybilne;
- usunięcie/zmiana typu, semantyki lub wymagania pola wymaga nowej wersji albo
  okresu migracji;
- endpointy i webhooki mają jawny lifecycle deprecation;
- schema diff jest analizowany w review, nawet gdy narzędzie nie wykryje breaking;
- test kontraktowy uruchamia wygenerowanego klienta przeciwko API.

### Zdarzenia i outbox

Wewnętrzne zdarzenie ma envelope:

```text
event_id: UUIDv7
event_type: stabilny identyfikator, np. organization.created
event_version: integer
occurred_at: UTC
organization_id: UUID lub null dla zdarzeń globalnych
actor_id: UUID lub null
correlation_id: UUID
causation_id: UUID lub null
payload: obiekt wersjonowany per event_type
```

Zdarzenie i rekord outbox są zapisywane w tej samej transakcji. Celery dostarcza
co najmniej raz; każdy consumer zapisuje idempotency po `event_id`. Handlery nie
wywołują się synchronicznie między modułami w sposób ukrywający zależność.
Webhook publiczny jest osobnym kontraktem z podpisem i wersją payloadu.

## Konsekwencje

- wire format pozostaje blisko Django, a typowany klient usuwa ręczne duplikaty;
- RFC 9457 daje jeden format błędów dla panelu i integracji;
- ręczne adaptery Query ograniczają nadmiar wygenerowanego kodu;
- transaction outbox daje niezawodność bez wdrażania Kafki;
- at-least-once wymaga idempotentnych consumerów i tabeli deduplikacji.

## Alternatywy odrzucone

- GraphQL — niepotrzebny drugi system autoryzacji i kontraktów;
- ręczne interfejsy TypeScript — nieunikniony drift;
- generowanie rozbudowanego SDK z logiką cache — większy coupling narzędzia;
- synchroniczne sygnały Django jako główna komunikacja modułów — ukryte skutki;
- Kafka/RabbitMQ na starcie — koszt operacyjny bez obecnej skali.

## Źródła

- https://drf-spectacular.readthedocs.io/en/latest/readme.html
- https://openapi-ts.dev/openapi-fetch/
- https://www.rfc-editor.org/rfc/rfc9457

