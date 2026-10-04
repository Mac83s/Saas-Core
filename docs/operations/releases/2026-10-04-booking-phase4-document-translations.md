# Rezerwacje uniwersalne, faza 4d-2: tłumaczenia dokumentów dla klientów — wydanie 2026-10-04

Zakres: druga część plastra 4d fazy 4 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
§9 i „Rozstrzygnięcia plastra 4d-2”; protokół
[`translation-sources.md`](../../architecture/translation-sources.md) §5, §6.6,
§8.1 i §11). Bez migracji. Produkty biorą zmianę przez `core:update`.

## Co się zmieniło

- **Dokument jest źródłem tłumaczeń `customers.document`**
  (`shared/customers/translation_source.py`, rejestrowane w `AppConfig.ready`,
  bez importu silnika). Obiektem jest dokument z zatwierdzoną wersją, źródłem
  — wersja, która wchodzi w życie ostatnia (obowiązująca albo zatwierdzona na
  późniejszy dzień), fragmentem — cały jej tekst.
- **Tłumaczenie maszynowe nigdy nie wychodzi samo.** Zlecenie (kliknięcie albo
  automat zmian) niczego nie zapisuje w dokumencie: wynik czeka w
  „Tłumaczenia → Do akceptacji” z powodem „Dokument prawny”, w każdym trybie
  tłumaczeń firmy. Zlecone znaki są rozliczane jak każdy dostarczony wynik.
- **Akceptacja wymaga osoby i kodu z aplikacji.** „Zaakceptuj” dopisuje wiersz
  tekstu przez ten sam serwis co tekst wpisany ręcznie (`documents.add_text`):
  `customers.manage`, bramka osoby, świeży drugi składnik. Bez kodu API
  odpowiada 403 `step_up_required` — panel pyta o kod i wysyła tę samą decyzję
  jeszcze raz; konto bez weryfikacji dwuetapowej dostaje
  `step_up_mfa_setup_required` i wskazówkę, gdzie ją włączyć. Wiersz pamięta,
  że napisał go model (`provenance.origin = "ai"`), a zaakceptowała osoba.
- **Asystent nie akceptuje dokumentu.** Polecenie `translation.review.accept`
  odmawia już w podglądzie (`person_required` na `item_ids`), zanim osoba
  kliknie zgodę.
- **Panel:** Ustawienia › „Dokumenty dla klientów” › dokument — w sekcji
  tłumaczonej wersji „Przetłumacz brakujące” (wycena, potwierdzenie kosztu) i,
  przy języku, „Tłumaczenie AI czeka na Twoją akceptację” z odnośnikiem do
  „Do akceptacji”. API dokumentu oddaje do tego `translation`
  (`object_id`, `version`, `waiting`).
- **Zgłoszenia zmian:** zatwierdzenie wersji i poprawka tekstu w języku wersji
  zgłaszają `changed` — automat zmian (ze zgodą firmy) zleca wtedy tłumaczenie
  w językach, w których dokument już miał tekst; wynik i tak czeka na osobę.
- **Zestaw kontraktu źródeł** (`saas_core/testing/translation_sources.py`) ma
  tryb `legal_only` oraz zdolności `single_unit` i `persons_only`.

## Przy okazji (centrum tłumaczeń)

- „Zadania” na telefonie: wybór „Wstrzymane” nie zamyka już arkusza filtrów.
- `python manage.py sites_close_decided_reviews [--dry-run]` — jednorazowe,
  powtarzalne porządki: zamyka pozycje „Do akceptacji”, których wersję
  rozstrzygnięto w edytorze podstrony, zanim edytor zaczął o tym mówić kolejce
  (`7f240269`). Wypisuje identyfikatory, nigdy treści.

## Dla produktów

1. Produkt bez `shared.translation` niczego nie zauważy: źródło rejestruje się,
   ale nikt go nie woła, a ekran dokumentu nie pokazuje zlecenia.
2. Produkt z własnymi źródłami tłumaczeń, którego każdy obiekt jest dokumentem
   prawnym, deklaruje w sterowniku testu kontraktu `legal_only` (protokół §11).
3. Po `core:update` z `shared.translation` i `shared.sites` uruchom raz
   `sites_close_decided_reviews --dry-run`, potem bez `--dry-run`.

## Wdrożenie

Bez migracji i bez nowych ustawień. Backend i frontend przebudować razem
(nowe pole w API dokumentu, nowe słowa w panelu). Po wdrożeniu raz
`sites_close_decided_reviews`.
