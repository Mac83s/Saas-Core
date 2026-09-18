# Kontrakt modułów

## 1. Warstwy i kierunek zależności

Moduły tworzą acykliczny graf. Import jest dozwolony wyłącznie w dół:

```text
configuration layer  (np. medplano)
          |
          v
vertical modules      (np. medical)
          |
          v
shared modules        (np. booking, billing, sites)
          |
          v
core modules          (np. health, identity, organizations)
```

Core nie zna Shared ani Vertical. Shared nie zna Vertical. Moduły vertical i
konfiguracja produktu nie leżą w Saas-Core: każdy produkt to osobne
repozytorium wyprowadzone z Saas-Core (ADR-049, §6). Komunikacja w górę
odbywa się przez publiczne interfejsy, zdarzenia domenowe albo rejestry
rozszerzeń należące do niższej warstwy.

## 2. Identyfikatory i lokalizacja

Identyfikator ma format `<layer>.<name>`, używa małych liter i nie zmienia się
po utworzeniu migracji. Przykłady: `core.identity`, `shared.booking`,
`vertical.medical`, `config.medplano`.

Backend znajduje się w `apps/backend/src/saas_core/modules/<layer>/<name>`, a
frontend w `apps/frontend/src/modules/<layer>/<name>`. Publiczny interfejs
pakietu jest eksportowany wyłącznie z `api.py` albo `index.ts`.

## 3. Deskryptor

Każdy moduł posiada deskryptor backendowy i frontendowy zgodny ze wspólnym
schematem JSON. Minimalny dokument ma postać:

```json
{
  "id": "shared.booking",
  "layer": "shared",
  "version": 1,
  "dependsOn": ["core.identity", "core.organizations"],
  "backend": {
    "djangoApp": "saas_core.modules.shared.booking",
    "urlPrefix": "/api/v1/booking",
    "permissions": ["booking.appointment.read", "booking.appointment.manage"],
    "entitlements": ["booking.enabled"],
    "eventSchemas": ["booking.appointment.created.v1"],
    "publicTables": []
  },
  "frontend": {
    "routes": ["/calendar"],
    "navigation": ["calendar"],
    "translationNamespaces": ["booking"]
  }
}
```

Pola tablicowe są jawne, nawet jeśli są puste. Moduł jest właścicielem swoich
migracji, permissionów, entitlementów, tłumaczeń, schematów zdarzeń i testów.
Nie wolno deklarować cudzych permissionów ani modyfikować cudzych migracji.

`backend.publicTables` wymienia tabele, które publiczny renderer czyta bez
kontekstu tenanta (ADR-039). Każda inna tabela tenantowa modułu ma wymuszone
RLS; test `tests/test_tenant_isolation_regimes.py` sprawdza to na prawdziwym
PostgreSQL w obie strony, a walidator katalogu pilnuje, że moduł deklaruje
wyłącznie własne tabele.

## 4. Aktywacja

1. `DEPLOYMENT=<name>` wybiera `deployments/<name>/deployment.json`.
2. Walidator sprawdza profil względem `packages/contracts/deployment.schema.json`.
3. Resolver buduje domknięcie zależności i odrzuca brak, cykl lub naruszenie
   kierunku warstw.
4. Backend generuje deterministyczną listę `INSTALLED_APPS`, URL-i, event
   handlers i konfigurację admina.
5. Frontend otrzymuje bezsekretny profil publiczny (`src/generated/deployment.ts`)
   z listą modułów i po niej pokazuje pozycje menu. Pola `frontend` deskryptora
   są deklaracją, nie źródłem routingu: menu, tłumaczenia i strony produktu
   wnosi slot `apps/frontend/src/product/` (§6).

Frontend nie może samodzielnie włączyć funkcji. Ostateczną decyzję podejmuje API
na podstawie aktywnego modułu, permissionu oraz entitlementu.

## 5. Egzekwowanie granic

- Python: `import-linter` sprawdza warstwy i zakazuje importów przez prywatne
  ścieżki modułu.
- TypeScript: reguły ESLint `boundaries` sprawdzają ten sam graf.
- `module-catalog check` waliduje deskryptory i zależności obu aplikacji.
- test kontraktowy porównuje backendowy i frontendowy katalog modułów;
- CI uruchamia test negatywny z celowo brakującą zależnością.

Naruszenie kontraktu blokuje merge i build obrazu. Dynamiczne importowanie
modułu niewymienionego w profilu wdrożenia jest zabronione.

## 6. Moduły produktu (ADR-049)

Produkt (HoofCare, MedPlano, kolejne) żyje we własnym repozytorium — kopii
Saas-Core z Saas-Core jako `upstream`. Dokłada nowe pliki i nie zmienia plików
rdzenia poza slotami; pilnuje tego `pnpm core:check`, a rdzeń przychodzi przez
`pnpm core:update`. Wertykał podłącza się bez edycji rdzenia:

| Potrzeba | Punkt rozszerzenia |
|---|---|
| API | `backend.urlPrefix` + `djangoApp` (`urls.py` wertykału) |
| uprawnienia ról systemowych | `backend.roleGrants` (tylko własne `permissions`) + migracja wertykału |
| cecha planu | `backend.entitlements` + migracja wertykału publikująca wersję planu |
| typ wizyty w booking | `backend.appointmentKinds` |
| menu, tłumaczenia, treść marketingowa | `apps/frontend/src/product/index.ts` |
| strony panelu | nowe pliki w `apps/frontend/src/app/` |
| profil, obrazy, testy, kontrakt | `deployments/<produkt>/`, `product.json` |

Punktu rozszerzenia nie ma jeszcze dla middleware i zadań cyklicznych
wertykału. Pierwszy produkt, który ich potrzebuje, dodaje go w Saas-Core (pole
deskryptora), a nie linię w `base.py` swojej kopii.
