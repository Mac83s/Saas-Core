# Profil firmy i konfigurator asystenta — kontrakt

Faza A2 planu asystenta (memex `saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy`),
uzupełnienie ADR-076. Bez modelu: profil to zapis tego, co powiedział właściciel, a
konfigurator to czysta funkcja, która z profilu i stanu konta wylicza, o co zapytać i
co wykonać. Rozmowę, która profil wypełnia, dodaje A3-2.

## Profil (`company-profile.v1`)

Schemat: `packages/contracts/assistant/company-profile.v1.schema.json` — pisany z kodu
(`shared/assistant/profile_schema.py`), nie ręcznie; przykłady czterech firm w
`packages/contracts/assistant/examples/`.

- Sekcje: `company` (nazwa, czym się zajmuje, miasto, kategoria, kontakt), `card`
  (zdanie i opis), `languages`, `places`, `people` (z tygodniem pracy), `offers`
  (rodzaj rezerwacji — id presetu, czas, sztuki, pojemność, cena, miejsca, osoby,
  odpowiedzi na `requiredInputs` presetu), `sources`.
- **Każda wartość ma pochodzenie i potwierdzenie**:
  `{"value", "origin": owner | existing_site | preset_default | assistant, "confirmed"}`.
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

Klasa danych: `personal` (słowa właściciela, imiona osób). Profil znika razem z firmą;
wersje starsze od bieżącej podlegają `assistant.retention.conversation_days`. **A2 nie
ma własnego zadania czyszczącego**: tabelę rejestruje hak retencji platformy (plan
ustawień, plaster 2). Gdyby moduł trafił na VPS przed tym hakiem, starsze wersje
dopisujemy do `purge_assistant_conversations`.

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

`configure(profile, reads, commands)` — bez modelu, bez bazy, bez wykonywania poleceń.

- `reads`: wyniki poleceń odczytu, po nazwie polecenia — asystent sięga do innych
  modułów tylko przez rejestr (ADR-076 pkt 9): `organization.read@1`,
  `organization.public_locales.read@1`, `profiles.organization.read@1`,
  `profiles.catalog_options.read@1`, `booking.setup.read@1`, `booking.preset.list@1`.
  Obszar bez swoich odczytów jest pomijany.
- `commands`: nazwy poleceń, którymi wolno planować.

Wynik to cztery listy:

| Lista | Co zawiera |
| --- | --- |
| `missing` | pytania do właściciela, od najważniejszych: `ask` (brakuje wartości) albo `confirm` (jest, ale niepotwierdzona), z `reason`, propozycją i dozwolonymi odpowiedziami |
| `plan` | polecenia gotowe do wykonania: `ref`, `command`, `arguments` |
| `blocked` | kroki, które czekają: `waits` (na wcześniejszy krok — `waits_for`), `command_missing` (produkt nie ma polecenia), `person_only` (krok właściciela, np. włączenie usługi) |
| `unsupported` | czego właściciel chce, a produkt jeszcze nie umie: `preset_not_ready`, `price_list`, `city_not_in_catalog`, `language_not_offered`, `language_limit`, `preset_unknown`, `category_unknown`, `booking_unavailable` |

Zasady:

- **Rundy.** Argumenty planu są ustalone przed wykonaniem, więc krok nie może użyć
  identyfikatora, który powstaje w tym samym planie. Usługa czeka na miejsce i osoby,
  godziny czekają na osobę i miejsce; po wykonaniu rundy ta sama funkcja daje następną.
- **Tylko dokłada.** Miejsce, osoba, język albo wykonawca usługi, których profil nie
  wymienia, zostają. Wyjątek: tydzień pracy osoby to jedna wartość — tydzień z profilu
  zastępuje ten z konta. O miasto i kategorię, które wizytówka już ma, nie pyta.
- **Dopasowanie po nazwie**: miejsca, osoby i usługi konta poznaje po nazwie bez
  wielkości liter, znaków diakrytycznych i interpunkcji.
- **Usługa** powstaje przez `booking.preset.apply@1`, gdy produkt ma to polecenie; do
  tego czasu wizyta na godzinę (`slot`) powstaje przez `booking.offer.create@1`, bez
  zapisanego presetu. Zawsze wyłączona — włącza ją właściciel.
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
