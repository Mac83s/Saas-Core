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

Odpowiedzi błędów używają `application/problem+json` (RFC 9457) z handlera
`problem_details_exception_handler` (`apps/backend/src/saas_core/http/exceptions.py`).
Kształt i podział statusów ustala ADR-076 §5:

```json
{
  "type": "about:blank",
  "title": "Żądanie nie może zostać obsłużone",
  "status": 400,
  "code": "invalid",
  "detail": {"legal_name": ["To pole jest wymagane."]},
  "correlation_id": "019c5f88-66c1-7b45-9ab4-3df6a5a6d7f0",
  "errors": [
    {"field": "legal_name", "code": "required", "message": "To pole jest wymagane."}
  ]
}
```

- **400** — wszystko, co wołający może poprawić w danych. `code` to `invalid`
  albo kod domenowy z podklasy `ValidationError` z `problem_code`.
- **422** — tylko odmowy operacji treści (zestawy zmian, szkic z briefu, media
  AI w slocie); mają jeden wpis `errors`.
- `errors` ma każda odpowiedź 400 i 422: `field` to ścieżka w danych żądania
  (segmenty łączone kropką, indeks listy jako liczba, `null` = całe żądanie),
  `code` — kod pola z DRF, walidatora Django albo domenowy
  (`ValidationError({...}, code="slug_taken")`), `message` — zdanie tylko do
  wyświetlenia. Rozwijana jest wyłącznie `ValidationError`; inny wyjątek daje
  jeden wpis z `problem_code` i opcjonalnym `problem_field`.
- `detail` zostaje dla zgodności i tylko do wyświetlenia; nowy kod czyta `errors`.

Frontend mapuje `errors` do React Hook Form (notacja ścieżek jak `path.join(".")`
w Zod), a pozostałe problemy prezentuje w spójnym komponencie z `packages/ui`.
Tekst z backendu jest bezpiecznym fallbackiem; znane kody domenowe frontend
tłumaczy przez `next-intl`.

## 3. OpenAPI i klient TypeScript

Źródłem prawdy jest kod DRF opisany przez drf-spectacular. Kanoniczny artefakt
to `packages/contracts/openapi/v1.yaml`, a klient jest generowany przez
`openapi-typescript` i konsumowany przez `openapi-fetch`.

Komendy wdrożone w W1:

```text
pnpm api:schema        # zapisuje kanoniczny v1.yaml
pnpm api:client        # generuje packages/api-client/src/schema.d.ts
pnpm api:check         # dryf (generuje do pliku tymczasowego) i podłoga jakości
pnpm api:quality       # sama podłoga; --write-baseline zmniejsza linię bazową
```

CI uruchamia `api:check`: dryf schematu i podłogę jakości nowych i zmienionych
operacji (ADR-076 §7, `packages/contracts/openapi/README.md`). Ręczne
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
