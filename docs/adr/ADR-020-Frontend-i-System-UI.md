# ADR-020 — frontend i system UI

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core  
**Zakres:** panel, landing produktu i Site Renderer

## Kontekst

Panel będzie formularzowym produktem B2B z rozbudowanymi Selectami,
Comboboxami, tabelami, dialogami i przepływami onboardingowymi. Komponenty
muszą być dostępne klawiaturowo, spójne między produktami i możliwe do
modyfikowania bez forkowania całego frontendu.

## Decyzja

### Fundament

- Next.js 16.2 App Router i React Server Components jako domyślny model;
- Client Components tylko dla interakcji, formularzy i stanu przeglądarki;
- `next-intl` dla PL/EN, formatowania liczb, dat i routingu locale;
- Tailwind CSS 4 oraz CSS variables jako warstwa design tokens;
- Lucide jako podstawowy zestaw ikon.

### shadcn/ui

`shadcn/ui` jest podstawowym systemem komponentów panelu. Nowy projekt używa:

- shadcn CLI v4;
- bazy **Base UI**;
- neutralnego stylu Nova jako punktu startowego;
- komponentów przechowywanych w `packages/ui`, a nie ukrytych w aplikacji;
- `components.json` wersjonowanego w repozytorium.

Base UI wybieramy dlatego, że jest aktualną domyślną bazą shadcn, ma stabilne
prymitywy Select, Combobox i Autocomplete oraz obsługuje focus, klawiaturę i
wzorce WAI-ARIA. Radix pozostaje dozwolony wyłącznie, gdy brak konkretnego
prymitywu Base UI zostanie udokumentowany.

### Warstwy komponentów

```text
packages/ui/src/
  components/ui/       kod shadcn blisko upstreamu
  components/forms/    nasze typowane Field, SelectField, ComboboxField
  components/data/     DataTable, filtry, pagination, empty/error states
  components/layout/   shell, sidebar, page header
  tokens/              semantyczne tokeny i warianty deploymentu
```

Kod domenowy importuje komponenty przez publiczny interfejs `@saas-core/ui`.
Nie importuje bezpośrednio `@base-ui/react`. Modyfikacje w `components/ui`
utrzymujemy małe; zachowanie produktowe trafia do warstwy wyżej.

### Reguły pól

- `NativeSelect` — bardzo krótkie listy, gdy natywne zachowanie jest zaletą;
- `Select` — zamknięta, niewielka lista bez wyszukiwania;
- `Combobox` — lista zamknięta, duża lub filtrowalna;
- `Autocomplete` — gdy dozwolony jest tekst spoza listy;
- `Command` — paleta akcji, nie zamiennik pola formularza;
- każde pole ma widoczny label, opis błędu i prawidłowe `aria-*`;
- listy z backendu obsługują loading, empty, error, pagination i anulowanie;
- klawiatura, focus restore i czytnik ekranu są częścią testu komponentu.

### Formularze i stan

- React Hook Form + Zod + `zodResolver` dla formularzy klienckich;
- walidacja przeglądarkowa pozostaje włączona tam, gdzie ma sens;
- backend jest ostatecznym źródłem walidacji biznesowej;
- błędy RFC 9457 mapujemy do pól bez uzależniania UI od tekstu komunikatu;
- TanStack Query stosujemy dla interaktywnego stanu serwerowego w Client
  Components; Server Components pobierają dane bezpośrednio typed clientem;
- nie dublujemy tych samych danych równocześnie w cache RSC i Query bez jawnej
  strategii invalidacji.

### Dostępność i testy

- minimalny cel: WCAG 2.2 AA dla panelu i publicznych przepływów;
- automatyczne testy axe są uzupełnieniem, nie zamiennikiem testów klawiatury;
- Storybook dokumentuje warianty, stany i komponenty formularzowe;
- Playwright pokrywa krytyczne przepływy klawiaturą oraz mobile viewport;
- kontrast, focus-visible, reduced motion i komunikaty live region są wymagane.

## Konsekwencje

- większość złożonych kontrolek powstaje z dojrzałych prymitywów zamiast od zera;
- kod shadcn jest naszą własnością, więc aktualizacja wymaga diffu i testów;
- wspólny pakiet UI może obsługiwać MedPlano i Beauty przez tokeny, bez forków;
- Base UI jest decyzją implementacyjną, a publiczne API `@saas-core/ui` ogranicza
  koszt przyszłej zmiany prymitywów.

## Alternatywy odrzucone

- Material UI — większa warstwa stylów i trudniejsze dopasowanie do produktów;
- ręczne tworzenie Select/Combobox — wysokie ryzyko błędów a11y i focusu;
- bezpośrednie importy shadcn w każdym module — utrata jednego kontraktu UI;
- globalny Redux dla danych API — TanStack Query i RSC pokrywają ten problem.

## Źródła

- https://ui.shadcn.com/docs/changelog
- https://ui.shadcn.com/docs/components
- https://ui.shadcn.com/docs/forms/react-hook-form
- https://base-ui.com/react/components/combobox
- https://base-ui.com/react/overview/accessibility
- https://nextjs.org/blog/next-16
- https://next-intl.dev/docs/getting-started/app-router

