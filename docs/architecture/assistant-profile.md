# Profil firmy i konfigurator asystenta — kontrakt

Faza A2 planu asystenta (memex `saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy`),
uzupełnienie ADR-076. Bez modelu: profil to zapis tego, co powiedział właściciel, a
konfigurator to czysta funkcja, która z profilu i stanu konta wylicza, o co zapytać i
co wykonać. Rozmowę, która profil wypełnia, opisuje `assistant-chat.md` („Dwa
rodzaje rozmowy”, A3-2).

## Profil (`company-profile.v1`)

Schemat: `packages/contracts/assistant/company-profile.v1.schema.json` — pisany z kodu
(`shared/assistant/profile_schema.py`), nie ręcznie; przykłady czterech firm w
`packages/contracts/assistant/examples/`.

- Sekcje: `company` (nazwa, czym się zajmuje, miasto, kategoria, kontakt), `card`
  (zdanie i opis), `languages`, `places`, `people` (z tygodniem pracy), `offers`
  (rodzaj rezerwacji — id presetu, czas, sztuki, pojemność, cena, stawka VAT ceny,
  sezony, miejsca, osoby, odpowiedzi na `requiredInputs` presetu), `sources`.
- **Sezony pobytu albo wynajmu** (`offers[].seasons`) to jedna wartość — lista sezonów
  tak, jak nazwał je właściciel: `starts_on`, `ends_on` (dni kalendarza, oba włącznie,
  ostatni nie przed pierwszym — inaczej błąd pola), a z zasad tylko to, co padło:
  `min_stay` (najkrótszy pobyt w nocach albo dniach oferty), `arrival_days` (dni
  przyjazdu, 0 = poniedziałek), `name`.
- **Cena to kwota właściciela** (`offers[].price`: kwota do 999 999,99, waluta, za
  co — rezerwację, osobę, godzinę, dzień, noc) i osobno **stawka VAT**
  (`offers[].vat`: `23`, `8`, `5`, `0`, `zw`, `np`). Żadna z nich nie ma wartości
  domyślnej.
- **Każda wartość ma pochodzenie i potwierdzenie**:
  `{"value", "origin": owner | account | existing_site | preset_default | assistant, "confirmed"}`.
  Do konta trafia wyłącznie wartość potwierdzona; niepotwierdzona wraca jako pytanie.
- Wpisy list mają `key` — nazwę wewnątrz dokumentu. Oferta wskazuje miejsca i osoby
  po kluczach, godziny wskazują miejsce; klucz powtórzony albo wskazujący na brak
  wpisu to błąd pola.
- Limit dokumentu: 64 kB.

## Przechowywanie

Tabela `assistant_assistantprofileversion` (RLS FORCE, migracja `assistant 0005`):
jeden wiersz na zapisany stan — dokument, numer wersji, kto zapisał, kanał
(`acting_via`: pusty = osoba w panelu, `assistant` = rozmowa) i `conversation_id`.
Najnowszy wiersz to profil, starsze to historia. Zapis, który niczego nie zmienia, nie
tworzy wersji.

Klasa danych: `personal` (słowa właściciela, imiona osób). Profil znika razem z firmą.
Wcześniejszy stan znika `assistant.retention.conversation_days` dni po tym, jak
zastąpił go następny; stan bieżący nie znika nigdy. Robi to wspólny nocny przebieg
prywatności — moduł rejestruje przemiatanie `assistant.profile_versions`
(`assistant/retention.py`, `platform_days`) i nie ma własnego zadania czyszczącego.

## API (`/api/v1/assistant/profile/`)

| Operacja | Co robi |
| --- | --- |
| `GET profile/` | profil: `schema`, `version` (0, gdy nic nie zapisano), `document`, `updated_at` |
| `PATCH profile/` | zmiana: `expected_version` i `changes` — JSON merge patch (RFC 7396): pole zastępuje pole, `null` usuwa, lista zastępowana w całości; `Idempotency-Key` |
| `POST profile/preview/` | to samo bez zapisu: dokument po zmianie i `changed` |

Czyta i zmienia ten, kto zarządza ustawieniami firmy (`organization.settings.manage`
i `assistant.use`), także asystent działający w jego imieniu; cecha planu
`assistant.text.enabled`. Kody: 409 `assistant_profile_version_conflict`, 409
`assistant_idempotency_conflict`, 403 `assistant_not_in_plan`, 400 z nazwanym polem
(`changes.offers.0.duration_minutes.value`). Zapis profilu nie zmienia konta.

## Konfigurator (`shared/assistant/configurator.py`)

`configure(profile, reads, commands, setup_refs=(), origins=None)` — bez modelu, bez
bazy, bez wykonywania poleceń.

- `reads`: wyniki poleceń odczytu, po nazwie polecenia — asystent sięga do innych
  modułów tylko przez rejestr (ADR-076 pkt 9): `organization.read@1`,
  `organization.public_locales.read@1`, `profiles.organization.read@1`,
  `profiles.catalog_options.read@1`, `booking.setup.read@1`, `booking.preset.list@1`,
  `booking.prices.read@1`, `booking.seasons.read@1`. Obszar bez swoich odczytów jest
  pomijany.
- `commands`: nazwy poleceń, którymi wolno planować.
- `setup_refs`: rozmowy ustawiające tej firmy, w postaci, w jakiej usługa nazywa
  rozmowę, która ją założyła (`origin_ref` w `booking.setup.read@1`). Podaje je
  `setup._setup_refs` z tabeli rozmów — konfigurator sam niczego nie czyta.
- `origins`: po identyfikatorze usługi — dla której oferty z notatek (`offer`, klucz)
  rozmowa ustawiająca ją założyła albo zmieniła i jak się wtedy nazywała (`name`).
  Podaje je `setup._origins` z wyników planów (`made` przy kroku `offer:<klucz>`,
  zapisywane przez `turns.record_plan`).

Wynik to cztery listy:

| Lista | Co zawiera |
| --- | --- |
| `missing` | pytania do właściciela, od najważniejszych: `ask` (brakuje wartości) albo `confirm` (jest, ale niepotwierdzona), z `reason`, propozycją, dozwolonymi odpowiedziami (`options`) i tym, co zapowiedziane, ale jeszcze nie do wyboru (`soon`) |
| `plan` | polecenia gotowe do wykonania: `ref`, `command`, `arguments`; krok o czymś, czego notatki już nie nazywają (usunięcie szkicu), niesie nazwę w `about` |
| `blocked` | kroki, które czekają: `waits` (na wcześniejszy krok — `waits_for`), `command_missing` (produkt nie ma polecenia), `person_only` (krok właściciela, np. włączenie usługi) |
| `unsupported` | czego właściciel chce, a produkt jeszcze nie umie: `preset_not_ready`, `price_list` (rejestr bez poleceń cennika), `price_currency` (cena w innej walucie niż firma — nie przeliczamy), `city_not_in_catalog`, `language_not_offered`, `language_limit`, `preset_unknown`, `category_unknown`, `booking_unavailable`, `presets_unavailable`, `seasons_for_stays` (sezon przy wizycie na godzinę), `season_rules` (rejestr bez poleceń sezonów) |

Zasady:

- **Rundy.** Argumenty planu są ustalone przed wykonaniem, więc krok nie może użyć
  identyfikatora, który powstaje w tym samym planie. Usługa czeka na miejsce i osoby,
  godziny czekają na osobę i miejsce; po wykonaniu rundy ta sama funkcja daje następną.
- **Tylko dokłada.** Miejsce, osoba, język albo wykonawca usługi, których profil nie
  wymienia, zostają. Wyjątek: tydzień pracy osoby to jedna wartość — tydzień z profilu
  zastępuje ten z konta. O miasto i kategorię, które wizytówka już ma, nie pyta.
- **Jedno cofa: szkic, którego notatki już nie nazywają.** Usługa, która jest szkicem
  (`draft` — nigdy niewłączona), którą założyła rozmowa ustawiająca (`origin_ref` z
  `setup_refs`) i której nazwy nie ma żadna oferta w notatkach — bo właściciel ofertę
  usunął albo nazwał inaczej — dostaje krok `discard:<id usługi>` z poleceniem
  `booking.offer.discard@1` (klasa `irreversible`, osobne kliknięcie), na końcu planu.
  Nazwa, którą notatki nadal mają — potwierdzona albo nie — zatrzymuje szkic. Szkicu
  założonego w panelu, w zwykłej rozmowie albo w rozmowie, którą retencja już usunęła,
  konfigurator nie rusza; bez polecenia w rejestrze nie mówi o nim nic.
- **Usługa przemianowana w panelu zostaje ofertą z notatek** (`origins`): gdy usługę
  założono dla oferty o tym kluczu i notatki nazywają ofertę tak, jak usługa nazywała
  się wtedy, konfigurator bierze ją za usługę tej oferty — nie zakłada drugiej, nie
  proponuje usunięcia, a brakujące jednostki, cenę i sezon planuje dla niej. Oferta
  nazwana w notatkach inaczej jest inną ofertą, jak dotąd.
- **Rodzaj rezerwacji**: pytanie `offer_needs_kind` podaje jako odpowiedzi tylko
  rodzaje gotowe (`readiness: ready`); zapowiedziane trafiają do `soon` — asystent
  nazywa je „wkrótce” i nie proponuje.
- **Dopasowanie po nazwie**: miejsca, osoby i usługi konta poznaje po nazwie bez
  wielkości liter, znaków diakrytycznych i interpunkcji; usługę — gdy nazwa nie
  pasuje — także po pochodzeniu (wyżej).
- **Usługa** powstaje przez `booking.preset.apply@1`, gdy produkt ma to polecenie; do
  tego czasu wizyta na godzinę (`slot`) powstaje przez `booking.offer.create@1`, bez
  zapisanego presetu. Zawsze wyłączona — włącza ją właściciel.
- **Jednostki pobytu i wynajmu** (oferta `range`): liczba z profilu staje się krokiem
  `booking.offer.units.set@1`, gdy oferta ma już identyfikator — do tego czasu krok
  czeka na ofertę (`units:<klucz>` po `offer:<klucz>`). Polecenie dostaje liczbę
  docelową, nie przyrost, i tylko dokłada: pula, która ma tyle albo więcej jednostek,
  zostaje. Pulę o nazwie oferty, do której oferta nie jest jeszcze podpięta (szkic
  usunięty i założony ponownie), konfigurator liczy jako pulę tej oferty. Jednostek
  ułożonych w panelu inaczej — pojedynczo albo w kilku grupach — nie rusza. Oferta
  `range` bez liczby jednostek dostaje pytanie `offer_needs_units`.
- **Pieniędzy się nie zgaduje.** Cena staje się krokiem `booking.price.save@1` (cena
  podstawowa oferty) tylko wtedy, gdy: kwota jest potwierdzona przez właściciela,
  waluta jest walutą firmy, to, za co jest cena, pasuje do oferty (noc albo dzień
  tylko tam, gdzie oferta je liczy; rezerwacja i osoba zawsze) i właściciel podał
  stawkę VAT. Czego brakuje, o to konfigurator pyta: `offer_needs_price` (pobyt albo
  wynajem bez ceny — wizyta ceny mieć nie musi), `price_needs_vat`,
  `price_per_not_offered` (z dozwolonymi odpowiedziami). Kwotę oznaczoną przez model
  jako słowa właściciela serwer przyjmuje tylko wtedy, gdy właściciel napisał tę
  liczbę w rozmowie (`setup.amount_typed`: „450 zł”, „1 200”, „89,50”); inaczej zostaje
  propozycją do potwierdzenia. **Oferta, która ma już jakąkolwiek cenę — własną albo
  swojej grupy jednostek — zostaje nietknięta**: cennik na koncie należy do
  właściciela, notatka go nie nadpisuje.
- **Sezony** (oferta `range`): każdy sezon z notatek staje się krokiem
  `booking.season.save@1` (`season:<klucz>:<pierwszy dzień>`), gdy oferta ma już
  identyfikator — z datami i tylko tymi zasadami, które właściciel nazwał. O sezony
  konfigurator nie pyta: planuje je dopiero, gdy właściciel sam o nich powie. Sezon,
  który oferta albo jej grupa jednostek ma już na te same daty, zostaje nietknięty —
  jak cena. Sezon przy wizycie na godzinę to `seasons_for_stays`.
- **Włączenie oferty** (`person_only`) konfigurator podaje dopiero wtedy, gdy nic z
  oferty nie zostało do ustawienia — także jednostki, cena i sezony.
- **Kategoria katalogu**: propozycja z presetu oferty, a gdy jej nie ma — kategoria,
  której słowo kluczowe pada najwcześniej w opisie działalności, a potem w nazwach
  ofert (zawód pada przed szczegółami: „hydraulik: awarie, instalacje”). Zawsze jako
  pytanie do właściciela.
- **Miasto** musi być w słowniku katalogu (ADR-053 §7); inne trafia do `unsupported`.

## Dowody

- `tests/test_assistant_profile.py`: wersje, konflikt wersji, merge patch, klucz
  idempotencji, podgląd bez zapisu, błędy pól, kto czyta i zmienia, zapis przez
  asystenta z rozmową, osobny profil każdej firmy.
- `tests/test_assistant_configurator.py`: złote odpowiedzi czterech firm na zamrożonych
  katalogach (`tests/assistant_setup/`), kolejne rundy, i **jeden test związany z
  prawdziwym kontraktem** — `test_what_the_product_can_do_today`: rejestr poleceń,
  katalog presetów i słownik katalogu dla nowej firmy. Gdy produkt się zmieni, ten test
  mówi, co poprawić.
- `docs/assistant/co-asystent-zalozy-dzis.md`: raport dla właściciela, pisany przez ten
  test.
- `packages/contracts/tests/assistant-profile-contracts.test.mjs`: schemat i przykłady.
