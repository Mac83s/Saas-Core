# Rezerwacje uniwersalne, faza 5: pobyty na formularzu publicznym (5a–5b) — wydanie 2026-10-04

Zakres: pierwsze dwa plastry fazy 5 planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Uzupełnienie 2026-10-04: faza 5 w plastrach”, „Rozstrzygnięcia plastra 5a” i
„…5b”). Bez migracji.

## Co się zmieniło

- **Gość rezerwuje pobyt albo wynajem na stronie rezerwacji firmy**
  (`/<język>/book/<slug>`): w „Usługa” są teraz także oferty okresu (noce,
  dni). Gość wybiera, co rezerwuje (grupę jednostek albo jednostkę), liczbę
  osób, przyjazd i wyjazd z list wolnych dni, dopłaty — i widzi cenę z
  kaucją, przedpłatą i warunkami zwrotu, zanim zarezerwuje. Akceptuje
  dokumenty firmy jak przy wizycie.
- **Wszystko z fazy 4 działa dla pobytu**: zamówienie, przedpłata przelewem z
  terminem („Rezerwacja czeka na wpłatę” z danymi do przelewu), „na prośbę”,
  progi zwrotu przy rezygnacji z linku.
- **Rezerwacja z formularza jest w „Obłożeniu”** jak pobyt wpisany przez
  zespół; jednostkę z grupy dobiera serwer.
- **Link klienta** pokazuje pobyt dniami i jednostką i przenosi go datami:
  „Sprawdź termin” pokazuje nowy termin i cenę, „Przenieś rezerwację” go
  zapisuje.
- **Klient nigdy nie dostaje ceny, której nie widział**: publiczny zapis
  pobytu z ceną (rezerwacja, przeniesienie) wymaga skrótu wyceny; bez niego
  albo przy innej cenie odpowiedź to 409 `quote_changed` z wyceną.
- **Presety „Nocleg”, „Wypożyczalnia”, „Pobyt z opieką” w wersji 3** nie mówią
  już „rezerwacja przez stronę — wkrótce”; oferta z nich powstaje widoczna w
  rezerwacji online (jako wyłączona wersja robocza, jak dotąd).
- **API** (publiczne, bez sesji): `stays`, `participant_categories` i
  `online.period_last_day` w `GET /api/v1/booking/public/<slug>/`;
  `GET …/stays/starts/`, `GET …/stays/ends/`, `POST …/stays/quote/`,
  `POST …/stays/`; `time_model`, `range_unit`, `unit_name` w odpowiedzi
  rezerwacji i linku; `POST /api/v1/booking/self-service/<token>/stay/` i
  `…/stay/preview/`.

## Na co uważać przy wdrożeniu

- **Oferta okresu z włączonym „W rezerwacji online na stronie” staje się
  rezerwowalna przez gości.** Przełącznik był dotąd włączony domyślnie także
  dla ofert okresu zakładanych ręcznie, ale formularz ich nie pokazywał. Po
  wdrożeniu aktywna oferta okresu z jednostką i tym przełącznikiem jest na
  formularzu. Firma, która woli wpisywać pobyty sama, wyłącza go w ofercie
  (Ustawienia › Usługi i grafik › „Edytuj usługę”). Oferty założone z presetów
  w wersji 2 mają go wyłączony.
- Ustawienie firmy „Na ile dni naprzód” (rezerwacje online) dotyczy wizyt.
  Jak daleko naprzód gość rezerwuje pobyt, mówi „okno naprzód” sezonu
  (Ustawienia › Sezony i zasady); bez niego granicą jest
  `BOOKING_PERIOD_HORIZON_DAYS` platformy (domyślnie 548 dni).

## Dla produktów

- Nic do zrobienia przy `pnpm core:update`: formularz i link klienta są
  plikami rdzenia. Produkt bez ofert okresu nie zobaczy różnicy — katalog
  oddaje wtedy pustą listę `stays`.
- `booking.periods.book_stay` i `move_stay` wołane przez produkt w kontekście
  członka zespołu działają jak dotąd. W kontekście formularza
  (`public_booking_context`) znajdują tylko to, co firma oferuje online, i
  wymagają `quote_digest` dla pobytu z ceną.
- Teksty gości są w `apps/frontend/messages/pl.json`, `en.json` i
  `messages/public/de.json` (przestrzenie `PublicBooking`,
  `BookingSelfService`); produkt z własnym językiem gości dopisuje nowe klucze
  w swoim katalogu `messages/public/<język>.json`.
