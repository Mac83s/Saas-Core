# ADR-076 — asystent AI: rejestr poleceń, błędy pól i działanie „w imieniu” osoby

**Status:** Accepted — faza A1a planu memex
`saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy` (decyzje techniczne
AI-T1–AI-T5; odpowiedź właściciela 23 b z 2026-10-02 dla oferty asystenta).
**Data:** 2026-10-02

**Rozszerza** ADR-033 §Pipeline działania (ADR-033:63-79) i nadaje kształt
rozszerzeniu `errors`, które ADR-024 wymienia bez kształtu (ADR-024:22).
**Zmienia częściowo:** ADR-032 — §Poziomy oferty pkt 1–3 w części AI
(ADR-032:46-53) i §Entitlementy produktu w części asystenta (ADR-032:79-84);
ADR-033:137 (limit akcji asystenta → kredyty); ADR-070 pkt 2 w części o statusie
`locale_unit_invalid` (ADR-070:54; 400 z `errors`, nie 422). Reszta tych ADR-ów
obowiązuje. Stosuje ADR-044 (digest i token podglądu), ADR-035 §4 (granice
człowieka, ADR-035:127-129), ADR-045 (kredyty) i ADR-046 (pokwitowanie
idempotencji, ADR-046:31-36). Dzieli mechanizm „w imieniu” z ADR-069 (tłumaczenia
AI) i korzysta z portu modeli ADR-068 (kontrakt `docs/architecture/model-port.md`;
oba ADR-y powstają równolegle w sesji tłumaczeń).

## Kontekst

- Z ADR-033 nie zbudowano nic: nie ma modułu `shared.assistant` (ani deskryptora
  w `packages/contracts/modules/`), rejestru poleceń ani portu modeli. Port powstaje
  raz, jako `shared.model-port` (TL3 planu wielojęzyczności, ADR-068). Ten ADR
  ustala kontrakt poleceń przed kodem rejestru (A1b) i to, czego ten kod
  potrzebuje od API już teraz.
- Walidacja odpowiadała 400 z `code: invalid` i `detail` = mapa pole → komunikaty.
  Kody pól (`ErrorDetail.code`) istniały tylko w `exc.get_codes()` i nie docierały
  do klienta (`problem_details_exception_handler` w
  `apps/backend/src/saas_core/http/exceptions.py`), a
  `docs/architecture/api-and-events.md` §2 obiecywał 422, kod `validation_error`
  i mapę `errors`, których kod nigdy nie wysłał.
- OpenAPI na `main` z 02.10 (c17e5bc): 288 operacji i 799 naruszeń reguł A0,
  każda operacja łamała co najmniej jedną (119 automatycznych `operationId`,
  `summary` w 2 operacjach, `description` w 82, `Idempotency-Key` w 40 ze 169
  mutacji). Reguła A0 z `AGENTS.md` („API ma być obsługiwalne przez asystenta
  AI”) była samą prozą.
- Tożsamość: każdy kontekst inny niż `membership` to automatyzacja
  (`_is_automation` w `shared/sites/services.py`) — potrzebuje grantu i odbija się
  od bramek osoby; generator obrazów i audyt SEO wymagają `membership`
  (`shared/image_generation/services.py:150`, `shared/seo/services.py:46`), a
  rezerwacje traktują inny principal jak klienta
  (`shared/booking/services.py:638, 748`). Audyt zapisywał
  `channel = principal_kind` (`record_audit`, decyzja memex
  `historia-zmian-osobny-typ-akcji-i-pe-ne-kto-co-b`) i nie znał „w imieniu”.
- Automat tłumaczeń (TL-T24) potrzebuje tego samego: działa jako członkostwo
  osoby, która go włączyła, z identyfikatorem zadania i tym, co je wyzwoliło.
- Odpowiedź 23 b zmienia ofertę asystenta z ADR-032: codzienny asystent jest w
  każdym planie i liczony kredytami, a rozmowa zakładająca firmę jest bezpłatna po
  wyborze planu i podaniu karty.

## Decyzja

1. **Polecenie i jego deklaracja.** Polecenie to wersjonowany, cienki adapter nad
   tym samym serwisem, który woła widok panelu; audyt, outbox i transakcja zostają
   w serwisie. Niezmienna deklaracja:
   - `name@version` (`booking.offer.create@1`); zmiana łamiąca wejście, wyjście
     albo skutek to nowa wersja, a stara żyje, dopóki wiąże ją plan albo zgoda;
   - `module` — polecenie istnieje tylko w profilu, który składa moduł
     (allowlista, ADR-033:46-47);
   - tytuł i opis dla człowieka {pl, en} (podgląd, zgoda, historia — w języku
     interfejsu) i opis dla modelu po angielsku: co robi, kiedy go użyć, kiedy
     nie, warunki wstępne;
   - `input_schema` i `output_schema`: JSON Schema 2020-12 w podzbiorze trybu
     strict wywołań narzędzi (obiekt na korzeniu, `additionalProperties: false`,
     każde pole w `required` i z `description`, pole opcjonalne jako unia z
     `null`, enumy, granice, jednostki), bez tenanta i klucza idempotencji; pola
     wyjścia mają klasę danych — te same cztery klasy co port modeli (ADR-068):
     `public`, `public_personal`, `personal`, `health` — a teksty z cudzych
     źródeł znacznik `untrusted`;
   - `permission` i `entitlement` — po nich manifest filtruje polecenia, a
     wykonawca przy **każdym** wykonaniu woła `decide_feature` dla cechy kanału
     (`assistant.text.enabled`, `assistant.voice.enabled`, a dla poleceń strony
     `assistant.site_generation.enabled`) i dla zadeklarowanego entitlementu
     polecenia. Żaden serwis domenowy nie zna `assistant.*`, a downgrade w trakcie
     rozmowy ma zatrzymać następne wykonanie (ADR-032:86-87). Serwis nadal sam
     woła `authorize` i `authorize_entitled`; eval sprawdza odmowę;
   - klasa ryzyka i modyfikatory (pkt 2); `escalate(podgląd)` może klasę tylko
     podnieść;
   - podgląd: czysta funkcja bez zapisu, wywołań zewnętrznych i rezerwacji
     kredytów (typowane skutki, obserwowane wersje zasobów, wycena, efektywna
     klasa) albo jawny powód, dlaczego go nie ma;
   - idempotencja (klucz nadaje wykonawca, semantyka pokwitowania z
     ADR-046:31-36) i nazwa pola wersji zasobu (`expected_version`, `version`,
     `crew_version`) albo powód jej braku;
   - cofnięcie: polecenie odwrotne, przywrócenie wersji, odrzucenie przebiegu
     (AI-T6), kompensacja albo „brak” z powodem;
   - dane osobowe: bez zadeklarowanego celu pola `personal` są wycinane, `health`
     nigdy nie trafia do modelu, a odczyty danych osobowych są audytowane
     (ADR-033:128-130);
   - `exposure` (domyślnie `assistant`; `mcp` tylko jawnie, A9) i niepusta lista
     evali deterministycznych: odmowa uprawnienia, inny tenant, wyłączony
     entitlement, podgląd bez zapisu, powtórka klucza, nieaktualna wersja, złe
     argumenty → `errors`, brak zgody, kanał i `acting` w audycie.
2. **Klasy ryzyka i zgody** (doprecyzowuje ADR-033:67-71). `read` — wykonanie
   automatyczne; `draft` (odwracalna zmiana wersji roboczej albo nieaktywnej
   konfiguracji) — jedno kliknięcie na digest całego planu (decyzja A2); `apply`
   (odwracalna zmiana działającej konfiguracji) — kliknięcie, we wspólnym
   digeście tylko z `draft` i `apply` tego samego planu; `publish` — osobne
   kliknięcie na jedno polecenie; `irreversible` (wiadomość, płatność, anulowanie
   i przeniesienie wizyty, wydanie kredytów) — osobne kliknięcie, przy koszcie z
   digestem wyceny. Modyfikatory: `spends_credits` (zgoda wiąże wycenę i nie łączy
   się z innymi), `bulk` (zawsze osobno, ADR-035:127-129), `legal_document` i
   `changes_billing` (step-up). Step-up należy do serwisu i obowiązuje jednakowo w
   panelu i u asystenta; rejestr nie dodaje ani nie zdejmuje kontroli ścieżki
   panelu, tylko ujawnia ją w podglądzie (`step_up_required`). Polecenia
   tłumaczeń: `translation.offer.read`, `.quote`, `.status.read`, `.review.list` —
   `read`; `sites.locale_body.save` — `draft`; `translation.glossary.*`,
   `.job.cancel`, `.review.reject` — `apply`; `translation.review.accept`,
   `sites.locale_body.accept` i `.publish` — `publish` (dokument prawny:
   step-up); `translation.job.create` — `irreversible` + `spends_credits`;
   `translation.settings.update` — `apply`, z eskalacją do `irreversible` +
   `changes_billing` przy włączeniu automatu, przejściu na automat albo
   podniesieniu limitu; `organization.public_locales.update` — `apply`, a
   usunięcie języka eskaluje do `publish`.
3. **Digest i token zgody.** Digest to SHA-256 (hex) kanonicznego JSON:
   `json.dumps(wartość, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
   zakodowanego w UTF-8 — ta sama kanonikalizacja co skrót katalogu z
   ADR-046:13-15 i `canonical_json_hash` digestu zmian treści z ADR-044. Funkcja
   żyje w rdzeniu, bo rejestr w `core` nie może importować `shared` (kontrakt
   warstw import-linter); `shared.sites` deleguje do niej, gdy A1b doda kod (dziś
   ta sama kanonikalizacja jest w `shared/sites/models.py` i w
   `shared/notifications/security.py`). Digest obejmuje wersję kontraktu,
   organizację, członkostwo, aktora, `acting_via` i `acting_ref`, wywołania
   (`name@version`, argumenty, klucze idempotencji, obserwowane wersje, skutki)
   i wycenę; każda zmiana planu, argumentu albo zasobu daje inny digest. Token
   zgody to podpis Django z osobną solą (`core.commands.consent.v1`) i krótkim
   TTL; wiąże digest, członkostwo, rozmowę (`acting_ref`) i czas step-upu, więc
   zgody z jednej rozmowy nie da się odtworzyć w innej. Wybija go wyłącznie
   endpoint panelu dla bezpośredniej osoby (sesja, CSRF, kontekst bez
   `acting_via`); nie jest poleceniem i model go nie widzi; tekst „potwierdzam”
   nigdy nie jest zgodą (ADR-033:72-75). Token podglądu z ADR-044 dowodzi skutku,
   nie zgody człowieka (ADR-044:44-45) — stąd osobna sól. Jednorazowość daje klucz
   idempotencji w digeście; niejednoznaczny wynik rozstrzyga odczyt stanu po
   kluczu, nie ponowienie (ADR-035:185-186).
4. **Gdzie żyje rejestr i co z OpenAPI.** Rejestr żyje w rdzeniu
   (`core.organizations`, obok rejestrów zdarzeń i referencji z `api.py`); moduły
   rejestrują polecenia w `AppConfig.ready()`, a produkt dokłada polecenia
   wertykału nowymi plikami (ADR-049). `shared.assistant` (A3) i MCP (A9) sięgają
   do modułów wyłącznie przez rejestr. Nazwa narzędzia jest wyprowadzana
   (`booking.offer.create@1` → `booking_offer_create_v1`; alfabet
   `[a-zA-Z0-9_-]`, do 64 znaków; kolizję odrzuca rejestracja); format jest
   neutralny wobec dostawcy (`name`, `description`, `input_schema`), a mapowanie
   na `tools` i `tool_choice` robi port (ADR-068). OpenAPI zostaje kontraktem
   panelu; narzędzi nie generujemy z OpenAPI.
5. **Błędy, które model może poprawić** (kształt `errors` z ADR-024:22). Każda
   odpowiedź 400 i 422 z handlera Problem Details ma niepuste
   `errors: [{field, code, message}]`; inne statusy go nie mają.
   - Rozwijana jest wyłącznie `ValidationError` z DRF, bo tylko jej `detail` ma
     kształt wejścia: klucz to pole, a pozycja na liście to indeks. `field` to
     ścieżka w danych żądania (ciało albo parametr zapytania): segmenty łączone
     kropką, indeks listy jako liczba (`address.city`, `items.1.name`,
     `units.0/data/title`), `null` = całe żądanie; klucz `non_field_errors`
     (i `__all__` Django) nigdy nie jest segmentem. To notacja React Hook Form i
     `issue.path.join('.')` z Zod.
   - Każdy inny wyjątek, cokolwiek trzyma w `detail`, daje dokładnie jeden wpis:
     `field` z atrybutu `problem_field` albo `null`, `code` z `problem_code`
     (`http/exceptions.py`), `message` z `detail`, gdy to zdanie, a inaczej z
     `default_detail`. Moduł może mieć w `detail` własny słownik, a jego
     rozwinięcie nazwałoby pola, których żądanie nie miało.
   - `code` to kod DRF (`required`, `max_length`, `invalid_choice`…), walidatora
     Django (`password_entirely_numeric`) albo domenowy z
     `ValidationError(…, code=…)`. `message` — zdanie dla człowieka w języku
     serwera, tylko do wyświetlenia.
   - Bez zmian: status 400 dla wszystkiego, co wołający może poprawić w danych;
     `type` i `title`; `code: invalid` (kod domenowy na górze daje podklasa
     `ValidationError` z `problem_code`); dotychczasowy `detail`, tylko do
     wyświetlenia (ADR-024:23). 422 zostaje dla odmów operacji treści
     (ADR-044:53, ADR-059:89, ADR-070:183) i dostaje jeden wpis.
   - Błędne fragmenty wersji językowej (`locale_unit_invalid`, ADR-070 pkt 2) to
     dane do poprawienia, więc 400: podklasa `ValidationError` z
     `problem_code = "locale_unit_invalid"` i `detail`
     `{"units": {<klucz>: [komunikat z kodem fragmentu]}}` daje wpisy
     `units.<klucz>` z kodem fragmentu (tak odpowiada kod TL8c od c79cde9).
   - Ten sam kształt zwraca walidacja argumentów polecenia (`absolute_path` z
     JSON Schema łączone kropką) i błąd `tool_args_invalid` portu.
6. **Działanie „w imieniu” osoby (AI-T5, TL-T24).** `TenantContext` dostaje
   `acting_via` (`assistant`, `ai_translation`), `acting_ref`
   (`conversation:<uuid>`, `translation_job:<uuid>` — każdy kanał ma dokładnie
   jeden rodzaj odniesienia) i `acting_trigger` (puste albo
   `user|api_key|schedule|conversation:<uuid>`). „Kanał assistant /
   ai_translation” z planu to `acting_via`; kolumna `channel` dalej znaczy
   principal (`membership` — w historii „Panel”, `api_key`, principal
   serwisowy). Słownik należy do rdzenia (`ACTING_VIA` i `ACTING_TRIGGER_KINDS` w
   `core/organizations/context.py`) i jest sprawdzany przy tworzeniu kontekstu;
   nowy kanał (np. `mcp`) to jeden wpis i etykieta. Pola stoją tylko nad
   `principal_kind == membership`, bez zagnieżdżania; kontekst buduje
   `acting_context(context, via=…, ref=…, trigger=…)`, a ustawia go wyłącznie kod
   serwera z wierszy serwera (rozmowa należąca do członkostwa, zgoda zapisana na
   zadaniu), nigdy treść żądania ani wyjście modelu (ADR-033:63-64).
   `record_audit` kopiuje je do trzech kolumn wpisu (organizations 0052); „w
   imieniu” to `actor_user`. Słownik A0: `user` = panel bez `acting`,
   `assistant` = `acting_via=assistant`, `integration` = `api_key`, `system` =
   principal serwisowy; automat tłumaczeń = `acting_via=ai_translation`.
   - **Praca odroczona przenosi `acting`.** `deferred_tenant_context(…,
     acting_via, acting_ref, acting_trigger)` nakłada je ponownie na kontekst
     odbudowany z członkostwa, a wartości, które się nie trzymają, odrzuca jak
     członkostwo, którego już nie ma. Rekord, który przechowuje prawo do
     późniejszego działania, przechowuje też te trzy pola. Kontrakt zadania (v2)
     ich nie przenosi, więc `issue_tenant_task_contract` odmawia wydania go w
     kontekście z `acting` — zadanie nie może po cichu działać jako osoba
     decydująca sama. Kontrakt v3 z `acting` dokłada pierwszy producent, który
     kolejkuje zadania w takim kontekście.
   - **`acting` nigdy nie rozszerza praw.** Rola, uprawnienia i `principal_kind`
     się nie zmieniają. Działanie w imieniu osoby nie jest decyzją osoby, więc
     bramki osoby są dla niego zamknięte: `assert_person_required` odmawia
     (`PersonRequired`), chyba że etykietę otwiera dla tego `acting_via` tabela
     rdzenia `ACTING_PERSON_GATE_ALLOWED` (kanał → etykiety), w A1a pusta;
     `assert_page_writable` (strona prawna) i `assert_person_blocks` (cennik, nowe
     cytaty, nowe podpisy zdjęć) wykonują swoją część „tylko osoba” także dla
     kontekstu z `acting`. Granica z ADR-035 §4 (ADR-035:127-129) i kontekst
     człowieka przy akceptacji propozycji (ADR-044:62) wiążą więc kontekst z
     `acting`. Etykiety otwiera A1b — dla zgody z kliknięcia, ze step-upem tam,
     gdzie wymaga go panel — i ADR-069 dla nazwanych wyjątków automatu
     tłumaczeń. Kontrole `membership` w generatorze obrazów, SEO i GSC się nie
     zmieniają: przepuszczają kontekst z `acting` jak osobę, a wydanie kredytów
     pilnuje klasa `spends_credits` (pkt 2) albo granice automatu z ADR-069.
     Zawęża tylko kod, który czyta `acting_via`: bramki osoby, bramka zgody i
     step-upu wykonawcy (A1b) i granice automatu z ADR-069 (TL-T25).
7. **Podłoga kontraktu operacji.** Każda nowa i każda zmieniona operacja OpenAPI
   spełnia pięć reguł o stałych identyfikatorach:
   - `operation-id` — jawne `operationId` w `snake_case`, nie automatyczne z
     drf-spectacular (odtwarzane ze ścieżki bez parametrów z dopiskiem `list`
     albo `retrieve` dla GET i `create`, `update`, `partial_update` albo
     `destroy` dla reszty);
   - `summary` i `description` (skill `change-api-and-events`, reguła A0);
   - `idempotency-key` — POST, PUT, PATCH i DELETE deklarują nagłówek
     `Idempotency-Key` z `required: true`. Nie dotyczy operacji oznaczonej
     `x-dry-run: true` (podgląd bez zapisu, pkt 1), która spełnia pozostałe
     reguły;
   - `error-400` — operacja, która przyjmuje dane (ciało, parametr zapytania,
     wymagany nagłówek), deklaruje 400, a każda zadeklarowana 400 i 422 wskazuje
     `ProblemDetails`.

   Wyjątek dopuszczają tylko `idempotency-key` i `error-400`:
   `x-quality-exempt: {reguła: powód}` przy widoku (`extend_schema(extensions=…)`),
   z niepustym powodem. Reguła globalna, nigdy nie wpisywana do linii bazowej:
   `operationId` postaci `^(.+)_(\d+)$`, którego pierwsza grupa jest innym
   `operationId` dokumentu, to zdublowany jawny identyfikator — drf-spectacular
   rozwiązuje kolizję sam, dopisując `_2`, i tylko ostrzega.

   Dzisiejszy dług stoi w linii bazowej
   `packages/contracts/openapi/quality-baseline.json` (wersja 1, posortowana,
   pisana wyłącznie przez skrypt): odcisk każdej operacji i jej uchylone reguły.
   Po utworzeniu plik tylko maleje — skrypt nigdy nie dopisuje operacji ani
   reguły i nie zmienia odcisku, a nieaktualny wpis (naprawione naruszenie,
   operacja, której już nie ma) psuje kontrolę, dopóki zapis go nie usunie.
   Operacja spoza linii bazowej nie może łamać żadnej reguły; operacja o
   zmienionym odcisku traci uchylenia; nowe naruszenie operacji niezmienionej
   psuje kontrolę.

   Odcisk to metoda, ścieżka, parametry bez `Idempotency-Key` sprowadzone do
   `{in, name, required, schema}`, wejście ciała żądania rozwinięte o jeden
   poziom i odpowiedzi 1xx–3xx jako nierozwinięte `$ref`. Wejście ciała to
   schemat z raz rozwiązanym `$ref`: nazwy właściwości, `type`, `format`,
   `enum`, `nullable`, `required` i granice; właściwości `readOnly` odpadają, a
   `description`, `title` i `example(s)` znikają tylko jako słowa kluczowe
   schematu, nigdy jako nazwy właściwości. Nowe pole wejścia w serializerze
   zmienia więc odcisk, a poprawka opisu albo zmiana komponentu odpowiedzi (np.
   `ProblemDetails.errors`) — nie. Produkt (istnieje `.saas-core-upstream`) czyta
   i pisze własny `quality-baseline.product.json` dla operacji, których nie
   obejmuje linia bazowa rdzenia. `pnpm api:check` to kontrola dryfu i podłogi.
   Polecenie, które opakowuje operację panelu, wymaga, żeby ta spełniała
   podłogę.
8. **Oferta asystenta (zmienia ADR-032 zgodnie z 23 b).** Codzienny asystent jest
   w każdym planie i rozliczany kredytami (operacje `assistant.*` z billing 0016,
   pula `credits.monthly` z 0017). Rozmowa zakładająca firmę jest bezpłatna po
   wyborze planu i podaniu karty — w A3 jako osobne, nieaktywne (czyli
   bezpłatne) operacje kredytowe i budżety portu. `assistant.text.enabled`,
   `assistant.site_generation.enabled` i `assistant.voice.enabled` są w katalogu
   jako aktywne cechy modułu `shared.assistant` w żadnej wersji planu (billing
   `0026_assistant_features`): decyzja `feature_disabled` zamiast
   `unknown_feature`, pilot przez audytowane nadpisanie operatora, nic w cenniku
   (ADR-032:54-56). Do planów wpisuje je migracja `shared.assistant` przez
   `publish_feature`: tekst w A3, stronę w A4 (po katalogu szablonów,
   ADR-033:106-107), głos w A8. `assistant.actions.monthly` i
   `assistant.voice_minutes.monthly` nie są zasiewane: licznikiem są kredyty, a
   sufit nadużyć, jeśli będzie potrzebny, ustali A3 migracją modułu (wzór:
   `image_generation` 0003). To zmienia ADR-033:137 — plan ogranicza asystenta
   kredytami, nie liczbą akcji. Prefiks `assistant.` ma trzy przestrzenie nazw:
   cechy planu, operacje kredytowe i zadania portu modeli.
9. **Podział faz.**
   - **A1a** (ten przyrost): ten ADR; `errors` w handlerze i w schemacie
     `ProblemDetails`; podłoga OpenAPI z linią bazową rdzenia i odczytem linii
     bazowej produktu; `acting` w `TenantContext`, w audycie (organizations
     0052) i w `deferred_tenant_context`, z zamkniętymi bramkami osoby; cechy
     `assistant.*` w katalogu (billing 0026).
   - **Odroczone do pierwszego, kto tego potrzebuje:** `acting` w API historii i
     „w imieniu” na ekranie historii — sesja, która pierwsza zapisze wiersze z
     `acting` (TL6/TL11 albo A3); kontrakt zadania v3 — pierwszy producent, który
     kolejkuje zadania w kontekście z `acting`; pomocnicy klienta dla `errors`
     (`@saas-core/api-client`, mapowanie na React Hook Form) — pierwszy formularz,
     który czyta `errors`; przeliczenie odcisków linii bazowej bez zmiany operacji
     — pierwszy commit, który zmieni ustawienia generatora schematu.
   - **A1b:** kod rejestru (typy, rejestracja, test kompletności), wykonawca (z
     `decide_feature` przy każdym wykonaniu, pkt 1), endpoint zgody, step-up,
     eksport manifestu z kontrolą dryfu, evale, pierwsze polecenia (firma,
     wizytówka, usługi, grafik, szkic strony, tłumaczenia), etykiety
     `ACTING_PERSON_GATE_ALLOWED` dla zgody z kliknięcia i spłata linii bazowej.
   - **A3:** `shared.assistant`, rozmowa, UI zgody, kontrakt import-linter
     „asystent tylko przez rejestr”. **A9:** MCP.

## Konsekwencje

- Kontekst z `acting` nie przechodzi bramek osoby. Dopóki A1b nie otworzy
  etykiet dla zgody z kliknięcia, a ADR-069 nie nazwie wyjątków automatu
  tłumaczeń, ani asystent, ani automat nie zmienią domeny, menu głównego,
  wyglądu, stron prawnych ani cennika, nie opublikują całej witryny i nie
  zdecydują o propozycji treści. W A1a nic nie tworzy kontekstu z `acting`, więc
  w działaniu nic się dziś nie zmienia.
- Każde miejsce, które odbudowuje kontekst z członkostwa
  (`context_from_membership`), musi ponownie nałożyć `acting` tak jak
  `deferred_tenant_context` — pułapka w skillu `change-tenant-data`. Workery
  obrazów i SEO dostaną to razem z poleceniami A4 i A7.
- Historie lokalne (wersje stron, status wizyty) zapisują principal i nie pokażą
  asystenta; źródłem „kto w czyim imieniu” jest historia organizacji.
- `detail` zostaje drugim, starszym źródłem obok `errors`, dopóki konsumenci nie
  przejdą. Panel czyta dalej `code` i `detail`; SeoContentRank czyta tylko
  status, `code` i `detail`, więc zmiana go nie dotyka.
- `docs/architecture/api-and-events.md` §2 opisuje prawdziwy kształt błędów, a
  zdanie o diffie zmian łamiących w CI znika: CI uruchamia `pnpm api:check`,
  czyli dryf i podłogę.
- Dotknięcie starej operacji (parametry, wejście ciała, odpowiedzi 1xx–3xx)
  podnosi ją do podłogi — łącznie z idempotencją albo jawnym wyjątkiem z
  powodem; podgląd oznacza się `x-dry-run`.
- Produkty przy najbliższym `core:update` zakładają
  `quality-baseline.product.json` dla operacji wertykałów i przechodzą własne
  suity.

## Odrzucone

- **Nowy `principal_kind` dla asystenta albo zadania** — odziedziczyłby blokady
  automatyzacji w każdym module (AI-T5, TL-T24).
- **`channel = acting_via`** — miesza principal z kanałem i gubi principal;
  **`acting` w `metadata`** — decyzja z 23.09 (memex
  `historia-zmian-osobny-typ-akcji-i-pe-ne-kto-co-b`): kolumny, nie metadane.
- **Bramki osoby przepuszczające `acting`** — pierwszy producent takich
  kontekstów (automat tłumaczeń, TL6) przeszedłby granice ADR-035 §4 i
  ADR-044 z samą stałą zgodą z konfiguracji, zanim powstanie bramka zgody A1b.
- **422 i `validation_error` dla walidacji** — łamie klientów i testy
  (`apps/backend/tests/test_identity_api.py:116-126`); **`errors` jako mapa pole →
  lista albo wskaźnik JSON Pointer z RFC 9457** — mapa nie wyraża „bez pola”, a
  wskaźnik wymaga ucieczek `~0`/`~1` i przeliczenia przed React Hook Form.
- **Rozwijanie `detail` każdego wyjątku** — pierwsza wersja TL8c trzymała w
  `detail` własną listę `errors`; rozwinięta dałaby ścieżki `message` i
  `errors.0.field`, których żądanie nie miało, i dwie listy w jednej odpowiedzi.
- **Narzędzia generowane z OpenAPI** — operacje nie niosą ryzyka, podglądu ani
  cofnięcia i są dla modelu zbyt drobne.
- **Rejestr w `shared.assistant`** (W9.5.7) — moduły zależałyby od asystenta;
  **kod rejestru w A1a** — plan wiąże A1a z kontraktem przed kodem.
- **„Zmienione operacje” z git diff** — płytki checkout w CI, push na `main` bez
  bazy, inna baza w produktach. **Odcisk bez rozwinięcia ciała żądania** — prawie
  każda zmiana wejścia to zmiana serializera, czyli komponentu: w 40 ostatnich
  commitach `v1.yaml` przeoczyłby 31 operacji ze zmienionym wejściem (np.
  64cd0b3, `place_town` i `place_address` w `AppointmentCreate`), a rozwinięcie
  o jeden poziom łapie 30 z nich. **Rozwinięcie na każdą głębokość** — zmiana
  wspólnego schematu zagnieżdżonego zmieniłaby odcisk każdej operacji, która go
  używa.
- **Kontrola unikalności `operationId`** — drf-spectacular sam rozwiązuje
  kolizję jawnych identyfikatorów, więc w wygenerowanym pliku duplikatu nigdy nie
  ma; stąd reguła `_N`.
- **Klucz idempotencji przy podglądzie** — podgląd nic nie zapisuje;
  `x-dry-run: true` zwalnia go z tej jednej reguły.
- **Cechy w planach z `is_active=False`** — `unknown_feature`, brak pilota przez
  nadpisanie, nowe wersje planów i mapowania cen bez przeniesienia subskrypcji.
- **Zasianie `assistant.actions.monthly` i `assistant.voice_minutes.monthly`** —
  licznikiem są kredyty; nieużywany klucz limitu byłby martwy albo pułapką, gdyby
  A3 rezerwował na nim bez wartości w planie.

## Uzupełnienie 2026-10-02: zakres step-upu, tylko 2FA i kolejność poleceń rezerwacji

Odpowiedzi właściciela 30–32 (plan asystenta, faza A1b):

- **30 a — zakres step-upu bez zmian.** Step-up obowiązuje wyłącznie przy
  modyfikatorach `legal_document` i `changes_billing` (pkt 2), w panelu i u
  asystenta jednakowo. Publikacja strony i zmiana domeny nie wymagają step-upu;
  u asystenta wymagają osobnego kliknięcia zgody (klasa `publish`). Dawna
  decyzja A2 planu („publikacja i domena ze step-upem”) przestaje obowiązywać.
- **31 b — step-up to wyłącznie kod drugiego składnika.** Samo hasło nie
  wystarcza, a kody zapasowe nie są przyjmowane. Konto bez 2FA nie zaakceptuje
  dokumentu prawnego i nie zmieni rozliczeń, dopóki nie włączy 2FA: serwis
  odmawia kodem 403 `step_up_mfa_setup_required` (różnym od
  `mfa_setup_required` logowania operatora), z komunikatem „Włącz weryfikację
  dwuetapową, aby…” i bezpośrednią drogą do włączenia 2FA w panelu. Asystent
  dostaje ten sam kod i podaje osobie tę drogę; sam 2FA nie włącza. Prymityw
  (`core/identity/step_up.py`, `require_step_up`) jest jeden dla asystenta i
  dla poziomu 2 operatora z planu ustawień platformy.
- **32 a — polecenia usług i grafiku po ADR-072 §11.** Sesja rezerwacji buduje
  najpierw pokwitowanie zapisów konfiguracji, kontrolę wersji i podgląd z
  ADR-072 §11, a polecenia `booking.*` z pkt 9 (A1b) powstają na nim — bez
  tymczasowych wersji `@1` z drugim mechanizmem idempotencji. Szkic strony z
  szablonu zostaje w A1b (pkt 9), nie w A4.

## Uzupełnienie 2026-10-02: bramka osoby otwierana na jedno wykonanie (A1b-8)

Zawężenie pkt 6 zgodne z jego intencją. `ACTING_PERSON_GATE_ALLOWED` jest
**sufitem**, nie otwarciem: etykieta w tabeli nie przepuszcza żadnego kontekstu
z `acting` sama z siebie. Przepuszcza dopiero pole kontekstu `acting_opened` —
etykiety otwarte na jedno wykonanie, zawsze podzbiór sufitu kanału
(sprawdzane przy tworzeniu kontekstu). Kto je ustawia, zależy od kanału:

- `assistant` — wyłącznie wykonawca poleceń, dla wywołania, którego grupa ma
  własną, zweryfikowaną zgodę: przecięcie `person_gates` deklaracji, bramek
  zgłoszonych w podglądzie i sufitu kanału, tylko na czas `spec.run`;
- `ai_translation` — worker tłumaczeń ze zgody zapisanej w wierszu zlecenia
  (ADR-069), kiedy ADR-069 nazwie takie wyjątki.

Sufit `assistant` ma dziś trzy etykiety: „Usunięcie języka firmy” (TL10a,
`organization.public_locales.update@1`), „Decyzja o tłumaczeniu AI”
(`translation.review.accept@1` i `.reject@1`) i „Zgoda na automat tłumaczeń”
(`translation.settings.update@1`, gdy włącza automat — wtedy także
`irreversible` ze step-upem), obie od TL6c. Sufit `ai_translation` zostaje
pusty (ADR-069 pkt 15): zlecenie nie decyduje za osobę.

`acting_context`, `deferred_tenant_context` i kontrakt zadania nigdy nie
przenoszą `acting_opened`, więc praca odroczona zaczyna z zamkniętymi
bramkami. Miejsca, które wybijają zgodę (`mint_consent`), ustawiają
`acting_opened=` albo wołają `acting_context(`, są policzone w
`tests/test_command_doors.py` z powodem każdego; tam też etykiety sufitu i
`person_gates` poleceń muszą istnieć jako etykiety bramek w kodzie.

## Uzupełnienie 2026-10-02: plan czekający na zgodę i endpoint zgody (A1b-6)

Doprecyzowanie pkt 3. Serwer podpisuje tylko to, co sam pokazał: `offer_plan`
zostawia każdą grupę wymagającą kliknięcia w pamięci podręcznej pod jej
digestem (`COMMAND_PENDING_TTL`, 30 min) — z tytułami, typowanymi skutkami,
wyceną, klasą i informacją o step-upie. Panel czyta ją przez
`GET /api/v1/organizations/current/command-consents/{digest}/`, a dialog zgody
(A3) renderuje wyłącznie tę odpowiedź, nigdy opis planu z tekstu modelu, który
wstrzyknięcie promptu mogłoby zmyślić. `POST` na ten sam adres wybija token
(sesja, CSRF, principal `membership` bez `acting_via`; inaczej 403
`consent_person_only`); rozmowę, którą token wiąże, bierze z zapisanego planu,
nie z żądania. Plan innego członkostwa i plan wygasły dają to samo 404
`consent_preview_not_found`. Grupa ze step-upem odpowiada 403
`step_up_required`, dopóki step-up (A1b-7) nie zostanie potwierdzony. Kliknięcie
trafia do historii organizacji jako `commands.consent.granted` (polecenia,
klasa, prefiks digestu, rozmowa), bez `acting` — to decyzja osoby. Token
oddaje się wykonawcy pod identyfikatorem grupy (pierwszy krok grupy).

## Uzupełnienie 2026-10-02: step-up w `core.identity` (A1b-7)

Wykonanie odpowiedzi 31 b. `core/identity/step_up.py` jest jedynym prymitywem
dla asystenta, panelu i poziomu 2 operatora z planu ustawień platformy:
`POST /api/v1/auth/step-up/` przyjmuje wyłącznie kod z aplikacji (kod zapasowy
nie — służy do odzyskania konta), zapisuje czas w sesji na
`STEP_UP_MAX_AGE` (300 s), a pięć błędnych kodów w 15 minut kończy sesję (403
`step_up_locked`). Konto bez 2FA dostaje 403 `step_up_mfa_setup_required`.
Serwis woła `require_step_up(user_id=…, reason=…)`. Żądanie panelu ma aktywny
step-up swojej sesji (middleware sesji), a wykonawca poleceń na cały podgląd i
wykonanie zastępuje go pustym i tylko na czas grupy aktywuje czas z tokenu
zgody — endpoint zgody wpisuje do tokenu świeży step-up sesji, gdy grupa go
wymaga. Step-up z panelu nigdy więc nie odpowiada za to, co asystent robi bez
niego.

## Uzupełnienie 2026-10-03: kontrakt zadania v3 przenosi `acting` (A1b-11)

Wykonanie odroczonej części pkt 6. Pierwszym producentem zadań w kontekście z
`acting` jest polecenie `sites.page_draft.from_template@1`: szablon z
zdjęciami kopiuje je do magazynu firmy, a przetwarzanie zdjęcia idzie do
kolejki. `issue_tenant_task_contract` wydaje wtedy kontrakt **wersji 3** z
`acting_via`, `acting_ref` i `acting_trigger`; zadanie otwiera kontekst tak
samo działający w imieniu osoby (`tenant_task_context` woła `acting_context`).
Kontekst bez `acting` dostaje dalej dokładnie wersję 2, więc zapisane kontrakty
i workery sprzed zmiany czytają go bez zmian. Wersja 3 bez `acting`, `acting`
w wersji 2, nieprawidłowe odniesienie i principal inny niż `membership` są
odrzucane jak każdy zły kontrakt. `acting_opened` nigdy nie trafia do kontraktu:
zadanie zaczyna z zamkniętymi bramkami osoby. Nowe miejsce wywołania
`acting_context(` jest policzone w `tests/test_command_doors.py`.

## Uzupełnienie 2026-10-03: rozmowa w panelu (A3-1)

Pierwszy plaster A3: czat, który obsługuje już zarejestrowane polecenia. Profil
firmy i konfigurator (A2) oraz rozmowa zakładająca firmę (A3-2) przychodzą po
nim. Kontrakt wykonawczy: `docs/architecture/assistant-chat.md`.

1. **Moduł `shared.assistant`** (zależy od `core.identity`, `core.organizations`,
   `shared.billing`, `shared.model-port`). Do pozostałych modułów sięga wyłącznie
   przez rejestr poleceń — pilnuje tego kontrakt import-linter
   „assistant-through-the-registry” (pkt 9 tego ADR).
2. **Tura biegnie w workerze `ai`, nie w żądaniu.** Jedna wiadomość to kilka
   wywołań modelu po maks. 18 s, a port dopuszcza jedno wywołanie WWW na proces.
   `POST …/turns/` odpowiada 202, a panel czyta rozmowę ponownie, aż tura będzie
   `done`, `failed` albo `awaiting_consent`. Strumieniowanie (`stream` z ADR-068
   pkt 5) zostaje odłożone: wymaga innego serwera niż dzisiejszy gunicorn i nie
   zmienia niczego w zgodach.
3. **Jedna odpowiedź modelu = jeden plan.** Wywołania narzędzi z jednej odpowiedzi
   dostają od serwera `step_id` i idą razem do `offer_plan`. Same odczyty wykonują
   się od razu, a ich wyniki wracają do modelu. Plan z odmową wraca do modelu jako
   błędy pól. Plan z zapisem zatrzymuje turę (`awaiting_consent`) z digestami grup
   zgody; dialog rysuje wyłącznie to, co zwraca endpoint zgody.
4. **Zgoda wykonuje się w żądaniu osoby.** `POST …/turns/{id}/consents/` przyjmuje
   tokeny (grupa → token) albo `declined`. Plan wykonuje `execute_plan` w tym samym
   żądaniu, w kontekście „w imieniu” tej rozmowy — token nie opuszcza żądania — a
   worker tylko kontynuuje rozmowę z wynikami kroków. Grupa bez tokenu się nie
   wykonuje; tekst modelu i tekst osoby w rozmowie nigdy nie są zgodą.
5. **Model widzi tylko wyniki kroków.** „Zrobione” wolno powiedzieć wyłącznie po
   `"status": "done"`; wynik narzędzia to dane, nie polecenie. Prompt jest stały dla
   całej rozmowy, a czas wiadomości dochodzi przy każdej wiadomości osoby, żeby
   historia była tylko dopisywana (cache dostawcy i `continuation` z ADR-068).
6. **Limity** (warunki otwarcia czatu z decyzji A1): limit wiadomości na osobę na
   minutę, limit nowych rozmów z adresu na godzinę, liczba wywołań modelu na
   wiadomość i dzienny sufit wdrożenia to ustawienia platformy
   (`assistant.limits.*`, ADR-078); budżety w dolarach pilnuje port modeli. Bez
   workera kolejki `ai`, bez wybranego modelu albo ponad sufit czat odpowiada 503
   i odsyła do panelu; powód podaje `GET /api/v1/assistant/offer/`.
7. **Oferta i rozliczenie** (pkt 8): migracja modułu publikuje
   `assistant.text.enabled` we wszystkich planach. Wiadomość rezerwuje jeden kredyt
   `assistant.conversation_turn`, wydaje go po odpowiedzi i zwraca po porażce tury.
8. **Rozmowa to dane osobowe.** Czyta ją wyłącznie osoba, która ją prowadzi; tabele
   mają RLS; treść nie trafia do logów. Rozmowy znikają po
   `assistant.retention.conversation_days` (domyślnie 90, pytanie 58) i razem z
   firmą. Profil wdrożenia musi dopuścić klasę `personal`
   (`ai.sendableDataClasses`); klasy `health` rejestr poleceń nie zwraca nigdy.
9. **Model rozmowy wybiera właściciel na evalach** (`manage.py assistant_eval`,
   raporty w `docs/evals/assistant/`): trafność wywołań i argumentów, dopytywanie
   zamiast zgadywania, brak „zrobione” bez wyniku, odporność na polecenia wszyte w
   wyniki narzędzi, koszt wiadomości i czas wywołania. Zmiana promptu albo modelu
   idzie z ponownym przebiegiem.
10. **Wdrożenie:** moduł jest w profilach `business` i `agro`. Do `vps-dev` dołącza
    dopiero po wyborze modelu przez właściciela; do tego czasu na VPS nie ma ani
    tras, ani tabel, ani pozycji w menu.

## Uzupełnienie 2026-10-03: profil firmy i konfigurator (A2)

Kontrakt wykonawczy: `docs/architecture/assistant-profile.md`.

1. **Profil to dokument z pochodzeniem wartości** (`company-profile.v1`). Każda
   wartość niesie `origin` i `confirmed`; do konta trafia tylko potwierdzona. Profil
   jest firmy, nie rozmowy: czyta go i zmienia zarządzający ustawieniami firmy, a
   każdy zapis to nowa wersja z autorem i rozmową. Zapis profilu nie zmienia konta.
2. **Konfigurator jest czystą funkcją nad wynikami poleceń odczytu.** Nie importuje
   innych modułów (pkt 9), nie woła modelu i niczego nie wykonuje; dostaje też listę
   poleceń, którymi wolno planować. Krok, do którego brakuje polecenia, raportuje
   jako `command_missing` — konfigurator nie obchodzi rejestru.
3. **Plan idzie rundami.** Argumenty planu są stałe przed wykonaniem (pkt 3 pierwotnej
   decyzji), więc krok zależny od identyfikatora z tego samego planu czeka na
   następną rundę. Konfigurator tylko dokłada: niczego, czego profil nie wymienia,
   nie usuwa.
4. **Dodane pole wyjścia nie zmienia wersji polecenia.** `organization.read@1`
   zwraca teraz `organization_type`, a `booking.setup.read@1` tydzień pracy każdej
   osoby (`hours`) — w kształcie, który przyjmuje `booking.staff.hours.set@1`.
   Wyjście polecenia jest otwarte na dodanie pola; zmiana łamiąca (usunięcie, zmiana
   typu albo znaczenia) wymaga `@2`. Różnicę pokazuje manifest poleceń.
5. **Nowe polecenia dla zakładania firmy:** `profiles.catalog_options.read@1`
   (kategorie z nazwami i słowami kluczowymi, miasta z nazwami) i
   `booking.location.save@1` (`apply`: nowe miejsce jest od razu włączone i widoczne
   w rezerwacji online, jak w panelu; adres nie trafia do słów zgody).
   `booking.preset.list@1`, `booking.preset.apply@1` i `booking.staff.add@1` są
   zapowiedziane w `commands/planned.json` (plan rezerwacji, faza 3). — Od
   03.10 wszystkie trzy są w rejestrze. `booking.staff.add@1` dodaje osobę bez
   konta w klasie `apply`; z zaproszeniem do panelu podgląd podnosi klasę do
   `publish` (pkt 2: osobne kliknięcie), bo to e-mail do osoby trzeciej i konto
   z rolą, a słowa zgody podają adres i rolę.
6. **Lista typów firm i szablonów usług przechodzi z A2 do A6.** Asystent nie zakłada
   organizacji i nie zmienia jej typu, a szablony usług zastępują presety (ADR-072
   §10); listę typów potrzebuje dopiero zakładanie firmy przez asystenta jako ścieżka
   domyślna.
7. **Retencja:** profil znika z firmą, a wersje starsze od bieżącej podlegają
   `assistant.retention.conversation_days`. A2 nie dodaje zadania czyszczącego —
   tabelę przejmuje hak retencji platformy; warunek zastępczy jest w kontrakcie
   wykonawczym.

## Uzupełnienie 2026-10-03: rozmowa zakładająca firmę (A3-2)

Zapisane przed kodem. Podział ról z planu asystenta: **model notuje i pyta,
konfigurator planuje, właściciel klika.** Model nie pisze argumentów żadnego
polecenia zakładania — dzięki temu plan jest powtarzalny i tani, a wstrzyknięta
treść może najwyżej zostawić błędną notatkę, którą właściciel widzi w dialogu
zgody, zanim cokolwiek się zmieni.

1. **Trzy narzędzia własne asystenta, poza rejestrem poleceń.**
   - `profile_note` — merge patch profilu firmy, każda wartość z pochodzeniem.
     Wykonuje się od razu, bez kliknięcia: nie zmienia niczego na koncie.
   - `setup_status` — wykonuje polecenia odczytu przez rejestr, uruchamia
     konfigurator i zwraca kolejne pytania (z dozwolonymi odpowiedziami), kroki
     gotowe do wykonania, kroki czekające i to, czego produkt jeszcze nie umie.
   - `setup_apply` — oddaje bieżący plan konfiguratora do `offer_plan`. Tura czeka
     wtedy na kliknięcie tak samo jak w A3-1, plan wykonuje żądanie osoby, a
     następne `setup_status` daje kolejną rundę.

   To świadome odstępstwo od „narzędzia modelu pochodzą z rejestru” (pkt 4).
   Rejestr zna odczyt, który niczego nie zapisuje, i zapis, który wymaga
   kliknięcia; notatka nie jest żadnym z nich, a kliknięcie przy każdej notatce
   zabiłoby rozmowę. Notatnik asystenta nie jest poleceniem na koncie firmy: nie
   może zmienić konta i nie jest wystawiany do MCP (A9). Do innych modułów asystent
   sięga nadal wyłącznie przez rejestr — `setup_status` odczytami, `setup_apply`
   planem.
2. **Bramki, których nie da egzekutor, narzędzia niosą same:** uprawnienie i
   tenant osoby (jak zapis profilu: `assistant.use` i `organization.settings.manage`,
   członkostwo, cecha planu), schemat profilu, limit rozmiaru profilu i limit
   notatek na turę. **Jedyna droga do zapisu na koncie w rozmowie zakładającej to
   zgoda na plan z `setup_apply`** — pilnuje tego test listy narzędzi.
3. **Pochodzenie „owner” mają wyłącznie słowa właściciela z tej rozmowy.** Nie
   wynik narzędzia, nie treść wklejona jako cudza, nie strona zaimportowana w A5
   (ta ma `existing_site`). `confirmed: true` serwer przyjmuje tylko z `origin:
   owner`. Dla wartości, które stają się publiczne albo służą do kontaktu — nazwa
   firmy, telefon, e-mail, adres — serwer dodatkowo wymaga, by wartość po
   normalizacji występowała w wiadomościach właściciela w tej rozmowie; inaczej
   zapisuje ją jako propozycję asystenta (`assistant`, niepotwierdzoną) i
   konfigurator o nią zapyta. Model, który pomyli cyfrę w numerze telefonu, nie
   może oznaczyć go jako potwierdzonego.
4. **Rodzaj rozmowy: `setup` albo `operate`.** Rozmowa zakładająca dostaje
   wyłącznie trzy narzędzia z pkt 1; zwykła — rejestr jak dotąd. To także odpowiedź
   na koszt listy narzędzi: 3 definicje zamiast kilkudziesięciu w każdym wywołaniu.
   Prośbę spoza zakładania („ile mam rezerwacji?”) asystent w rozmowie zakładającej
   nazywa wprost i proponuje zwykłą rozmowę.
5. **Rozmowa zakładająca jest bezpłatna** (decyzja 23 b): tura nie rezerwuje
   kredytu. Budżety są ustawieniami platformy w `assistant.limits`: tury zakładania
   na firmę (150) i na osobę na dzień (60) — pytanie 72 a. Po przekroczeniu tura
   jest odrzucana zdaniem, które mówi, jak dokończyć ręcznie w panelu; profil
   zostaje. Bramka cechy planu zostaje, więc rozmowa zaczyna się po wyborze planu.
6. **Stanem jest profil, nie rozmowa.** Rozmowa zakładająca — nowa albo wznowiona
   — zaczyna od `setup_status`. To, co konto już ma (miejsca, osoby), trafia do
   profilu z pochodzeniem `account` i jest potwierdzone, bo to fakty; konfigurator
   nie pyta o miejsce, które istnieje.
7. **Do modelu idzie tylko to, czego wymaga pytanie.** `setup_status` nie zwraca
   profilu w całości. Zwraca nazwy miejsc i osób firmy — dane klasy `personal`,
   którą profil wdrożenia musi dopuścić; produkcja zostaje wyłączona do wpisania
   procesora w dokumentach prywatności.
8. **Poza A3-2:** strumieniowanie odpowiedzi (własny plaster, pytanie 74 a);
   cofnięcie na koncie — wszystko, co powstaje przy zakładaniu, jest wyłączone albo
   nieopublikowane, ale usuwanie wersji roboczej czeka na `discard_run` z planu
   rezerwacji; dobór narzędzi w zwykłej rozmowie — po pomiarze kosztu.
9. **Evale** (koszt do 3 USD, pytanie 73 a): notatka ma właściwe pochodzenie,
   zgadywana wartość nigdy nie jest potwierdzona, kolejne pytanie pochodzi z
   `setup_status`, plan idzie przez `setup_apply`, nigdy przez ręcznie pisane
   polecenia, rzeczy nieobsługiwane są nazywane wprost, prośba spoza zakładania
   dostaje odesłanie, a instrukcje we wklejonym tekście są danymi.

## Uzupełnienie 2026-10-03: jednostki, cennik i cofnięcie szkicu

Rozmowa zakładająca firmę ma kończyć ofertę pobytu albo wynajmu, a nie tylko ją
zakładać. Polecenia są cienkimi adapterami serwisów konfiguracji z ADR-072 §11
(`shared/booking/pricing_commands.py`).

1. **Polecenia.** `booking.offer.units.set@1` (pula jednostek oferty `range`
   doprowadzona do podanej liczby), `booking.price.save@1`,
   `booking.extra.save@1` (dopłata albo kaucja),
   `booking.participant_category.save@1`, odczyty `booking.prices.read@1` i
   `booking.quote.read@1` (wycena bez zapisu — jedyne miejsce, w którym powstaje
   cena) oraz `booking.offer.discard@1`.
2. **Cena, którą zobaczy klient, nie jest szkicem.** Cena, dopłata i jednostka
   oferty wyłączonej niczego nie zmieniają w tym, co da się zarezerwować — klasa
   `draft`. Ten sam zapis dla oferty włączonej, albo dla grupy lub jednostki, którą
   rezerwuje oferta włączona, podgląd podnosi do `apply`: obowiązuje od razu dla
   nowych rezerwacji (rezerwacje już złożone mają zamrożoną wycenę). Kategoria
   uczestników należy do całej firmy, więc jest `apply` zawsze. Odrzucone:
   `publish` dla ceny oferty włączonej — zmiana jest odwracalna i dotyczy
   działającej konfiguracji, czyli definicji `apply` z pkt 2; osobne kliknięcie na
   każdą cenę sezonu zrobiłoby z cennika serię dialogów.
3. **Słowa zgody pisze serwer z podglądu zapisu**: kwota, za co, brutto albo netto
   (ustawienie firmy `pricing.entry.amounts`), stawka VAT, sezon i zawężenia. Model
   nie ma jak podmienić kwoty między tym, co pokazał, a tym, co się zapisze —
   digest wiąże argumenty i klasę.
4. **Jednostki tylko przybywają.** `booking.offer.units.set@1` dostaje liczbę
   docelową, zakłada grupę pod nazwą oferty (albo bierze grupę firmy o tej nazwie),
   podpina ją i dodaje brakujące jednostki „<grupa> <numer>”. Liczba mniejsza niż
   stan to odmowa `units_cannot_be_removed` na polu `count`: jednostka może mieć
   rezerwacje, więc wyłącza się ją z nazwy, w panelu. Serwis
   `setup.set_offer_units` jest jednym zapisem konfiguracji (klucz z
   pokwitowaniem, wersja oferty, podgląd) złożonym z tych samych zapisów grupy i
   jednostki, których używa panel.
5. **Cofnięciem poleceń zakładających szkic jest `booking.offer.discard@1`** —
   adapter `setup.discard_draft`: usuwa ofertę nigdy niewłączoną i bez rezerwacji
   razem z jej cenami, dopłatami i zasadami sezonów; jednostki i grupa zostają.
   Klasa `irreversible` (osobne kliknięcie, „Nie da się cofnąć”), bo kwoty wpisane
   przez właściciela giną. `booking.offer.create@1` i `booking.preset.apply@1`
   wskazują je jako `undo` (zamiast etykiety `discard_run`). W rozmowie
   zakładającej firmę cofnięcia jeszcze nie ma: ma ona trzy narzędzia własne
   (pkt 1 poprzedniego uzupełnienia), a usunięcie oferty z notatek nie usuwa
   szkicu z konta — konfigurator tylko dokłada.
6. **Pieniędzy się nie zgaduje.** W rozmowie zakładającej cena trafia do planu
   tylko jako kwota, którą właściciel sam napisał w rozmowie (serwer sprawdza
   liczbę w jego wiadomościach, jak telefon i e-mail z pkt 3 poprzedniego
   uzupełnienia), w walucie firmy, za to, co oferta potrafi liczyć, i ze stawką
   VAT podaną przez właściciela — profil dostaje pole `offers[].vat`. Stawka nie
   ma wartości domyślnej: przy cenniku netto zmienia kwotę, którą płaci klient, a
   przy brutto — podział na netto i podatek w zamrożonej wycenie. Odrzucone:
   domyślne 23% jak w formularzu panelu — w formularzu właściciel widzi pole i
   sam je zmienia, w rozmowie zobaczyłby stawkę dopiero w dialogu zgody. Oferta,
   która ma już cenę, zostaje nietknięta. W zwykłej rozmowie tę samą regułę niosą
   opisy poleceń (`amount_minor` i `vat_code` to słowa osoby) i dialog zgody z
   kwotą.
7. **Dodane pola wyjścia** (pkt 4 uzupełnienia „profil firmy i konfigurator”):
   `booking.setup.read@1` zwraca `groups`, `booking.preset.list@1` — `range_unit`
   presetu `range` (noc albo dzień), żeby konfigurator umiał powiedzieć, że cena
   „za dzień” nie pasuje do noclegu, zanim oferta powstanie.
8. **Retencja asystenta przeszła pod wspólny przebieg prywatności** (zamyka pkt 7
   uzupełnienia „profil firmy i konfigurator”): przemiatania
   `assistant.conversations` i `assistant.profile_versions` z regułą
   `platform_days(assistant.retention.conversation_days)`; własne zadanie
   `purge_assistant_conversations` i wpis harmonogramu `assistant-purge` usunięte.

## Uzupełnienie 2026-10-04: cofnięcie w rozmowie ustawiającej, sezony i rodzaje gotowe

Zamyka trzy rzeczy, które poprzednie uzupełnienie zostawiło otwarte: cofnięcie szkicu
w samej rozmowie ustawiającej, zasady sezonów jako polecenia i pytanie o rodzaj
rezerwacji, które podawało też rodzaje jeszcze niedostępne.

1. **Polecenia sezonów.** `booking.seasons.read@1` (`read`) i `booking.season.save@1`
   to cienkie adaptery `rules.list_rules` i `rules.save_rule` (ADR-072 §5 i §11;
   `shared/booking/season_commands.py`): sezon usługi, grupy jednostek albo jednostki
   — daty i zasady rezerwacji w nich (najkrótszy i najdłuższy pobyt, wielokrotność,
   dni przyjazdu i wyjazdu, wyprzedzenie, termin zamknięty, przerwa po pobycie).
   Klasa jak przy cenie (pkt 2 poprzedniego uzupełnienia): sezon oferty wyłączonej to
   `draft`, a oferty włączonej — albo grupy lub jednostki, którą taka rezerwuje —
   podgląd podnosi do `apply`, bo obowiązuje od razu dla nowych rezerwacji. Słowa
   zgody pisze serwer z podglądu zapisu, słowami panelu „Sezony i zasady”. Pole o
   wartości null zostaje, jak było; zasady nie da się tu wyczyścić, a sezonu usunąć —
   wyłącza się go (`active: false`), usuwa w panelu. Cofnięciem jest to samo
   polecenie. Odrzucone teraz: osobne polecenia usuwania sezonu i dni zamkniętych —
   ustawienie firmy ich nie potrzebuje, dojdą z asystentem codziennym (A7).
2. **Sezony w rozmowie ustawiającej.** Profil dostaje `offers[].seasons`: jedną
   wartość z listą sezonów, jak tydzień pracy osoby — daty zawsze, a z zasad tylko
   najkrótszy pobyt i dni przyjazdu, i tylko te, które właściciel nazwał. Konfigurator
   planuje `season:<oferta>:<pierwszy dzień>` po powstaniu oferty i **o sezony nie
   pyta**: sezon jest krokiem planu dopiero wtedy, gdy właściciel sam o nim powie.
   Sezon, który oferta albo jej grupa ma już na te same daty, zostaje nietknięty —
   ta sama reguła co „oferta, która ma cenę” (pkt 6 poprzedniego uzupełnienia).
   Daty przepisuje model ze słów właściciela na dni kalendarza; serwer sprawdza, że to
   prawdziwe dni we właściwej kolejności, a właściciel czyta je w dialogu zgody przed
   zapisem. Kontroli „właściciel napisał to sam”, jak dla kwoty, daty nie mają: nikt
   nie pisze dat w zapisie, w którym je przechowujemy, a sezon — inaczej niż cena —
   nie jest pieniędzmi i w wersji roboczej niczego nie zmienia dla klientów.
3. **Cofnięcie w rozmowie ustawiającej** (zamyka pkt 5 poprzedniego uzupełnienia i
   pkt 8 uzupełnienia „rozmowa zakładająca firmę”). Konfigurator nadal tylko dokłada,
   z jednym wyjątkiem: szkic (`draft`, nigdy niewłączony), który założyła rozmowa
   ustawiająca i którego nazwy nie ma już żadna oferta w notatkach — bo właściciel
   ofertę usunął albo nazwał inaczej — planuje do usunięcia poleceniem
   `booking.offer.discard@1`, jako ostatni krok planu.
   - **Skąd wiadomo, czyj to szkic.** Usługa niesie rozmowę, która ją założyła
     (`origin_ref`, ADR-072 §11); `booking.setup.read@1` zwraca ją jako dodane pole
     wyjścia, a `shared.assistant` sprawdza we własnej tabeli rozmów, które z nich są
     rodzaju `setup`, i podaje je konfiguratorowi (`setup_refs`) — konfigurator
     zostaje czystą funkcją. W rozmowie ustawiającej jedyną drogą do zapisu jest plan
     konfiguratora (pkt 2 uzupełnienia A3-2), więc jej szkic na pewno powstał z
     notatek i notatki mogą go zabrać.
   - **Zgoda.** Klasa `irreversible`: osobna grupa, jedno kliknięcie tylko na ten
     krok, ze słowami serwera (ile cen, dopłat i sezonów ginie; jednostki zostają) i
     etykietą „Nie da się cofnąć”. To samo mówią notatki obok rozmowy („…— tego nie da
     się cofnąć”, a przy usuwaniu oferty z notatek — co dalej stanie się w koncie).
     Model ma to powiedzieć sam (reguła promptu), ale **w pomiarze tego nie robi**:
     eval `undo_pl` na Sonnet 5.5 i przejście w przeglądarce 04.10 pokazują plan
     zaproponowany bez słowa asystenta o nieodwracalności
     (`docs/evals/assistant/README.md`). Dziś mówi to więc serwer i notatki, nie model
     — reguła do poprawy. Odmowa zostawia szkic i resztę planu bez zmian.
     (Poprawione tego samego dnia: zdanie pisze serwer obok planu — następne
     uzupełnienie, pkt 1.)
   - **Odrzucone:** usuwanie każdego szkicu, którego notatki nie nazywają — zabrałoby
     szkice założone w panelu albo w zwykłej rozmowie; ślad usuniętej oferty zapisany
     w profilu — drugi zapis tej samej prawdy, który nie obejmuje zmiany nazwy w
     notatkach i wymaga sprzątania; usunięcie bez kliknięcia — giną kwoty wpisane
     przez właściciela.
   - **Granice.** Nazwa, którą notatki nadal mają — potwierdzona albo nie —
     zatrzymuje szkic. Szkic przemianowany w panelu, gdy notatki mają starą nazwę,
     też dostanie propozycję usunięcia (obok założenia oferty pod nazwą z notatek):
     właściciel widzi nazwę w kroku i może nie kliknąć. Gdy retencja usunie rozmowę,
     która szkic założyła, szkic przestaje być „z notatek” i zostaje w koncie.
     (Szkic przemianowany w panelu nie jest już proponowany do usunięcia — następne
     uzupełnienie, pkt 6.)
4. **Rodzaje rezerwacji: gotowe i zapowiedziane.** Pytanie `offer_needs_kind` podaje
   jako odpowiedzi tylko presety `ready`. Zapowiedziane (`soon`) są osobną listą
   pytania, którą model dostaje słowami, bez identyfikatorów: nazywa je „wkrótce” i
   nie proponuje, więc nikt nie wybiera rodzaju, którego nie da się ustawić. Rodzaj
   zapowiedziany zapisany wcześniej w notatkach zostaje `preset_not_ready`.
5. **Dodane pola wyjścia** (pkt 4 uzupełnienia „profil firmy i konfigurator”):
   `booking.setup.read@1` zwraca `origin_ref` usługi; API notatek
   (`GET …/conversations/{id}/setup/`) zwraca w `ready[]` pole `name` — nazwę tego,
   czego notatki już nie nazywają.
6. **Prompt `assistant.setup@3`** dokłada dwie reguły: `soon` nie jest odpowiedzią;
   usunięcie oferty z notatek nie usuwa niczego z konta, a krok oznaczony
   `cannot_be_undone` asystent nazywa wprost, zanim zaproponuje plan. Evale: trzy
   nowe scenariusze (`season_pl`, `kind_soon_pl`, `undo_pl`); ocena czyta też słowa
   modelu napisane obok wywołania narzędzia, bo tam miało paść „nie da się cofnąć”.
   Wynik przebiegu 04.10 na Sonnet 5.5: 17 / 20 — `undo_pl` nie przeszedł (druga
   reguła nie zadziałała), a dwa wcześniej zaliczone scenariusze nie przeszły przez
   formę z rodzajem; pierwsza reguła („wkrótce”) i sezony przeszły.

## Uzupełnienie 2026-10-04: słowa serwera, dobór narzędzi i koszt rozmowy

Zamyka to, co poprzednie uzupełnienie zostawiło „do poprawy” (pkt 3: zdanie o
nieodwracalności i szkic przemianowany w panelu), i to, co uzupełnienie A3-2 odłożyło
„do pomiaru” (pkt 8: dobór narzędzi w zwykłej rozmowie). Pomiary:
`docs/evals/assistant/README.md`.

1. **Czego nie wolno zostawić pamięci modelu, mówi serwer.** Plan z krokiem klasy
   `irreversible` dostaje zdanie serwera obok planu — w rozmowie, przed kliknięciem:
   „Zanim się zgodzisz: tego kroku nie da się cofnąć.” i słowa podglądu tego kroku, te
   same, które pokazuje okno zgody (`turns.warning`). Powstaje przy `offer_plan`, w obu
   rodzajach rozmowy; czeka z planem (`pending.said`), po kliknięciu albo odmowie
   zostaje w wyniku pierwszego kroku planu, a gdy plan jest proponowany ponownie po
   wygaśnięciu podglądu — jest pisane od nowa. API oddaje je jako zwykły tekst
   asystenta tuż przed krokami planu, więc panel nie potrzebuje zmiany. Model go nie
   dostaje: wynik kroku mówi mu, jak krok się skończył, jak dotąd. Reguła promptu
   „nazwij wprost, zanim zaproponujesz plan” znika (`assistant.setup@4`); zostaje:
   nie obiecuj, że da się to przywrócić, i nie mów „usunięto” przed wynikiem.
   Odrzucone: zdanie w wyniku `setup_status` do powtórzenia przez model — nadal zależy
   od modelu, a to właśnie nie zadziałało; odmowa `setup_apply`, dopóki model zdania
   nie napisze — dodatkowe wywołanie przy każdym cofnięciu i nadal słowa modelu.
2. **Formy z rodzajem sprawdza serwer, raz.** Reguła promptu jest jedna dla obu
   rozmów i nazywa obie formy z zamiennikami („pominąłem” → „Pominięto”, „Pomijam”;
   „żebym pokazał” → „żeby pokazać”). Odpowiedź końcowa z taką formą wraca do modelu
   z notatką panelu, która formę nazywa, zanim osoba ją zobaczy (`style.py`); ani
   wstrzymana odpowiedź, ani notatka nie trafiają do rozmowy. Pierwsza odpowiedź
   zostaje, gdy wiadomość nie ma już wywołania modelu, przepisanie się nie uda albo
   zamiast słów wraca wywołanie narzędzia; druga odpowiedź jest pokazywana, jaka jest.
   Wzorzec jest ten sam, którym ocenia eval, a runner evali robi to samo co rozmowa
   i liczy przepisane odpowiedzi (`rewritten` w raporcie) — to one mówią, czy sama
   reguła promptu działa. Wzorzec jest szerszy niż dotąd: nie lista rdzeni czasowników
   („zmieniłem” tak, „zmieniałem” nie), tylko każde słowo zakończone jak taki
   czasownik, bez rzeczowników i czasowników w czasie teraźniejszym o tym samym
   zakończeniu („działem”, „z Michałem”, „działam”, „wysyłam”), oraz „będę
   sprawdzał” i „powinienem”. Ocena jest przez to surowsza, nie łagodniejsza;
   rzeczownik wzięty za czasownik kosztuje w rozmowie jedno wywołanie, nie błędną
   odpowiedź. Koszt: jedno wywołanie więcej w około jednej odpowiedzi na dziesięć.
   Słowa pisane obok wywołania narzędzia nie są sprawdzane (przepisanie powtórzyłoby
   wywołanie) — zostają regule promptu.
3. **Zwykła rozmowa dostaje narzędzia obszarów, których dotyka** (`topics.py`), nie
   cały rejestr: każda definicja narzędzia jedzie z każdym wywołaniem modelu.
   - **Obszar** to grupa poleceń nazwana wzorcami ich nazw (firma, usługi i grafik,
     cennik, wycena, sezony, ustawienia rezerwacji, wizytówka, strona, tłumaczenia,
     dokumenty, magazyn). Polecenie, którego żaden obszar nie nazywa — polecenie
     produktu — jest obszarem po pierwszym członie nazwy, opisanym tytułami swoich
     poleceń.
   - **Obszar otwierają słowa osoby** (początki słów po polsku i angielsku: „cen”,
     „koszt”, „godzin”…), najpierw tylko jego odczyty. Polecenia zmieniające dochodzą,
     gdy osoba prosi o zmianę („zmień”, „ustaw”, „dodaj”…) — wtedy we wszystkich
     obszarach już otwartych. Słowa zbyt częste, żeby coś znaczyły („usługa”,
     „oferta”, „firma”, „strona”, „rezerwacja”), otwierają obszar tylko wtedy, gdy
     żaden nie jest jeszcze otwarty: „zmień cenę oferty Wigwamy” to cennik, nie
     usługi.
   - **Model poszerza na żądanie** jednym narzędziem własnym asystenta, `more_tools`
     (obszary i `change`); jego opis wymienia wszystkie obszary osoby, więc nic nie
     jest poza zasięgiem — kosztuje jedno wywołanie więcej. Jak trzy narzędzia rozmowy
     ustawiającej, nie jest poleceniem rejestru: niczego nie zmienia na koncie.
   - **Wybór jest czystą funkcją transkryptu**: te same wiadomości dają te same
     narzędzia, w kolejności dodania; zestaw tylko rośnie, a narzędzie raz wywołane
     w nim zostaje. Rejestr do 12 poleceń idzie w całości, bez `more_tools`.
   - **Poszerzenie kosztuje.** Dostawca liczy cache od narzędzi, więc narzędzie
     dodane w środku rozmowy zapisuje do cache całą rozmowę od nowa (zmierzone 04.10:
     4 centy przy rozmowie o 17 tys. tokenów). Stąd słowa dokładne zamiast ogólnych i
     wycena jako osobny obszar: zestaw ma być trafny od pierwszej wiadomości.
   - Wybór decyduje tylko o tym, co model dostaje: egzekutor sprawdza każde wywołanie
     jak dotąd, a port odrzuca wywołanie narzędzia, którego w żądaniu nie było. Pytanie
     o usługi nie niesie więc poleceń zmieniających — treść wszyta w wynik odczytu
     musiałaby najpierw skłonić model do sięgnięcia po nie.
   Odrzucone: wybór obszaru osobnym wywołaniem modelu — koszt i czas w każdej
   rozmowie, gdy zwykle wystarczają słowa osoby; pole `topic` w deklaracji polecenia —
   dotyka każdego modułu naraz (do wzięcia, gdy produkt zechce własnych słów
   kluczowych); stały zestaw wszystkich odczytów — około 7 tys. tokenów w każdym
   wywołaniu.
4. **Transkrypt w cache dostawcy i szczuplejsze wyniki.** Ostatnia wiadomość
   transkryptu dostaje znacznik cache (trzeci po narzędziach i prompcie; dostawca
   przyjmuje cztery): kolejne wywołanie czyta wcześniejsze wyniki narzędzi za dziesiątą
   część ceny, zamiast płacić za nie od nowa — to one, nie definicje, kosztowały
   najwięcej po pierwszym odczycie. Wynik polecenia idzie do modelu bez pól `null` i
   bez spacji po przecinkach. `booking.prices.read@1` i `booking.seasons.read@1`
   zwracają `names` — nazwy usług, grup i jednostek, do których należą ceny albo
   sezony — i `switched_off` — które z tych usług są wyłączone (dodane pola wyjścia).
   Pytanie o cenę nie czyta więc całego ustawienia firmy tylko po to, żeby dopasować
   nazwę do identyfikatora, a asystent nadal wie, że ceny oferty wyłączonej nikogo
   jeszcze nie obowiązują.
5. **Dowody i evale liczone osobno.** `ASSISTANT_PROOF_ACCOUNTS` (zmienna
   środowiskowa, lista e-maili, domyślnie pusta) nazywa konta, których rozmowy są
   dowodami: ich wywołania idą do portu z celem `eval`. Port liczy wywołania `eval` i
   `probe` tylko w sufitach miesięcznych — i od teraz tylko tam: sumy doby (puli,
   zadania, firmy, osoby) i rozmowy ich pomijają, więc dowód ani przebieg evali nie
   zabiera dnia osobie, która ogląda stos. Tylko lokalnie: stos serwowany przez https
   z tą zmienną nie startuje (`assistant.E001`, jak `model_port.E003`), a kod i tak ją
   wtedy pomija. Kredyty i limity wiadomości zostają bez zmian.
6. **Szkic poznawany po pochodzeniu, nie po nazwie** (zmienia „Granice” w pkt 3
   poprzedniego uzupełnienia). Wynik planu zapisuje przy kroku `offer:<klucz>` usługę,
   którą krok założył albo zmienił, i nazwę, którą wtedy miała (`made` w wyniku
   narzędzia — we własnej tabeli asystenta, bez zmiany w rezerwacjach).
   `shared.assistant` podaje to konfiguratorowi (`origins`), który zostaje czystą
   funkcją: usługa założona dla oferty z notatek jest tą ofertą, dopóki notatki
   nazywają ofertę tak, jak wtedy — także po zmianie nazwy usługi w panelu. Taki szkic
   nie jest proponowany do usunięcia ani zakładany drugi raz, a brakujące kroki
   (jednostki, cena, sezon) dotyczą jego. Oferta nazwana w notatkach inaczej to nadal
   inna oferta (klucz mógł zostać użyty ponownie): stary szkic do usunięcia, nowa do
   założenia — jak dotąd. Szkice sprzed tej zmiany nie mają zapisu pochodzenia i
   zostają przy nazwie. Odrzucone: pochodzenie w profilu albo w usłudze — drugi zapis
   tej samej prawdy albo zmiana modelu rezerwacji dla czegoś, co asystent już wie z
   własnych planów.
7. **Prompty i evale.** `assistant.operate@3` (reguła o obszarach: najpierw
   narzędzia, które są, `more_tools` dopiero gdy żadne nie pasuje — `@2` z tego samego
   dnia kazał sięgać po nie „zanim powiesz, że się nie da” i model wołał je także
   wtedy, gdy miał już właściwe narzędzie; wspólna reguła stylu) i
   `assistant.setup@4`. Scenariusz `undo_pl` sprawdza to, co osoba czyta w
   rozmowie: słowa modelu i zdanie serwera obok planu. Runner zwykłej rozmowy dobiera
   narzędzia tak jak rozmowa i odpowiada na `more_tools`.

## Uzupełnienie 2026-10-04: zamówienia, wpłaty i prośby o rezerwację

Polecenia nad tym, co zbudowała faza 4 rezerwacji (ADR-073, plastry 4e–4h). Zamyka
pierwszą pozycję „Poza 4h” w ADR-073; polecenia zwrotów i progów oferty zostają
otwarte (niżej, pkt 7).

1. **Polecenia.** `commerce.orders.read@1` (lista, 20 naraz, filtr stanu i
   wyszukiwanie), `commerce.order.read@1` (jedno zamówienie po identyfikatorze albo
   po numerze: pozycje, wpłaty, zwroty), `commerce.payment.record@1` (wpłata
   oznaczona ręcznie), `commerce.payment.void@1` (wpłata oznaczona przez pomyłkę) —
   `shared/commerce/command_declarations.py`, rejestrowane tylko tam, gdzie profil
   składa `shared.commerce`. `booking.requests.read@1`, `booking.request.accept@1`
   i `booking.request.decline@1` — `shared/booking/request_commands.py`, nad
   `dispatch.requests` i `services.answer_request` (ten sam klucz i ta sama odmowa
   co przyciski „Próśb”).
2. **Kupujący nie trafia do modelu.** Zamówienie nazywa jego numer i to, za co jest
   (pierwsza pozycja); prośbę — usługa, jednostka i termin. Imienia, e-maila i
   telefonu klienta nie ma w żadnym wyjściu, nie ma też osoby z firmy, która
   oznaczyła wpłatę, ani własnych słów firmy o zwrocie. Powód: pole klasy `personal`
   wymaga celu i audytowanego odczytu (pkt 1 decyzji), a tego audytu wykonawca
   jeszcze nie ma — pierwszy odczyt danych klientów nie może powstać bez niego.
   Wyszukiwanie przyjmuje słowa osoby (`q`: część numeru, nazwiska albo e-maila),
   a odpowiedź mówi, które zamówienia pasują, nie czyje są. Słowa zgody też nie
   nazywają klienta — są zapisywane przy planie w tabelach asystenta. Kto prosił,
   widać w panelu („Prośby”, strona zamówienia). Odrzucone: `personal` z celem bez
   audytu — kopia danych klientów u dostawcy modelu bez śladu, kto o nie zapytał.
3. **Pieniędzy się nie zgaduje — także przy wpłacie.** `amount_minor` i `method` to
   słowa osoby (opis polecenia); „resztę” albo „całość” model bierze z `due_minor`
   odczytu i mówi kwotę; bez kwoty albo sposobu — pyta. Słowa zgody pisze serwer z
   podglądu serwisu (`record_payment(preview=True)`, `void_payment(preview=True)` —
   nowy argument, ta sama walidacja co zapis): kwota, sposób, numer i przedmiot
   zamówienia, ile jest wpłacone po tym kroku i ile zostaje. Zgoda wiąże wersję
   zamówienia (`expected_version`), więc wpłata oznaczona w panelu między podglądem
   a kliknięciem unieważnia zgodę.
4. **Klasa `irreversible` dla wpłaty i jej wycofania** (pkt 2 decyzji: „płatność”).
   Księga jest tylko do dopisywania: wpis zostaje w historii zamówienia, a pomyłkę
   koryguje wpis przeciwny, nie usunięcie — to właśnie mówi zdanie zgody obok
   „Nie da się cofnąć”. Wpłata, która pokrywa przedpłatę, na którą czeka rezerwacja,
   mówi też, że rezerwacja zostanie potwierdzona, a klient dostanie potwierdzenie.
   Każda wpłata ma własne kliknięcie i zdanie serwera obok planu (`turns.warning`).
   Odrzucone: `apply` we wspólnym kliknięciu z innymi krokami — kwota ginie wśród
   zmian konfiguracji; `publish` — osobne kliknięcie, ale z etykietą „Będzie widoczne
   publicznie”, która o pieniądzach mówi nieprawdę.
5. **Odpowiedź na prośbę to `irreversible`**: wiadomość do klienta wychodzi od razu,
   a termin zostaje zajęty albo zwolniony. Podgląd niczego nie zapisuje — sprawdza
   stan prośby i mówi, co dostanie klient: potwierdzenie albo, gdy oferta wymaga
   przedpłaty, a firma ma zamówienia i rachunek, dane do przelewu z kwotą; gdy klient
   nie podał adresu — że trzeba dać mu znać inaczej. Prośba nie ma wersji, więc zgoda
   wiąże jej stan (`pending_request`) i słowa podglądu: odpowiedź kogoś innego albo
   wygaśnięcie to odmowa przed kliknięciem (409 `appointment_not_changeable`).
   Powód odmowy to słowa osoby — do 300 znaków, bez linku (400 `links`, ta sama reguła
   co w panelu); model go nie pisze i nie redaguje (opis polecenia).
6. **Obszary rozmowy** (`topics.py`): `orders` („zamówienie”, „wpłata”, „płatność”,
   „przelew”, „zwrot”…) i `requests` („prośba”, „odmów”…); słowa zmiany dostały
   „oznacz”, „przyjmij”, „zaakceptuj”, „odrzuć”, „odmów”, „wycofaj”. Kwota w złotych
   („zł”, „PLN”) przestała sama otwierać cennik, gdy osoba nazwała coś dokładniej:
   pada przy wpłacie równie często jak przy cenie, a definicje poleceń cennika są
   najcięższe w rejestrze. Sama — nadal go otwiera.
7. **Czego tu nie ma.** Poleceń zwrotu (`record_refund`, `void_refund`) i progów
   oferty: zwrot ponad warunki wymaga powodu słowami firmy, który może nazywać
   klienta — do rozstrzygnięcia razem z pkt 2. Odwołania i przeniesienia rezerwacji
   (A7). Rachunku do przelewów — zmienia go osoba kodem z aplikacji (ADR-073 §5).
8. **`translation.status.read@1` mówi, na czym stoi automat** (dodane pola wyjścia):
   `held` — do dwudziestu zmian, których automatyczne tłumaczenie nie zaczęło, z
   powodem i chwilą ponownej próby, jak lista „Wstrzymane” w panelu — oraz
   `held_count` i `waiting_count`. Etykieta obiektu to tekst firmy (`x-untrusted`).
   Tylko przy odczycie ostatnich zleceń; pytanie o jedno zlecenie zostaje, jak było.
9. **Raport evali mówi, co model dostał.** Runner zwykłej rozmowy dobiera narzędzia
   jak rozmowa od pakietu L3; raport podawał jednak pod `tools` liczbę poleceń
   rejestru (69) i stąd wniosek w `docs/evals/assistant/README.md`, że przebieg
   04.10 szedł na całym rejestrze — nie szedł: `read_timezone_en` kosztował w nim
   USD 0,0029 za dwa wywołania, a samo przeczytanie 69 definicji z cache dostawcy
   to około USD 0,008 na wywołanie (27,6 tys. tokenów, pomiar pakietu L2); dobór
   pilnuje też test runnera na atrapie modelu. Raport ma teraz `registry` (z czego rozmowa
   wybiera), `tools_per_call` (najmniej, mediana, najwięcej definicji w jednym
   wywołaniu modelu), `widened` (wywołania `more_tools`) i przy każdym scenariuszu
   listę `tools` — po jednej liczbie na wywołanie. Bateria dostała dziewięć
   scenariuszy tego uzupełnienia (zamówienia, wpłata w słowach osoby, „całość”,
   brak kwoty, wycofanie, prośby, dwie prośby naraz, wstrzymane tłumaczenia).
   Prompt `assistant.operate@3` bez zmian: reguły niosą opisy poleceń.

## Uzupełnienie 2026-10-04: karty osób — uchwyt dla modelu, karta dla osoby

Kierunek właściciela (04.10): asystent ma być przydatny przy klientach („czy pan
Kowalski zapłacił?”, „podaj mi telefon do klienta z jutrzejszej wizyty”), dostawcy
modeli nie mogą uczyć się na naszych zapytaniach, docelowo własny model platformy;
narzędzia mają zwracać odpowiedzi deterministyczne. Rozstrzyga pkt 2 i pkt 7
poprzedniego uzupełnienia („czy dane klientów mogą trafiać do modelu”): nie muszą.

1. **Wynik narzędzia ma dwie części.** Model dostaje nieprzezroczysty uchwyt osoby
   (`klient:k7m2q`) i fakty bez danych osobowych: numer zamówienia, kwoty, stany,
   terminy. Osoba przy ekranie dostaje **kartę** — imię i nazwisko, e-mail, telefon,
   „Kopiuj” i odnośnik do zamówienia albo dnia w kalendarzu — którą serwer czyta przy
   odczycie rozmowy, z rekordu takiego, jaki jest w tej chwili. Treść karty nie jest
   częścią żadnego żądania do modelu: model jej nie dostał, więc nie może jej
   wypisać. W tabelach asystenta nie powstaje kopia danych klienta — przy wyniku
   narzędzia zapisane jest tylko, który rekord oznacza uchwyt (`result.people`
   wiadomości `tool`, obok `content`, którego jedynego czyta model). Klient
   zanonimizowany znika więc także z kart starych rozmów — także wtedy, gdy opłacone
   zamówienie zatrzymuje jeszcze kupującego na swojej stronie (ADR-073, plaster 4i):
   karta czyta rekord klienta, nie kopię z zamówienia.
2. **Uchwyt jest wyprowadzony, nie numerowany**: HMAC z firmy, rozmowy
   (`acting_ref`), rodzaju i identyfikatora rekordu, pięć znaków base32 (dłuższy, gdy
   dwa zaczynają się tak samo). Ta sama osoba ma w rozmowie jeden uchwyt, którekolwiek
   narzędzie ją nazwie; inna rozmowa ma dla niej inny; uchwyt wymyślony nie oznacza
   nikogo. Odrzucone: `klient:1`, `klient:2` — model zgaduje sąsiedni numer i pokazuje
   cudzą kartę, a ten sam numer w dwóch rozmowach znaczy dwie różne osoby.
3. **Rejestr poleceń** (`core/organizations/command_people.py`, eksport z
   `core.organizations.api`): `person_handle(kind, id)` — polecenie pisze uchwyt tam,
   gdzie odpowiedź znaczy osobę; `resolve_person(kind, handle, field=…)` — polecenie
   przyjmujące uchwyt dostaje rekord albo odmawia `person_handle_unknown` z nazwą
   pola; `known_people(book)` — kanał (rozmowa) wykonuje plan ze swoją księgą
   uchwytów, a wydane przy tym uchwyty do niej trafiają; `register_person_kind` i
   `person_cards` — moduł-właściciel rekordu robi kartę dla wołającego. Rozwiązuje
   się tylko uchwyt z księgi wołającego, więc uchwyt z innej rozmowy, z innej firmy
   albo zgadnięty jest odmową — także w podglądzie planu i przy wykonaniu po zgodzie
   (ta sama księga). Wykonanie poza kanałem z księgą wydaje uchwyty, których nic
   potem nie rozwiąże.
4. **Kto co widzi — jak w panelu.** Rodzaj `customer` należy do `shared.customers`,
   ale reguły widoczności są tam, gdzie panel pokazuje klienta
   (`register_customer_viewer`): kalendarz mówi nazwisko na każdej wizycie, którą
   osoba widzi, a e-mail i telefon planującym wizyty i osobom na tej wizycie
   (ADR-067, `visible_contacts`); zamówienia mówią kupującego temu, kto czyta
   zamówienia. Karta to suma tego, co pozwalają moduły; klienta, którego żaden nie
   pokazuje wołającemu, wyszukiwanie nie znajduje, a jego karta jest pusta („osoba,
   której danych nie widzisz”). Karta nie jest audytowanym odczytem `personal` z pkt 1
   decyzji: model niczego nie dostaje, a osoba widzi to, co pokazałby jej panel.
5. **Polecenia.** Nowe: `customers.find@1` (słowa osoby — imię i nazwisko, e-mail
   albo telefon — dopasowuje serwer; wynik to uchwyty, co pasowało i skąd panel zna
   osobę; uprawnienie `organization.read`, bo widoczność rozstrzygają moduły) i
   `booking.appointments.read@1` (wizyty i pobyty z dni od–do, jak lista kalendarza
   tej osoby: usługa, godziny na zegarze firmy, miejsce, jednostka, stan, numer
   zamówienia, klient jako uchwyt). Dodane pola wyjścia: `buyer` w
   `commerce.orders.read@1` i `commerce.order.read@1`, `customer` w
   `booking.requests.read@1`. Dodane wejście `customer` (uchwyt) w
   `commerce.orders.read@1` — w istniejącej wersji: odczyt nie wiąże planu ani zgody,
   więc żadna zapisana zgoda nie zależy od kształtu jego wejścia.
6. **Zapis o osobie bierze uchwyt** — mechanizm (pkt 3) jest i ma testy; dziś żadne
   polecenie zapisujące nie nazywa osoby (rezerwacja dla klienta, odwołanie i
   przeniesienie to A7) i pierwsze takie użyje go bez zmian w rejestrze.
7. **Imię wpisane przez osobę to jej słowa** i jedyne dane osobowe klienta, jakie
   model widzi: trafia do modelu z wiadomością i wraca w jego własnym wywołaniu
   (`q`). Serwer dopasowuje je do rekordów i oddaje uchwyty.
8. **Rozmowa** (`assistant-chat.md`): prompt `assistant.operate@5` (reguła o
   osobach; uchwyt jest jedynym identyfikatorem, który wolno napisać, a o samym
   uchwycie model osobie nie mówi — `@4` tego zdania nie miał i model tłumaczył
   „Dostaję tylko uchwyt, na przykład …”, gdzie osoba czyta imię i nazwisko); obszar
   `customers` (`customers.find`, `booking.appointments.*`; słowa „telefon”,
   „kontakt”, „nazwisko”, „mail”, „kalendarz”, „wizyta”, „pobyt”, a „klient”, „jutro”
   i „dziś” tylko, gdy nic dokładniejszego nie padło); obszar `documents` zawężony do
   `customers.document*`; obszar `orders` dostał „zapłacił”, „zapłacone”, „opłacone”
   („ile zapłaci” zostaje wyceną). API rozmowy oddaje przy tekście asystenta `people`
   — karty uchwytów, które ten tekst nazywa; panel pokazuje imię i nazwisko w miejscu
   uchwytu i kartę pod tekstem.
9. **Dostawcy modeli** (`model-port.md`, „Dostawcy i prywatność zapytań”): ustawienie
   platformy `model_port.privacy.no_training_providers` (domyślnie włączone) —
   zapytania idą tylko do dostawców, którzy nie zapisują promptów i nie uczą na nich
   modeli, a gdzie model ma takie serwery, bez przechowywania danych (ZDR); gdy żaden
   taki dostawca nie obsługuje modelu, wywołanie kończy się błędem konfiguracji i
   nic nie jest wysyłane ponownie. Zapytania klasy `personal` — każda rozmowa
   asystenta — idą tak zawsze, cokolwiek mówi przełącznik. Drugie ustawienie,
   `model_port.privacy.claude_provider`, nazywa jedynego dostawcę, który może wykonać
   żądanie do modelu Claude — bez zastępców, a odpowiedź od kogoś innego to błąd.
   Domyślnie `google-vertex/europe` (Google Cloud, Vertex AI, region europejski żądany, niepotwierdzony;
   decyzja właściciela z 04.10): do tego dnia rozmowy obsługiwał Google, którego
   dokumenty nie nazywały, a sam Anthropic nie ma u OpenRoutera punktu ZDR, więc nie
   może wykonać żadnej rozmowy asystenta. Odpowiedź potwierdza dostawcę, nie region
   (`model-port.md`, „Dokładny dostawca dla modeli Claude”).
10. **Dowody.** `tests/test_assistant_people.py`: każde żądanie, które port przekazał
    adapterowi, zamienione na dokładne JSON dla OpenRoutera i przeszukane pod kątem
    imienia, nazwiska, e-maila i telefonu każdego klienta — jest tam tylko to, co
    osoba wpisała (test czerwienieje po dodaniu `buyer_name` do wyjścia); karta dla
    właściciela, dla pracownika na wizycie i poza nią, po anonimizacji; uchwyt z innej
    rozmowy, z innej firmy i wymyślony. Evale: pytanie po nazwisku, prośba o telefon,
    wyszukanie po e-mailu, uchwyt z innej rozmowy, prośba o wypisanie danych z karty —
    12 / 12 na Sonnet 5.5 za USD 0,30 na prompcie `@4` i 13 / 13 za USD 0,30 na `@5`,
    już u przypiętego dostawcy (`docs/evals/assistant/README.md`).
11. **Czego tu nie ma.** Osoby firmy (pracownicy) nadal są nazwami w
    `booking.setup.read` (klasa `personal`, bez zmian). Polecenia zwrotów z powodem
    słowami firmy zostają otwarte. Wyszukiwanie klienta porównuje bez polskich znaków
    i po rdzeniu nazwiska („Brzeczyszczykiewicz”, „Kowalskiego”, „z Kowalską” znajdują
    właściwe osoby) — tanio: rdzeń „Kowalsk” znajduje i Kowalskiego, i Kowalską, a
    osoba wybiera na kartach; krótkie imiona („Anny”) nie są odmieniane, a
    wyszukiwanie zamówień po `q` zostało, jakie jest w panelu. Godziny w
    `booking.appointments.read@1` i `booking.requests.read@1` to zegar firmy bez pola
    `timezone` obok — przy tym polu model przesunął w przeglądarce godziny o dwie.
