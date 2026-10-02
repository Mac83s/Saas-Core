# ADR-066 — miejsce wizyty: miejscowość i adres na wizycie, przed tym, co wie produkt

**Status:** Accepted — decyzja właściciela 14a z 2026-10-02.
**Data:** 2026-10-02

## Kontekst

01.10 karta wizyty w kalendarzu dostała miejscowość, ale tylko od produktu:
`booking.api.register_appointment_place` pozwala modułowi powiedzieć, gdzie jest
wizyta, którą zna (HoofCare: `HerdVisit` → `Farm.village`). Wizyta założona w
Kalendarzu przez „Nowa wizyta” jest zwykłą rezerwacją — jej klient nie ma
adresu, a nic nie łączy jej z gospodarstwem — więc miejscowości nie miała.
Właściciel 02.10 (decyzja 14a): **każda** wizyta ma „Miejsce wizyty”.

`Location` to miejsce firmy (gabinet, baza), z którego się przyjmuje albo
wyjeżdża — nie miejsce wizyty terenowej. Adres w kartotece klienta przyjdzie z
planem rezerwacji uniwersalnych; teraz go nie budujemy.

## Decyzja

1. **Miejsce na wizycie.** `Appointment.place_town` (120) i `place_address`
   (240, ulica i numer, opcjonalnie) — migracja `booking 0012`, odwracalna,
   puste domyślnie. Pola przyjmuje `POST /booking/appointments/` (`place_town`,
   `place_address`, część skrótu idempotencji, gdy podane); zmienia je
   `PUT /booking/appointments/{id}/place/` (`town`, `address`; oba puste
   czyszczą; to samo jeszcze raz nic nie zmienia; odwołanej wizyty nie —
   `appointment_not_changeable`). Zmiana idzie do historii jako
   `booking.appointment.place_changed` z miejscowością przed i po; **ulica
   nigdy** — bywa domem klienta. Anonimizacja klienta czyści ulicę jego wizyt,
   miejscowość zostaje.
2. **Wyświetlanie.** `place` w odpowiedzi to miejscowość z wizyty, a gdy pusta —
   z dostawcy produktu (`register_appointment_place`). Karty, tablica, agenda,
   miesiąc i lista pokazują `place`; szczegóły wizyty — „Miejsce wizyty” z
   miejscowością i ulicą oraz „Zmień miejsce” dla tego, kto planuje wizyty.
3. **Zapisane miejsca z produktu.** `booking.api.register_place_search(name,
   search)` — moduł podaje miejsca, które firma ma u siebie (`PlaceSuggestion`:
   nazwa, miejscowość, adres); `GET /booking/places/?q=&limit=` je zbiera, a
   katalog mówi `place_search: true`. Formularz wizyty pokazuje wtedy „Zapisane
   miejsce” (lista, przy więcej niż 12 — wyszukiwanie); wybór wpisuje
   miejscowość i adres do pól, które dalej można poprawić. HoofCare podaje
   gospodarstwa firmy (wieś i adres gospodarstwa) i sprawdza własne
   `farms.read`. Rdzeń nie zna produktu z nazwy.
4. **Gdzie indziej** miejscowość wpisuje się ręcznie.

## Konsekwencje

- Wizyta z wybranym gospodarstwem nie staje się wizytą w gospodarstwie
  (`HerdVisit`): ma tylko miejsce. **Zmienione przez ADR-067 (02.10):** wizyty
  rodzaju produktu rezerwuje sekcja produktu w „Nowej wizycie”, a HoofCare nie
  podpowiada już gospodarstw jako „Zapisanych miejsc”.
- Miejsce wizyty jest tekstem, nie odniesieniem: zmiana wsi gospodarstwa po
  fakcie nie przepisuje zaplanowanych wizyt — tak samo jak migawka nazwy usługi.
- Formularz na stronie publicznej miejsca nie pyta (klient nie ma adresu) —
  wróci z adresem klienta w planie rezerwacji uniwersalnych.

## Odrzucone

- **Odniesienie do gospodarstwa na wizycie w rdzeniu** — rdzeń nie składa się
  bez `shared.farms` (MedPlano), a gospodarstwo to tylko jedno z miejsc.
- **Adres w `Location`** — miejsce firmy to nie miejsce wizyty terenowej.
- **Wyszukiwanie zapisanych miejsc w polu „Miejscowość”** (Autocomplete) —
  nazwa gospodarstwa w polu miejscowości myli; osobne „Zapisane miejsce” nie.
