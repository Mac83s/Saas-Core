# Rezerwacje: pole, które nie wiąże zespołu, i dłuższy tekst (uzupełnienie 5j) — wydanie 2026-10-11

Zakres: uzupełnienie plastra 5j planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5j”, dopiski z 11.10). Jedna migracja: booking 0039.

## Co się zmieniło

- **Pole obowiązkowe może zostawić zespół wolnym.** W „Pola formularza” pod
  „Czy klient musi odpowiedzieć?” pojawia się pole „Obowiązkowe także, gdy
  rezerwację wpisuje zespół” (włączone od razu, tylko przy polu obowiązkowym i
  nie przy zgodzie). Wyłączone: klient rezerwujący sam musi odpowiedzieć, a
  osoba z zespołu w oknach „Nowa wizyta” i „Nowy pobyt” może zapisać
  rezerwację bez tej odpowiedzi. Pola, które już są, zachowują się jak
  dotąd — obowiązkowe wiąże też biuro.
- **Nowy rodzaj „Dłuższy tekst”.** Wieloliniowa odpowiedź do 500 znaków (zwykły
  tekst: 200). Formularz publiczny i okna panelu pokazują pole tekstowe w trzech
  wierszach, a szczegóły rezerwacji i lista „Do odpowiedzi” zachowują złamania
  wiersza. Za długa odpowiedź to `field_too_long`, jak przy tekście.
- **Wzorce ofert** mogą nieść `long_text` i opcjonalne `mandatoryForStaff`
  (domyślnie prawda). Opublikowanych wersji wzorców nie zmieniliśmy.
- **Asystent**: `booking.form_field.save` jest teraz w wersji `@2` (nowy klucz
  wejścia `mandatory_for_staff`; zestaw kluczy wersji jest zamrożony, `@1`
  znika); `booking.form_fields.read@1` oddaje dodatkowo `mandatory_for_staff` i
  `limits.max_long_answer_length`.
- Komunikat „odpowiedź jest za długa” mówi teraz właściwy limit (200 albo 500).

## Wdrożenie

- **Migracja booking 0039** (`0039_form_field_staff_and_long_text`): kolumna
  `booking_formfield.mandatory_for_staff` (domyślnie prawda, więc istniejące pola
  zachowują się jak dotąd) i nowa lista dozwolonych rodzajów; odwracalna
  (cofnięcie usuwa kolumnę). Numer może się zmienić, jeśli przed scaleniem
  `main` dostanie inną migrację booking.
- Wzorce czyta backend z obrazu: schemat kontraktu (`long_text`,
  `mandatoryForStaff`) wchodzi z przebudową obrazu backendu.
- Przebudowa backendu i frontendu razem. Bez nowych zmiennych środowiskowych.

## Produkty (HoofCare, MedPlano) przy następnym `core:update`

- Migracja booking 0039 na każdym stacku. Nic do zmiany w kodzie produktu;
  `booking.api` bez zmian (produkt rezerwujący bez formularza nadal nie jest
  pytany o nic).
- Produkt, który przypina wersję polecenia `booking.form_field.save@1`, musi
  przejść na `@2` (w repozytoriach produktów takiego użycia nie ma).
- Słowa: `FormFields.mandatoryForStaff`, `FormFields.mandatoryForStaffHint` i
  parametr `{max}` w `PublicBooking.fieldTooLong` (`pl.json`, `en.json`,
  `public/de.json`, `es.json`, `ru.json`); produkt, który nadpisuje te
  przestrzenie w swoim slocie, dopisuje je u siebie.

## Dowody

- `tests/test_booking_form_fields.py` (pole wolne dla zespołu: wizyta i pobyt,
  klient nadal pytany; dłuższy tekst: 500 i 501 znaków, złamania wiersza;
  wzorzec z `mandatoryForStaff: false` i `long_text`; migracja 0039 w przód i w
  tył), `tests/command_evals/booking.py` (`booking.form_field.save@2`),
  `packages/contracts/tests/booking-preset-contracts.test.mjs`,
  `offer-fields-dialog.test.tsx` (drugie pole edytora), `own-fields.test.tsx`
  (`useOfferFields`, `OwnFields` z dłuższym tekstem).
- Nie sprawdzone w przeglądarce ani na przebudowanym stacku (to robi następna
  paczka).

## Czego nie ma

- Osobnej reguły „dla zespołu” przy zgodach (zgodę daje tylko klient).
- Pola obowiązkowego tylko dla zespołu.
- Nowej wersji wzorców z takim polem (HoofCare dodaje swoje pole w ofercie).
