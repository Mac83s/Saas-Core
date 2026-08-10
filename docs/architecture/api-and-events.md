# Kontrakt API i zdarzeń

## 1. REST

- publiczny prefiks wersji: `/api/v1/`;
- JSON używa `snake_case`;
- UUID jest stringiem, Decimal stringiem, czas ISO 8601 w UTC;
- listy używają paginacji cursorowej: `items` oraz nullable `next_cursor`;
- każde żądanie otrzymuje `correlation_id`, zwracane również w nagłówku;
- retryowalne mutacje przyjmują `Idempotency-Key` i przechowują wynik w zakresie
  organizacji, endpointu i użytkownika;
- kompatybilne pola mogą być dodawane w `v1`; usunięcie, zmiana znaczenia lub
  typu wymaga nowej wersji albo okresu deprecacji opisanego w schemacie.

## 2. Błędy

Odpowiedzi błędów używają `application/problem+json` zgodnego z RFC 9457:

```json
{
  "type": "https://docs.medplano.pl/problems/validation-error",
  "title": "Dane formularza są nieprawidłowe",
  "status": 422,
  "code": "validation_error",
  "detail": "Popraw oznaczone pola.",
  "instance": "/api/v1/organizations/current",
  "correlation_id": "019c5f88-66c1-7b45-9ab4-3df6a5a6d7f0",
  "errors": {
    "legal_name": [{"code": "required", "message": "To pole jest wymagane."}]
  }
}
```

Frontend mapuje `errors` do React Hook Form, a pozostałe problemy prezentuje w
spójnym komponencie z `packages/ui`. Tekst z backendu jest bezpiecznym fallback;
znane kody domenowe frontend tłumaczy przez `next-intl`.

## 3. OpenAPI i klient TypeScript

Źródłem prawdy jest kod DRF opisany przez drf-spectacular. Kanoniczny artefakt
to `packages/contracts/openapi/v1.yaml`, a klient jest generowany przez
`openapi-typescript` i konsumowany przez `openapi-fetch`.

Komendy wdrożone w W1:

```text
pnpm api:schema        # zapisuje kanoniczny v1.yaml
pnpm api:client        # generuje packages/api-client/src/schema.d.ts
pnpm api:check         # generuje do pliku tymczasowego i wykrywa drift
```

CI uruchamia walidację schematu, diff zmian łamiących oraz `api:check`. Ręczne
typy odpowiedzi API w frontendzie są zabronione. Hooki use case'ów mogą być
pisane ręcznie, ale opierają się wyłącznie na wygenerowanych typach.

## 4. Zdarzenia wewnętrzne

Przykład `OrganizationCreated`:

```json
{
  "id": "019c5f88-66c1-7b45-9ab4-3df6a5a6d7f0",
  "type": "organizations.organization.created",
  "version": 1,
  "occurred_at": "2026-08-10T12:00:00Z",
  "organization_id": "019c5f87-fce8-739b-b960-b7a195bfc298",
  "actor_id": "019c5f87-a0bd-7da5-bf81-61ee9ed0b153",
  "correlation_id": "019c5f88-1f6d-7a17-991c-c3c662676fe6",
  "causation_id": null,
  "payload": {
    "slug": "demo-clinic",
    "kind": "company"
  }
}
```

Use case zapisuje agregat i rekord outbox w jednej transakcji. Publisher Celery
dostarcza zdarzenie co najmniej raz; każdy konsument zapisuje `event_id` i jest
idempotentny. Retry używa opóźnienia wykładniczego z limitem, po którym rekord
trafia do stanu wymagającego obsługi. Payload nie zawiera sekretów ani danych
wrażliwych, jeżeli konsument może pobrać je po identyfikatorze.

## 5. Webhooki publiczne

Webhook nie jest bezpośrednim odbiciem zdarzenia wewnętrznego. Ma osobny,
wersjonowany kontrakt, allowlistę pól, podpis HMAC, timestamp, identyfikator
dostawy, retry oraz rejestr prób. Odbiorca może deduplikować po identyfikatorze
dostawy. Transformacja event -> webhook jest odpowiedzialnością modułu
integracji.
