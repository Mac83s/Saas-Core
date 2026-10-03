# Rezerwacje uniwersalne, faza 4d-1: polecenia asystenta dla dokumentów — wydanie 2026-10-04

Zakres: pierwsza część plastra 4d fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§9 i „Rozstrzygnięcia plastra 4d”; ADR-076). Bez migracji. Produkty biorą
zmianę przez `core:update`.

## Co się zmieniło

- **Dwa polecenia w rejestrze** (`shared/customers/command_declarations.py`,
  manifest `packages/contracts/commands/manifest.json`):
  - `customers.documents.read@1` (odczyt, `customers.read`) — dokumenty firmy
    dla klientów: szkic, wersja obowiązująca i czekająca, języki z tekstem,
    adres publiczny; z `kind` — jeden dokument z tekstami. Bez nazwisk osób.
  - `customers.document.draft.save@1` (klasa `draft`, `customers.manage`) —
    zapis szkicu dokumentu albo jego usunięcie pustym tekstem, po jednym
    kliknięciu zgody; szkic niesie identyfikator rozmowy (`origin_ref`).
- **Zatwierdzenie nie ma polecenia.** Wersję zatwierdza wyłącznie osoba w
  panelu, po kodzie z aplikacji uwierzytelniającej — tak jak w 4b.
- **Panel** (Ustawienia › „Dokumenty dla klientów” › dokument): przy szkicu
  napisanym przez asystenta stoi „Ten szkic napisał asystent AI…”; uwaga
  znika, gdy osoba zapisze szkic sama.
- `documents.plan_draft` — podgląd zapisu szkicu: te same sprawdzenia i
  odmowy co zapis, bez zapisu.

## Dla produktów

1. Produkt z własnymi słowami dla dokumentów może nazwać polecenia po swojemu
   przez `retitle_command` (jak ustawienia przez `relabel_settings`).
2. Typ organizacji bez `customers.manage` w rolach nie dostanie zapisu szkicu
   od asystenta — polecenie sprawdza to samo uprawnienie co panel.

## Wdrożenie

Bez migracji i bez nowych ustawień. Backend i frontend przebudować razem
(nowe polecenia w rejestrze, nowa uwaga w panelu).
