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
| Fryzjer — Salon Fryzjerski Ania | 4 | 5 | 2 | 0 |
| Hydraulik — Hydraulik Kowalski | 2 | 5 | 0 | 0 |
| Domki letniskowe — Domki nad Jeziorem | 2 | 2 | 0 | 0 |
| Wypożyczalnia kajaków — Kajaki Krutynia | 2 | 2 | 3 | 0 |

## Czego dziś brakuje w produkcie

- rodzaj rezerwacji „Nocleg”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- rodzaj rezerwacji „Wypożyczalnia”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- rodzaj rezerwacji „Usługa u klienta”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- cennik poza ceną podstawową (sezony, ceny weekendowe, dopłaty, kaucje): rozmowa ustawiająca firmę o nie nie pyta — właściciel wpisuje je w panelu albo zleca asystentowi w zwykłej rozmowie (`booking.price.save`, `booking.extra.save`)
- zasady sezonów (najkrótszy pobyt, dni przyjazdu): asystent nie ma polecenia — ustawia je właściciel w panelu, w Sezonach

## Fryzjer — Salon Fryzjerski Ania, Olsztyn

Właściciel powiedział: „fryzjer damski i męski”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, adres, miasto
- miejsce „Salon na Mazurskiej”
- osoba „Ania” — bez konta w panelu
- osoba „Ola” — bez konta w panelu

**Zapyta**

- jaka stawka VAT obowiązuje dla ceny „Strzyżenie damskie” (wybór z listy)
- potwierdzenie — „Koloryzacja”: rodzaj rezerwacji: „Wizyta u specjalisty” (propozycja asystenta)
- w jakich godzinach pracuje Ola
- kategoria w katalogu firm — asystent podpowie „Uroda i zdrowie”
- potwierdzenie — jedno zdanie o firmie: „Strzyżenie i koloryzacja w centrum Olsztyna” (propozycja asystenta)

**Czeka**

- usługa „Strzyżenie damskie” — w następnej rundzie, gdy będą: miejsce „Salon na Mazurskiej”, osoba „Ania”, osoba „Ola”
- godziny pracy: Ania — w następnej rundzie, gdy będą: osoba „Ania”, miejsce „Salon na Mazurskiej”

**Produkt jeszcze nie umie**

- nic

## Hydraulik — Hydraulik Kowalski, Mrągowo

Właściciel powiedział: „hydraulik: awarie, instalacje wodne i kanalizacyjne”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, miasto
- osoba „Jan Kowalski” — bez konta w panelu

**Zapyta**

- jaka stawka VAT obowiązuje dla ceny „Usuwanie awarii” (wybór z listy)
- „Montaż instalacji”: czas trwania
- skąd firma wyjeżdża do klientów (miejsce, w którym zespół ma godziny pracy)
- w jakich godzinach pracuje Jan Kowalski
- kategoria w katalogu firm — asystent podpowie „Usługi dla domu”

**Czeka**

- nic

**Produkt jeszcze nie umie**

- nic

## Domki letniskowe — Domki nad Jeziorem, Mikołajki

Właściciel powiedział: „domki letniskowe nad jeziorem”.

**Ustawi od razu**

- języki firmy: pl, en
- wizytówkę firmy: nazwa, opis, e-mail, miasto

**Zapyta**

- gdzie firma przyjmuje
- kategoria w katalogu firm — asystent podpowie „Turystyka i noclegi”

**Czeka**

- nic

**Produkt jeszcze nie umie**

- nic

## Wypożyczalnia kajaków — Kajaki Krutynia, Mrągowo

Właściciel powiedział: „wypożyczalnia kajaków na Krutyni”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, miasto
- miejsce „Przystań”

**Zapyta**

- jakim rodzajem rezerwacji jest „Transport kajaków” (wybór z listy)
- kategoria w katalogu firm — asystent podpowie „Turystyka i noclegi”

**Czeka**

- usługa „Kajak dwuosobowy” — w następnej rundzie, gdy będą: miejsce „Przystań”
- jednostki usługi „Kajak dwuosobowy” — w następnej rundzie, gdy będą: usługa „Kajak dwuosobowy”
- cena usługi „Kajak dwuosobowy” — w następnej rundzie, gdy będą: usługa „Kajak dwuosobowy”

**Produkt jeszcze nie umie**

- nic

## Skąd te dane

- konto: odczyty przez rejestr poleceń (`organization.read`, `organization.public_locales.read`, `profiles.organization.read`, `profiles.catalog_options.read`, `booking.setup.read`, `booking.prices.read`) dla firmy typu `business` bez wizytówki, miejsc, osób, usług i cen;
- rodzaje rezerwacji: polecenie `booking.preset.list@1`, czyli kontrakt `packages/contracts/booking-presets/` w najnowszych wersjach;
- języki: oferuje je profil wdrożenia (testy liczą na profilu z polskim i angielskim, Business ma też niemiecki), więc przykład używa pary pl + en;
- reguły konfiguratora mają osobne testy na zamrożonych katalogach — ten plik pokazuje stan produktu, nie reguły.
