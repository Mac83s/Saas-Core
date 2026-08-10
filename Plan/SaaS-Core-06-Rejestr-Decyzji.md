# SaaS Core - rejestr decyzji

## 1. Statusy

- **Accepted** - decyzja obowiązuje.
- **Proposed** - rekomendacja oczekująca na potwierdzenie.
- **Deferred** - decyzja odłożona.
- **Superseded** - zastąpiona nowszą decyzją.

## 2. Decyzje zaakceptowane

### ADR-001 - wspólne repozytorium i osobne deploymenty

**Status:** Accepted

Produkty korzystają ze wspólnego kodu, ale mają osobne deploymenty, bazy, sekrety i konfiguracje. Verticale rozszerzają Core.

### ADR-002 - modularny monolit

**Status:** Accepted

Początkowa architektura jest modularnym monolitem. Moduły mają wyraźne granice, ale nie są osobnymi mikroserwisami.

### ADR-003 - Django i Next.js

**Status:** Accepted

Django odpowiada za logikę, dane, API i wewnętrzne narzędzia. Next.js odpowiada za panel klienta, stronę produktu i Site Renderer.

### ADR-004 - Django Admin wyłącznie wewnętrzny

**Status:** Accepted

Klienci nie korzystają z Django Admin. Otrzymują dedykowany panel Next.js. Django Admin jest ograniczonym narzędziem operatora.

### ADR-005 - User, Organization, Membership

**Status:** Accepted

Użytkownik reprezentuje osobę. Konto prywatne lub firma jest organizacją. Membership przypisuje użytkownika i rolę do organizacji.

### ADR-006 - rozdzielenie ról i abonamentu

**Status:** Accepted

RBAC określa, kto może wykonać operację. Entitlement określa, czy organizacja ma dostęp do funkcji.

### ADR-007 - własna lokalna warstwa entitlementów

**Status:** Accepted

Stripe jest dostawcą płatności, ale aplikacja posiada lokalny katalog planów, funkcji, limitów i nadpisań.

### ADR-008 - Docker na własnym VPS-ie

**Status:** Accepted

System jest wdrażany w kontenerach. Kopie bezpieczeństwa znajdują się poza podstawowym VPS-em.

### ADR-009 - wielojęzyczność od początku

**Status:** Accepted

Interfejs, treści, strony, wiadomości i dokumenty posiadają model tłumaczeń oraz fallback.

### ADR-010 - własne domeny przez Caddy

**Status:** Accepted

Klient korzysta z subdomeny platformy i może zweryfikować własną domenę. Caddy On-Demand TLS korzysta z autoryzacyjnego endpointu backendu.

### ADR-011 - zewnętrzna poczta transakcyjna jako domyślna

**Status:** Accepted

Kod korzysta z interfejsu dostawcy poczty. Własny mail server nie jest częścią głównego deploymentu aplikacji.

### ADR-012 - osobna baza per produkt, wspólny schemat tenantowy wewnątrz produktu

**Status:** Accepted

Każdy deployment ma własny PostgreSQL. Organizacje wewnątrz deploymentu używają wspólnego schematu i `organization_id`.

### ADR-013 - sesja przez bezpieczne cookies

**Status:** Accepted

Panel korzysta z cookie HttpOnly, Secure i SameSite oraz ochrony CSRF. Tokeny nie są przechowywane w localStorage.

### ADR-014 - PostgreSQL RLS dla wybranych tabel

**Status:** Accepted

RLS stanowi drugą warstwę izolacji dla danych szczególnie wrażliwych, przy zachowaniu kontroli aplikacyjnej.

Początkowy zakres obejmuje `Customer`, `Appointment` i prywatne `MediaAsset`.

### ADR-017 - kontrolowane bloki zamiast dowolnego page buildera

**Status:** Accepted

Strony korzystają z wersjonowanych bloków i design tokens. Klient nie może uruchamiać własnego JavaScriptu.

### ADR-018 - wspólny moduł Booking

**Status:** Accepted

Booking przechowuje neutralne branżowo lokalizacje, usługi, personel, zasoby, dostępność i rezerwacje. Verticale dodają osobne rozszerzenia.

### ADR-019 - baseline technologiczny

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-019-Baseline-Technologiczny.md`

Backend używa Python 3.14, Django 5.2 LTS i PostgreSQL 18. Frontend używa Node 24 LTS, pnpm 11, Next.js 16.2 i React 19.2.

### ADR-020 - frontend i system UI

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-020-Frontend-i-System-UI.md`

Podstawą UI jest shadcn/ui CLI v4 z Base UI, Tailwind CSS 4, React Hook Form, Zod i `next-intl`. Wspólne komponenty należą do `packages/ui`.

### ADR-021 - monorepo, moduły i deployment

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-021-Monorepo-Moduly-i-Deployment.md`

Monorepo używa jawnych warstw modułów oraz wersjonowanych profili deploymentu walidowanych wspólnym JSON Schema.

### ADR-022 - identyfikatory, tenancy i RLS

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-022-Identyfikatory-Tenancy-i-RLS.md`

Identyfikatory są UUIDv7, tenant context pochodzi z serwerowej sesji, a wybrane tabele od początku chroni PostgreSQL RLS.

### ADR-023 - uwierzytelnianie i sesje

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-023-Uwierzytelnianie-i-Sesje.md`

Panel używa same-origin Django sessions z bezpiecznymi cookies i ochroną CSRF. API integracyjne pozostaje oddzielone.

### ADR-024 - API, OpenAPI i zdarzenia

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-024-API-OpenAPI-i-Zdarzenia.md`

REST `/api/v1` używa Problem Details, generowanego klienta TypeScript oraz transakcyjnego outboxa dla zdarzeń.

### ADR-025 - runtime staging, sekrety i odtwarzanie

**Status:** Accepted  
**Dokument:** `docs/adr/ADR-025-Runtime-Staging-Sekrety-i-Odtwarzanie.md`

Staging używa Docker Compose na osobnym VPS-ie, obrazów GHCR po SHA, sekretów
plikowych Compose, zewnętrznego storage S3 i backupu poza VPS-em. Stagingowe RPO
wynosi 24 godziny, a RTO 4 godziny.

## 3. Decyzje proponowane

### ADR-015 - trial uruchamiany po aktywacji produktu

**Status:** Accepted przez ADR-026

Konfigurowalny trial, początkowo 3 dni, zaczyna się po przygotowaniu/aktywacji strony, a nie w chwili pustej rejestracji.

### ADR-016 - karta wymagana dla triala zarządzanego

**Status:** Accepted przez ADR-026

Dla managed SaaS metoda płatności jest zbierana przed rozpoczęciem triala. Data pierwszego obciążenia jest jasno pokazana.

## 4. Otwarte decyzje produktowe

- [x] Pierwsza sprzedaż jest B2B — ADR-026.
- [x] Trial trwa początkowo 3 dni po aktywacji produktu — ADR-026.
- [x] Trial managed SaaS wymaga karty — ADR-026.
- [x] Pilot ma plany Starter i Pro z kontrolowanymi limitami — ADR-026.
- [x] Abonament obejmuje organizację, a strony i lokalizacje są quota — ADR-026.
- [ ] Kiedy uruchamiamy plan roczny?
- [x] Subdomena platformy jest dostępna we wszystkich planach — ADR-026.
- [x] Custom domain jest funkcją planu Pro — ADR-026.

## 5. Otwarte decyzje techniczne

- [x] wersje i konkretne biblioteki Django/Next.js — ADR-019;
- [x] biblioteka komponentów UI — shadcn/ui z Base UI, ADR-020;
- [x] biblioteka i18n — `next-intl`, ADR-020;
- [x] UUID v4 czy UUID v7 — UUIDv7, ADR-022;
- [x] dokładny tenant context — ADR-022 i ADR-023;
- [x] zakres RLS — ADR-022;
- [x] storage zewnętrzny czy MinIO — zewnętrzny S3, ADR-025;
- [ ] provider e-mail;
- [ ] provider skrzynek klientów;
- [ ] provider SMS;
- [ ] system fakturowania/KSeF;
- [x] monitoring i centralizacja logów — Prometheus, Loki, Alloy i Grafana, ADR-025;
- [x] zarządzanie sekretami — pliki Docker Compose poza repo, ADR-025;
- [x] RPO i RTO — staging 24 h / 4 h, produkcja wraca w W11, ADR-025;
- [ ] strategia CDN/WAF;
- [x] sposób publikowania generowanego klienta OpenAPI — ADR-024.

## 6. Szablon nowej decyzji

```markdown
### ADR-XXX - nazwa decyzji

**Status:** Proposed

#### Kontekst

Dlaczego decyzja jest potrzebna.

#### Decyzja

Co dokładnie wybieramy.

#### Konsekwencje

- korzyści;
- koszty;
- ograniczenia;
- wpływ na istniejące moduły.

#### Alternatywy

- alternatywa A;
- alternatywa B.
```

## 7. Historia zmian

| Data | Wersja | Zmiana |
| --- | --- | --- |
| 2026-08-10 | 0.2 | zamknięcie decyzji technicznych W0 i dodanie ADR-019–024 |
| 2026-08-10 | 0.3 | decyzje runtime i odtwarzania stagingu w ADR-025 |
| 2026-08-09 | 0.1 | utworzenie początkowego rejestru decyzji |
