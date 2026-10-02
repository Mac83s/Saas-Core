# Port modeli AI — kontrakt

Wykonywalna połowa [ADR-068](../adr/ADR-068-Port-Modeli-AI.md): co dokładnie wolno
wysłać do `shared.model-port`, co wraca, jakie są rodzaje błędów, jak działa
dopuszczenie i co zapisuje telemetria. Konsumenci: tłumaczenia (ADR-069) i asystent
(ADR-033, ADR-076). Zmiana zgodna wstecz — nowe pole opcjonalne, nowe zadanie, nowy
kod błędu w istniejącym rodzaju — poprawia ten dokument w tym samym commicie co kod;
zmiana łamiąca wymaga nowego ADR.

Jedyna powierzchnia importu: `saas_core.modules.shared.model_port.api`.

## Typy

Szkic kształtu, nie kod. Pola z treścią (`content`, `arguments_json`, `output`,
`text`, `continuation`) mają `repr=False` i nigdy nie trafiają do logów ani wierszy.

```text
Role       = "system" | "user" | "assistant" | "tool"
DataClass  = "public" | "public_personal" | "personal" | "health"
ToolChoice = "auto" | "none" | "required" | NamedTool(name)
Purpose    = "customer" | "platform" | "eval" | "probe"

Message(role, content: str | None = None,
        tool_calls: tuple[ToolCall, ...] = (),      # tylko role="assistant"
        tool_call_id: str | None = None,            # tylko role="tool"
        continuation: Continuation | None = None,   # tylko role="assistant"
        cache: bool = False)                        # wskazówka cache promptu
ToolSpec(name, description, input_schema: dict)     # JSON Schema obiektu
ToolCall(id, name, arguments_json: str,             # dokładny tekst modelu
         arguments: dict | None)                    # tylko gdy parsuje się i spełnia input_schema
JsonSchemaFormat(name, schema: dict)
ModelContext(organization_id: UUID | None, actor_id: UUID | None = None,
             conversation_id: UUID | None = None, purpose: Purpose | None = None)
FieldError(field: str, code: str, message: str)     # format błędów pól z A1a (ADR-076)

ModelRequest(task, messages, prompt_id, prompt_version, context, data_class,
             tools=(), tool_choice=None, parallel_tool_calls=None, cache_tools=False,
             response_format: JsonSchemaFormat | None = None,
             max_tokens=None, timeout_seconds=None,
             model=None,                            # tylko purpose eval/probe
             reference=None, resend_of=None, admission_id=None)

ModelResponse(text, tool_calls, output,             # output: sprawdzony obiekt przy response_format
              finish_reason,                        # "stop" | "length" | "tool_calls"
              usage=Usage(input_tokens, output_tokens, reasoning_tokens, cached_input_tokens),
              cost_usd_micros, cost_source,         # "provider" | "computed"
              adapter, requested_model, resolved_model, resolved_provider,
              provider_request_id, latency_ms, usage_entry_id,
              continuation: Continuation | None)
ModelResponse.as_message() -> Message               # tura asystenta do odesłania, bez zmian

ModelError(kind, code, retry_after=None, until=None,
           errors: tuple[FieldError, ...] = (),
           response: ModelResponse | None = None, usage_entry_id=None)   # str(error) == code
Admission(decision: "granted" | "deferred" | "denied", reason=None, until=None,
          id=None, expires_at=None)
TaskSpec(key, pool, adapter, model, timeout_seconds, max_tokens_rule, defaults,
         capabilities, max_data_class, required_context, resend_unknown, enabled,
         admission_ttl=timedelta(minutes=10), daily_cap_usd=None,
         purposes=None)                             # None: customer and platform
```

`Continuation` to nieprzezroczysty stan dostawcy (np. podpisane bloki rozumowania,
których część modeli wymaga w następnej turze z narzędziami) razem z modelem, z
którego pochodzi. Wołający przechowuje go z turą i odsyła przez `as_message()`.

## Funkcje

```text
complete(request) -> ModelResponse                  # synchronicznie; ModelError przy błędzie
admit(task, estimate_usd_micros, context) -> Admission
release(admission_id) -> None
estimate(task, *, input_characters, max_tokens=None) -> int            # USD micros
task_status(task, context=None) -> TaskStatus       # dostępność z powodem i możliwości modelu zadania
budget_state(task, context) -> BudgetState          # co zostało na każdym poziomie
record_settlement(task, context, *, reference, credits, units, unit) -> None
register_task(spec: TaskSpec) -> None               # AppConfig.ready modułu albo produktu
```

Później, bez zmiany powyższych: `stream(request)` (A3) z tym samym żądaniem,
bramkami, dopuszczeniem i telemetrią; `embed(...)` tylko osobnym ADR.

## Zadania

| Zadanie | Pula | Limit czasu | `max_tokens` | Model musi mieć | Wymagany kontekst | `resend_unknown` |
| --- | --- | --- | --- | --- | --- | --- |
| `translation.text` | `translation` | 150 s | 2,5 × tokeny treści + 1 024, najwyżej 16 384 | wynik według schematu | `organization_id` (albo `purpose` eval) | tak |
| `assistant.conversation` | `assistant` | 18 s | 1 536 | narzędzia, ZDR | `organization_id`, `actor_id`, `conversation_id` | nie |
| `assistant.extract_profile` | `assistant` | 15 s | 1 024 | wynik według schematu, ZDR | `organization_id`, `actor_id` | nie |

Silnik tłumaczeń rejestruje dodatkowo `translation.judge` (pula `translation`, tylko
`purpose` eval, bez firmy) — ADR-069. „Tokeny treści” to szacunek tokenów wiadomości
poza `system`; wołający może zażądać mniej, nigdy więcej. 1 024 w regule to rezerwa na
rozumowanie, które kandydaci prowadzą zawsze; `translation.text` ma domyślny wysiłek
`low`, a TL7 mierzy odsetek ucięć każdego modelu. Wartości asystenta stroi tor
asystenta w A3 — dopiero tam powstaje pętla rozmowy do zmierzenia.

Konfiguracja zadania: domyślne w kodzie, nadpisanie zmienną
`MODEL_PORT_TASK_<ZADANIE>_<POLE>` (np. `MODEL_PORT_TASK_TRANSLATION_TEXT_MODEL`), a od
fazy 1 planu ustawień klucz rejestru `model_port.task.<zadanie>.<pole>` z historią —
ustawiona zmienna daje wtedy ostrzeżenie kontroli systemowej. Pusty model:
`configuration` / `model_not_selected`.

## Reguły żądania

Naruszenie to `ModelError(kind="invalid_request")` bez wywołania:

- wiadomości `system` tylko na początku; wiadomość `tool` odpowiada na `id` z
  `tool_calls` poprzedniej wiadomości `assistant`, a każde wywołanie narzędzia ma
  odpowiedź przed kolejną wiadomością `user` albo `assistant`;
- nazwa narzędzia ma wzorzec `^[a-zA-Z0-9_-]{1,64}$` i jest unikalna; rejestr poleceń
  (ADR-076) mapuje swoje nazwy z wersją na tę postać i z powrotem — port nazw nie
  tłumaczy. `tool_choice` domyślnie `auto`, gdy są narzędzia; bez narzędzi tylko brak
  albo `none`; nazwane narzędzie musi być na liście;
- możliwość spoza macierzy modelu zadania — narzędzia, `tool_choice` `required` albo
  nazwane, `parallel_tool_calls: false`, `response_format` razem z narzędziami, klasa
  `personal` bez ZDR — to `capability_not_supported`. Port nigdy nie emuluje
  wymuszenia ani schematu wymuszonym narzędziem; `task_status` podaje możliwości, więc
  wołający wybiera tryb przed wywołaniem;
- `input_schema` i schemat `response_format` to poprawne JSON Schema obiektu;
  `max_tokens` nie przekracza reguły zadania ani wyjścia modelu, `timeout_seconds` —
  limitu zadania; żądanie po serializacji ma do 2 MiB i mieści się w oknie modelu;
- wiadomość `tool` ma `content` będący napisem; wynik narzędzia z błędem to obiekt JSON
  w `content` (np. `{"error": {"code": …, "message": …}}`), bo `Message` nie ma flagi
  błędu;
- przy aktywnym kontekście „w imieniu” asystenta (`acting_via="assistant"`,
  `acting_ref="conversation:<id>"`) `conversation_id` musi być tą rozmową
  (`context_mismatch`) — jedna rozmowa nie wydaje budżetu innej;
- `prompt_id` (`^[a-z][a-z0-9_.-]{0,79}$`), `prompt_version` (`^[a-z0-9_.-]{1,40}$`)
  i `reference` (`<rodzaj>:<uuid>`, np. `translation_item:<uuid>`,
  `conversation:<uuid>`) mają wzorce, bo trafiają do telemetrii i nie mogą nieść treści;
- pola z wymaganego kontekstu zadania są obowiązkowe (`context_missing`). Przy
  aktywnym `TenantContext` `organization_id` musi się z nim zgadzać, a `actor_id` być
  równy `TenantContext.actor_id` albo pusty w zadaniu bez budżetu osoby
  (`context_mismatch`) — firmy nie wskazuje argument z zewnątrz ani model
  (ADR-033:63-64). W pracy w tle wołający podaje kontekst jawnie.
  `organization_id=None` tylko z `purpose` eval albo probe;
- `model` tylko z `purpose` eval albo probe (`model_override_not_allowed`), i tylko
  model z macierzy;
- `data_class` to najwyższa klasa w całym żądaniu, także w wynikach narzędzi
  (`highest_data_class(...)` z `api.py`); `health` nigdy, a reszta nie przekracza klasy
  zadania ani listy profilu (`data_class_not_sendable`);
- `admission_id` wskazuje rezerwację tego samego zadania, firmy, osoby i rozmowy
  (`admission_mismatch`); `resend_of` — wiersz `unknown_outcome` tego samego zadania i
  modelu, jeszcze nie ponowiony, w zadaniu z `resend_unknown` (`resend_not_allowed`).

Wskazówki cache (`Message.cache`, `cache_tools`) adapter mapuje na znaczniki dostawcy,
gdy macierz modelu ma cache promptu, inaczej je pomija; nigdy nie są błędem.
`continuation` z innego modelu niż model tego wywołania (porównanie z modelem zadania i
jego datowanymi wariantami z macierzy) port pomija i liczy w telemetrii
(`continuations_dropped`) — zmiana modelu w ustawieniach w trakcie rozmowy jej nie zabija.
Zwracaną `continuation` port oznacza modelem zadania, nie datowaną nazwą z odpowiedzi
dostawcy, więc następna tura tego samego modelu zawsze ją dostaje. Rozmowa z `continuation` jest tylko dopisywana: odrzucenie przez
dostawcę zmienionej historii to `invalid_request`.

## Odpowiedź

- `finish_reason == "tool_calls"`: `output` pusty, każde wywołanie niesie
  `arguments_json` i `arguments`. Gdy któreś się nie parsuje, nie spełnia
  `input_schema` albo wskazuje narzędzie, którego nie oferowano, wynikiem jest
  `tool_args_invalid`: `error.response.as_message()` odtwarza turę `assistant` ze
  wszystkimi wywołaniami w oryginalnej postaci, a `error.errors` to lista w formacie
  A1a z `field = tool_calls.<tool_call_id>.arguments.<ścieżka>` (kropki, indeksy
  liczbowe) i komunikatem ogólnym dla kodu, bez wartości argumentów. Wołający odsyła
  tę turę i odpowiada wiadomością `tool` na każde wywołanie.
- Puste albo powtórzone `id` wywołań narzędzi to `invalid_output` /
  `tool_call_id_invalid`.
- Tryb ścisły (`strict` narzędzi i `json_schema`) dostaje kopię schematu bez ograniczeń,
  których nie przyjmuje (`minLength`, `maxLength`, `pattern`, `format`, granice liczb,
  `multipleOf`, ograniczenia tablic i obiektów); schemat z referencjami idzie bez trybu
  ścisłego. Pełny schemat i tak sprawdza walidacja portu.
- Z `response_format`: `output` to sparsowany i sprawdzony obiekt. Ucięcie (`length`)
  bez schematu zwraca tekst z `finish_reason: "length"`; ze schematem albo w
  argumentach narzędzia to `invalid_output` / `output_truncated`.
- `output_tokens` obejmują rozumowanie, `reasoning_tokens` to jego część; treści
  rozumowania port nie zwraca.

## Błędy

| Rodzaj | Kiedy | Port | Wołający |
| --- | --- | --- | --- |
| `refused` | 403 moderacji; 200 z `content_filter`, z odmową modelu albo z pustą odpowiedzią bez `length` | nie ponawia, nie blokuje dostawcy; zapisuje koszt, jeśli był | tłumaczenia: przegląd bez opłaty; asystent mówi to wprost |
| `retryable` | 429; 503 inne niż brak dostawcy; 5xx z `Retry-After` poza 502 i 504; błąd połączenia przed wysłaniem; zajęte miejsce WWW (`web_capacity`, 2 s) | `retry_after` z nagłówka albo backoffu | ponawia po `retry_after` |
| `unknown_outcome` | 408, 502, 504; inne 5xx bez `Retry-After`; 200 z `finish_reason: error`; termin minął albo połączenie zerwało się po wysłaniu | koszt pusty, do sufitów liczy się szacunek | najwyżej raz przez `resend_of`, gdy zadanie ma `resend_unknown` |
| `account_limit` | 402 | blokuje adapter na godzinę dla wszystkich zadań; alarm | czeka do `until` |
| `configuration` | 503 brak dostawcy (para zadanie–model na 15 min, trzeci raz w dobie — do decyzji operatora); 401 (adapter na godzinę); 404; pusty klucz; `key_not_mounted`; `model_not_selected`, `model_not_allowed`, `model_lacks_capability`, `adapter_unknown`, `processor_not_listed`, `task_disabled`, `resolved_model_mismatch` | alarm; bez wywołania, gdy przyczyną jest nasza konfiguracja | zadanie niedostępne do `until` albo zmiany konfiguracji |
| `invalid_request` | 400, 413 i inne 4xx; reguły żądania wyżej | bez wywołania, poza błędami dostawcy | błąd programu albo pozycja pominięta wcześniej |
| `invalid_output` | odpowiedź niezgodna ze schematem, ucięta przy schemacie albo w argumentach narzędzia, nieczytelna | zapisuje koszt; dołącza częściową odpowiedź | tłumaczenia jak odmowa; asystent decyduje sam |
| `tool_args_invalid` | argumenty nie są obiektem JSON albo nie spełniają `input_schema`; narzędzie spoza listy | zapisuje koszt; `response` i `errors` jak wyżej | odsyła turę i wiadomości `tool` z błędem |
| `budget` | dopuszczenie odroczone albo odmówione | bez wywołania | czeka do `until` albo kończy |

Wyjątek adaptera spoza `ModelError` zamyka wiersz jako `unknown_outcome` /
`adapter_exception` i idzie dalej do wołającego. `length` rozstrzyga przed pustą
odpowiedzią (pusta z `length` to ucięcie). Blokady
działają jak bramka: kolejne wywołania kończą się od razu tym samym rodzajem z
`until`, bez sieci; zdejmuje je `model_port_status --unblock <zadanie> --operator
<e-mail> --reason "…"`. Odpowiedź 200 z obiektem `error` mapujemy według jego kodu jak
status HTTP. Do telemetrii trafia tylko kod (`^[a-z0-9_.:-]{1,80}$`), nigdy komunikat
dostawcy.

## Dopuszczenie i budżety

`admit` zwraca `granted` (rezerwacja z `expires_at` = `admission_ttl` zadania),
`deferred` (`until`, powód) albo `denied` (powód). `complete` bez `admission_id`
dopuszcza sam, z szacunku: wejście 1 token na 2 znaki (z narzędziami i schematem; TL7
kalibruje to na telemetrii), wyjście pełne `max_tokens`, ceny z macierzy. Z
`admission_id` sprawdza zgodność i tylko nadwyżkę; rezerwacja zużyta, wygasła albo
zwolniona to pełne dopuszczenie od nowa, które może skończyć się `budget`. Konsument w
tle dopuszcza pozycję w workerze po przejęciu dzierżawy, nie przed wysłaniem do
kolejki.

Dopuszczenie to krótka transakcja na aliasie portu pod `pg_advisory_xact_lock`: sumy,
sprawdzenie, wiersz rezerwacji. Sumy obejmują stany `admitted`, `calling` i `done`,
każdy kosztem albo — gdy nieznany — szacunkiem (`COALESCE(cost_usd_micros,
estimate_usd_micros)`); `expired` się nie liczy. Doba i miesiąc w UTC.

Kolejność, pierwsze niespełnione rozstrzyga: bramki (zadanie włączone, adapter
skonfigurowany i niezablokowany, para zadanie–model niezablokowana, flaga podmiotu
przetwarzającego; blokada daje `deferred` do jej końca, reszta `denied`) → szacunek
mieści się w każdym sztywnym sufice w ogóle (inaczej `denied` /
`estimate_exceeds_ceiling`) → platforma → pula w miesiącu, z rezerwą → pula w dobie →
zadanie w dobie → firma → rozmowa → osoba. `eval` i `probe` przechodzą tylko platformę
i pulę w miesiącu.

| Poziom | Pula `translation` | Pula `assistant` | Po przekroczeniu |
| --- | --- | --- | --- |
| Platforma, miesiąc | USD 80 razem z drugą pulą | (ten sam sufit) | `deferred` do 1. dnia następnego miesiąca |
| Pula, miesiąc | USD 55 | bez sufitu; rezerwa USD 25, której inne pule nie zajmą | `deferred` do następnego miesiąca |
| Pula, doba | USD 6 | USD 4 | `deferred` do następnej doby |
| Firma | 25% dziennej puli, gdy czeka inna firma w granicach swojego udziału | USD 2 na dobę | udział: `deferred` o 5 min; budżet: do następnej doby |
| Rozmowa | — | USD 1,50 | `denied` (`conversation_budget`) |
| Osoba, doba | — | USD 1,50 | `deferred` do następnej doby |

Wartości są domyślne w kodzie, nadpisywane zmiennymi `MODEL_PORT_BUDGET_*`, potem
rejestrem ustawień. Rezerwa: dopuszczenie w innej puli nie może zostawić do sufitu
platformy mniej niż niewykorzystana część rezerwy asystenta w tym miesiącu. „Czeka inna
firma” znaczy: o tę pulę w ostatnich 5 minutach pytała firma, która swojego udziału
nie wykorzystała (znacznik w cache; jego utrata osłabia tylko sprawiedliwość, sufity
liczy baza). Kontrola systemowa odrzuca sufit platformy ponad 80% limitu klucza
(`model_port.key.month_limit_usd`, domyślnie 100), sufit puli ponad sufit platformy,
dobowy ponad miesięczny i rezerwy ponad sufit platformy.

## Wywołania z żądania WWW

Port ustawia znacznik „obsługa żądania HTTP” w swoim middleware (deklarowanym w
deskryptorze modułu). Tylko takie wywołania mają: limiter
`MODEL_PORT_WEB_CALLS_PER_PROCESS` (domyślnie 1 na proces; zajęte miejsce to od razu
`retryable` / `web_capacity`) i limit czasu `min(limit zadania,
GUNICORN_GRACEFUL_TIMEOUT − 2 s)`. CMD obrazu czyta tę samą zmienną
(`--graceful-timeout=${GUNICORN_GRACEFUL_TIMEOUT:-20}`). Worker i komendy działają bez
limitera, z limitem czasu zadania. Wołający w żądaniu nie bierze blokad wierszy przed
wywołaniem.

## Telemetria

Tabela `model_port_usageentry`, wiersz na wywołanie (`kind = call`) albo na
rozliczenie konsumenta (`kind = settlement`, nie liczy się do sufitów): `id`
(UUIDv7), `kind`, `state` (`admitted` → `calling` → `done` albo `expired`), `task`,
`pool`, `adapter`, `requested_model`, `resolved_model`, `resolved_provider`,
`organization_id` (UUID bez klucza obcego), `actor_id`, `conversation_id`, `purpose`,
`prompt_id`, `prompt_version`, `data_class`, `reference`, `resend_of`, `outcome` (`ok`
albo rodzaj błędu), `error_code`, `finish_reason`, `input_tokens`, `output_tokens`,
`reasoning_tokens`, `cached_input_tokens`, `continuations_dropped`,
`estimate_usd_micros`, `cost_usd_micros` i `cost_source` (oba puste przy koszcie
nieznanym), `latency_ms`, `provider_request_id`, `credits`, `units`, `unit` (tylko
rozliczenia), `created_at`, `expires_at`, `finished_at`. Indeksy: (`pool`,
`created_at`), (`organization_id`, `created_at`), (`actor_id`, `created_at`),
`conversation_id`, `reference`, częściowy po stanach otwartych, unikalny częściowy na
`resend_of`.

- Pisze i czyta ją wyłącznie alias `model_port` (ta sama baza i rola aplikacji), na
  który router kieruje modele aplikacji portu; migracje biegną tylko na `default`.
- Przejścia stanu to warunkowe `filter(id=…, state=…).update(…)`, nigdy `save()`: zero
  zmienionych wierszy znaczy, że wiersz zniknął z firmą, i port niczego nie odtwarza.
  Sprzątanie co 60 s wygasza stare rezerwacje i zamienia `calling` starsze niż limit
  zadania + 60 s w `unknown_outcome`.
- Usuwanie: `register_erasure_rows("shared.model-port.usage", …, "organization_id")`;
  `actor_id` po usunięciu konta wskazuje tombstone (ADR-036 §8); wiersze starsze niż 13
  miesięcy usuwa zadanie dobowe.
- Deklaracja w `platformTables` zostaje, a test
  `test_platform_tables_are_declared_tenant_tables_without_policies` przyjmuje tabelę,
  której model jest w `registered_erasure_rows()` z kolumną `organization_id`, i
  wymaga braku RLS (polityka po `app.organization_id` wyzerowałaby sumy sufitów).
- Odczyt: funkcje portu oraz operator — `GET /api/v1/model-port/platform/status/`
  (adaptery, blokady, zadania, zużycie wobec sufitów, limit i zużycie klucza z
  OpenRoutera) i `GET /api/v1/model-port/platform/usage/?from&to&group_by=task|model|organization|day`
  (koszt znany i szacowany osobno, tokeny, wyniki, kredyty z rozliczeń), z
  `operation_id`, opisem i ProblemDetails; komenda `model_port_status`. Żaden endpoint
  firmy nie czyta tej tabeli.
- Metryki bez etykiety firmy: `saas_core_model_port_calls_total{task,adapter,outcome}`,
  `saas_core_model_port_cost_usd_micros_total{task,adapter}` (tylko koszt `provider` i
  `computed`), `saas_core_model_port_estimated_usd_micros_total{task,adapter}`,
  histogram czasu per zadanie. Alarmy w `infra/observability/prometheus/rules.yml`:
  `SaasCoreModelPortAccountLimit` i `SaasCoreModelPortUnavailable`
  (`increase(saas_core_model_port_calls_total{outcome="…"}[10m]) > 0`).

## Konfiguracja

| Nazwa | Znaczenie | Domyślnie |
| --- | --- | --- |
| `MODEL_PORT_OPENROUTER_API_KEY_FILE` | sekret, jeden klucz na wdrożenie; tylko `backend` i `worker-ai` | pusty = nieskonfigurowany |
| `MODEL_PORT_OPENROUTER_BASE_URL` | adres API | `https://openrouter.ai/api/v1` |
| `MODEL_PORT_PROCESSOR_LISTED` | OpenRouter w polityce prywatności i umowie powierzenia; na VPS tylko przez `memex ops` | `false` |
| `MODEL_PORT_TASK_<ZADANIE>_<POLE>` | nadpisanie pola zadania | wartości z kodu |
| `MODEL_PORT_BUDGET_*` | nadpisanie sufitów i budżetów | tabela wyżej |
| `MODEL_PORT_WEB_CALLS_PER_PROCESS` | limiter wywołań z żądań HTTP | 1 |
| `GUNICORN_GRACEFUL_TIMEOUT` | łagodne zamknięcie gunicorna i górny limit wywołania WWW + 2 s | 20 |
| profil: `ai.sendableDataClasses` | klasy treści, które wolno wysłać | `["public", "public_personal"]` |

Od fazy 1 planu ustawień wartości bez sekretów przechodzą do rejestru ustawień z
historią (wpisem `memex ops` z `platform_setting`).

## Atrapa

Klucz `fake`, tylko przy `APP_ENV` `test` i `local`; gdzie indziej zadanie ustawione
na nią daje `configuration` / `adapter_unknown`. Skrypt to lista kroków: odpowiedź
(tekst, wywołania narzędzi z `arguments_json`, wynik strukturalny, `finish_reason`,
tokeny, koszt, rozwiązany model i dostawca, czas, `continuation`) albo błąd (rodzaj,
kod, status HTTP, `retry_after`). Wywołanie spoza skryptu oblewa test; otrzymane
żądania są dostępne do asercji. Testy adaptera OpenRouter podstawiają transport.

## Dowody

- Atrapa transportu: kształt żądania zgodny z macierzą (bez parametrów zakazanych,
  `provider` z `deny`, `require_parameters` i ZDR, `transforms: []`, `user` jako HMAC,
  narzędzia ze `strict`, znaczniki cache tylko przy modelu z cache), każde mapowanie z
  tabeli błędów, także statusy spoza niej i `length` przed pustą odpowiedzią; brak
  przekierowań; termin całkowity przy odpowiedzi sączonej porcjami; limity rozmiaru;
  brak treści w wyjątkach i logach.
- Atrapa adaptera: każda reguła żądania; `tool_args_invalid` z `as_message()` oddającym
  `arguments_json` bez zmian i `errors` w formacie A1a; `continuation` innego modelu
  pominięta i policzona; odmowy; zalew `translation.text` staje na suficie, a zadanie
  asystenta działa dalej; udział odracza firmę tylko przy konkurencji; rezerwa chroni
  asystenta; evale nie zużywają doby puli; `resend_of` przechodzi raz; limiter WWW
  działa w żądaniu, a nie w workerze; wiersz bez znaczników treści; usunięcie firmy
  zabiera wiersze, a wywołanie zakończone po nim ich nie odtwarza.
- Działający stos: wiersz telemetrii przeżywa wycofanie transakcji żądania; przy
  trwającym wywołaniu z żądania panel odpowiada z drugiego wątku procesu; przy
  `MODEL_PORT_PROCESSOR_LISTED=false` zadanie obszaru platformy przechodzi, a zadanie
  firmy klienta dostaje `processor_not_listed`.
- Próba na żywo każdego kandydata (Claude Opus 5.5, Claude Sonnet 5.5, Claude Haiku
  4.5, jeden model klasy Gemini Flash) z raportem w `docs/evals/model-port/`: parametry
  OpenRoutera, tryby `tool_choice`, schemat z narzędziami, brak emulacji, cache
  promptu, odsyłanie stanu rozumowania, kształt odmów i to, czy 503 odróżnia brak
  dostawcy od jego awarii.
