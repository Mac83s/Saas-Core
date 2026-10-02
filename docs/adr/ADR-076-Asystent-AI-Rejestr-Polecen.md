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

`acting_context`, `deferred_tenant_context` i kontrakt zadania nigdy nie
przenoszą `acting_opened`, więc praca odroczona zaczyna z zamkniętymi
bramkami. Miejsca, które wybijają zgodę (`mint_consent`), ustawiają
`acting_opened=` albo wołają `acting_context(`, są policzone w
`tests/test_command_doors.py` z powodem każdego; tam też etykiety sufitu i
`person_gates` poleceń muszą istnieć jako etykiety bramek w kodzie.
