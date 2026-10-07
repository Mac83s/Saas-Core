# Rezerwacje uniwersalne, faza 5: pola własne formularza (5j) — wydanie 2026-10-07

Zakres: plaster 5j planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5j”). Jedna migracja: booking 0038.

## Co się zmieniło

- **Firma dodaje do oferty własne pytania.** „Ustawienia › Usługi i grafik” →
  menu „…” przy usłudze → „Pola formularza”: pytanie tekstowe, liczba, data,
  wybór z listy albo zgoda do zaznaczenia; każde obowiązkowe albo nie, w
  ustalonej kolejności. Pola się nie usuwa, tylko wyłącza.
- **Formularz rezerwacji pyta o nie klienta.** Pola oferty pojawiają się w
  formularzu wizyty i pobytu pod danymi kontaktowymi, w języku strony tam,
  gdzie firma je przetłumaczyła („Tłumaczenia” przy polu). Bez odpowiedzi na
  pole obowiązkowe (albo bez zaznaczenia obowiązkowej zgody) rezerwacja z
  formularza nie przejdzie; zespół w panelu nie jest o nic pytany.
- **Odpowiedzi są przy rezerwacji.** Szczegóły rezerwacji w kalendarzu i lista
  „Do odpowiedzi” pokazują pytanie i odpowiedź — temu, kto widzi telefon
  klienta. Odpowiedzi nie ma w e-mailach, w historii zmian ani w linku klienta.
- **Zaznaczona zgoda trafia do dziennika zgód** słowo w słowo, w języku, w
  którym klient ją widział.
- **Odpowiedzi znikają razem z klientem**: ręczna anonimizacja i automatyczne
  usuwanie po okresie przechowywania czyszczą je jak uwagi do wizyty.
- **Wzorce ofert niosą pola.** „Nocleg” (wersja 6) pyta o przybliżoną godzinę
  przyjazdu, „Wypożyczalnia” (4) o numer prawa jazdy — oba nieobowiązkowe;
  „Pobyt z opieką” (4) wymaga odpowiedzi, kogo lub co firma przyjmuje. Oferty
  założone z wcześniejszych wersji nie zmieniają się.
- **Asystent ma te same operacje**: `booking.form_fields.read` i
  `booking.form_field.save`; podgląd `booking.preset.apply` mówi, o co
  formularz zapyta.
- **Formularz oznacza zdjęcia jednostek wygenerowane przez AI** znaczkiem „AI”
  i dopiskiem w opisie obrazu — jak strona firmy i katalog (ADR-059 pkt 7).
- **`seed_demo`**: „Domki nad Jeziorem” pytają o godzinę przyjazdu i łóżeczko
  dla dziecka; „Kajaki Krutynia” o to, ile osób nie umie pływać, i wymagają
  zaznaczenia „Znam zasady bezpieczeństwa na wodzie”.

## Wdrożenie

- **Migracja booking 0038** (`0038_form_fields`): tabele `booking_formfield` i
  `booking_formfieldtranslation` (tenantowe, wymuszone RLS, strażnik relacji)
  oraz kolumna `form_answers` na `booking_appointment`; odwracalna (cofnięcie
  usuwa tabele i kolumnę razem z odpowiedziami).
- Presety czyta backend z obrazu (`BOOKING_PRESET_CONTRACTS_PATH`): nowe
  wersje wchodzą z przebudową obrazu backendu.
- Przebudowa backendu i frontendu razem. Bez nowych zmiennych środowiskowych.
- Po wdrożeniu `seed_demo` (tam, gdzie są dane pokazowe) dopisze pola firmom
  pokazowym; rezerwacji już zasianych nie zmienia.

## Produkty (HoofCare, MedPlano) przy następnym `core:update`

- Migracja booking 0038 na każdym stacku.
- „Pola formularza” pojawią się przy każdej usłudze, a pola — w publicznym
  formularzu rezerwacji produktu (ten sam komponent rdzenia). Wizyty zakładane
  przez produkt (`booking.api.create_appointment`, nowy argument `answers` z
  wartością domyślną) nie są pytane o nic. Nic do zmiany w kodzie produktu.
- **MedPlano — do decyzji przed włączeniem:** pytanie dodane przez gabinet
  („Powód wizyty”) zbierze dane o zdrowiu. Odpowiedzi mają ten sam reżim co
  „Uwagi” (decyzja 1A z 28.09: tylko panel, nigdy e-mail, log ani historia,
  czyszczone przy anonimizacji) i węższy krąg czytających (jak telefon
  klienta), ale to dane szczególnej kategorii zbierane celowo — pytanie jest w
  raporcie paczki M12 i w planie.
- Słowa: nowe klucze `PublicBooking.field*`, `PublicBooking.answersRefused`,
  `PublicBooking.fieldsChanged` (w `pl.json`, `en.json` i `public/de.json`,
  `es.json`, `ru.json`), przestrzeń `FormFields`, `Translations.fieldOptions`,
  `Calendar.answerTicked` i `Requests.answerTicked`; produkt, który nadpisuje
  te przestrzenie w swoim slocie, dopisuje je u siebie.
- Presety własne produktu (profil, `organizationTypes[]`) mogą nieść `fields`
  — zastosowanie skopiuje je do oferty.

## Dowody

- `tests/test_booking_form_fields.py` (pole jako pozycja konfiguracji: odmowy,
  wersja, podgląd, klucz, limit, audyt; API z odmową dla osoby bez uprawnień i
  dla cudzej usługi; katalog formularza w języku gościa i możliwości wyboru;
  pobyt i wizyta z formularza: odmowy `field_required`, `field_invalid`,
  `field_unknown`, `field_too_long`, migawka odpowiedzi, wiersze dziennika
  zgód w języku gościa, brak odpowiedzi w odpowiedzi publicznej, w kontekście
  powiadomień i w audycie, klucz idempotencji; zespół bez pytań i odczyt
  odpowiedzi jak telefonu; anonimizacja; preset z polami i cofnięcie szkicu;
  znaczek AI w katalogu formularza), `tests/command_evals/booking.py`
  (`booking.form_fields.read@1`, `booking.form_field.save@1`),
  `packages/contracts/tests/booking-preset-contracts.test.mjs`,
  `public-booking-parts.test.tsx`, `offer-fields-dialog.test.tsx`.
- Przejście w Chromium (1280 i 390 px): `.local-dev/resume/package-m12/` —
  wynik w worklogu memex.

## Czego nie ma

- Odpowiedzi wpisywanych przez zespół w oknach „Nowa wizyta” i „Nowy pobyt”
  (API je przyjmuje).
- Pola wspólnego dla wszystkich ofert firmy; przeciągania kolejności.
- Odpowiedzi w linku klienta i w eksporcie.
- Rodzajów „plik” i „godzina”; pól zależnych od innej odpowiedzi.
- Tłumaczenia komunikatów odmów formularza na wszystkie języki firmy (5i).
