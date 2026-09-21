# ADR-052: Wizyty gospodarstwa w rejestrze rolnika

Status: proponowana, 2026-09-20. Rozszerza ADR-051 o poziom gospodarstwa;
ADR-051 pozostaje obowiązujący w całym dotychczasowym zakresie.

## Kontekst

Właściciel produktu postawił wymóg: **rolnik ma wiedzieć o terminach przyszłych
i przeszłych wizyt, mieć w nie wgląd oraz w raporty.**

Rolnik to organizacja typu `farm` (ADR-050). W profilu HoofCare dostaje moduły
`shared.billing`, `shared.notifications`, `shared.booking`, `shared.media`
i `shared.farms` — **nie dostaje `vertical.hoofcare`**. Nie zobaczy więc nigdy
`HerdVisit` ani `TrimmingEntry`: to wiersze w tenancie firmy, w module, którego
jego wdrożenie w ogóle nie składa. Wszystko, co ma widzieć, musi istnieć we
wspólnym rejestrze.

Rejestr ma już do tego drogę: `AnimalHealthEntry` publikowany przez
`herd_sync.publish_health_entry` pod udziałem `FarmShare.can_publish_health`
(ADR-051 pkt 8). Brakuje poziomu **gospodarstwa** — wizyty jako całości.

Rozważaliśmy trzy tańsze drogi i każda odpada na tym samym pytaniu:
**skąd rolnik ma wziąć termin wizyty, która jeszcze się nie odbyła.**

- Odwzorować `Appointment` w tenancie rolnika: niewykonalne. Ma cztery klucze
  obce z `PROTECT` (klient, usługa, pracownik, lokalizacja), więc kopia
  wymagałaby fabrykowania atrap całego katalogu firmy.
- Użyć istniejącego `AnimalHealthEntry` ze specjalnym `source`: niewykonalne.
  Wpis wymaga zwierzęcia i daty przeszłej, a w chwili planowania wizyta nie zna
  jeszcze zwierząt. Nie unosi też wizyty, na której nie zapisano żadnego wpisu.
- Dać rolnikowi rolę-gościa w tenancie firmy: łamie ADR-051 i RLS — rolnik
  zobaczyłby wtedy dane innych gospodarstw tej firmy.

## Decyzja

1. **`FarmVisitEntry` w `shared.farms`** — jeden wiersz na wizytę firmy w
   gospodarstwie: `farm`, `source` (np. `hoofcare.visit`), `source_reference`,
   `scheduled_for`, `occurred_on`, `status` (`planned`/`done`/`canceled`),
   `company_organization_id`, `company_name`, `summary`, `details`,
   `published_at`.

2. **Wiersz istnieje wyłącznie w rejestrze rolnika.** W tenancie firmy prawda
   jest o jeden `JOIN` dalej (`HerdVisit` jeden-do-jednego z `Appointment`),
   więc kopia po tamtej stronie byłaby drugim źródłem prawdy z własnym RLS,
   triggerem, ścieżką erasure i dryfem. Jedyny powód istnienia kopii w tej
   architekturze to granica tenanta, a ta dotyczy tylko strony rolnika.
   Panel firmy czyta `HerdVisit` przez slot produktowy karty gospodarstwa.

3. **Klucz unikalności obejmuje firmę:**
   `(organization, farm, company_organization_id, source, source_reference)`.
   Bez niej dwa źródła w jednym gospodarstwie dzielą przestrzeń nazw i jedno
   nadpisuje drugie przez `update_or_create`.
   `company_organization_id` to `UUIDField`, nie klucz obcy — z tego samego
   powodu, dla którego jest nim `AnimalHealthEntry.author_organization_id`:
   klucz obcy do `Organization` wpadłby w `erasure.organization_scoped_models`
   i kasowanie firmy sięgnęłoby wierszy w cudzym tenancie.

4. **Osobna zgoda `can_publish_schedule` na `FarmShare`, domyślnie wyłączona.**
   Nie rozszerzamy znaczenia `can_publish_health`: rolnik zgadzał się na wpisy
   zdrowotne, a termin przyszłej wizyty to informacja, która dziś nie
   przekracza granicy w ogóle. Historia wizyt zakończonych jedzie razem z
   raportem, pod `can_publish_health`.

5. **Publikacja ma dwa momenty, nie jeden:**
   - `plan_visit` i przełożenie terminu → wiersz `planned` ze `scheduled_for`;
   - wysyłka raportu (`_freeze`) → `done`, `occurred_on` i treść do wglądu.
   Publikacja przy samym zakończeniu wizyty nie wystarcza: raport zamraża się
   dopiero przy wysyłce, więc wiersz powstały wcześniej nigdy by się o nim nie
   dowiedział.

6. **Zakres raportu = to, co i tak idzie mailem.** Zamrożony snapshot raportu
   trafia dziś do hodowcy pocztą razem z nazwiskami załogi i notatką. Publikacja
   tego samego snapshotu nie ujawnia więc niczego nowego i wiąże przekazanie z
   czynnością, którą firma wykonuje świadomie. Nie udostępniamy pliku PDF przez
   granicę tenanta.

7. **Wertykał publikuje kształt już rozwiązany**, np.
   `{"sections": [{"title": ..., "rows": [{"label": ..., "value": ...}]}]}`.
   Rdzeń renderuje etykiety i wartości, nie wiedząc nic o HoofCare. Powód jest
   twardy: słownik kodów ICAR mieszka w wertykale, a kontrakt warstw
   (`.importlinter`) stawia `vertical` nad `shared` — `shared.farms` nie ma
   prawa go zaimportować.

8. **Odwołana wizyta zostaje w historii rolnika jako odwołana.** Nie kasujemy
   wiersza — obserwator przestawia go z `planned` na `canceled` i tam zostaje.
   Decyzja właściciela produktu (2026-09-20): odwołanie jest faktem, który
   hodowca ma prawo pamiętać, a nie zdarzeniem do wymazania. Kartoteka wizyt
   jest więc księgą, nie tylko listą tego, co się wydarzyło.

9. **Cofnięcie udziału obsługujemy przy odczycie, nie zapisem korygującym.**
   To inny przypadek niż odwołanie wizyty: po cofnięciu udziału drzwi są
   zamknięte i firma nie przestawi już żadnego statusu, więc wizyta `planned`,
   która nigdy się nie odbędzie, wisiałaby jako przyszła bez końca. Lista ukrywa
   wiersze `planned` firmy bez aktywnego udziału; `done` i `canceled` zostają,
   bo to już historia.

10. **Warunek konieczny: rejestr obserwatorów w `shared.booking`.** Termin żyje w
   `Appointment`, a przełożyć go może także sam rolnik linkiem samoobsługowym.
   Bez obserwatora `scheduled_for` zaczyna kłamać przy pierwszym przełożeniu.
   Rejestr jest pusty, dopóki moduł się nie zapisze — rdzeń nie zna konsumenta.

## Czego ta decyzja nie obejmuje

- **Terminu kontroli zwierzęcia.** HC-ADR-002 pkt 3 mówi, że kontrola jest
  *wyliczana* — zamyka ją późniejszy wpis z innej wizyty. Przechowywana kolumna
  w rejestrze pokazywałaby kontrole zamknięte jako otwarte i rozjeżdżała się z
  licznikiem firmy. Osobny ADR, jeśli w ogóle.
- **Kolumn „ostatnia / następna wizyta" na liście gospodarstw firmy.** To strona
  firmy, czyli slot produktowy; per wiersz byłoby N+1. Decyzja właściciela.
- **Backfillu historii sprzed połączenia.** Rolnik po przejęciu gospodarstwa
  kodem zobaczy historię dopiero od momentu połączenia.
- **Wizyt rozpoczętych z terenu bez rezerwacji w kalendarzu.** Powstają tą samą
  drogą (rezerwacja plus `HerdVisit`), więc publikują się bez wyjątku. Ich
  rezerwacja też emituje utworzenie, więc przechodzą przez krótkotrwały
  `planned`, zanim raport przestawi je na `done` — jeden wiersz, dwa stany.

## Konsekwencje

- Rolnik dostaje wizyty i raporty bez dostępu do tenanta firmy i bez wiedzy
  rdzenia o korekcji racic.
- Rośnie liczba użyć `registry_door` z czterech do pięciu: publikacja wizyty
  przechodzi przez drzwi, odczyt nie — rolnik czyta we własnym tenancie. Drzwi
  bez świadka to ta sama klasa ryzyka co `PRE_TENANT_DB`, więc powstaje
  `tests/test_registry_door.py` liczący użycia per funkcja, nie per plik:
  wszystkie siedzą w jednym module, więc świadek liczący pliki nic by nie
  pilnował.
- Wiersz w rejestrze przeżywa firmę, bo `company_organization_id` nie jest
  kluczem obcym. Przy erasure firmy zostaje jako księga; jeśli ma znikać albo
  być anonimizowany, wymaga to osobnej decyzji — ADR-042 o kopiach
  międzytenantowych milczy.
- Obserwator odpala się po zatwierdzeniu transakcji, więc pad procesu między
  commitem a wywołaniem gubi zdarzenie. Świadomy koszt rejestru zamiast
  outboxu; zdarzenie da się odtworzyć z `booking_appointmentstatushistory`.

## Alternatywy odrzucone

- **Wiersz w obu tenantach.** Odrzucona po krytyce: w tenancie firmy dane już
  są, a kopia bez granicy tenanta to drugie źródło prawdy do utrzymania przy
  każdym przełożeniu, odwołaniu i cofnięciu wpisu.
- **Outbox w `shared.booking`.** Outbox istnieje dziś tylko w `shared.sites`.
  Budowa drugiego kosztuje wielokrotnie więcej niż rejestr obserwatorów, a
  gwarancji at-least-once ten konsument nie potrzebuje.
- **`Appointment.farm` w `shared.booking`.** Profil może złożyć booking bez
  rejestru (Business, MedPlano), więc klucz obcy nie skomponowałby się.

## Relacje

Rozszerza ADR-051 (rejestr, udziały, publikacja wpisów zdrowotnych).
Zależy od ADR-050 (typy organizacji) i ADR-039/ADR-041 (RLS, nazwane drzwi).
Nie zmienia ADR-049: wertykał nadal wiesza szczegóły na `Appointment`.
