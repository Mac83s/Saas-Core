# ADR-067 — część produktu w Kalendarzu: sekcja „Nowej wizyty”, szczegóły i znaczniki; kontakt klienta dla planujących i jadących

**Status:** Accepted — decyzja właściciela 15a z 2026-10-02 (odpowiedzi 15.1 a,
15.2 b, 15.3 a), projekt koordynatora 15a. Zmienia konsekwencję ADR-066 „wizyta z
wybranym gospodarstwem nie staje się wizytą w gospodarstwie”.
**Data:** 2026-10-02

## Kontekst

HoofCare planował wizyty w gospodarstwie na osobnej stronie `/panel/visits`, a
Kalendarz rezerwował zwykłe wizyty. Decyzja 15a: wizyty w gospodarstwie
planuje się w Kalendarzu, w „Nowej wizycie” — biuro wybiera gospodarstwo z listy,
dodaje nowe albo zostawia je korektorowi na miejscu. Rdzeń nie zna gospodarstw
(ADR-049, ADR-066 „Odrzucone”), a wizyta w gospodarstwie to rezerwacja plus
szczegół produktu (`HerdVisit`) zapisane razem.

## Decyzja

1. **Slot `src/product/calendar.tsx`** (rdzeń: `null`, typ `ProductCalendar` w
   `lib/product-extension.ts`). Produkt podaje rodzaje wizyt, które rezerwuje
   sam (`kinds`, czyli `Service.appointment_kind`), sekcję formularza
   (`formSection`), sprawdzenie (`check`), zapis (`save`), odczyt błędów pól z
   odpowiedzi serwera (`problemErrors`) i sekcję pod szczegółami wizyty
   (`detailsSection`). Sekcja dostaje usługę, wartość, `fill` (wypełnia klienta
   i miejsce wizyty, które osoba dalej widzi i może zmienić), swoje błędy,
   `access` panelu i parametry produktu z adresu Kalendarza. Dla usługi rodzaju
   produktu sekcja przejmuje „Zapisz”: formularz rdzenia składa wejście jak dla
   swojego POST, a zapisuje produkt — atomowo, przez własne API. Kontrakt jest
   mały celowo, żeby przetrwał przebudowę formularza (presety rezerwacji
   uniwersalnych). **Rdzeń nie dostaje pola `details` w `create_appointment`.**
2. **Adres Kalendarza**: `?new=1&service_id=<usługa>` otwiera formularz z usługą
   (`service` to dalej filtr po nazwie), a każdy inny parametr należy do sekcji
   produktu (np. `farm`); zostają w adresie, dopóki formularz jest otwarty.
3. **Szczegóły wizyty**: telefon (`tel:`), e-mail (`mailto:`) i „Nawiguj”
   (mapa z miejscowości i ulicy miejsca wizyty); pod nimi sekcja produktu.
4. **Znaczniki** (`booking.api.register_appointment_flags`): produkt mówi o
   swoich wizytach coś, czego rdzeń nie wie (HoofCare: `farm_missing`), raz na
   listę; panel pokazuje odznakę ze słowem z komunikatów produktu
   (`Calendar.flags.<znacznik>`). Odpowiedź wizyty ma też `appointment_kind`.
5. **Telefon i e-mail klienta w odpowiedzi wizyty** (15.2 b, reguła rdzenia dla
   wszystkich produktów): widzi je ten, kto planuje wizyty
   (`booking.appointment.manage`), i osoby na tej wizycie (prowadzący bez wakatu
   albo z zablokowanym czasem; po odwołaniu — ci, którzy byli). Pozostali
   dostają `null`, a ulicę miejsca wizyty (`place_address`) — pustą, bo bywa
   domem klienta; miejscowość widzą wszyscy (przegląd 02.10). Kolejka „Do
   przydzielenia” bez zmian (tylko planujący).
7. **Dostawcy produktu nie psują rdzenia**: dostawca miejsc, znaczników i
   wyszukiwania bez uprawnienia swojego modułu odpowiada niczym; taki, który
   mimo to rzuci wyjątek, jest logowany i pomijany w punkcie zapisu (savepoint),
   więc lista i właśnie zapisana zmiana zostają.
6. **Wyszukiwanie kart gospodarstw** (`GET /farms/?q=&active=1`) obejmuje e-mail
   i telefon (ostatnie dziewięć cyfr, jakkolwiek wpisany), z jawnym filtrem
   organizacji, i może pominąć karty wyłączone.

## Konsekwencje

- Produkt bez slotu (Business, MedPlano) ma formularz i szczegóły jak dotąd,
  plus telefon, e-mail i „Nawiguj”.
- Uprawnienia sekcji ocenia API produktu; `access` służy tylko do ukrycia opcji.
- Błędy pól serwera formularz czyta w jednym miejscu (`fieldProblems`); gdy API
  zmieni kształt błędów pól (A1a), zmienia się tylko ono.

## Odrzucone

- **`details` w rdzeniowym POST wizyty z rejestrem modułów** — słabo typowane w
  OpenAPI, ryzyko dla wszystkich produktów, a zapis atomowy daje już API
  produktu.
- **Zapis w dwóch krokach z frontu** (rezerwacja, potem potwierdzenie) — nie
  jest jedną transakcją; produkt robi to atomowo.
- **Telefon klienta dla każdego, kto widzi Kalendarz** — w MedPlano to telefon
  pacjenta dla całego personelu.

## Uzupełnienie 03.10 — nazwa wizyty od modułu, szczegóły wizyt bez rodzaju (plan UX/UI, W1–W2)

Przegląd panelu z 02.10 (plan `saas-core-poprawki-ux-ui`, W2): ta sama wizyta
w gospodarstwie nazywała się w Kalendarzu imieniem klienta („Jan Kowalski”), a w
„Dziś” produktu nazwą gospodarstwa; rezerwacji starej usługi bez rodzaju nie
dało się w Kalendarzu zamienić na wizytę produktu (W1).

8. **Nazwa wizyty od modułu** (`booking.api.register_appointment_title`, jak
   miejsca: jedno wywołanie na listę, pierwsza odpowiedź wygrywa, dostawca bez
   uprawnienia swojego modułu odpowiada niczym, błąd w punkcie zapisu jest
   logowany i pomijany). Odpowiedź wizyty ma `title` — pusty, gdy moduł nic nie
   wie. Panel pokazuje `title`, a gdy jest, klienta w drugiej linii (karta
   tygodnia, Lista, szczegóły — wiersz „Klient”); węższe widoki (miesiąc, tablica
   dnia, kolejka) tylko nazwę. Wyszukiwanie listy i kolejki obejmuje obie.
9. **Szczegóły dla innych rodzajów niż własne**: `ProductCalendar.detailsKinds`
   (domyślnie `kinds`) mówi, pod szczegółami których wizyt stoi sekcja
   produktu; `""` to usługa bez rodzaju. Formularz „Nowej wizyty” dalej
   przejmuje tylko `kinds`.
