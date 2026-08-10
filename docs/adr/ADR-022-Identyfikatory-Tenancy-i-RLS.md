# ADR-022 — identyfikatory, tenancy i RLS

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core

## Kontekst

Każdy produkt ma osobną bazę, ale wiele organizacji współdzieli schemat. Błąd
scope jest najpoważniejszym ryzykiem platformy, a identyfikatory muszą działać
spójnie w API, zdarzeniach i imporcie.

## Decyzja

### Bazy i identyfikatory

- ADR-012 zostaje przyjęty: osobny PostgreSQL per deployment, wspólny schemat
  tenantowy wewnątrz deploymentu;
- główne encje używają UUIDv7 generowanego w aplikacji przez Python 3.14;
- UUID nie jest sekretem ani mechanizmem autoryzacji;
- wszystkie timestamps są zapisywane jako timezone-aware UTC;
- encje tenantowe mają obowiązkowe `organization_id` i indeksy rozpoczynające
  się od `organization_id` dla najważniejszych zapytań/unikalności.

### Tenant context

1. Middleware pobiera `active_organization_id` z sesji.
2. Ładuje aktywne `Membership` i `Organization` bez zaufania danym requestu.
3. Odrzuca suspended/archived oraz nieaktywne membership.
4. Ustanawia niemutowalny `TenantContext` w `ContextVar` na czas requestu.
5. Warstwa danych wymaga contextu przez `for_tenant()`; próba użycia tenantowego
   managera bez contextu zgłasza błąd zamiast zwracać wszystkie rekordy.
6. Context jest czyszczony w `finally`.

`organization_id` przesłane w URL/body może wskazać zasób, lecz nigdy nie
ustanawia autoryzowanego tenanta. Operacje operatora używają oddzielnej,
audytowanej ścieżki, a nie magicznego wyłączenia filtrów.

Zadanie Celery otrzymuje jawne `organization_id`, `actor_id`, `correlation_id`
i `causation_id`. Task ponownie waliduje organizację i ustanawia context.

### RLS

ADR-014 zostaje przyjęty w zakresie warstwowym:

- aplikacyjny tenant scope jest obowiązkowy dla każdej tabeli tenantowej;
- PostgreSQL RLS jest drugą warstwą dla tabel z danymi osobowymi lub prywatnymi,
  początkowo `Customer`, `Appointment`, prywatne `MediaAsset` i ich rozszerzenia;
- połączenie aplikacji nie ma `BYPASSRLS`; migracje używają osobnej roli;
- request/task działa w transakcji i ustawia `SET LOCAL app.organization_id`;
- brak zmiennej sesyjnej oznacza brak rekordów, nie dostęp globalny;
- każda polityka RLS ma test z prawdziwym PostgreSQL.

Rozszerzenie RLS na kolejne tabele jest dozwolone bez nowego ADR-u, jeżeli
zachowuje ten kontrakt. Usunięcie RLS lub użycie roli bypass wymaga nowego ADR-u.

### Modele bazowe

- `User`: UUIDv7, znormalizowany lowercase email, stan aktywności, locale,
  timezone i znaczniki czasu; customowy model od migracji `0001`;
- `Organization`: UUIDv7, name, slug, workspace_kind, status, locale, timezone,
  currency i znaczniki czasu;
- `Membership`: organization, user, role, status, joined_at, invited_by;
- `Role`: stabilny key, scope system/organization, name, permission set, immutable
  system roles i wersja;
- `BillingProfile`: relacja 1:1 do organizacji i dane prawno-rozliczeniowe.

Unikalność aktywnego membership i slug organizacji jest egzekwowana constraintem
bazy. Soft delete stosujemy tylko tam, gdzie istnieje wymaganie retencji lub
odtworzenia; nie dodajemy go automatycznie do każdej tabeli.

## Konsekwencje

- UUIDv7 poprawia lokalność indeksu i pozostaje bezpieczny do generowania przed
  zapisem, ale ujawnia przybliżony czas utworzenia;
- ContextVar zmniejsza ryzyko przypadkowego braku filtra, lecz nie zastępuje
  jawnego API repozytorium ani RLS;
- RLS zwiększa koszt testów i transakcji, ale chroni najbardziej wrażliwe dane;
- osobna rola migracyjna staje się obowiązkowym elementem deploymentu.

## Alternatywy odrzucone

- UUIDv4 — prostszy, lecz ma gorszą lokalność indeksów przy dużym zapisie;
- tenant id wyłącznie z requestu — podatny na IDOR;
- schema/database per organizacja — zbyt ciężkie operacyjnie dla pilota;
- RLS na wszystkich tabelach od migracji `0001` — koszt bez proporcjonalnej
  korzyści dla katalogów i danych globalnych.

## Źródła

- https://www.postgresql.org/docs/current/functions-uuid.html
- https://www.postgresql.org/docs/current/ddl-rowsecurity.html

