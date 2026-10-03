# ADR-069 — tłumaczenia AI treści: silnik `shared.translation`, protokół źródeł, tryb firmy i kredyty za znaki

**Status:** Accepted — decyzje właściciela z 2026-10-02: tłumaczenie AI to funkcja
rdzenia na OpenRouter, budowana najpierw; firma wybiera automat (domyślnie) albo
akceptację, z wartością domyślną operatora; kredyty za 1000 znaków na język docelowy;
odpowiedzi 2, 2b, 3, 4 i 7 drugiej rundy (memex
`multilingual-customer-sites-full-page-bodies-aut`,
`owner-answers-02-10-on-multilingual-plan-cheapes`,
`ai-translations-go-live-only-through-derived-pub`,
`credits-are-metered-by-quantity-with-partial-per`); plan memex
`saas-core-wielojezycznosc-i-tlumaczenia-ai`, fazy TL0, TL5–TL7, TL11, TL21.
**Data:** 2026-10-02

**Zmienia częściowo** ADR-035 §4 (127-129: cennik i publikacja masowa przy
tłumaczeniach — pkt 16), ADR-035 §4a (136-153: polityka automatyzacji podstrony i
blokada edycji nie dotyczą zleceń tłumaczeń — pkt 16), ADR-035:228 (odrzucony
przełącznik „auto” nie obejmuje trybu tłumaczeń — pkt 12) i ADR-045:72-74 (wynik
rozdzielny rozlicza część dostarczoną — pkt 24); robi wąski wyjątek od pilotażu
autonomii fali W9.6 (pkt 17). Port modeli i ponowienie wyniku nieznanego — ADR-068;
treść podstron per język, pochodna publikacja i wstrzymanie po zmianie faktów —
ADR-070; języki firmy, brak cechy planu i SEO/GEO — ADR-071. Protokół źródła:
[`docs/architecture/translation-sources.md`](../architecture/translation-sources.md).

## Kontekst

Właściciel 02.10: tłumaczenie treści przez AI jest potrzebne w MVP Business, HoofCare,
MedPlano i Puppily. Druga runda: cena X po evalach (2); tłumaczenie odrzucone w
przeglądzie kosztuje jak wykonane, a odrzucone przez naszą kontrolę jakości i odmowy
modelu — nie (2b); zmiany tłumaczą się same po jednej zgodzie firmy, w miesięcznym
limicie kredytów — domyślnie 100, 0 wyłącza (3); w automacie zawsze czekają tylko
dokumenty prawne, cenniki idą przez twardą bramkę liczb i walut, opinie i cytaty
wiernie, nazwy bez zmian (4); klucz OpenRouter na wdrożenie, treści Puppily z budżetu
USD 50 miesięcznie z potwierdzeniem powyżej USD 5 (7).

Dziś koszt operacji kredytowej jest stały, a rozliczenie „wszystko albo nic”
(`shared/billing/credits.py:113-123`, `:357-367`); obszar platformy nie płaci
(`shared/billing/services.py:117-126`), a kredyty wydaje tylko osoba
(`shared/image_generation/services.py:150`). `shared.sites` traktuje jako
automatyzację każdy kontekst inny niż członkostwo (`shared/sites/services.py:810-816`)
i tylko jej odmawia stron prawnych, cennika, nowych cytatów, nawigacji, publikacji
całej witryny, wyglądu, domen i usuwania. Kanał audytu bierze się z
`principal_kind` (`core/organizations/audit.py:21-43`), a praca odroczona działa jako
zwykłe członkostwo (`core/organizations/tasks.py:182-212`): zlecenie wyglądałoby w
historii jak kliknięcie i przeszłoby obok strażników integracji. Tokeny, pochodzenie i
fakty treści są od TL8a w neutralnym pakiecie `saas_core/content_protocol/`.

## Decyzja

### Moduł i protokół źródła

1. **Silnik `shared.translation`; moduły treści od niego nie zależą.** Moduł zależy od
   `core.organizations`, `shared.billing`, `shared.notifications` i
   `shared.model-port` (zadanie `translation.text`, ADR-068) i prowadzi segmentację,
   maski, glosariusz, kontrolę jakości, wycenę, zlecenia, przegląd, rozliczenie,
   ustawienia firm i popyt automatu. Składają go profile ze stronami (`business`,
   `agro`, `vps-dev`) i typy organizacji produktów ze stronami, wizytówką albo
   rezerwacjami; `core-only` bez zmian. Tabele (`TranslationSettings`,
   `TranslationGlossaryTerm`, `TranslationJob`, `TranslationJobItem`,
   `TranslationDemand`) mają FORCE RLS, są w testach izolacji i znikają z firmą
   (ADR-042). Uprawnienia: `translation.request` (menedżer, administrator, właściciel)
   i `translation.manage` (administrator, właściciel: ustawienia, glosariusz, zgoda
   automatu).

2. **Protokół i rejestr źródeł żyją w `saas_core/content_protocol/`.** `tokens.py`,
   `provenance.py` i `facts.py` są w `main` od TL8a; `registry.py` dopisuje TL5:
   `register_translation_source(source)` (moduły w `AppConfig.ready`, produkty nowymi
   plikami — ADR-049), `register_translation_policy(policy)` (jeden obiekt silnika:
   tryb skuteczny i limit publikacji masowej, czytane przez moduł przy zapisie wyniku),
   `register_source_change_listener(listener)` (odbiorca zgłoszeń silnika) i
   `notify_source_changed(context=…, source_key=…, object_ids=…, change=…, cause=…)` z
   `change` `changed`, `withdrawn` albo `deleted`. Bez silnika polityka mówi
   „wyłączone”, zgłoszenie nic nie robi, a ręczne tłumaczenie działa. Pakiet nie importuje `saas_core.modules`
   (kontrakt `.importlinter`), więc importują go `core`, `shared` i `vertical`;
   tokeny i fakty to pojęcia treści, nie organizacji, a edycja ręczna (TL8) i
   wstrzymanie po zmianie faktów (TL9) potrzebują ich bez silnika (decyzja memex
   `the-translation-source-registry-and-protocol-liv`).

3. **Adapter jest właścicielem treści, silnik ją tylko tłumaczy.** Źródło (np.
   `sites.page`, `sites.entry`, `profiles.public_profile`, `puppily.breed`) deklaruje
   rodzaj — `versioned` z własną publikacją albo `live_record` (np. wizytówka) — i
   prawo publikacji (strony: `site.publish`, rekord na żywo: prawo edycji). Adapter
   podaje fragmenty z klasą danych, limitami i `review_always`, przenosi tłumaczenia
   na nową wersję źródła i prowadzi pamięć tłumaczeń (ADR-070 pkt 4–5), lokalizuje
   linki, podaje terminy chronione (nazwa firmy i strony, marka, imiona zespołu) i
   zapisuje własnymi serwisami: `write` z celem `draft`, `pending` albo `live`,
   `review` i `revert`. Silnik nie pisze tabel modułów, więc ich blokady, audyt,
   publikacja i odświeżenie katalogu zostają jedyną ścieżką.

4. **Wyzwalacze tylko zgłaszają popyt i nigdy nie rzucają.** Serwis źródła woła
   `notify_source_changed` w transakcji zmiany publicznego tekstu (nigdy przy zapisie
   szkicu); funkcja nie wykonuje zapytań, a odbiorca silnika zapisuje popyt dopiero po
   commicie (`on_commit`, `robust=True`): wycofana zmiana nie zostawia popytu, a błąd
   odbiorcy nie zatrzyma zapisu firmy ani outboxu stron i webhooków SCR. Zgłoszenie
   zgubione między commitem a callbackiem naprawia dobowy przegląd
   `reconcile_translation_demand`. `changed` tworzy `TranslationDemand` tylko przy
   włączonym automacie (pkt 14); `withdrawn` i `deleted` zawsze, bez kredytów, tworzą
   pozycję przeglądu „wycofaj tłumaczenia”, gdy tłumaczenie jest publiczne osobno
   (rodzeństwo wpisu). Zapis tłumaczenia, publikacje pochodne i rollback nie zgłaszają
   zmian, więc automat nie zapętla się.

### Fragmenty, dane i jakość

5. **Model widzi tylko segmenty tekstu.** Rodzaje fragmentu z protokołu: `text`;
   `inline` — bieg `core.rich_text` z pogrubieniem, kursywą i linkiem jako tokenami
   `⟦n⟧…⟦/n⟧`, a adresy linków, kotwice, zdjęcia i `rel` zostają w strukturze; `name` i
   `address` — kod je kopiuje (do cyrylicy transliteruje), nigdy nie wysyła i nie
   liczy. Rodzaj wchodzi do `unit_hash`, więc do klucza pamięci i digestu. Adresy www,
   e-maile i telefony `content_protocol.tokens.mask` zamienia w drodze do modelu na
   `⟦m:k⟧`; zapisany tekst nie jest maskowany. Fragmentu ze znacznikiem
   „[Uzupełnij: …]” silnik nie wysyła i nie liczy (`placeholder`), a wersja czeka na
   uzupełnienie źródła (ADR-070 pkt 3 i 6). Slug liczy kod z przetłumaczonego tytułu
   (ADR-070 pkt 18). Nazw firm i osób w tekście nie maskujemy — polska odmiana gubi
   dopasowanie; prowadzi je glosariusz.

6. **Klasy danych i zgoda na przetwarzanie.** Fragment ma klasę `public`,
   `public_personal` (opinie, cytaty, bio) albo `health` (nigdy do modelu); profil
   wdrożenia mówi, co wolno wysłać (`ai.sendableDataClasses`, ADR-068 pkt 9; MedPlano
   tylko `public`, z testem w MedPlano), a fragment niewysyłany wycena pomija
   (`not_sendable`). Treść firmy wychodzi dopiero przy fladze operatora
   `model_port.processor_listed` i po jednorazowym potwierdzeniu firmy przy pierwszym
   zleceniu albo włączeniu automatu, że treść trafi do OpenRouter i dostawców modeli
   poza EOG (osoba i czas w `TranslationSettings`; bez tego `processing_ack_required`).
   Obszar platformy i evale są zwolnione — to treść operatora.

7. **Glosariusz to dane, nie polecenia.** Termin ma regułę `keep` (bez zmian w każdym
   alfabecie), `name` (bez zmian w łacince, transliteracja w cyrylicy) albo
   `translate_as`, język źródłowy, opcjonalnie docelowy i do 10 form odmiany. Termin i
   tłumaczenie mają do 120 znaków bez nowych wierszy, znaków sterujących i tokenów;
   firma ma do 500 terminów. Model dostaje tylko terminy wykryte w paczce, w tej samej
   ramie danych co segmenty.

8. **Kontrola jakości w dwóch warstwach, bez wywołania modelu.**
   - **Silnik, twarde:** każdy segment, token i maska wraca dokładnie raz, tekst
     niepusty i w limicie, bez adresu, e-maila i telefonu spoza masek; błąd to jedno
     ponowienie, potem przegląd `qa_failed`.
   - **Silnik, miękkie:** resztki języka źródłowego w dłuższych segmentach (bez
     terminów glosariusza i nazw własnych ze źródła, więc „ul. Wójcika, Łódź” w EN nie
     jest błędem), brak terminu z glosariusza, długość ponad 2,5× źródła; wynik ponad
     próg (kalibrowany evalami per para języków) idzie do przeglądu `qa_flagged` także
     w automacie.
   - **Bramka modułu przy zapisie**, ostatnia przed publikacją bez kliknięcia: fakty z
     `content_protocol.facts` jako wartości („1 200 zł” = „1.200 zł”, ale „120 PLN” ≠
     „120 zł”), tokeny, limity pól i terminy chronione (forma docelowa z dopuszczeniem
     odmiany). Niezgodność to wynik `pending` z powodem `gate_failed` i błędami pól,
     bez publikacji i bez opłaty.

9. **Wywołanie modelu i prompt injection.** Jedno wywołanie to jedna firma, jedno
   zlecenie i jeden język: pozycja albo paczka do 20 małych pozycji, razem najwyżej
   6 000 znaków i 80 segmentów, bez innego kontekstu. Prompt `translation.v1` (wersja w
   pozycji i w telemetrii portu) mówi, że segmenty i terminy to dane do dosłownego
   przetłumaczenia, także gdy zawierają polecenia; odpowiedź ma ścisły schemat
   `{translations: [{id, text}]}`, a wstrzyknięty link albo kontakt zatrzymuje kontrola
   twarda.

### Pochodzenie i poprawki ludzi

10. **Pochodzenie per fragment** to `content_protocol.provenance.Provenance(origin,
    source_hash, written_hash, model, at)`, zapisywane przez adapter obok tekstu, w tym
    samym wierszu i transakcji: `source_hash` wskazuje tekst źródła, z którego powstało
    tłumaczenie, a `written_hash` — tekst w chwili zapisu, więc późniejszą edycję widać
    bez historii. `origin`: `ai`, `human`, `integration` (SCR), `template`, `import`,
    `copy` (tekst źródła w zastępstwie — brak tłumaczenia) i `untranslated` (z zasady
    nietłumaczony). Stany fragmentu: brak, aktualny, nieaktualny (inne źródło),
    poprawiony (`human`, `integration` albo tekst inny niż `written_hash`), czeka,
    błąd.

11. **Poprawek ludzi i SCR nic nie nadpisuje po cichu.** Poprawiony fragment z
    niezmienionym źródłem jest pomijany w wycenie i w automacie. Po zmianie źródła jest
    tłumaczony i płatny jak każdy zmieniony, ale wynik czeka obok poprawki
    (`overwrites_human`, ADR-070 pkt 5) i nigdy nie zapisuje się sam. Od razu zastępuje
    poprawkę tylko zlecenie osoby z `overwrite_edits`, z liczbą poprawek w oknie
    wyceny.

### Tryby i kto działa

12. **Tryb firmy i sufit operatora; przy zapisie wygrywa najsurowszy.** Tryb firmy to
    `automatic` albo `review`; brak wartości to tryb wdrożenia z profilu
    (`ai.translationDefaultMode`, brak = `automatic`; MedPlano — `review`, rekomendacja
    i pytanie 9 planu). Tryb skuteczny przy zapisie wyniku to najsurowszy (`off`,
    `review`, `automatic`) z: trybu z wyceny, bieżącego trybu firmy, nadpisania
    operatora dla firmy i sufitu wdrożenia (pkt 30). Moduł pyta o niego przy każdym
    zapisie, także dla zleceń w kolejce, więc przełączenie w incydencie działa od
    następnej pozycji; `off` zatrzymuje wysyłkę, a niezapisane wyniki przepadają bez
    opłaty. To nie jest przełącznik „auto” odrzucony w ADR-035:228: automat tłumaczy
    tylko treść opublikowaną przez osobę albo grant SCR, nie pisze źródła ani
    struktury i działa w granicach pkt 16.

13. **Kliknięcie działa jako ta osoba.** Zlecenie z panelu — także od asystenta po
    zgodzie kliknięciem — wykonuje się jako członkostwo klikającego. Worker przy każdej
    pozycji sprawdza aktywne członkostwo, uprawnienie, prawo zapisu i entitlement
    źródła, jak przy obrazach AI; utrata praw kończy pozycje kodem
    `authorization_revoked`. Wynik osoby bez prawa publikacji (menedżer nie ma
    `site.publish`) czeka na akceptację także w automacie (`publisher_required`).

14. **Automat zmian: jedna zgoda i miesięczny limit (odpowiedź 3).** Włącza go jednym
    aktem osoba z `translation.manage`, z ceną i limitem na ekranie. Wyzwalacze bez
    kliknięcia (publikacja przez osobę, SCR albo harmonogram) działają jako
    członkostwo osoby od zgody, sprawdzane przy każdym uruchomieniu; bez takiej osoby
    automat staje i powiadamia właścicieli, a kto potwierdzi ponownie, zostaje nową
    osobą od zgody. Limit to domyślnie 100 kredytów miesięcznie (stała liczba, nie pula
    planu; 0 wyłącza), liczony z kredytów zarezerwowanych i rozliczonych przez zlecenia
    bez kliknięcia w miesiącu UTC. Popyt łączy się w jeden wiersz na obiekt i czeka 5
    minut; popyt witryny daje jedno zlecenie dla wszystkich jej żywych języków.
    Wyczerpany limit, brak kredytów albo dostawcy blokują popyt z powodem, a ostatnie
    dobre tłumaczenie zostaje publiczne jako nieaktualne albo — po zmianie faktu —
    wstrzymane z 307 (ADR-070 pkt 10).

15. **Audyt „w imieniu” i bezpiecznik kontekstu (A1a, ADR-076).** Kontekst zostaje
    członkostwem: osobny `principal_kind` odziedziczyłby blokady integracji i odmówił
    stron z cennikiem albo opinią, wbrew odpowiedzi 4. Zlecenie działa w
    `deferred_tenant_context(..., acting_via="ai_translation",
    acting_ref="translation_job:<id>", acting_trigger=…)` z `core.organizations.tasks`,
    a `record_audit` zapisuje te pola w kolumnach `acting_via`, `acting_ref` i
    `acting_trigger`; `channel` zostaje principalem (członkostwo). Wyzwalacz to `user`
    (kliknięcie albo publikacja osoby), `api_key` (publikacja SCR), `schedule`
    (harmonogram) albo `conversation:<id>` (zlecenie asystenta po zgodzie). Działanie
    „w imieniu” nigdy nie poszerza praw. **Bezpiecznik:**
    `ACTING_PERSON_GATE_ALLOWED["ai_translation"]` jest pusty — każda bramka
    `assert_person_required` odmawia zleceniu (403 `person_required`); zlecenie
    publikuje wyłącznie pochodną publikacją `translation_job` z serwisów tłumaczeń
    modułów, które same stosują granice z pkt 16. Zapis i publikacja źródła (szkic
    podstrony, `publish_site`, wpis źródłowy) i wydatki kredytów spoza tłumaczeń
    (obrazy AI, audyt SEO) odmawiają `acting_via="ai_translation"`. Test woła każde z
    tych miejsc z kontekstem zlecenia; wpis na liście dozwolonych wymaga zmiany tego
    ADR.

### Granice automatu (ADR-035 §4 i §4a)

16. **Granice sprawdza serwis zapisu tłumaczeń modułu przy każdym zapisie wyniku:**
    1. **Dokumenty prawne zawsze czekają** (strony `PageType.LEGAL`, dokumenty prawne
       Puppily, źródła z `review_always`); asystent akceptuje je tylko ze step-upem.
    2. **Cennik wychodzi sam wyłącznie przez twardą bramkę faktów** z pkt 8, bez
       potwierdzenia osoby — zmiana ADR-035:127-129 w części „cennik” (odpowiedź 4).
       Opinie i cytaty wiernie, autorzy bez zmian.
    3. **Nawigacja bez zmian struktury**: etykiety menu to przetłumaczone tytuły stron
       (`NavigationItem` nie ma własnej etykiety, `shared/sites/models.py:1052-1053`).
    4. **Usuwa tylko osoba**: zlecenie nie usuwa podstrony, wpisu, tłumaczenia ani
       języka; wycofanie źródła to pozycja przeglądu (pkt 4).
    5. **Domeny i ustawienia witryny nietknięte** (wygląd, domeny, przekierowania,
       język źródłowy, polityki automatyzacji); hasło i stopka to teksty witryny
       tłumaczone po skrócie (ADR-070 pkt 15).
    6. **Pierwsze wejście języka na witrynę tylko po kliknięciu osoby** („Dodaj
       język”, „Przetłumacz” z wyceną). Zlecenie bez kliknięcia tłumaczy tylko języki
       już żywe (`live_locales`, ADR-070 pkt 7) i tylko wersję źródła z bieżącej
       migawki, nigdy szkic (ADR-070 pkt 6 i 9).
    7. **Publikacja masowa**: zlecenie bez kliknięcia publikuje najwyżej N podstron
       (ustawienie operatora, domyślnie 20), a resztę zostawia jako jedną pozycję
       `mass_publication` do akceptacji jednym kliknięciem; zlecenie osoby obejmuje
       zakres wyceny, a okno mówi, ile podstron wyjdzie od razu.
    8. **Blokada edycji (ADR-035:145-150) nie wstrzymuje zlecenia**, bo ono nie pisze
       źródła; wersja językowa ma własną blokadę (`body_version`, ADR-070 pkt 2), a
       starszy zapis przegrywa konfliktem 409.
    9. **Polityka automatyzacji podstrony i kolekcji (ADR-035:136-143, 152-153)
       dotyczy integracji piszących źródło, nie zleceń tłumaczeń** — domyślne `manual`
       zrobiłoby z odpowiedzi 3 martwy przełącznik, a zlecenie i tak ograniczają
       punkty 1–8 i tryb z pkt 12.

17. **Wąski wyjątek od pilotażu autonomii.** Fala W9.6 dopuściła autonomiczną
    publikację integracji tylko w obszarze platformy (`SITES_AUTONOMOUS_PILOT_ONLY`,
    `config/settings/base.py:215-223`, wyprowadzony z ADR-035:214-215). Automatyczna
    publikacja tłumaczeń na stronach klientów jest świadomym wyjątkiem: tylko wersje
    języków innych niż źródłowy, tylko treść opublikowana przez osobę albo grant SCR,
    nigdy struktura ani powierzchnie z pkt 16.1 i 16.3–16.5, w trybie firmy, z
    wyłącznikiem i wymuszonym przeglądem operatora (pkt 30). Granty SCR pilotaż nadal
    ogranicza.

### Zlecenia i publikacja

18. **Wycena z digestem.** `POST /api/v1/translation/quotes/` niczego nie zapisuje.
    Liczy punkty kodowe widocznego tekstu źródłowego fragmentów do przetłumaczenia per
    (obiekt, język) — bez tokenów, adresów, slugów i promptu — i pomija z powodem
    poprawione bez zmiany źródła, w toku, bez zmian, niewysyłane i ze znacznikiem
    braku, a osobno liczy propozycje z pkt 11. Pokazuje znaki, jednostki, kredyty i
    saldo po zleceniu (dla obszaru platformy USD), tryb skuteczny i części zlecenia.
    Digest to SHA-256 kanonicznej wyceny razem z wersjami i skrótami źródła, trybem i
    ceną.

19. **Zlecenie, pozycje i worker.** `POST /api/v1/translation/jobs/` przyjmuje
    `Idempotency-Key`, digest i oczekiwany koszt; nieaktualny digest daje 409
    `translation_quote_changed` z nową wyceną, zmieniona cena — 409
    `credit_price_changed`. `TranslationJobItem` (obiekt × język) to trwała kolejka z
    jedną aktywną pozycją na parę; nowszy wynik zastępuje oczekujący (`superseded`).
    Część zlecenia ma najwyżej 500 jednostek; większe zlecenie ma kilka części z
    jednym digestem i jedną zgodą, każda z rezerwacją kredytów przy starcie. Zadanie
    okresowe co minutę na kolejce `ai` zamienia dojrzały popyt w zlecenia i pilnuje
    terminów; worker (`worker-ai`) bierze pozycję albo paczkę z dzierżawą 5 minut,
    dopuszcza ją w porcie po przejęciu dzierżawy, woła model poza transakcją i zapisuje
    w transakcji sprawdzającej dzierżawę (wzór `shared/image_generation/worker.py`).
    Błędy portu (ADR-068): `output_truncated` dzieli paczkę na pół aż do jednej
    pozycji; `refused` albo `invalid_output` paczki wysyła każdą pozycję osobno, a
    pojedynczej — kieruje ją do przeglądu `model_refused` bez ponowienia na tym samym
    modelu; `unknown_outcome` wraca najwyżej raz przez `resend_of`; `budget` to
    czekanie z godziną, nie błąd.

20. **Termin i zakończenie częściowe.** Część zlecenia ma termin 72 h od startu;
    czekanie na pulę portu przesuwa go najwyżej do 7 dni, a z nim ważność rezerwacji
    kredytów. Po terminie część kończy się jako `succeeded`, `partial` albo `failed`,
    rozlicza dostarczone, zwalnia resztę i zgłasza rozliczenie do telemetrii portu
    (`record_settlement`); panel proponuje „Przetłumacz brakujące”. Anulowanie
    zatrzymuje wysyłkę i rozlicza dostarczone.

21. **Kiedy zlecenie publikuje (ADR-070 pkt 11).** Pochodną publikacją
    `translation_job` raz na partię i witrynę: partia zamyka się na końcu części
    zlecenia albo wtedy, gdy część czeka na pulę portu dłużej niż 30 minut — gotowe
    pozycje wychodzą wtedy od razu, bo wersja wstrzymana po zmianie ceny nie powinna
    czekać godzinami. Strona główna języka jest pierwszą pozycją, a język wchodzi na
    witrynę dopiero z nią (ADR-070 pkt 7). Do publikacji trafiają tylko wersje
    publikowalne według ADR-070 pkt 6, z decyzją `live` według reguł
    `content_protocol.policy.decide_publication`; pozostałe czekają w `body_pending` z
    powodem (`legal_document`, `review_mode`, `operator_forced_review`,
    `publisher_required`, `locale_first_appearance`, `mass_publication`,
    `overwrites_human`, `qa_flagged`, `gate_failed`). `publish_site` zlecenie nie woła
    nigdy.

22. **Cofnięcie zlecenia.** „Cofnij ostatnie zadanie” (osoba z prawem publikacji) i
    `translation_revert_job --job <id> --operator --reason` wołają `revert` adaptera:
    strony — pochodna publikacja `translation_revert` z wersjami sprzed zlecenia
    (ADR-070 pkt 11 i 13); wpisy — poprzednia wersja rodzeństwa; rekordy na żywo —
    poprzedni tekst i pochodzenie, z audytem. Cofnięta pozycja wstrzymuje automat dla
    tej pary (obiekt, język) i tej wersji źródła, dopóki źródło się nie zmieni albo
    osoba nie kliknie „Przetłumacz”. Kredyty nie wracają same; zwrot to audytowana
    korekta operatora (`grant_operator_credits`).

### Kredyty i budżet platformy

23. **Operacja `translation.characters` liczona ilością.** Jednostka: 1000 widocznych
    znaków źródła × jeden język docelowy; cena: X kredytów. Billing dostaje (migracją
    odwracalną) `CreditOperation.unit`, rezerwację z ilością, ceną jednostkową i
    okresem puli, ilość w księdze i `settle_credits(key, quantity)`, które w jednej
    transakcji zatwierdza dostarczoną ilość (najpierw z puli planu), zwalnia resztę i
    działa po terminie rezerwacji, dopóki jest ona utrzymana. Zwolnienie robi jedna
    funkcja, która wygasza zwolnioną pulę z poprzedniego miesiąca — używają jej
    `release_credits`, `settle_credits` i sprzątanie. Ilość domyślna 1 zostawia obrazy
    i audyt SEO bez zmian. Zlecenie osoby: suma znaków zaokrąglona w górę raz na
    zlecenie (najmniej 1 kredyt), rozliczenie z dostarczonych, nie więcej niż
    rezerwacja. Zlecenie bez kliknięcia rozlicza pełne tysiące zebrane w miesiącu;
    reszta (najwyżej 999 znaków) przechodzi na następne takie zlecenie w miesiącu —
    minimum 1 kredyt na każdą drobną poprawkę zjadłoby pulę Starter (200 kredytów,
    `shared/billing/migrations/0017_plan_credit_allowance.py:13`).

24. **Co jest płatne (2b).** Płatny jest fragment dostarczony — przeszedł kontrolę
    twardą i bramkę modułu, a kontrola miękka go nie oznaczyła — czy wyszedł od razu,
    czy czeka z powodu trybu, dokumentu prawnego, poprawki albo prawa publikacji, także
    gdy osoba go odrzuci: koszt dostawcy jest poniesiony, a tryb „po akceptacji” nie
    jest darmowym podglądem. Bezpłatne są fragmenty odrzucone przez kontrolę twardą
    albo bramkę, oznaczone przez kontrolę miękką, odmowy i złe wyniki modelu, pozycje
    `authorization_revoked` i `locale_not_enabled` oraz wyniki przepadłe po `off`. To
    zawęża ADR-045:72-74: przy wynikach rozdzielnych część dostarczona jest
    rozliczana, a reszta zwalniana.

25. **X po evalach (odpowiedź 2).** Migracja zasiewa `translation.characters` jako
    nieaktywną. Billing liczy jej koszt 0, ale silnik — jak obrazy (ADR-059), inaczej
    niż audyt SEO (ADR-045) — czyta to jako „cena nieustalona”: oferta ma
    `available=false` z powodem `operation_unpriced`, zlecenie dostaje 503
    `translation_unavailable`, a darmowych tłumaczeń dla firm nie ma. X wynika z kosztu
    zmierzonego w TL7 i wchodzi migracją danych billingu, potem edytorem kosztów planu
    ustawień.

26. **Treści platformy z budżetu USD (odpowiedź 7).** Obszar platformy (np. Puppily)
    rozlicza się w trybie `platform_budget`: bez kredytów, z wyceną w USD, w
    miesięcznym budżecie (domyślnie USD 50) w puli `translation` wdrożenia, z progiem
    potwierdzenia USD 5. Zlecenie ponad próg, także bez kliknięcia, czeka na operatora
    (`translation_confirm_job --job <id> --operator --reason`, potem panel z TL22), a
    wyczerpany budżet je wstrzymuje.

27. **Dostęp bez cechy planu.** Zlecenie wymaga entitlementu i prawa zapisu źródła
    (sprawdza adapter), uprawnienia z pkt 1, języka włączonego dla firmy i kredytów;
    cechy `translation.enabled` nie ma (ADR-071 pkt 7). Dodanie języka niczego nie
    tłumaczy i nie wydaje kredytów (ADR-071 pkt 5).

### API, evale i operator

28. **API obsługiwalne przez asystenta.** Pod `/api/v1/translation/`: oferta
    (dostępność z powodem — z portu: `processor_not_listed`, `model_not_selected`; z
    silnika: `operation_unpriced`, `worker_unavailable`, `disabled`, `suspended`,
    `processing_ack_required`; tryb skuteczny, stan automatu, dozwolone i domyślne
    wartości), ustawienia z wersją i podglądem bez zapisu, glosariusz, wyceny,
    zlecenia, stan obiekt × język i przegląd z akceptacją zbiorczą po digeście. Widoki
    spełniają minimum A1a: jawne `operation_id`, opis, wymagany `Idempotency-Key` na
    mutacjach, podglądy z `x-dry-run`, błędy walidacji 400 jako ProblemDetails z
    `errors[{field, code, message}]` i ścieżkami z kropkami, 403 `person_required`, 409
    przy konflikcie, 503 `translation_unavailable`. W rejestrze poleceń (ADR-076)
    złożenie zlecenia wymaga zgody kliknięciem z digestem wyceny (ADR-033:72-75), a
    włączenie automatu, podniesienie limitu i akceptacja dokumentu prawnego — także
    step-upu; poziomy ryzyka nadaje ADR-076.

29. **Evale przed ruchem klientów (TL7).** Zestawy pl→en, pl→de, pl→es, pl→ru i en→pl
    obejmują ładunki prompt injection, które mają wyjść przetłumaczone dosłownie, bez
    nowego linku i kontaktu; próbki z dziedzin HoofCare i MedPlano są syntetyczne,
    nigdy treść klientów. `translation_eval --max-usd` mierzy przejścia kontroli
    twardej, odsetek odmów (kryterium wyboru), ocenę sędziego z innej rodziny modeli
    (zadanie portu `translation.judge`, rejestrowane przez silnik, tylko `purpose`
    eval), koszt na 1000 znaków i p95 czasu; raporty trafiają do `docs/evals`. Model
    domyślny wybiera właściciel na liczbach; evale powtarzamy przy każdej zmianie
    modelu.

30. **Wyłącznik operatora z historią.** Sufit wdrożenia (`none`, `review`, `off`) to
    od TL6 tabela platformowa tylko do dopisywania, jak `AiBadgeSwitch`
    (`shared/sites/models.py:2067`): najnowszy wiersz to stan, a pisze ją tylko
    `translation_ceiling --operator --reason` (konto `is_staff` z MFA, zdarzenie w logu
    bezpieczeństwa). Zmienna środowiskowa odpada z powodu z ADR-059:303-304 — zmiana w
    incydencie wymagałaby odtworzenia kontenera i nie zostawiałaby śladu. Nadpisania
    firmy (wstrzymanie, wymuszony przegląd, limit automatu) zapisuje
    `translation_org_override --operator --reason` z wpisem w historii firmy. Od fazy 1
    planu ustawień sufit jest kluczem rejestru z tą samą historią, a panel przychodzi w
    TL22; pozostałe wartości (N podstron, odczekanie, termin, budżet platformy) do tego
    czasu mają domyślne w kodzie z nadpisaniem zmienną.

31. **Prywatność.** Tekst źródłowy ani wynik nie trafiają do logów, telemetrii ani
    audytu — tylko skróty, liczby i identyfikatory. Wynik leży w `TranslationJobItem` do
    zapisu przez adapter, potem zostają skróty; wyniki rekordów na żywo czekające w
    przeglądzie znikają po 30 dniach z powiadomieniem. Przekazanie poza EOG (OpenRouter
    i dostawcy modeli) wymaga standardowych klauzul umownych albo Data Privacy
    Framework i wpisu na liście podprzetwarzających, zanim operator włączy
    `processor_listed`.

## Konsekwencje

- Pierwszy wydatek kredytów i pierwsza publikacja na stronie klienta bez kliknięcia.
  Chronią je zgoda z osobą, limit, granice z pkt 16, limit podstron, sufit i wyłącznik,
  a przed błędem w kodzie — bezpiecznik z pkt 15 sprawdzany testem. RLS i wyścigi
  (publikacja, zlecenie, akceptacja, zapis fragmentu) trzeba udowodnić na działającym
  stosie, bo baza testowa omija RLS.
- Zmiana księgi kredytów dotyka każdej płatnej powierzchni; chronią ją ilość domyślna
  1, jedna funkcja zwolnienia i testy przełomu miesiąca.
- Dla firm funkcja jest wyłączona, dopóki nie ma klucza, aktywnej operacji z ceną X,
  żywego `worker-ai`, wybranego modelu, flagi `processor_listed` i potwierdzenia firmy;
  kod można wdrożyć wcześniej.
- Płynne, ale błędne zdanie (zgubione „nie”, zły termin medyczny) może w automacie
  przejść bramkę faktów; ograniczają to dokumenty prawne po akceptacji, tryb po
  akceptacji, `review` w MedPlano, pochodzenie i cofnięcie.
- Awaria OpenRoutera albo limit klucza zatrzymują tłumaczenia (fail closed, ADR-068);
  ostatnie dobre tłumaczenia zostają, ręczna edycja działa. Sufity rozkładają dużą
  witrynę na kilka dni, a panel pokazuje czekanie z godziną.
- Treści publikowane autonomicznie przez SCR tłumaczą się w automacie z kredytów firmy
  w limicie automatu (rekomendacja, pytanie 8 planu) — u klientów dopiero po zdjęciu
  pilotażu.
- HoofCare i MedPlano dostają moduł przez `core:update`: profile, klucz
  `ai.translationDefaultMode` (MedPlano `review`), moduły typów organizacji, uprawnienia
  `translation.*` ról, `.agents/evals/routing.json`; migracje i `worker-ai` idą przez
  `memex ops`.

## Rozważane alternatywy

- **Rejestr źródeł w `core.organizations`** — tokeny i fakty to pojęcia treści;
  **moduły treści zależne od silnika** — każdy profil ze stronami składałby silnik i
  port; **silnik piszący tabele modułów albo ogólna tabela tłumaczeń pól** — omija
  blokady, audyt i publikację modułów (ADR-027:60-61).
- **Nowy `principal_kind` dla zleceń** — dziedziczy blokady integracji i odmawia stron
  z cennikiem i opinią; **lista dozwolonych bramek osoby dla zleceń** — rozmywa granicę
  między decyzją osoby a publikacją zlecenia (ADR-070 pkt 12).
- **Uszanowanie polityki `manual` podstrony** — automat zmian byłby martwy na
  większości stron.
- **Darmowe tłumaczenia, dopóki X jest nieznane** — przyzwyczajają do zera; **cena od
  znaków wyniku** — nieznana przed zleceniem; **minimum 1 kredyt na zlecenie
  automatu** — drobne poprawki zjadłyby pulę.
- **Automat włączony domyślnie albo tłumaczenie przy zapisie szkicu** — wydatek bez
  zgody i płacenie za pracę w toku.
- **HTML do modelu, slug z modelu** — model nie tworzy struktury ani adresów; **twarde
  kontrole resztek języka** — nazwy miejsc i firm dawałyby fałszywe błędy.
- **W automacie czekają też cenniki, opinie i cytaty** (wariant 4c) — u fryzjera czy
  lekarza większość stron czekałaby na kliknięcie.
- **Wyłącznik w zmiennej środowiskowej** — bez śladu i z odtworzeniem kontenera w
  incydencie.

## Relacje

- **ADR-027**, **ADR-042**, **ADR-044**, **ADR-049**, **ADR-056**, **ADR-061**,
  **ADR-064** obowiązują; ten ADR je stosuje (zmiany SCR w języku docelowym mają
  pochodzenie `integration`).
- **ADR-033** — zgody i digest (72-75), MedPlano (125-130), evale z prompt injection,
  logi bez treści i fail closed obowiązują; asystent pisze po polsku i angielsku, inne
  języki robi silnik w trybie firmy (decyzja A6 planu asystenta, zmieniona 02.10).
- **ADR-035** — §4 i §4a w pkt 16, pilotaż w pkt 17, linia 228 w pkt 12; **ADR-045** —
  zawężenie 72-74 w pkt 24; **ADR-059** — wzór sufitu z historią i ceny nieustalonej.
- **ADR-068** — port, sufity i zadania; **ADR-070** — treść podstron, pamięć,
  publikowalność, pochodna publikacja, 307 po zmianie faktu, rollback; **ADR-071** —
  języki firmy, brak cechy planu, SEO/GEO i znacznik tekstu AI; **ADR-076** — rejestr
  poleceń i „w imieniu”; **ADR-077** — Puppily jako źródło tłumaczeń.

## Uzupełnienie 2026-10-03: wartości silnika jako ustawienia platformy (TL22b, pkt 30)

Pkt 30 zostawił wartości klasy A w środowisku „do czasu tabeli ustawień platformy”.
Tabela i panel „Platforma” są, więc sześć wartości silnika ma klucze w rejestrze
(grupa `translation.engine`, obszar „ai”), a kod czyta je przy użyciu — zmiana działa
bez restartu:

| Klucz | Domyślnie | Poziom operatora |
| --- | --- | --- |
| `demand_wait_minutes` — odczekanie po zmianie | 5 | 1 |
| `demand_max_wait_minutes` — najdłuższe odczekanie | 30 | 1 |
| `mass_publication_cap` — próg publikacji masowej | 20 | 1 |
| `leftover_threshold_percent` — kontrola jakości: słowa źródła | 30 | 1 |
| `length_ratio_max_percent` — kontrola jakości: długość | 250 | 1 |
| `platform_confirm_usd` — treści platformy czekają na potwierdzenie | 5 | 2 |

- Poziom 1 to strojenie pracy silnika; poziom 2 (ze step-upem) to pieniądze wdrożenia.
- `mass_publication_cap` i `platform_confirm_usd` mają wartość wdrożenia
  (`TRANSLATION_MASS_PUBLICATION_CAP`, `TRANSLATION_PLATFORM_CONFIRM_USD`, parsowane
  i sprawdzane w `settings/base.py`) pod wartością operatora — `platform_env`.
  Kwota potwierdzenia jest w całych dolarach.
- Progi kontroli jakości worker czyta raz na przebieg (`quality_thresholds()`) i
  podaje do `check_soft`; funkcja zostaje czysta, a evale liczą na wartościach z kodu.
- Zostają poza rejestrem: wyłącznik `translation.ceiling` (własna tabela i komenda z
  powodem) i sufity USD portu modeli (limity ochronne w `.env`, ADR-078).

