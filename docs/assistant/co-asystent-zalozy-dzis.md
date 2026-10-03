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
| Fryzjer — Salon Fryzjerski Ania | 4 | 4 | 2 | 1 |
| Hydraulik — Hydraulik Kowalski | 2 | 4 | 0 | 1 |
| Domki letniskowe — Domki nad Jeziorem | 2 | 2 | 0 | 1 |
| Wypożyczalnia kajaków — Kajaki Krutynia | 2 | 2 | 1 | 1 |

## Czego dziś brakuje w produkcie

- rodzaj rezerwacji „Nocleg”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- rodzaj rezerwacji „Wypożyczalnia”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- rodzaj rezerwacji „Usługa u klienta”: firma ustawia ofertę i ceny, rezerwacje wpisuje zespół w panelu; rezerwacja przez stronę — wkrótce (plan rezerwacji, faza 5: formularz publiczny)
- jednostki pobytów i wynajmu (domki, kajaki): asystent ich nie zakłada — dodaje je właściciel w panelu, w Ustawieniach › Usługi i grafik
- ceny usług: cennik jest w produkcie, ale asystent nie ma jeszcze polecenia, które zapisuje cenę — cenę wpisuje właściciel w cenniku; odblokuje: polecenie cennika dla asystenta (plan asystenta)

## Fryzjer — Salon Fryzjerski Ania, Olsztyn

Właściciel powiedział: „fryzjer damski i męski”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, adres, miasto
- miejsce „Salon na Mazurskiej”
- osoba „Ania” — bez konta w panelu
- osoba „Ola” — bez konta w panelu

**Zapyta**

- potwierdzenie — „Koloryzacja”: rodzaj rezerwacji: „Wizyta u specjalisty” (propozycja asystenta)
- w jakich godzinach pracuje Ola
- kategoria w katalogu firm — asystent podpowie „Uroda i zdrowie”
- potwierdzenie — jedno zdanie o firmie: „Strzyżenie i koloryzacja w centrum Olsztyna” (propozycja asystenta)

**Czeka**

- usługa „Strzyżenie damskie” — w następnej rundzie, gdy będą: miejsce „Salon na Mazurskiej”, osoba „Ania”, osoba „Ola”
- godziny pracy: Ania — w następnej rundzie, gdy będą: osoba „Ania”, miejsce „Salon na Mazurskiej”

**Produkt jeszcze nie umie**

- cena „Strzyżenie damskie” (90,00 PLN) — cennik jest w produkcie, ale asystent nie ma jeszcze polecenia, które zapisuje cenę — cenę wpisuje właściciel w cenniku; odblokuje: polecenie cennika dla asystenta (plan asystenta)

## Hydraulik — Hydraulik Kowalski, Mrągowo

Właściciel powiedział: „hydraulik: awarie, instalacje wodne i kanalizacyjne”.

**Ustawi od razu**

- wizytówkę firmy: nazwa, telefon, miasto
- osoba „Jan Kowalski” — bez konta w panelu

**Zapyta**

- „Montaż instalacji”: czas trwania
- skąd firma wyjeżdża do klientów (miejsce, w którym zespół ma godziny pracy)
- w jakich godzinach pracuje Jan Kowalski
- kategoria w katalogu firm — asystent podpowie „Usługi dla domu”

**Czeka**

- nic

**Produkt jeszcze nie umie**

- cena „Usuwanie awarii” (200,00 PLN) — cennik jest w produkcie, ale asystent nie ma jeszcze polecenia, które zapisuje cenę — cenę wpisuje właściciel w cenniku; odblokuje: polecenie cennika dla asystenta (plan asystenta)

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

- cena „Domek 6-osobowy” (450,00 PLN) — cennik jest w produkcie, ale asystent nie ma jeszcze polecenia, które zapisuje cenę — cenę wpisuje właściciel w cenniku; odblokuje: polecenie cennika dla asystenta (plan asystenta)

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

**Produkt jeszcze nie umie**

- cena „Kajak dwuosobowy” (60,00 PLN) — cennik jest w produkcie, ale asystent nie ma jeszcze polecenia, które zapisuje cenę — cenę wpisuje właściciel w cenniku; odblokuje: polecenie cennika dla asystenta (plan asystenta)

## Skąd te dane

- konto: odczyty przez rejestr poleceń (`organization.read`, `organization.public_locales.read`, `profiles.organization.read`, `profiles.catalog_options.read`, `booking.setup.read`) dla firmy typu `business` bez wizytówki, miejsc, osób i usług;
- rodzaje rezerwacji: polecenie `booking.preset.list@1`, czyli kontrakt `packages/contracts/booking-presets/` w najnowszych wersjach;
- języki: oferuje je profil wdrożenia (testy liczą na profilu z polskim i angielskim, Business ma też niemiecki), więc przykład używa pary pl + en;
- reguły konfiguratora mają osobne testy na zamrożonych katalogach — ten plik pokazuje stan produktu, nie reguły.
