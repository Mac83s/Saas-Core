# SaaS Core — reguły implementacji

## Źródła prawdy

- mapa fal: `Plan/Wdrozenie/00-MAPA-WDROZENIA.md`;
- bieżąca lokalna fala: `Plan/Wdrozenie/10A-W9.5-Customer-Experience-Commerce-i-AI.md`;
- równoległa gałąź kontraktowa publikacji: `Plan/Wdrozenie/10B-W9.6-Publication-Platform-i-Market-Maker.md`;
- punkt wznowienia następnej sesji: `docs/development/HANDOFF.md`;
- decyzje techniczne: `docs/adr/`;
- wykonywalne kontrakty: `docs/architecture/`.

Przed zmianą architektury przeczytaj właściwy ADR. Zmiana zaakceptowanej decyzji
wymaga nowego ADR, nie cichego odstępstwa w kodzie.

## Niezmienne zasady

- kierunek zależności: configuration -> vertical -> shared -> core;
- dane tenantowe wymagają jawnego `TenantContext`; nie twórz globalnego fallbacku;
- frontend nie jest granicą bezpieczeństwa: API sprawdza tenant, permission i entitlement;
- sesja panelu jest same-origin; tokenów nie zapisujemy w `localStorage`;
- typy API generujemy z OpenAPI, nie duplikujemy ich ręcznie;
- sekrety i dane osobowe nie trafiają do repozytorium, fixture'ów ani logów;
- każda mutacja biznesowa uwzględnia audyt, idempotencję i transakcję/outbox,
  jeśli emituje zdarzenie.

## Frontend i shadcn/ui

- shadcn/ui v4 z Base UI jest podstawowym systemem UI;
- komponenty bazowe należą do `packages/ui`; moduły domenowe importują wyłącznie
  publiczne API `@saas-core/ui` i nie importują Base UI bezpośrednio;
- dobieraj pole według ADR-020: `NativeSelect` dla krótkich prostych list,
  `Select` dla małego zamkniętego zbioru, `Combobox` dla zbioru dużego lub
  filtrowalnego, `Autocomplete` gdy dozwolony jest własny tekst;
- formularze używają React Hook Form + Zod, a błędy serwera mają Problem Details;
- zachowuj semantykę, klawiaturę i focus komponentów; testuj axe oraz PL/EN;
- nie kopiuj wariantów shadcn do aplikacji. Rozszerzaj wspólny komponent lub
  kompozycję w `packages/ui`.

## Granice pracy

Implementuj wyłącznie aktywną falę i jej konieczne fundamenty. Po znaczącym
etapie aktualizuj checklistę fali oraz Memex. Nie oznaczaj bramki jako ukończonej
bez testu lub jednoznacznego artefaktu będącego dowodem.
