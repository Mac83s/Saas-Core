# ADR-068 — port modeli AI: jeden moduł `shared.model-port` dla tłumaczeń i asystenta

**Status:** Accepted — decyzja właściciela 16a z 2026-10-02 (port buduje sesja
tłumaczeń, raz dla wszystkich konsumentów) i odpowiedź 7 z tego samego dnia (klucz
OpenRouter na wdrożenie, sufity); interfejs zrecenzowany 2026-10-02 przez sesję
asystenta pod kątem A1b. Decyzja memex `the-provider-neutral-model-port-is-one-separate-`,
plan memex `saas-core-wielojezycznosc-i-tlumaczenia-ai`, fazy TL0 i TL3.
**Data:** 2026-10-02

**Zmienia ADR-033:30-39:** port modeli to osobny moduł `shared.model-port`, a
„capability” to zadanie w jego rejestrze; mowa (realtime audio z 33-35, „głos” z 37)
dostaje osobny port. ADR-033:27-29 obowiązuje — `shared.assistant` powstaje i woła
port przez jego `api.py`. **Rozszerza ADR-041:55-58** (walidacja `platformTables`):
tabelą platformową bywa też tabela pisana w trakcie pracy firmy, wskazująca ją gołym
`organization_id`. **Zawęża ADR-046:20-21** w odczycie ADR-059:21-23 (nieznany wynik
płatnego wywołania nie uruchamia kolejnego): zadanie o wynikach rozdzielnych może
wysłać taki wynik ponownie najwyżej raz, tym samym modelem. **Dopisuje do ADR-049 §5**
punkt rozszerzenia `register_task`. ADR-059 zostaje bez zmian. Wykonywalny kontrakt
interfejsu: [`docs/architecture/model-port.md`](../architecture/model-port.md).

## Kontekst

ADR-033:30-39 zapowiedział provider-neutralny port modeli z rejestrem adapterów,
modelem per capability i pomiarem kosztu oraz czasu, jako część runtime'u asystenta.
Nie powstał: w `shared/` nie ma ani asystenta, ani portu. Są dwa adaptery
jednocelowe, każdy z własnym kluczem i bez wspólnego licznika — obrazy (ADR-059,
OpenAI Image API na stdlib bez przekierowań,
`shared/image_generation/provider.py:159-205`) i osadzenia katalogu (ADR-064,
OpenRouter `/embeddings` przez `urlopen`, który podąża za przekierowaniami,
`shared/profiles/embeddings.py:64`, z kluczem `CATALOG_EMBEDDING_API_KEY`,
`config/settings/base.py:858`).

Właściciel 2026-10-02: tłumaczenie treści przez AI to funkcja rdzenia na OpenRouter,
budowana najpierw; port powstaje raz i buduje go sesja tłumaczeń (16a); każde
wdrożenie ma własny klucz OpenRouter z limitem USD 100 miesięcznie, a nasze sufity
leżą niżej — USD 80 miesięcznie, tłumaczenia do USD 55 i do USD 6 dziennie, asystent
co najmniej USD 25, jedna firma do 25% dziennej puli tłumaczeń, gdy czekają inne.

Sesja asystenta przekazała wymagania A1b: rozmowa wieloturowa z rolami `system`,
`user`, `assistant` i `tool`; narzędzia z JSON Schema i `tool_choice`, z osobnym
błędem złych argumentów; wynik według schematu także razem z narzędziami; budżety
platforma → zadanie → firma → rozmowa → osoba; koszt i faktycznie użyty model w
wyniku; wywołanie synchroniczne z żądania WWW z krótkim limitem czasu; rejestr zadań
z `assistant.conversation` i `assistant.extract_profile`; klucz adaptera osobno od
modelu; atrapa ze skryptem; `data_collection: deny`, zero retencji, `user` jako HMAC
i żadnej treści w logach — rozmowy niosą dane osobowe, a MedPlano nie wysyła danych
klinicznych (ADR-033:125-130).

Kod narzuca trzy rzeczy. Kompozycja odrzuca cykle i zależność w górę warstw
(`config/composition.py:296-310`), więc port w module asystenta albo tłumaczeń
uzależniłby jednego konsumenta od drugiego. Każde żądanie API z tenantem biegnie w
jednej transakcji middleware'u (`core/organizations/middleware.py:46-53`), a backend
ma cztery wątki na kontener i 20 s na łagodne zamknięcie (`apps/backend/Dockerfile:88`).
ADR-046:20-21 w odczycie ADR-059:21-23 zabrania ponownego wysłania płatnego wywołania
o nieznanym wyniku, a tłumaczenia obciążają klienta tylko za dostarczone jednostki.

## Decyzja

1. **Osobny moduł `shared.model-port`.** Warstwa `shared`, aplikacja
   `saas_core.modules.shared.model_port`, zależna tylko od `core.identity` i
   `core.organizations`; jedyną powierzchnią importu jest `model_port/api.py`, a
   kontrakt `.importlinter` zabrania mu importu innych modułów `shared`. Konsumenci
   (tłumaczenia, asystent) zależą od niego, nigdy odwrotnie. Składają go profile
   `business`, `agro`, `vps-dev` i produkty; `core-only` bez zmian. Jeden klucz
   OpenRouter na wdrożenie (`MODEL_PORT_OPENROUTER_API_KEY_FILE`, wzór klucza obrazów),
   montowany tylko w `backend` i `worker-ai`. Pusty klucz to „nieskonfigurowany”:
   zadania są niedostępne, reszta działa; sprawdzenie klucza w procesie bez montażu to
   błąd programu (`key_not_mounted`), nie stan.

2. **Rejestr zadań.** Zadanie to nazwany sposób użycia modelu; wołający podaje jego
   klucz, a pula, adapter, model, limit czasu, reguła `max_tokens`, parametry,
   wymagane możliwości modelu, najwyższa klasa danych, wymagany kontekst, ważność
   rezerwacji i wyłącznik są w jednym miejscu. Od początku: `translation.text` (pula
   `translation`, 150 s, `max_tokens` 2,5 × tokeny treści + 1 024, najwyżej 16 384),
   `assistant.conversation` (pula `assistant`, 18 s, 1 536, narzędzia i ZDR) i
   `assistant.extract_profile` (pula `assistant`, 15 s, 1 024, schemat i ZDR); wartości
   asystenta to punkt startowy, który tor asystenta stroi w A3. Modelu domyślnego nie
   ma: dla tłumaczeń wybiera go właściciel po evalach (TL7), dla asystenta — tor
   asystenta; bez modelu zadanie zwraca `model_not_selected`. Wartości: domyślne w
   kodzie, nadpisywane zmienną `MODEL_PORT_TASK_<ZADANIE>_<POLE>`, a od fazy 1 planu
   ustawień — rejestrem ustawień z historią. Moduły rdzenia i produkty dokładają
   zadania przez `register_task` w `AppConfig.ready` (nowy punkt rozszerzenia z
   ADR-049 §5, jak `register_place_search` z ADR-066); nowa pula to zmiana rdzenia.

3. **Adapter to transport, model to ustawienie; macierz potwierdzona próbą.** Zadanie
   wskazuje parę (klucz adaptera, model w przestrzeni nazw adaptera), np. `openrouter`
   + `<dostawca>/<model>`; bezpośredni adapter dostawcy dojdzie jako nowy klucz bez
   zmiany typów. Macierz modelu w kodzie mówi, co model umie (narzędzia, tryby
   `tool_choice`, ścisłe narzędzia i schemat, schemat razem z narzędziami, wysiłek
   rozumowania, `temperature`, endpointy z zerową retencją, cache promptu, odsyłanie
   stanu rozumowania, okno i największe wyjście), czego nie wolno wysłać i ile kosztuje.
   Model da się wybrać dla zadania tylko po udanej próbie na żywo
   (`model_port_probe … --max-usd`, raport w `docs/evals/model-port/`) i z wymaganymi
   możliwościami; macierz zmienia człowiek commitem. Jawny model w żądaniu wolno podać
   tylko przy `purpose` `eval` albo `probe` (kandydaci i sędzia evali). Mowa ma własny
   port (decyzja A4 planu asystenta).

4. **Adapter OpenRouter.** Stdlib HTTP bez przekierowań i bez SDK, z całkowitym
   terminem wywołania (nie na pojedynczą operację gniazda, jak we wzorcu obrazów),
   limitem rozmiaru odpowiedzi i walidacją adresu bazowego. `POST /chat/completions`
   z dokładnie tym modelem — bez `models`, bez `openrouter/auto`, z `transforms: []`,
   więc OpenRouter nie podmienia modelu ani nie skraca rozmowy; zapasowy host tego
   samego modelu jest dozwolony, inny model nigdy (ADR-033:152-155). `provider`:
   `data_collection: "deny"`, `require_parameters: true`, `zdr: true` tam, gdzie model
   ma takie endpointy, i zawsze dla klasy `personal`; `usage: {include: true}`; `user`
   = `salted_hmac` identyfikatora firmy z `SECRET_KEY`. Wynik według schematu idzie
   jako ścisły `json_schema`, gdy model i schemat na to pozwalają, inaczej jako tryb
   JSON ze schematem w instrukcji — wybór przed wywołaniem, nigdy drugie płatne
   wywołanie — i zawsze przechodzi naszą walidację. Narzędzia w formacie zgodnym z
   OpenAI, ze `strict`, gdy model to umie. Wskazówki cache promptu (instrukcja
   systemowa, lista narzędzi) adapter mapuje na znaczniki dostawcy, gdy macierz ma
   cache, inaczej je pomija — wskazówka nigdy nie psuje wywołania. Rozwiązany model
   musi być tym, o który prosiliśmy (albo jego datowanym wariantem z macierzy).

5. **Jedno wywołanie synchroniczne, bez Celery.** `complete(request)` to zwykła
   funkcja: działa w widoku, zadaniu Celery i komendzie, niczego nie kolejkuje. W
   żądaniu WWW biegnie w transakcji middleware'u, więc wołający pyta model przed
   blokadami wierszy, a własne zapisy portu idą osobnym połączeniem (pkt 8). **Tylko
   wywołania z obsługi żądania HTTP** (port wie to z kontekstu ustawianego przez swój
   middleware) mają limiter: najwyżej jedno takie wywołanie naraz w procesie
   (`MODEL_PORT_WEB_CALLS_PER_PROCESS`, domyślnie 1 — drugi wątek procesu zostaje dla
   panelu, ADR-033:140-141; zajęte miejsce to od razu `retryable`, nigdy czekanie) i
   limit czasu przycięty do `GUNICORN_GRACEFUL_TIMEOUT` − 2 s, żeby restart nie uciął
   opłaconego wywołania; CMD obrazu czyta tę samą zmienną. Worker wołający zadanie
   asystenta limitera nie ma. Strumieniowanie to później osobna metoda `stream` z
   tym samym żądaniem, bramkami i telemetrią; A3-1 jej nie potrzebuje, bo tura biegnie
   w workerze, a panel odpytuje rozmowę (ADR-076, uzupełnienie 2026-10-03).

6. **Port sam nie ponawia.** Zwraca rodzaj błędu z `retry_after` albo `until`, a o
   ponowieniu decyduje wołający — ukryte ponowienia płacą podwójnie i psują limity
   czasu. Wynik nieznany (`unknown_outcome`) wolno wysłać ponownie tylko przez
   `resend_of`, najwyżej raz (unikalny indeks), tym samym modelem i tylko w zadaniu z
   flagą `resend_unknown`, którą ma zadanie o wynikach rozdzielnych, płatnych za
   dostarczone — dziś wyłącznie `translation.text`. Innego modelu port nie uruchamia
   nigdy. Odmowa modelu (moderacja, `content_filter`, odmowa albo pusta odpowiedź) nie
   blokuje dostawcy wszystkim, inaczej niż 403 w adapterze obrazów; 402 blokuje adapter
   na godzinę, a 503 „brak dostawcy spełniającego wymagania” — parę zadanie–model na
   15 minut, bo bywa chwilową awarią jedynego hosta spełniającego `deny` i ZDR.

7. **Dopuszczenie przed każdym wywołaniem, w hierarchii sufitów.** Platforma w
   miesiącu → pula w miesiącu (z rezerwą asystenta) → pula w dobie → opcjonalnie
   zadanie w dobie → firma → rozmowa → osoba w dobie; doba i miesiąc w UTC. Wartości
   startowe: platforma USD 80 (80% limitu klucza); pula `translation` USD 55 miesięcznie
   i USD 6 dziennie, firma do 25% dziennej puli, gdy w ostatnich 5 minutach pytała
   inna firma w granicach swojego udziału; pula `assistant` bez własnego sufitu
   miesięcznego, ale z rezerwą USD 25, której inne pule nie zajmą, USD 4 dziennie,
   firma USD 2 dziennie, rozmowa USD 1,50, osoba USD 1,50 dziennie (propozycja toru
   asystenta z 02.10, do strojenia na telemetrii). Rezerwacja to krótka transakcja na
   połączeniu portu pod blokadą doradczą, więc dwa procesy nie wezmą ostatniego dolara;
   nieznany koszt liczy się szacunkiem. Przekroczenie to opóźnienie z godziną
   (`deferred`), a przy rozmowie — odmowa; kontrola systemowa odrzuca sufit platformy
   ponad 80% limitu klucza. Wywołania evali i próby przechodzą tylko sufity
   miesięczne (komendy mają własne `--max-usd`). Port liczy dolary; kredyty klienta
   zostają u konsumentów (ADR-045, ADR-069).

8. **Telemetria operatora bez treści, w jednej tabeli.** Każde wywołanie to wiersz
   `model_port_usageentry`: identyfikatory, liczby tokenów, szacunek i koszt w USD,
   czas, wynik, rozwiązany model i dostawca, `prompt_id` i wersja — nigdy treść,
   argumenty i wyniki narzędzi, stan rozumowania ani komunikat dostawcy (błąd
   moderacji niesie fragment wejścia). Wiersz pisze osobny alias bazy z tą samą rolą
   aplikacji, na który router kieruje modele portu: rezerwacja jest od razu widoczna
   dla innych procesów, a wiersz przeżywa wycofanie transakcji żądania. Organizację
   wskazuje gołe `organization_id` bez klucza obcego — klucz brałby `FOR KEY SHARE` na
   wierszu organizacji, który żądania trzymają `FOR UPDATE`, i port czekałby na
   wołającego, a wołający na port, czego PostgreSQL nie wykryje. Wiersze znikają z
   firmą przez `register_erasure_rows`, starsze niż 13 miesięcy usuwa zadanie dobowe.
   Czyta je tylko port i operator (`/api/v1/model-port/platform/status/` i `usage/`,
   do fazy 1 planu ustawień za tą samą bramką co `MfaAdminSite.has_permission`,
   `core/identity/admin_site.py:30-38`); metryki są bez etykiety firmy, a reguły
   alarmu obejmują limit konta i niedostępność zadania.

9. **Klasy danych i prywatność.** Żądanie deklaruje najwyższą klasę treści: `public`,
   `public_personal` (tekst publiczny nazywający osoby — opinie, bio), `personal`
   (dane osobowe niepubliczne — rozmowa, klienci firmy) albo `health` (nigdy). Profil
   wdrożenia dostaje klucz `ai.sendableDataClasses` (domyślnie `public` i
   `public_personal`); `personal` wychodzi wyłącznie do endpointów z zerową retencją.
   Asystent nie umie sklasyfikować tekstu wpisanego przez osobę, więc deklaruje
   wiadomości użytkownika jako `personal`: `assistant.conversation` zawsze wymaga ZDR,
   a profile Business i HoofCare muszą dopuścić `personal` przed A3; MedPlano zostaje
   przy `public` do oceny DPIA. Treść firmy wychodzi dopiero, gdy operator potwierdzi
   flagą `model_port.processor_listed`, że OpenRouter jest w polityce prywatności i
   umowie powierzenia; zwolnione są obszar platformy i evale (treść operatora). Do
   fazy 1 planu ustawień flaga to zmienna środowiskowa zmieniana na VPS tylko wpisem
   `memex ops` z wersją dokumentów — świadome, czasowe odstępstwo od powodu z
   ADR-059:303-304.

10. **Atrapa adaptera.** Klucz `fake`, rejestrowany tylko przy `APP_ENV` `test` i
    `local`, odgrywa skrypt odpowiedzi i błędów (z wywołaniami narzędzi, odmowami i
    ucięciami), zapamiętuje żądania i oblewa test przy wywołaniu spoza skryptu. Idzie
    przez ten sam rdzeń portu — bramki, dopuszczenie, walidację i telemetrię — więc
    testy konsumentów sprawdzają wszystko poza HTTP.

11. **Adaptery jednocelowe zostają.** Obrazy zachowują bezpośredni adapter OpenAI,
    swoje błędy, worker i limit wydatków po stronie OpenAI i nie liczą się do sufitów
    portu (ADR-059 bez zmian); współbieżność `worker-ai` zostaje 2, bo jest limiterem
    tempa obrazów. Osadzenia katalogu zachowują własny klucz; mogą przejść na port
    później jako metoda `embed` — każde takie przeniesienie wymaga osobnego ADR.

12. **Interfejs opisuje kontrakt `docs/architecture/model-port.md`**: typy żądania i
    odpowiedzi, reguły żądania, rodzaje błędów, dopuszczenie, telemetria, konfiguracja
    i dowody. Zmiana zgodna wstecz (nowe pole opcjonalne, np. części treści z obrazami
    dla A4) poprawia kontrakt; zmiana łamiąca albo zmiana decyzji z tego ADR wymaga
    nowego ADR.

## Konsekwencje

- Tłumaczenia i asystent mają jeden klucz, jeden licznik i jeden zestaw sufitów;
  wyczerpana pula odracza tylko swoją pracę, a asystent ma zagwarantowane USD 25 w
  miesiącu. Twardy limit klucza zadziała pierwszy tylko przy rozjeździe naszego
  licznika z rozliczeniem OpenRoutera ponad 20%; rozjazd pokazuje `model_port_status`.
- Awaria albo limit OpenRoutera zatrzymuje tłumaczenia i asystenta (fail closed,
  ADR-033:152-155); ręczna praca w panelu działa dalej.
- Wywołania, za które klient nie płaci (odmowy, wyniki nieznane, jedno ponowienie
  tłumaczenia, wyniki niezgodne ze schematem), są kosztem platformy; telemetria
  pokazuje go per zadanie, model i firmę, a rozliczenia konsumentów
  (`record_settlement`) dają marżę.
- Dochodzi alias bazy z tą samą rolą aplikacji; w testach jest lustrem `default`, więc
  przetrwanie wiersza po wycofaniu transakcji dowodzi się na działającym stosie.
- Żaden model nie jest wybieralny przed próbą na żywo, do której potrzebny jest klucz
  wdrożenia; do fazy 1 planu ustawień wartości żyją w kodzie i zmiennych, a każda
  zmiana na VPS idzie przez `memex ops`.
- Wdrożenie: sekret, `compose.yaml` dla `backend` i `worker-ai` (profil compose `ai`
  obok `image-generation`), `GUNICORN_GRACEFUL_TIMEOUT` w CMD obrazu, migracja
  `model_port 0001`, alias i router, alarmy, test i opis `platformTables` z ADR-041,
  wpis w `.agents/evals/routing.json`, `memex ops` dla Business, HoofCare i MedPlano.

## Rozważane alternatywy

- **Port w `shared.assistant` albo `shared.translation`** — jeden konsument
  zależałby od drugiego, a przy wzajemnym użyciu kompozycja dałaby cykl.
- **LiteLLM albo SDK dostawców** — nowa zależność z własnymi ponowieniami,
  logowaniem i modelami zapasowymi; stdlib wystarcza, jak w adapterze obrazów.
- **Modele zapasowe OpenRoutera (`models`, `openrouter/auto`)** — jakość i koszt
  zależne od routingu; cicha zmiana modelu łamie ADR-033:152-155.
- **Emulacja wymuszonego narzędzia albo schematu** (`auto` z instrukcją, schemat jako
  wymuszone narzędzie) — zachowanie zależne od modelu; wołający dostaje
  `capability_not_supported` i wybiera tryb sam.
- **Jedna wspólna pula** — duże zlecenie tłumaczeń zatrzymałoby asystenta u wszystkich.
- **Wiersz telemetrii w transakcji wołającego, z kluczem obcym albo z RLS** — znika przy
  wycofaniu żądania, klucz obcy zakleszcza połączenia, a RLS zeruje sumy sufitów, bo
  połączenie portu nie ustawia tenanta.
- **Liczniki w Redis albo koszty w tabelach konsumentów** — brak wspólnych sufitów i
  widoku między firmami; Redis nie jest trwały ani audytowalny.
- **Limiter i limit czasu WWW jako cecha zadania** — worker wołający zadanie asystenta
  dławiłby się limiterem przeznaczonym dla wątków gunicorna.
- **`user` jako SHA-256 bez sekretu albo identyfikator osoby** — pierwszy powiąże wpisy
  u dostawcy z każdym, kto zna UUID firmy; drugi wysyła pseudonim człowieka bez
  korzyści dla wykrywania nadużyć.

## Relacje

- **ADR-033** — zmiana 30-39; realizacja 36-39 (model i adapter per zadanie, koszt i
  czas), 63-64 (firma nie z argumentu ani z modelu), 121-122 (klucz tylko na
  serwerze), 125-130 (MedPlano), 138-139 (bez promptów w logach), 152-155 (fail closed).
- **ADR-036 §8** — `actor_id` po usunięciu konta wskazuje tombstone; **ADR-041** —
  rozszerzenie 55-58, definicja z 46-47 bez zmian; **ADR-042** — telemetria znika z
  firmą.
- **ADR-045** — kredyty poza portem; **ADR-046** — zawężenie 20-21, „nieznany koszt
  pozostaje nieznany” obowiązuje; **ADR-049** — dopisek do §5 (`register_task`) i klucz
  profilu `ai.sendableDataClasses`; **ADR-059**, **ADR-064** — bez zmian.
- **ADR-069** — pierwszy konsument: partie, kontrola jakości, kredyty, budżet treści
  platformy, `resend_of`, dopuszczenie w workerze po przejęciu dzierżawy, sędzia evali.
- **ADR-076** — rejestr poleceń daje definicje narzędzi (nazwy mapowane na wzorzec
  portu) i format błędów pól, którego używa `tool_args_invalid`; audyt „w imieniu”
  należy do wołającego, port nie pisze audytu.
