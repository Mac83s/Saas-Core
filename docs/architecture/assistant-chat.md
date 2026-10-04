# Rozmowa z asystentem — kontrakt

Wykonywalna połowa [ADR-076](../adr/ADR-076-Asystent-AI-Rejestr-Polecen.md),
uzupełnienie 2026-10-03 (A3-1). Moduł `shared.assistant`; model przez
[port modeli](model-port.md), zadanie `assistant.conversation`.

## Przebieg wiadomości

```text
osoba            panel/API                         worker `ai`                 port modeli
POST turns/  ->  tura queued, kredyt zarezerwowany
                 202                          ->   tura running
                                                   transkrypt + narzędzia  ->  complete()
                                                   <- tekst | wywołania narzędzi
                                                   wywołania = plan (step_id od serwera)
                                                   offer_plan
                                                     odmowa   -> błędy do modelu, dalej
                                                     odczyty  -> wykonane, wyniki do modelu, dalej
                                                     zapis    -> awaiting_consent (digesty grup)
GET rozmowa  <-  tura awaiting_consent, grupy
GET command-consents/{digest}   (dialog rysuje tylko to)
POST command-consents/{digest}  -> token (300 s)
POST turns/{id}/consents/       -> execute_plan w żądaniu osoby, wyniki kroków zapisane
                                                   tura running -> model raportuje z wyników
GET rozmowa  <-  tura done
```

- Tura ma stany `queued → running → (awaiting_consent → running)* → done | failed`.
  Rozmowa ma najwyżej jedną turę w toku (ograniczenie w bazie); druga wiadomość to 409
  `assistant_turn_in_progress`.
- Wywołań modelu na wiadomość jest najwyżej `assistant.limits.model_steps_per_turn`;
  po przekroczeniu tura kończy się `step_limit`.
- Tura bez ruchu przez 180 s (worker padł albo go nie ma) kończy się `timeout`
  (zadanie `assistant-reconcile`, kolejka domyślna). Otwarte wywołania narzędzi
  dostają wtedy wynik, żeby transkrypt dało się pokazać modelowi ponownie.
- Plan czekający na kliknięcie dłużej niż `COMMAND_PENDING_TTL` jest proponowany
  ponownie przy odczycie rozmowy, na stanie z tej chwili.
- **Plan z krokiem nieodwracalnym** (`irreversible`) ma obok siebie zdanie serwera:
  „Zanim się zgodzisz: tego kroku nie da się cofnąć.” i słowa podglądu tego kroku.
  API oddaje je jako pozycję `text` tuż przed krokami planu — gdy plan czeka, po
  kliknięciu i po odmowie. Nie pisze go model i model go nie dostaje.
- **Odpowiedź z polską formą z rodzajem** („zmieniłem”, „żebym pokazał”) wraca do
  modelu raz, z nazwaną formą, zanim trafi do rozmowy; liczy się jako wywołanie
  modelu tej wiadomości. Zapisywana jest tylko odpowiedź, którą osoba czyta.

## Dwa rodzaje rozmowy

`kind` rozmowy wybiera się przy jej założeniu i nie zmienia.

- **`operate`** (domyślna) — wszystko powyżej i poniżej: narzędziami modelu są
  polecenia rejestru — te z obszarów, których rozmowa dotyka („Co widzi model”) —
  wiadomość kosztuje kredyt.
- **`setup`** — rozmowa zakładająca firmę (ADR-076, uzupełnienie A3-2). Model
  dostaje **trzy narzędzia własne asystenta i żadnego polecenia rejestru**
  (`shared/assistant/setup.py`):
  - `profile_note` — notatki do profilu firmy (`assistant-profile.md`): lista
    `{field, value, source: owner | assistant}`. Wykonuje się od razu; nie zmienia
    konta. Słowami właściciela (`origin: owner`, potwierdzone) wartość zostaje
    tylko ze źródłem `owner`, a nazwa firmy, telefon, e-mail i adres — tylko gdy
    właściciel sam je napisał w tej rozmowie; inaczej to propozycja do
    potwierdzenia. Błędne notatki wracają do modelu jako błędy pól.
  - `setup_status` — odczyty konta przez rejestr + konfigurator: kolejne pytania z
    dozwolonymi odpowiedziami, kroki gotowe, kroki czekające z powodem słowami,
    rzeczy nieobsługiwane i to, co już wiadomo (dane kontaktowe tylko jako
    „znane”, bez wartości). Miejsca i osoby, które konto już ma, trafiają
    wcześniej do profilu z pochodzeniem `account`.
  - `setup_apply` — plan konfiguratora idzie do `offer_plan`; tura czeka na
    kliknięcie jak każda (`awaiting_consent`), plan wykonuje żądanie osoby, a
    jedno wywołanie narzędzia dostaje wynik z każdym krokiem osobno.
  Polecenie rejestru nazwane mimo to przez model dostaje odmowę `unknown_tool`.
- Rozmowę `setup` zakłada zarządzający ustawieniami firmy
  (`organization.settings.manage`). Jest **bezpłatna** (decyzja 23 b): tura nie
  rezerwuje kredytu, a liczy się do budżetów `assistant.limits.setup_turns_per_company`
  (150) i `assistant.limits.setup_turns_per_person_per_day` (60). Po wyczerpaniu —
  429 `assistant_setup_budget` / `assistant_setup_daily_budget` ze zdaniem, jak
  dokończyć w panelu; profil zostaje.
- `GET conversations/{id}/setup/` — to samo, co widzi model, dla panelu obok
  rozmowy: dokument profilu z pochodzeniem każdej wartości i cztery listy z tytułami
  w obu językach. Odczyt: niczego nie zapisuje.

## Co widzi model

- Stały prompt (`prompts.py`: `assistant.operate@2`, w rozmowie zakładającej
  `assistant.setup@4`) i język panelu rozmowy.
- Wiadomości osoby z czasem wysłania w nawiasie kwadratowym (UTC).
- Narzędzia zwykłej rozmowy: z `command_tools(context)` — poleceń, do których osoba
  ma uprawnienie i moduł — te z obszarów, których rozmowa dotyka (`topics.select`,
  ADR-076 „słowa serwera, dobór narzędzi i koszt rozmowy” pkt 3):
  - obszar otwierają słowa osoby, najpierw same odczyty; polecenia zmieniające
    dochodzą, gdy osoba prosi o zmianę;
  - `more_tools` (`topics`: lista obszarów, `change`: czy także zmieniające) —
    narzędzie własne asystenta, którym model poszerza zestaw; wynik
    `{"opened", "unknown", "change"}`, nowe narzędzia przy następnym wywołaniu;
  - wybór jest funkcją transkryptu, a kolejność narzędzi — kolejnością dodania;
  - rejestr do 12 poleceń idzie w całości, bez `more_tools`.
  Wykonawca sprawdza wszystko jeszcze raz, cokolwiek model dostał.
- Wynik kroku jako wiadomość `tool`: `{"status": "done", "output": …}` albo
  `{"status": "refused" | "failed" | "skipped" | "declined", "error": {"code", "errors"}}`,
  zwarty JSON; z wyniku polecenia wypadają pola `null`.
  Wynik dłuższy niż 24 000 znaków jest zastępowany błędem `output_too_large`.
- Ostatnia wiadomość transkryptu niesie znacznik cache dostawcy (obok narzędzi i
  promptu): następne wywołanie czyta wcześniejsze wyniki za dziesiątą część ceny.
- Klasa danych żądania to zawsze `personal`.

## Dowody na lokalnym stosie

`ASSISTANT_PROOF_ACCOUNTS=<e-mail>[,<e-mail>]` w środowisku backendu i workera `ai`:
rozmowy tych kont idą do portu modeli z celem `eval` — liczone tylko w sufitach
miesięcznych, w telemetrii obok evali, poza dniem każdej osoby i firmy
(`model-port.md`). Domyślnie puste. Na stosie serwowanym przez https zmienna
zatrzymuje start (`assistant.E001`) i jest pomijana. Kredyty, limity wiadomości i
budżet rozmowy ustawiającej liczą się jak zwykle.

## API (`/api/v1/assistant/`)

| Operacja | Co robi |
| --- | --- |
| `GET offer/` | czy czat przyjmie wiadomość i dlaczego nie (`reasons`), czy jest w planie, koszt wiadomości w kredytach |
| `GET conversations/` | rozmowy zalogowanej osoby w tej firmie |
| `POST conversations/` | nowa rozmowa (`Idempotency-Key`) |
| `GET conversations/{id}/` | tury: wiadomość osoby, teksty asystenta, kroki ze statusem, grupy zgody |
| `POST conversations/{id}/turns/` | wiadomość (`Idempotency-Key`), 202 |
| `POST conversations/{id}/turns/{turn}/consents/` | tokeny zgód albo `declined`, 202 |
| `GET`, `PATCH profile/`, `POST profile/preview/` | profil firmy (A2) — `assistant-profile.md` |
| `GET conversations/{id}/setup/` | stan zakładania firmy dla rozmowy `setup` (A3-2) |

Kody: 503 `assistant_unavailable`, 403 `assistant_not_in_plan`, 403
`assistant_person_only` (klucz API, kontekst „w imieniu”), 429
`assistant_rate_limited`, 409 `assistant_turn_in_progress`, 409
`assistant_consent_not_awaited`, 409 `assistant_idempotency_conflict`, 404
`assistant_conversation_not_found` (cudza rozmowa wygląda tak samo jak brak), 402
`credits_exhausted`, 429 `assistant_setup_budget` i `assistant_setup_daily_budget`
(rozmowa zakładająca).

## Dane

`assistant_assistantconversation`, `assistant_assistantturn`,
`assistant_assistantmessage` — tabele firmy z RLS. Treść rozmowy nie trafia do
logów ani telemetrii portu. Retencja: `assistant.retention.conversation_days`,
wykonywana przez wspólny nocny przebieg prywatności (`assistant/retention.py`,
przemiatanie `assistant.conversations`); usunięcie firmy zabiera rozmowy.

`assistant_assistantprofileversion` — profil firmy i jego wersje (A2), opisany w
`assistant-profile.md`. Profil nie trafia do żadnego wywołania modelu: w A2 nie ma
kodu, który by go wysyłał, a A3-2 wyśle tylko to, czego wymaga pytanie.

## Ustawienia platformy

`assistant.limits.turns_per_person_per_minute` (12),
`assistant.limits.conversation_starts_per_ip_per_hour` (20),
`assistant.limits.model_steps_per_turn` (6),
`assistant.limits.daily_turns_ceiling` (2000),
`assistant.limits.setup_model_steps_per_turn` (10),
`assistant.limits.setup_turns_per_company` (150),
`assistant.limits.setup_turns_per_person_per_day` (60),
`assistant.retention.conversation_days` (90). Budżety w USD: port modeli.

## Dowody

- `tests/test_assistant_chat.py`: odczyt bez kliknięcia; zapis dopiero po kliknięciu;
  plan bez tokenu i plan odrzucony nie wykonują nic; argumenty poza schematem wracają
  do modelu; rozmowę czyta tylko jej osoba; jedna tura naraz; czat zamknięty bez
  workera, modelu albo cechy planu; limity z ustawień platformy; porażka modelu
  zwraca kredyt; osoba usunięta z firmy; sprzątanie i retencja.
- `tests/test_assistant_setup.py` (rozmowa zakładająca, na prawdziwym rejestrze):
  trzy narzędzia i żadne polecenie; słowa właściciela tylko wtedy, gdy je napisał;
  błędne notatki wracają polami; plan konfiguratora czeka na kliknięcie i dopiero
  po nim powstaje miejsce; plan odrzucony nic nie zmienia; bezpłatność i budżet;
  kto może zakładać; to, co konto już ma, trafia do profilu jako fakty.
- `tests/test_assistant_evals.py` i `manage.py assistant_eval [--kind setup]`:
  scenariusze modelu dla obu rodzajów rozmowy.
- `tests/test_assistant_topics.py`: dobór narzędzi — pytanie niesie odczyty swojego
  obszaru, prośba o zmianę także polecenia zmieniające, `more_tools` poszerza, każde
  polecenie jest w zasięgu, polecenie produktu jest obszarem po nazwie.
- `tests/test_assistant_chat.py` (od 04.10): zdanie serwera obok planu z krokiem
  nieodwracalnym, przed kliknięciem i po nim; odpowiedź z formą z rodzajem przepisana
  raz; narzędzia według tematu rozmowy; znacznik cache i wyniki bez `null`; konto
  dowodowe liczone z evalami, a na https — kontrola `assistant.E001`.
- Panel: `apps/frontend/src/modules/shared/assistant/assistant-panel.test.tsx`.
