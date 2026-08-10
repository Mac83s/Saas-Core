# W4 — Organizations, RBAC i i18n

**Status:** zakończone lokalnie (2026-08-10); staging odłożony
**FINDING (2026-08-10):** wspólny runner Vitest nadpisywał wyłącznie `TMPDIR`,
podczas gdy procesy robocze w WSL wybierały windowsowe `TMP`/`TEMP`. Zbieranie
testów kończyło się błędem `ENOENT` przed wykonaniem przypadków; runner musi
ustawiać wszystkie trzy zmienne na `/tmp`.
**Szacunek:** 1,5–2 tygodnie  
**Poprzednik:** W3  
**Rezultat:** izolowane organizacje, członkostwa, uprawnienia i panel PL/EN

## 1. Scenariusz demonstracyjny

Użytkownik tworzy organizację, zaprasza drugą osobę, przypisuje jej rolę i
przełącza aktywną organizację. Próba odczytu lub modyfikacji danych innego
tenanta kończy się odmową niezależnie od danych przesłanych przez frontend.

## 2. Pakiety pracy

### W4.1 — modele organizacji

**Stan:** zakończone lokalnie (2026-08-10)

- wdrożyć `Organization`, `Membership`, `Role` i `BillingProfile`;
- zapewnić jedną aktywną relację użytkownika z organizacją;
- dodać statusy onboarding/active/suspended/archived;
- zapisać strefę czasową, walutę i domyślny język;
- oddzielić profil rozliczeniowy od publicznych danych organizacji.

### W4.2 — tenant context

**Stan:** zakończone lokalnie (2026-08-10). Aktywacja polityk RLS pozostaje
odroczona do pierwszego modelu z zatwierdzonego zakresu (`MediaAsset` w W6 oraz
`Customer`/`Appointment` w W9); test ochronny wymusza wtedy zastąpienie
odroczenia właściwą polityką i testem bezpośredniego SQL.

- rozwiązywać aktywną organizację z sesji i aktywnego membership;
- nie ufać `organization_id` z body, query ani nagłówka bez autoryzacji;
- wymagać tenant context w repozytoriach/QuerySetach danych tenantowych;
- propagować identyfikator organizacji do zadań Celery w podpisanym kontrakcie;
- czyścić context po requestach i zadaniach, aby nie przeciekał między pracami;
- wdrożyć zatwierdzony w W0 zakres RLS albo test dokumentujący jego odroczenie.

### W4.3 — role i permissions

**Stan:** zakończone lokalnie (2026-08-10); audyt zmian membership i ról jest
realizowany razem z endpointami lifecycle w W4.4.

- zdefiniować stabilne klucze permissions i role domyślne;
- wdrożyć centralną funkcję decyzji autoryzacyjnej po stronie API;
- oddzielić kontrolę roli od przyszłej kontroli entitlementu;
- ograniczyć zmianę Ownera, billing i usunięcie organizacji;
- audytować zmianę ról, zawieszenie i operacje operatora.

### W4.4 — zaproszenia i lifecycle membership

**Stan:** zakończone lokalnie (2026-08-10)

- tworzyć jednorazowe, wygasające zaproszenia z ograniczoną rolą;
- obsłużyć zaproszenie dla istniejącego i nowego użytkownika;
- uniemożliwić przyjęcie po wycofaniu, wygaśnięciu lub wcześniejszym użyciu;
- zdefiniować odejście członka, odebranie dostępu i transfer własności;
- unieważnić albo przeliczyć sesję po zmianie membership.

### W4.5 — i18n i panel

**Stan:** zakończone lokalnie (2026-08-10). Routing locale używa polskiego bez
prefiksu i angielskiego pod `/en`; katalogi mają test identyczności kluczy, a
panel używa komponentów shadcn/Base UI dla dialogów, list zamkniętych i
wyszukiwalnych wyborów.

- wdrożyć zatwierdzoną bibliotekę i routing locale;
- dostarczyć PL i EN dla przepływów W3–W4;
- oddzielić język użytkownika od domyślnego języka organizacji;
- zapewnić fallback oraz wykrywanie brakujących kluczy w CI;
- lokalizować daty, strefy czasowe, waluty i komunikaty walidacji.

## 3. Macierz testów obowiązkowych

Każdy chroniony endpoint jest testowany co najmniej dla:

- użytkownika bez sesji;
- użytkownika bez membership;
- aktywnego członka niewłaściwej organizacji;
- Viewer, Staff, Manager, Admin i Owner;
- zawieszonego membership oraz zawieszonej organizacji;
- zadania Celery z brakującym albo nieprawidłowym tenant context.

## 4. Bramka wyjścia

- [x] jeden użytkownik może bezpiecznie należeć do kilku organizacji;
- [x] zmiana aktywnej organizacji rotuje lub aktualizuje właściwy stan sesji;
- [x] testy próbują odczytu, zapisu i identyfikacji zasobu innego tenanta;
- [x] zaproszenie jest jednorazowe, wygasające i audytowane;
- [x] wszystkie permissions są egzekwowane w API;
- [x] panel W3–W4 działa w języku polskim i angielskim;
- [x] role i entitlementy pozostają osobnymi mechanizmami.

Walidacja lokalna: 115 testów backendu całego etapu W4, 6 testów frontendu,
2 testy biblioteki UI, kontrola OpenAPI/klienta, lint, typecheck i produkcyjny
build Next.js. Środowisko nadal zgłasza ostrzeżenie Node 22 wobec wymaganego
Node 24; komendy zakończyły się kodem 0.
