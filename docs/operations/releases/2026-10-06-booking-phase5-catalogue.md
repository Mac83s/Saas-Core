# Rezerwacje uniwersalne, faza 5: katalog wie, kogo można zarezerwować online (5h) — wydanie 2026-10-06

Zakres: plaster 5h planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Rozstrzygnięcia plastra 5h”) i podtyp `LodgingBusiness` z faktu
([ADR-071](../../adr/ADR-071-Jezyki-Tresci-Adresy-i-SEO-GEO.md)
„Uzupełnienie 2026-10-06”). Dwie migracje: profiles 0011, booking 0037.

## Co się zmieniło

- **Katalog firm ma odznakę i filtr „Rezerwacja online”.** Firma, której
  formularz przyjmuje rezerwacje, dostaje odznakę na liście; pole „Tylko firmy
  z rezerwacją online” zawęża wyniki. Filtr widać tylko w produkcie, który ma
  rezerwacje.
- **Wizytówka w katalogu pozwala zarezerwować.** Sekcja „Rezerwacja online”:
  przycisk do formularza firmy i — u firmy z pobytami — karty jednostek, które
  firma pokazuje gościom (zdjęcie, miejscowość, pojemność, „od X zł za noc”).
- **Jednostka ma stronę w katalogu**: `/katalog/<miasto>/<firma>/<jednostka>`
  z galerią, wyposażeniem, kalendarzem wolnych dni i przyciskiem do formularza
  na wybrany termin. Strona przyjmuje `from`, `to` i `people` z adresu.
- **Rezerwacja mówi, skąd przyszła.** Odnośniki z katalogu niosą podpisany
  token; rezerwacja z nim ma źródło „Katalog firm” (w szczegółach rezerwacji
  w panelu), a jej zamówienie kanał „Katalog”. Bez tokenu rezerwacja z
  formularza to „Formularz rezerwacji firmy”, a zespołu — biuro.
- **Wizytówka podpowiada kategorię z wzorca oferty**: firma bez kategorii,
  która założyła ofertę ze wzorca (np. „Nocleg”), widzi pod polem „Kategoria”
  podpowiedź i przycisk „Ustaw…”.
- **Firma, która wynajmuje na noce, jest `LodgingBusiness`** w danych
  strukturalnych — bez względu na kategorię katalogu. Wizytówka w katalogu
  mówi to od razu, własna strona firmy od następnej publikacji.
- **`seed_demo` wypełnia wizytówki firm pokazowych**: „Kajaki Krutynia”
  stoją w katalogu od razu (z odznaką), a wizytówka „Domków nad Jeziorem”
  czeka na kategorię z podpowiedzią wzorca „Nocleg” — właścicielka ustawia ją
  jednym kliknięciem i sama włącza katalog.
- **API**: `GET /api/v1/public/catalog/` przyjmuje `badge`, a wiersz niesie
  `badges`; słownik katalogu oddaje `badges`; wizytówka oddaje `booking` i
  `business_type`; nowe `GET /api/v1/public/catalog/<miasto>/<firma>/units/<jednostka>/`;
  rezerwacje publiczne (`…/appointments/`, `…/stays/`) przyjmują `origin`;
  odczyt rezerwacji w panelu ma `channel`; `GET /api/v1/profiles/organization/`
  ma `catalog.suggested_category`.

## Wdrożenie

- **Migracja profiles 0011** (`0011_catalog_entry_badges`): kolumna `badges` i
  indeks GIN na `profiles_catalogentry`; odwracalna.
- **Migracja booking 0037** (`0037_appointment_channel`): kolumny `channel` i
  `origin_token` na `booking_appointment`; odwracalna. Rezerwacje sprzed
  wdrożenia mają pusty kanał — panel nic przy nich nie pokazuje.
- **Po migracjach, raz:** `python manage.py refresh_catalog_badges` — wpisy
  katalogu opublikowane przed wdrożeniem nie mają odznaki, dopóki firma czegoś
  nie zmieni. Polecenie przy okazji dopisuje `badges` do atrybutów filtrowanych
  indeksu wyszukiwarki (Meilisearch), jeśli jest skonfigurowana. Można je
  powtarzać.
- Bez nowych zmiennych środowiskowych. Token podpisuje `SECRET_KEY` wdrożenia:
  jego zmiana unieważnia odnośniki z katalogu wystawione wcześniej (rezerwacje
  z nich powstają dalej, z kanałem „strona firmy”).
- Przebudowa backendu i frontendu razem.
- Strona firmy noclegowej dostaje `LodgingBusiness` po **ponownej publikacji**
  (fakty firmy są w migawce publikacji).

## Produkty (HoofCare, MedPlano) przy następnym `core:update`

- Obie migracje i jednorazowe `refresh_catalog_badges` na każdym stacku.
- Odznaka i filtr pojawią się w ich katalogach same: oba produkty mają
  rezerwacje i formularze publiczne. Stron jednostek nie będzie, dopóki firma
  nie ma ofert okresu z jednostkami „publicznymi” — korektor racic i gabinet
  dostają na wizytówce sam przycisk „Zarezerwuj online”.
- Podpowiedź kategorii działa tylko dla kategorii, którą słownik typu
  organizacji produktu ma (własne `catalogCategories` w profilu); wzorce
  rdzenia nazywają kategorie rdzenia, więc w produkcie z własnym słownikiem
  podpowiedzi nie będzie — bez błędu.
- `booking.api.create_appointment` ma nowy argument `origin` z wartością
  domyślną; rezerwacje produktu zapisane z kontekstu członka zespołu dostają
  kanał `office`. Nic do zmiany w kodzie produktu.
- Słowa: nowe klucze `Catalog.*`, `Calendar.channel*`, `Profile.categoryHint`
  i `Profile.useCategory` są w `pl.json` i `en.json` rdzenia (i `Catalog.*` w
  `public/de.json`); produkt, który nadpisuje te przestrzenie w swoim slocie,
  dopisuje je u siebie.

## Dowody

- `tests/test_booking_catalog_card.py` (token: firma, wiek, zmiana; odznaka i
  filtr z wiersza, zdjęcie odznaki po wyłączeniu oferty, polecenie
  uzupełniające; wizytówka z jednostkami i tokenem; strona jednostki z
  kolejnością `SET LOCAL` przed odczytem tabel rezerwacji; kanał `catalog`,
  `company_site` i `office` oraz kanał zamówienia; podpowiedź kategorii;
  `LodgingBusiness` z faktu), `catalog-search.test.tsx`, `catalog-seo.test.ts`,
  `catalog-stay-picker.test.tsx`, `public-stay-flow.test.tsx`,
  `profile-panel.test.tsx`.
- Przejście w Chromium (1280 i 390 px): `.local-dev/resume/package-m11/` —
  wynik w worklogu memex.

## Czego nie ma

- Wyszukiwarki wolnych terminów w wielu firmach i przełącznika „Pokazuj wolne
  terminy w katalogu” (faza 16).
- Stron jednostek w mapie strony platformy.
- Automatycznego odświeżenia odznaki, gdy plan firmy przestaje obejmować
  rezerwacje (wizytówka i formularz mówią prawdę od razu; listę naprawia
  następna zmiana oferty albo `refresh_catalog_badges`).
- Kopii tokenu na zamówieniu i tokenów dla innych kanałów (sklep).
