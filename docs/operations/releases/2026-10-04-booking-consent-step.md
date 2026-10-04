# Rezerwacje: krok zgód formularzy publicznych — wydanie 2026-10-04

Zakres: plaster „zgody” fazy 5 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-073](../../adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md)
„Uzupełnienie 2026-10-04: krok zgód formularzy publicznych”). Dotyczy
formularza wizyty i formularza pobytu. Bez migracji.

## Co się zmieniło

- **W języku, w którym regulamin rezerwacji nie ma tekstu, nie rezerwuje się
  online.** Gdy firma ma obowiązujący regulamin rezerwacji, formularz w
  języku bez jego tekstu pokazuje kartę „W tym języku nie można zarezerwować
  online” z odnośnikami do języków, które regulamin mają; zapis z takiego
  języka to 409 `booking_language_unavailable`. Polityka prywatności niczego
  nie zamyka. Firma bez regulaminu i zespół w panelu rezerwują jak dotąd.
- **Panel ostrzega**: Ustawienia › Dokumenty dla klientów (lista i ekran
  regulaminu rezerwacji) oraz Ustawienia › Języki mówią, w których językach
  firmy rezerwacja online jest wyłączona; okno zatwierdzenia nowej wersji
  regulaminu mówi, że pozostałe języki zamkną się od dnia jej obowiązywania.
- **Zgoda marketingowa**: jedno nieobowiązkowe pole, domyślnie odznaczone —
  „Chcę otrzymywać oferty i promocje od (firma) e-mailem.” (pl, en, de).
  Zaznaczone to osobny wpis w dzienniku zgód (`marketing`). Firma wyłącza pole
  w Ustawienia › Rezerwacje › „Rezerwacja online” („Pytaj o zgodę na oferty i
  promocje”, domyślnie włączone).
- **Zbyt częste pytanie o cenę pobytu** mówi „Za dużo zapytań naraz. Spróbuj
  za chwilę.” i ponawia pytanie samo — zamiast „tego terminu nie można
  zarezerwować”.
- **API** (publiczne): `GET /api/v1/booking/public/<slug>/consents/` oddaje
  też `bookable`, `bookable_locales` i `marketing` (`statement` albo null);
  `consents.marketing` (bool) w `POST …/appointments/` i `POST …/stays/`;
  nowa odmowa 409 `booking_language_unavailable` z `detail.locales`. Opis
  `quote_digest` w `POST …/appointments/` mówi to, co kod robi od fazy 3d:
  wizyta z ceną wymaga skrótu wyceny pokazanej klientowi.

## Na co uważać przy wdrożeniu

- **Firma z regulaminem tylko po polsku przestaje przyjmować rezerwacje
  online w pozostałych swoich językach** od chwili wdrożenia — dotąd klient w
  takim języku rezerwował bez regulaminu. Ostrzeżenie widać w panelu; tekst
  w brakującym języku dodaje się w Ustawienia › Dokumenty dla klientów ›
  Regulamin rezerwacji (ręcznie albo tłumaczeniem do akceptacji).
- **Pole zgody marketingowej pojawia się na formularzach wszystkich firm**
  (ustawienie jest domyślnie włączone). Brzmienie jest robocze do odpowiedzi
  prawnika; lista zgód i ich cofanie w panelu to osobna praca.
- Wdrożenie: przebudowa backendu i frontendu z tego samego commita; bez
  migracji i bez zmian w `.env`.

## Dowody

- Testy: `tests/test_booking_consents.py` (język bez regulaminu — wizyta i
  pobyt, zespół w panelu, zgoda marketingowa i przełącznik firmy),
  `public-stay-flow.test.tsx`, `customers/documents.test.tsx`,
  `customers/terms-languages.test.tsx`.
