# Co asystent założy dziś — cztery przykładowe firmy

Ten plik pisze test, nie człowiek: `apps/backend/tests/test_assistant_configurator.py::test_what_the_product_can_do_today`.
Bierze cztery przykładowe profile firm (`packages/contracts/assistant/examples/`),
konto firmy tuż po rejestracji i to, co produkt naprawdę ma dziś: zarejestrowane
polecenia asystenta, katalog rodzajów rezerwacji i słownik katalogu firm. Zmiana w
produkcie zmienia ten plik w tym samym commicie.

Asystent nie wywołuje tu modelu i niczego nie zapisuje. To wynik konfiguratora (faza A2
planu asystenta): z tego, co powiedział właściciel, wylicza cztery listy.

- **Ustawi od razu** — polecenia gotowe do wykonania po jednym kliknięciu zgody.
- **Zapyta** — czego brakuje albo co zaproponował sam i właściciel musi potwierdzić.
- **Czeka** — kroki na następną rundę albo na polecenie, którego produkt jeszcze nie ma.
- **Produkt jeszcze nie umie** — czego właściciel chce, a czego nie da się dziś ustawić.

| Firma | Ustawi od razu | Zapyta | Czeka | Produkt jeszcze nie umie |
| --- | --- | --- | --- | --- |
| Fryzjer — Salon Fryzjerski Ania | 2 | 4 | 4 | 1 |
| Hydraulik — Hydraulik Kowalski | 1 | 1 | 1 | 2 |
| Domki letniskowe — Domki nad Jeziorem | 2 | 1 | 0 | 2 |
| Wypożyczalnia kajaków — Kajaki Krutynia | 2 | 2 | 0 | 1 |

## Czego dziś brakuje w produkcie

- polecenie `booking.preset.apply@1` — plan rezerwacji, faza 3 (zastosowanie rodzaju rezerwacji)
- polecenie `booking.preset.list@1` — plan rezerwacji, faza 3 (odczyt rodzajów rezerwacji)
- polecenie `booking.staff.add@1` — plan rezerwacji, faza 3 (dodanie osoby jako polecenie asystenta)
- rodzaj rezerwacji „Nocleg” jest w przygotowaniu — plan rezerwacji, faza 2 (silnik okresu: pobyty i wynajem na dni lub godziny)
- rodzaj rezerwacji „Wypożyczalnia” jest w przygotowaniu — plan rezerwacji, faza 2 (silnik okresu: pobyty i wynajem na dni lub godziny)
- rodzaj rezerwacji „Usługa u klienta” jest w przygotowaniu — plan rezerwacji, faza 13 (pozostałe rodzaje rezerwacji)
- ceny usług: produkt ich nie przechowuje — plan rezerwacji, faza 3 (cennik i wycena)
- miasto „Mikołajki” jest poza słownikiem miast katalogu firm

## Fryzjer — Salon Fryzjerski Ania, Olsztyn

Właściciel powiedział: „fryzjer damski i męski”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, adres, miasto
- miejsce „Salon na Mazurskiej”

**Zapyta**

- potwierdzenie — „Koloryzacja”: rodzaj rezerwacji: „Wizyta u specjalisty” (propozycja asystenta)
- w jakich godzinach pracuje Ola
- kategoria w katalogu firm — asystent podpowie „Uroda i zdrowie”
- potwierdzenie — jedno zdanie o firmie: „Strzyżenie i koloryzacja w centrum Olsztyna” (propozycja asystenta)

**Czeka**

- osoba „Ania” — produkt nie ma polecenia `booking.staff.add@1`; odblokuje: plan rezerwacji, faza 3 (dodanie osoby jako polecenie asystenta)
- osoba „Ola” — produkt nie ma polecenia `booking.staff.add@1`; odblokuje: plan rezerwacji, faza 3 (dodanie osoby jako polecenie asystenta)
- usługa „Strzyżenie damskie” — w następnej rundzie, gdy będą: miejsce „Salon na Mazurskiej”, osoba „Ania”, osoba „Ola”
- godziny pracy: Ania — w następnej rundzie, gdy będą: osoba „Ania”, miejsce „Salon na Mazurskiej”

**Produkt jeszcze nie umie**

- cena „Strzyżenie damskie” (90,00 PLN) — produkt nie przechowuje cen; odblokuje: plan rezerwacji, faza 3 (cennik i wycena)

## Hydraulik — Hydraulik Kowalski, Mrągowo

Właściciel powiedział: „hydraulik: awarie, instalacje wodne i kanalizacyjne”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, miasto

**Zapyta**

- kategoria w katalogu firm — wybór z listy, bez podpowiedzi

**Czeka**

- osoba „Jan Kowalski” — produkt nie ma polecenia `booking.staff.add@1`; odblokuje: plan rezerwacji, faza 3 (dodanie osoby jako polecenie asystenta)

**Produkt jeszcze nie umie**

- „Usuwanie awarii” — rodzaj rezerwacji „Usługa u klienta” jest w przygotowaniu; odblokuje: plan rezerwacji, faza 13 (pozostałe rodzaje rezerwacji)
- „Montaż instalacji” — rodzaj rezerwacji „Usługa u klienta” jest w przygotowaniu; odblokuje: plan rezerwacji, faza 13 (pozostałe rodzaje rezerwacji)

## Domki letniskowe — Domki nad Jeziorem, Mikołajki

Właściciel powiedział: „domki letniskowe nad jeziorem”.

**Ustawi od razu**

- języki firmy: pl, en
- wizytówkę firmy: nazwa, opis, e-mail

**Zapyta**

- kategoria w katalogu firm — asystent podpowie „Turystyka i noclegi”

**Czeka**

- nic

**Produkt jeszcze nie umie**

- miasto „Mikołajki” — nie ma go w słowniku miast katalogu firm, więc wizytówka nie trafi do katalogu; odblokuje: dopisanie miasta do słownika (ADR-053 §7, słownik rośnie z zasięgiem sprzedaży)
- „Domek 6-osobowy” — rodzaj rezerwacji „Nocleg” jest w przygotowaniu; odblokuje: plan rezerwacji, faza 2 (silnik okresu: pobyty i wynajem na dni lub godziny)

## Wypożyczalnia kajaków — Kajaki Krutynia, Mrągowo

Właściciel powiedział: „wypożyczalnia kajaków na Krutyni”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, miasto
- miejsce „Przystań”

**Zapyta**

- jakim rodzajem rezerwacji jest „Transport kajaków” (wybór z listy)
- kategoria w katalogu firm — asystent podpowie „Turystyka i noclegi”

**Czeka**

- nic

**Produkt jeszcze nie umie**

- „Kajak dwuosobowy” — rodzaj rezerwacji „Wypożyczalnia” jest w przygotowaniu; odblokuje: plan rezerwacji, faza 2 (silnik okresu: pobyty i wynajem na dni lub godziny)

## Skąd te dane

- konto: odczyty przez rejestr poleceń (`organization.read`, `organization.public_locales.read`, `profiles.organization.read`, `profiles.catalog_options.read`, `booking.setup.read`) dla firmy typu `business` bez wizytówki, miejsc, osób i usług;
- rodzaje rezerwacji: kontrakt `packages/contracts/booking-presets/`, dopóki polecenie `booking.preset.list@1` jest tylko zapowiedziane;
- języki: oferuje je profil wdrożenia (testy liczą na profilu z polskim i angielskim, Business ma też niemiecki), więc przykład używa pary pl + en;
- reguły konfiguratora mają osobne testy na zamrożonych katalogach — ten plik pokazuje stan produktu, nie reguły.
