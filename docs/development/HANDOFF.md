# Stan bieżący Saas-Core

Ten plik opisuje **stan na dziś** i jest aktualizowany w miejscu: zmieniasz
sekcję, której dotyczy Twoja praca, zamiast dopisywać nowy wpis na górze.
Plany, fazy i odpowiedzi właściciela żyją w memeksie (`desk/plans`, projekt
`saas-core`); historia sesji — w git i w worklogach memeksu. Ostatnia wersja
dawnego dziennika (59 sekcji, do 2026-09-23):
`git show cd66b20:docs/development/HANDOFF.md`.

Stan na: **2026-09-23**. Punkty „otwarte” niżej sprawdzono tego dnia w kodzie
i git; zamknięte pozycje z dawnego dziennika zostały pominięte.

## Żywe plany (memex)

| Plan | O czym | Gdzie jesteśmy |
| --- | --- | --- |
| `saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka` | standard list panelu, szablon strony panelu, wizytówka, historia zmian, limit podstron, wyszukiwarka katalogu | fazy 1–4 i 7 zrobione (DataTable, przełącznik wizytówki, historia zmian, limit podstron; 24.09 szablon strony panelu, ADR-057, w trzech aplikacjach); faza 6 zrobiona 29.09 lokalnie, niewdrożona (22 pozostałe listy na DataTable, start panelu i ekrany SEO na PanelPage, odpowiedzi 1A i 2B); faza 5 — wyszukiwarka katalogu (ADR-064, `docs/operations/catalog-search.md`): 5a scalone 29.09, niewdrożone — Meilisearch `search` w compose (sieć `data`, limit 384 MB, sekret `search_master_key`), indeks `<DEPLOYMENT>-catalog` budowany w tenancie z usługami z Bookingu i polem bez ogonków, sygnały + `reconcile_catalog_search` co 10 min + `reindex_catalog`, powrót do PostgreSQL przy awarii, promień miasto–miasto (`radius_km`, `lat`/`lng`), edycja opublikowanej wizytówki odświeża katalog; 5b scalone 29.09, niewdrożone — wyszukiwanie po znaczeniu: wektory liczy backend przez OpenRouter (`qwen/qwen3-embedding-8b`, 1024 wymiary, sekret `catalog_embedding_api_key`, pusty = tylko słowa), `similar` w odpowiedzi („Podobne”/„Może też”), próg `CATALOG_SIMILAR_MIN_SCORE` tymczasowy do strojenia na prawdziwych wektorach — klucz od właściciela jeszcze nie włożony (lokalnie `.runtime/secrets/catalog_embedding_api_key`, VPS ops mac-20260929-23); 5c scalone 29.09 — katalog: „Nie znaleźliśmy dokładnie… Podobne:” albo „Może też” pod trafieniami, suwak promienia (miasto albo „Blisko mnie” z przeglądarki, punkt tylko w zapytaniu), odległość na karcie, pauza 300 ms przy pisaniu, `Slider` w `@saas-core/ui`, Caddy daje /katalog `geolocation=(self)`; 5d scalone 29.09 — HoofCare i MedPlano na rdzeniu 94fae08 z nakładką wspólnego silnika na dev VPS (profil `own-search`, klucz ograniczony do `<deployment>-catalog*`); VPS: ops mac-20260929-22, -23 (klucz), -25, -26, -27, -28; otwarte: klucz OpenRouter od właściciela i strojenie progu `CATALOG_SIMILAR_MIN_SCORE` na prawdziwych wektorach (produkty, wspólny silnik na dev VPS jako nakładka `own-search`); poprawki UI z 01.10 (sesja UI, zbierane przez koordynatora): zwarty nagłówek `PanelPage` z lekką linią, `PanelToolbar` (ADR-057 pkt 8), na telefonie bez opisu; miejscowość wizyty na każdym widoku kalendarza z `booking.api.register_appointment_place` (HoofCare: wieś gospodarstwa); 02.10 decyzja 14a — „Miejsce wizyty” na każdej wizycie (ADR-066, migracja booking 0012): miejscowość i adres w formularzu i w szczegółach, zapisane miejsca produktu przez `register_place_search`; decyzja 15a — slot kalendarza produktu (ADR-067), telefon, e-mail i ulica klienta tylko dla planujących i załogi; otwarte: `PUT …/place/` bez `expected_version` (przegląd 02.10, L4 — dwa biura mogą nadpisać sobie miejsce), zapisane miejsca >200 filtrowane w przeglądarce (L7) |
| `magazyn-materia-o-w-od-pakietu-korektora-do-kare` | uniwersalny magazyn firm (`shared.inventory` v2, ADR-055): dokumenty, miejsca, rezerwacje, rezerwacje stanu przy wizytach, przyszły sklep | fazy 1–8 zrobione 23–24.09 (rdzeń v2, HoofCare przepięty, panel na DataTable, włączony wszędzie, produkty przy wizycie; 24.09 wieczorem przygotowanie do wizyty i mały stan w terenie w HoofCare, raport `2026-09-24-inventory-phase7`); faza 9 (partie, ważność, FEFO, karencja leków — odpowiedzi 1a–5a z 25.09) scalona w rdzeniu (`8fd0882`, `d9da766`, `f436fe4`) i w HoofCare, **niewdrożona**; dalej wdrożenie i odbiór (na localhost) |
| `saas-core-zespol-pracownicy-i-przydzial-wizyt` | kierunek CRM (decyzja 24.09): lista pracowników z kontem i bez, zespoły, wiele osób na wizycie, dobór osoby przez serwer, przydział i „kto jest wolny”, historia i wydajność z miar produktu (ADR-058) | koncepcja i 16 makiet przyjęte 24.09 (odpowiedzi 1–8; pkt 1 „potwierdzona od razu” potwierdzony 25.09); faza 1 bez widocznych zmian (przypomnienia jako usługa i za przełożoną wizytą, terminy: dni → godziny → walidacja, dobór najmniej obciążonej osoby, przycięcie alokacji przy zakończeniu, lista wizyt z oknem, klient bez danych pracowników) wdrożona na saas i w HoofCare 25.09 (raport `2026-09-25-team-dispatch-phase1`), MedPlano scalone na rdzeniu `a1fb1ea`, niewdrożone; faza 2 (26.09, scalona do main `961e279` + poprawki z odbioru na żywo `d84a16e`, `74b6ff9`, niewdrożona; odbiór na :8080 w Studio Testowe zrobiony w całości — bez planu i z kalendarzem włączonym na czas odbioru): Zespół → Pracownicy (konta, zaproszenia, osoby bez konta i byli na jednej liście, „Dziś”, limit kont), Dodaj pracownika z usługami i godzinami, Zmień rolę w grupach Zarządzanie / Praca bez wylogowania, karta osoby z Grafikiem i nieobecnościami, Moja karta, Role i uprawnienia na DataTable, kalendarz ze stanem w adresie i oknem wizyt; faza 3 (plan przyjęty 28.09, kroki 3a–3e): 3a — backend bez ekranów: zespoły, usługa „ile osób”, skład wizyty (prowadzący + pozostali, każdy z blokadą czasu) zmieniany tylko przez `crew.set_crew`, dobór N najmniej obciążonych, terminy dla N osób, przydział z wersją składu (409 z nazwiskiem), wakaty z nieobecności i odejścia („Usuń z firmy” już nie odmawia), kolejka, „kto jest wolny”, powiadomienia pracowników w dzwonku i e-mailem; migracje booking 0009–0010, organizations 0051 (scalone do main `bb6e587`, niewdrożone); 3b — panel (28.09, lokalnie): Zespół › Zespoły, kolumna i filtr „Zespół” na Pracownikach, zespoły przy dodawaniu osoby i na karcie, sekcja Kalendarz (Kalendarz, Do przydzielenia z licznikiem — obie strony przydziału chowają się, gdy wizyty przyjmuje jedna osoba), Zmień osoby / Przydziel z wersją składu, Nowa wizyta z „Kto wykona” (osoby, zespół, dobór automatyczny, wspólne terminy) i „Uwagi”, skład i wakaty na kartach wizyt, w szczegółach i w przełożeniu, wizyty w dzwonku z linkiem do dnia (scalone do main `5a55dcb`); 3c — Ustawienia › Usługi i grafik od nowa (28.09, lokalnie): usługi, miejsca i zasoby jako listy z edycją i wyłączaniem, usługa z „ile osób”, kto wykonuje, gdzie, zasoby, wybór klienta na stronie i produktami z magazynu, gotowe usługi typu firmy otwierają formularz; stary formularz pracownika i godzin zniknął (scalone do main `ce312ff`); 3d — formularz na stronie (28.09, lokalnie): krok „Do kogo?” (zespół po nazwie albo osoba z „Pokazuj klientom”, gdy usługa na to pozwala), terminy liczą tyle osób, ile wymaga usługa, pole „Uwagi” we wszystkich produktach (tylko dla firmy, czyszczone przy anonimizacji), potwierdzenie z terminem, usługą, zespołem albo „Przyjmie Cię” i plikiem „Dodaj do kalendarza”, strona klienta z tym samym; „Pokazuj klientom” na karcie osoby (`PUT /booking/staff/{id}/public/`); 3e — `booking.api` dla produktów (`join_visit_crew`, `leave_visit_crew`, `crew_people`, `crew_member_filter`, `on_crew`), ADR-058 „Ustalenia fazy 3”, HoofCare „Kto jedzie” i „Dołącz” z blokadą czasu, MedPlano na rdzeniu (scalone do main `a3c78db`); odbiór na żywo 28.09 na :8080 i HoofCare :8081 zrobiony (kalendarz Studio Testowe włączony tylko na czas odbioru), a jego trzy znaleziska naprawione: potwierdzenie i przypomnienie mają link „Zmień termin lub odwołaj” (szablony v2, `ea384e3`), e-maile do osób ze składu znów wychodzą (rola `booking_notify`, `e2445b6`), prowadzący zdjęty z wakatu nie widzi go jako swojego (`7668086`). Faza 3 zakończona, niewdrożona: ops VPS mac-20260928-11 (migracje 3a) i -18. Faza 4 (29.09, lokalnie, odpowiedzi 1C i 2A): Kalendarz › Dzień jako tablica dnia, gdy dzień obejmuje co najmniej dwie osoby — wiersz osoby na osi godzin (grafik, nieobecność, wizyty z „Prow.” i „auto”), pas „Do przydzielenia” z dialogiem Przydziel, wolne okno otwiera Nową wizytę z osobą i godziną; na telefonie agenda według osób; filtr Pracownik z zespołami; Kalendarz pamięta ostatni widok osoby na urządzeniu (bez migracji i zmian API; main `ddebd79`, poprawki z odbioru `05fb0a5`, `2970afd`). Odbiór na żywo 29.09: :8080 Studio Testowe (kalendarz tylko na czas odbioru) — wakat w pasie i dialog Przydziel, wolne okno → Nowa wizyta z osobą i godziną, pamięć widoku, agenda na telefonie bez przewijania w bok, pracownik bez „Zaplanuj”; HoofCare :8081 (rdzeń `2a38561`, dwie osoby z godzinami tylko na czas odbioru) — tablica biura i Nowa wizyta z osobą i godziną, korektor ma listę; MedPlano :8082 bez usług i grafiku — lista. Faza 5 (29.09, lokalnie, odpowiedzi 2.1a, 2.2a, 3A, 4A): rejestr faktów pracownika `booking.api.register_staff_facts` — kalendarz (odbyte wizyty: czas minął i nie odwołano, jako prowadzący / w składzie; godziny do faktycznego końca; odwołane; wybór klienta; historia przydziałów, nieobecności i wizyt), konto i rola (historia z audytu), magazyn (pobrane, zużyte, zwrócone, na stanie po koszcie ruchu); `GET /booking/staff/{id}/facts/`, `…/history/`, `/booking/performance/`; nowe `booking.staff.performance.read` dla właściciela i administratora (booking 0011); cudzy zapas, partie, ruchy i przesunięcia tylko z `inventory.manage`; panel: Wyniki na karcie z porównaniem okresów, podstrony Historia i Magazyn, Zespół › Wydajność. HoofCare dokłada krowy, korekcje, przypadki i kontrole — autorowi wpisu. Wizyta zamknięta „Zakończ” liczy się do odbytych od razu (`5bd630e`). Odbiór na żywo 29.09 na :8080, HoofCare :8081 i MedPlano :8082 po zasiewie tablic: właściciel widzi Wydajność i karty, pracownik tylko swoje (cudze wyniki, historia i Wydajność → 403), menedżer i biuro → 403; liczby HoofCare zgodne z tabelami; telefon bez przewijania w bok. Faza 5 zakończona, niewdrożona: ops VPS mac-20260929-29 (saas), -30 (HoofCare), -31 (MedPlano) |
| `saas-core-site-studio-templates`, `saas-core-site-studio-rich-content-and-full-width` | Site Studio: szablony, warianty, bogata treść | bogata treść, pełna szerokość, wygląd strony i 3 strony demonstracyjne scalone i wdrożone 23.09 (saas, a wieczorem też HoofCare i MedPlano) (`docs/architecture/site-rich-content.md`, raport `2026-09-23-rich-content`); faza 3a (20 układów redakcyjnych pod konwersję, `core.rich_text` v3, katalog v6, ostrzeżenie o miejscach `[Uzupełnij: …]`) i 3b (8 stylów strony, kotwice sekcji i przyciski „do formularza”, 9 recept stron v5 z celem i ścieżką konwersji, 8 dawnych szablonów wycofanych z galerii) scalone 23.09; etap 2b — edytor WYSIWYG (TipTap, ADR-056) w panelu i na pełnym ekranie, panel ze składnią `**` usunięty — scalony i wdrożony na saas 24.09 (raport `2026-09-24-wysiwyg-editor`); formularz kontaktu v2 (4 warianty wymaganych pól, m.in. „Oddzwonimy” z wymaganym telefonem, egzekwowane przez serwer) wdrożony na saas 24.09 (raport `2026-09-24-contact-form-v2`); faza 4 (paczki F4-P0…P5, 24 sekcje, 3 strony, 6 dodatków branżowych): F4-P0a (katalog v7, najnowsza wersja sekcji w bibliotece, harness zrzutów) i F4-P0b (bez zmyślonych faktów w receptach, strażnik cytatów dla automatu, 503 przy zajętym skanerze, Manrope 800) wdrożone na saas 24.09 (raport `2026-09-24-phase4-p0`); F4-P1 (28.09, lokalnie; `docs/architecture/site-rich-content.md`, „Faza 4, paczka F4-P1”): `core.feature_list` v5 i 6 układów list, 4 dodatki gabinetu i gospodarstwa, recepta „Poradnik krok po kroku”, ostrzeżenia o danych przykładowych i linkach donikąd, inspektor bez pustych pól innych układów, domyślna branża biblioteki z produktu (`siteIndustry`); studio F3-Z1…Z3 (wstawianie „+” między sekcjami, zdjęcie z płótna, skróty cofania, porównanie układów z własną treścią, podstrony w studiu) i F4-A/F4-B (historia wersji strony z przywracaniem; szablony firmy — sekcja i strona z treścią, wersje, ADR-063; `docs/architecture/site-studio-editor.md`) scalone 28.09 lokalnie; F4-C (29.09, lokalnie; `docs/architecture/site-studio-editor.md`): szablon całej strony na stronie z treścią przenosi sekcje do sekcji szablonu tego samego rodzaju — podgląd „Twoja treść w nowym układzie / nowe z przykładową treścią / bez miejsca” i wybór dopisać albo pominąć, niezapisane zmiany zapisane najpierw jako wersja — oraz „Zmień rodzaj sekcji” (lista ↔ FAQ, lista/FAQ → tekst) według kontraktu `section-conversions.v1.json`; F4-P2 (29.09, lokalnie): `core.quote` v2 i 5 układów cytatów, wypowiedzi, autorzy i role jako `[Uzupełnij: …]`; F4-P3 (29.09, lokalnie; „Faza 4, paczka F4-P3”): `core.gallery` v1 i 6 układów galerii, kopie WebP zdjęć w `srcset` stron publicznych (`/media/<id>/<wariant>`), przesuwanie pozycji list w edytorze, recepta „Studio i portfolio”, automat nie pisze podpisów galerii ani kolejnych wypowiedzi cytatu; F4-P4 (29.09, lokalnie; „Faza 4, paczka F4-P4”): `core.product` v3 i 7 układów produktu, 2 dodatki elektroniki, katalog 158/150; F4-P5 (29.09, lokalnie): recepta „Kolekcja produktów” i raport fazy 4 — 24/24 nowe układy, 6 dodatków branżowych, 12/12 stron, katalog 158/150 (`docs/architecture/site-rich-content.md`, „Faza 4, paczka F4-P5”); `core:update` HoofCare i MedPlano po F4-P5 (3a). Generator obrazów AI (OpenAI GPT Image 2.5, ADR-059) wdrożony na saas 24.09 bez klucza (raport `2026-09-24-image-generation`): oznaczanie AI, odznaka i sloty dowodowe działają; generowanie czeka na klucz, pilot SynthID i prawnika |
| `saas-core-site-studio-pages-crud` | Site Studio: lista podstron na standardzie panelu, usuwanie i przywracanie podstron, sekcja „Strona internetowa” na adresach (decyzja 7, 30.09, odpowiedzi 7.1–7.9 = a; ADR-065) | L1 (backend: miękkie usunięcie i przywrócenie, natychmiastowe zdjęcie z publikacji z 301, rollback bez usuniętych; migracja `sites 0039`) i L2 (lista podstron na DataTable z akcjami, okno usuwania, filtr „Usunięte”; ustawienie nowej głównej zamienia poprzednią na zwykłą) scalone i wypchnięte 30.09 (`58fd217`, `9d6319e`; `882ee24` lokalnie), niewdrożone — ops VPS mac-20260930-4 (migracja) i -5 (backend i frontend); L3 (30.09, lokalnie): Podstrony, Menu, Blog, Publikacja, Adres i domeny, Integracje jako adresy `/panel/sites/…` w `PANEL_SECTIONS` zamiast zakładek, edytor podstrony pod `/panel/sites/pages/<id>` (`?preview=1` z podglądem), typ podstrony i automatyzacja w „Ustawieniach strony” edytora; L4 (odbiór, `core:update` HoofCare i MedPlano) w toku |
| `scr-narzedzie-marketingowe-koncepcja-i-plan` (projekt seocontentrank, części rdzenia) | pomiar i linki dla narzędzia marketingowego: granty i hosty linków (E0), licznik odsłon i agregat zapytań (K0a, ADR-060), pole `rel` (L0) | E0 po stronie rdzenia domknięte 26.09 (granty na każdej trasie klucza, publikacja planowana kluczem, luki hostów linków; migracja sites 0035), K0a w kodzie 26.09 (migracja sites 0036, zakres `content:metrics`); oba **niewdrożone** — odbiór K0a to 4 tygodnie działania na wskazanej stronie; L0 w kodzie 26.09 (ADR-061: `rel` w tekście v4, liście linków v2 i stopce v2, `nofollow` domyślnie dla linków automatyzacji), niewdrożone |
| `korekty-wpisow-po-zakonczeniu-wizyty` (projekt hoofcare, część rdzenia) | kartoteka zwierzęcia bez nadpisywania i kasowania: korekta to następna wersja z powodem, zastąpiona zostaje przekreślona (ADR-062) | 28.09 rdzeń w kodzie: `farms 0014` (wersje, `retracted_at`, wyzwalacz append-only), `publish_health_entry(correction=…)`, powiadomienie hodowcy `farms.health_corrected`, karencja z wersji obowiązujących; `unpublish_health_entry` i `drop_own_health_entry` usunięte; 28.09 „Popraw”/„Wycofaj” przy każdym wpisie ręcznym (autor, powód poza prywatną notatką, historia wersji po rozwinięciu; organizations 0050); HoofCare: korekta po zakończeniu wizyty i wersje raportu; niewdrożone |
| `saas-core-rezerwacje-uniwersalne-i-sprzedaz`, `saas-core-ustawienia-platformy-w-panelu-administratora`, `saas-core-asystent-ai-zakladanie-i-konfiguracja-firmy` | (od 01.10 plany; 02.10 faza 1 rezerwacji: ADR-072–075 i kontrakt `packages/contracts/booking-presets` z testem; kod od fazy 2) rezerwacje dla każdej branży (termin, okres od–do, wydarzenie; presety jako dane), wspólne zamówienie z płatnościami klientów przez operatora z licencją, sklep, wolne terminy w katalogu wielu firm; panel ustawień platformy z audytem ustawień zaszytych w kodzie; asystent AI zakładający firmę w rozmowie (LLM rozumie, algorytm decyduje) | **Faza 2 rezerwacji** (02–03.10, lokalnie, niewdrożone; nota dla produktów `docs/operations/releases/2026-10-03-booking-phase2.md`): §11 — każdy zapis konfiguracji ma klucz z pokwitowaniem `BookingSetupMutation`, wersję (409 `booking_version_conflict`) i podgląd `…/preview/`, warianty usługi w `offer_settings.py` i `GET /booking/setup/options/` (ops mac-20261002-26, booking 0015); 2a — grupy jednostek, pola jednostki, blokada jednostki jako alokacja pod `EXCLUDE` (mac-20261002-27, 0016); 2b — sezony `BookingRule` i dni zamknięte `BookingClosure` wyłączające starty wizyt, „skopiuj na kolejny rok”, panel „Dni zamknięte” (mac-20261002-31, 0017); 2c — pobyty na noce i dni na jednostce bez osoby (`time_model` `range`, `Appointment.staff` puste przy `staff_required` 0, `/booking/stays/…`, sezon dnia przyjazdu, w panelu „Jak się rezerwuje”) (mac-20261003-4, 0018); link samoobsługi żyje do końca rezerwacji; dalej 2d (panel pobytów i obłożenia, sezony w panelu) i `core:update` HoofCare i MedPlano. odpowiedzi właściciela 1–20, reszta pytań rozstrzygnięta przez agenta po przeglądzie z kontrą; strategiczne 21–24 odpowiedziane 02.10; zasada „API obsługiwalne przez asystenta” w `AGENTS.md` i skillu `change-api-and-events` (27d0a07, 60bf6e9). **Pilne:** Django admin był osiągalny z internetu z logowaniem samym hasłem, a reguła `respond @private 404` w `Caddyfile.vps`/`.staging` nie działała od 12.08 (metryki i pytanie o zgodę TLS publiczne) — poprawka scalona 02.10 (`6524bc7`: admin bez własnego logowania, tylko sesja panelu po MFA; `handle @private` zamyka `/internal/*` w `Caddyfile.vps`/`.staging`; pełna suita backendu 1323 passed), niewdrożona — ops VPS mac-20261002-4 (przebudowa backendu, odtworzenie caddy); HoofCare i MedPlano mają ją w kodzie od rdzenia `9b18737`, a ich bramy zamkną `/internal/*` po odtworzeniu caddy w ops -9 i -10. 02.10: odpowiedzi 21–24 — sprawy prawne nie blokują (lista w memeksie `desk/regulamin-i-pytania-prawne.md`), tempo w dniach, asystent gotowy w przyszłym tygodniu; katalog firm jako podstrona serwisu z nagłówkiem, stopką i odnośnikiem w menu (faza 17) scalony 02.10 (`146170c`); każdy nieznany adres serwisu dostaje stronę 404 serwisu w języku odwiedzającego (wcześniej nieznana podstrona w profilu bez stron produktu dawała 500, a głębszy adres gołe 404 Next.js) — HoofCare (`dc24f419`) i MedPlano (`2f0b053`, „Katalog gabinetów”) na rdzeniu `ade9dee`; niewdrożone, ops VPS mac-20261002-8, -9, -10; następny krok: kategorie katalogu MedPlano (typ organizacji w profilu MedPlano, w oknie bez cudzego `core:update` produktów). Asystent A1a (02.10, lokalnie, niewdrożone; ADR-076): każdy 400 i 422 ma `errors` [{field, code, message}] (rozwijana tylko `ValidationError`); „w imieniu” osoby — `acting_via`/`acting_ref`/`acting_trigger` w `TenantContext` i w audycie (organizations 0052), `deferred_tenant_context(..., acting_*)`, bramki osoby zamknięte dla `acting` (`ACTING_PERSON_GATE_ALLOWED` pusta); podłoga OpenAPI `pnpm api:quality` w `api:check` z linią bazową, która tylko maleje (298 operacji, dług 799 — nowe i zmienione operacje muszą ją spełniać); cechy `assistant.*` w katalogu, w żadnym planie (billing 0026); wyświetlanie „w imieniu” w historii i kontrakt zadania v3 — z pierwszym producentem; A1b (02.10, plastry w planie memex; odpowiedzi 30a/31b/32a w ADR-076 „Uzupełnienie 2026-10-02”): A1b-2 — jeden kanoniczny JSON w `core/organizations/canonical.py` (sites i notifications delegują) i rejestr poleceń `command_registry.py` (`register_command` odrzuca przy starcie deklarację łamiącą ADR-076 §1, `command_tools` = pola `ToolSpec` portu); A1b-4 — wykonawca `command_executor.py`: `preview_plan` sam sprawdza ekspozycję, uprawnienie, moduł typu firmy, argumenty (`command_args_invalid` z polami), podgląd w wycofanej transakcji i bramki `register_command_gate` (billing rejestruje `features`: cecha kanału, dodatkowe cechy, entitlement; bez niej nic nie działa), grupuje zgody i liczy digest; `execute_plan` wykonuje tylko odczyty (też w wycofanej transakcji), reszta czeka na zgodę (A1b-5); `set_page_type` pod `acting` nie zmienia typu strony prawnej (26b0c7b); żadne polecenie nie jest jeszcze zarejestrowane; A1b-5 — zgoda z kliknięcia: token `command_consent.py` (sól `core.commands.consent.v1`, `COMMAND_CONSENT_TTL` 300 s, wiąże członkostwo, rozmowę i digest grupy), `execute_plan(invocations, consents)` najpierw czyta pokwitowania `CommandReceipt` (organizations 0054, RLS), potem świeży podgląd i tokeny wszystkich grup, potem savepoint na grupę; grupa ze step-upem zamknięta do A1b-7; A1b-3 — manifest poleceń `packages/contracts/commands/manifest.json` w `api:check` (`pnpm commands:manifest`), zapowiedziane polecenia w `planned.json`; A1b-8 — `TenantContext.acting_opened`: etykieta bramki osoby otwiera się tylko na jedno wykonanie polecenia ze zgodą, w obrębie sufitu `ACTING_PERSON_GATE_ALLOWED` (dziś pusty); liczniki drzwi `tests/test_command_doors.py`; A1b-6 — `offer_plan` zostawia grupę czekającą na zgodę z pełnym podglądem do pokazania, `GET`/`POST /api/v1/organizations/current/command-consents/{digest}/` (dialog A3 renderuje tylko to; token tylko dla osoby w panelu, wpis `commands.consent.granted` w historii); A1b-7 — step-up `core/identity/step_up.py` i `POST /api/v1/auth/step-up/`: tylko kod z aplikacji (odpowiedź 31b), 300 s, pięć błędnych kodów kończy sesję, konto bez 2FA `step_up_mfa_setup_required`; `require_step_up(user_id, reason)` dla dokumentów prawnych i rozliczeń; wykonawca wpuszcza tylko step-up z tokenu zgody; A1b-9 — pierwsze polecenia `organization.read@1` i `organization.update@1` (`core/organizations/command_declarations.py`, wspólna walidacja `planned_organization` z PATCH panelu), bateria evali `tests/test_command_evals.py` + `tests/command_evals/` dla każdego zarejestrowanego polecenia, spłata podłogi GET/PATCH `organizations/current/` (dług 780 → 773); polecenia działają tylko z cechą `assistant.text.enabled` (dziś w żadnym planie); A1b-1 — historia zmian pokazuje „Asystent AI w imieniu osoby” zamiast „Panel”, gdy członkostwo działało przez asystenta (`acting {via, ref, trigger}` w API historii; `channel` zostaje principalem), etykieta „Zgoda na działanie asystenta”; A1b-12 — polecenia rezerwacji `booking.setup.read@1`, `booking.offer.create@1` (usługa zawsze wyłączona), `booking.offer.update@1` (klasa apply dla usługi włączonej) i `booking.staff.hours.set@1` na serwisach §11 (pokwitowanie `BookingSetupMutation`, wersje, podgląd w wycofanym savepoincie; bateria evali z wpisem `preview_rolls_back`); następny: A1b-10 (wizytówka), A1b-11 (katalog szablonów, szkic strony, `sites.locale_body.save`) |
| `saas-core-wielojezycznosc-i-tlumaczenia-ai` | wielojęzyczne strony firm i tłumaczenia AI w rdzeniu (ADR-068–071), Puppily na rdzeniu; K1 (TL0–TL7, silnik) development-95, K2 (TL2, TL8–TL11, TL13–TL16, strony firm) development-9f | ADR-068 (port modeli, interfejs w `docs/architecture/model-port.md`, zrecenzowany przez sesję asystenta), ADR-069 (tłumaczenia AI, protokół źródeł w `docs/architecture/translation-sources.md`), ADR-070 i ADR-071 w main 02.10 — TL0 domknięte; TL1 (02.10, lokalnie, niewdrożone; ops mac-20261002-15, -18, -20): rejestr języków `packages/contracts/locales/registry.json` (pl, en, de, es, ru) czytany przez kontrolę profili i przy starcie backendu, `Organization.public_locales` (organizations 0053 + uzupełnienie z treści firm), języki treści jako kody z rejestru włączone dla firmy (`ContentLocaleField`, `locale_not_enabled`, `locale_not_seeded`; sites 0043, profiles 0006, booking 0014, notifications 0007), e-maile: odbiorca szablonu i łańcuch żądany → en → pl, zapytanie z formularza w języku panelu właściciela; do czasu TL10 firma dostaje nowy język tylko przez język swojej strony (kreator) — ustawienia języków to TL10; TL3 (02.10, lokalnie, niewdrożone; ops mac-20261002-23): moduł `shared.model-port` w profilach business, agro i vps-dev — rejestr zadań, adapter OpenRouter, sufity USD, telemetria `model_port_usageentry`, endpointy operatora; żaden model nie jest jeszcze wybieralny (próba na żywo czeka na klucz OpenRouter), a treści klientów nie wyjdą do modelu bez `MODEL_PORT_PROCESSOR_LISTED`; TL4 (02.10, lokalnie, niewdrożone; ops mac-20261002-24, `billing 0027`): kredyty liczone ilością — rezerwacja z ilością, ceną jednostkową i okresem puli, `settle_credits` rozlicza dostarczone (pula planu najpierw, reszta wraca), pula z poprzedniego miesiąca zwolniona później wygasa, `GET /api/v1/billing/credits/ledger/` (ruchy kredytów z jednostkami; bez ekranu); TL5 (02.10, lokalnie, niewdrożone; ops mac-20261002-30, `translation 0001–0004`): protokół źródeł w `content_protocol` (stany fragmentu, `sendable_units`, reguły publikacji, rejestr źródeł i polityki) z zestawem kontraktu dla adapterów w `saas_core/testing/translation_sources.py`, moduł `shared.translation` w business, agro i vps-dev (glosariusz, paczki wywołań, prompt `translation.v1`, kontrola twarda i miękka, wycena z digestem; `translation.characters` nieaktywne do evali) — bez API i workera; TL6 (03.10, lokalnie, niewdrożone; ops mac-20261003-3, -7, `translation 0005–0011`): ustawienia tłumaczeń firmy z pokwitowaniami, wersją i podglądem (`/translation/settings/`), polityka silnika dla modułów, glosariusz (`/translation/glossary/`), oferta z powodami niedostępności (`/translation/offer/`), wyłącznik i nadpisania operatora (`translation_ceiling`, `translation_org_override`), `settingsDefaults` w profilu; wycena z digestem (`/translation/quotes/`) i zlecenie (`/translation/jobs/`) z rezerwacją kredytów na część, worker na kolejce `ai` działający jako osoba zlecająca i rozliczający dostarczone — klientom nadal niedostępne (cena X po evalach, model po próbie na żywo, flaga procesora); przegląd tłumaczeń (`/translation/review/`, akceptacja zbiorcza i odrzucenie jako decyzja osoby, kolejka tekstów rekordów na żywo), „Cofnij ostatnie zadanie” (`/translation/jobs/<id>/revert/`, `translation_revert_job`), anulowanie zlecenia ze zwrotem niewykorzystanej rezerwacji, próg potwierdzenia budżetu platformy (`TRANSLATION_PLATFORM_CONFIRM_USD`, `translation_confirm_job`), dzwonek i e-mail przy zleceniu z brakami, dzienny skrót „czeka na akceptację”, 10 poleceń asystenta `translation.*` z evalami (zgoda na automat tylko przez osobę ze step-upem); następny w K1: TL7 (evale, wybór modelu — przebiegi na żywo czekają na klucz OpenRouter); TL8 (02.10, lokalnie, niewdrożone): `saas_core/content_protocol` (żetony, pochodzenie, fakty), klasyfikator fragmentów ze schematów bloków, `PageLocaleVersion` z samymi fragmentami związanymi z wersją źródła (migracja `sites 0040`), API `pages/<id>/translations/<locale>/body/` (zapis, podgląd, kopia, historia, przywrócenie, przeniesienie na nowe źródło) i przegląd `sites/<id>/translations/` — bez ekranu (TL15) i bez wpływu na stronę publiczną (TL9); TL2 (02.10, lokalnie, niewdrożone; ops mac-20261002-12): adresy kanoniczne stron firm odpowiadają 200 (ukośnik zostaje, inna pisownia — jedno 308), strona główna pod `/` i `/xx/` (adres ze slugiem → 308), dawne wersje `/en/…` z samymi metadanymi → 308 do strony polskiej i poza hreflang/sitemapą, jeden x-default na klaster wpisów, noindex w HTML (także logowanie, rezerwacje, zaproszenia), zarezerwowane pierwsze segmenty (`slug_reserved`, `sites_reserved_slugs`), `/site-renderer` z zewnątrz → 404 (poprawka przekierowań `39eaabd`: ten sam host dostaje samą ścieżkę); TL9b (02.10, lokalnie, niewdrożone; ops mac-20261002-17, `sites 0041`): publikacja pochodna przenosi zdjęcia z poprzedniej publikacji, `Publication.reason` w zdarzeniu, API i historii; TL9a (02.10, lokalnie, niewdrożone; ops mac-20261002-19): migawka v2 — wersje językowe z własnymi blokami, `live_locales`, `skipped_locales`, jedna reguła „publikowalne”, strona główna otwiera język, wersja z nieaktualnym faktem → 307; demo lokalne: witryna „Demo języków” Studio Testowe (`demo-jezyki-…business.localhost:8080`, `/` i `/en/`); TL9c (02.10, lokalnie, niewdrożone; ops mac-20261002-21, `sites 0044`): akceptacja, odrzucenie, publikacja i zdjęcie wersji językowej przez osobę (`…/body/accept|reject|publish|withdraw`, zbiorczo `sites/<id>/translations/accept` z digestem) jako publikacje pochodne — szkice nie wychodzą; zdjęta wersja zostaje zdjęta w publikacji całej witryny; bez ekranu (TL15); TL9d (02.10, lokalnie, niewdrożone; ops mac-20261002-25, `sites 0045`): formularz na stronie w innym języku bierze blok tego języka i przechodzi po późniejszej publikacji, gdy blok się nie zmienił (`SiteInquiry.locale`), odsłony z `PageViewDay.locale`, linki wewnętrzne prowadzą do wersji w języku czytelnika, wersja językowa niesie zdjęcia swojego źródła (usunięte → 307, `media_unavailable`), migawka czytana raz na proces; TL10a (02.10, lokalnie, niewdrożone; ops mac-20261002-29, `organizations 0055`, `billing 0028`): jeden serwis języków firmy — `GET`/`POST preview/`/`PUT /api/v1/organizations/current/public-locales/` z własną wersją, historią `PublicLocalesChange` (FORCE RLS, dowód na stosie: bez tenanta 0, własny 2, obcy 0), audytem `organization.settings_changed` (grupa `organization.public_locales`, w Historii zmian „było → jest”), limitem planu tylko przy dodawaniu (Profile 1, Site i Pro bez limitu), językiem źródłowym strony nie do usunięcia i usunięciem jako decyzją osoby (`assert_person_required` w rdzeniu); polecenia `organization.public_locales.read@1`/`update@1`; `create_site` dodaje język przez ten serwis; TL10c (03.10, lokalnie, niewdrożone; ops mac-20261003-2, bez migracji): język wyłączony przez firmę od razu znika ze strony publicznej — jego adresy odpowiadają 308 do strony w języku źródłowym, znikają z hreflang, menu, sitemapy i kanałów, nic nie jest kasowane ani publikowane, ponowne włączenie przywraca 200; podgląd zmiany języków wymienia przekierowania, `locale_path_conflict` przy dodawaniu; następny w K2: TL10d (rezerwacje, wizytówka, katalog), TL10f (strona „Języki i tłumaczenia”), migracje limitu w planach HoofCare i MedPlano po core:update development-aa |
| `saas-core-ustawienia-firmy` | przegląd tego, co firma może zmienić (96 kandydatów), i jeden rejestr ustawień platformy i firmy (ADR-078): deklaracja w module-właścicielu, `resolve()` ze źródłem, jeden kontrakt zapisu, API per grupa, polecenia jako adaptery, panel z metadanych | 02.10: R0 — ADR-078 i reguła w `AGENTS.md`; R2a (niewdrożone, ops mac-20261002-28) — waluta pozycji magazynu z firmy, daty magazynu i wpisu zdrowia w dniu firmy, waluty PLN/EUR/USD z `GET /organizations/options/`, `GET` preferencji bez zapisu; R1 (lokalnie, niewdrożone) — rejestr w `core.organizations` (`settings_registry.py`: `SettingGroup`/`SettingSpec`, kontrola przy starcie; `settings_service.py`: `resolve()`/`setting()` ze źródłem code/platform/organization, `change_settings()` z podglądem, tokenem wersji grupy, pokwitowaniem i historią `organization.settings_changed`; tabela `organization_setting` i pokwitowania z FORCE RLS), API `…/current/settings/schema/` i per grupa (odczyt, `preview/`, PATCH z `Idempotency-Key`), filtr historii po grupie i kluczu, bramka poleceń `settings`, polecenia grup z pełną baterią evali; pilot: „Rezerwacje” w Ustawieniach — przypomnienia firmy (włączone, ile godzin, bez przypomnienia blisko startu; zmiana przelicza niewysłane) i wstrzymanie rezerwacji online (formularz 409 `booking_paused`, panel działa, opcjonalnie do dnia); wartość platformy na razie z `.env` (`platform_env`), tabela platformy to faza 1 planu platformy; pytania właściciela 33–38 otwarte |
| `saas-core-poprawki-ux-ui` | poprawki UX/UI panelu Business, HoofCare i MedPlano po przeglądzie 02.10 (85 pozycji, zasady R1–R17 do ADR-057/054/020; decyzja 18a) | 03.10: część rdzenia W1–W6 scalona (`register_appointment_title` — nazwa wizyty od modułu, `detailsKinds`, miejsce przyjęć na karcie i kolumna „Miejsce”, `Calendar.placeAway`, historia `place_changed` słowami, teksty „Nowej wizyty”; ADR-067 pkt 8–9), niewdrożona; produkty dostaną ją przez `core:update`. D2 (odpady testowe w lokalnych bazach) czeka na pytanie 49; dalej P1 i U1–U13 |
| `domkna-c-saas-core-po-audycie-realna-kompozycja-` | baza P0–P3 po audycie | treść w `Plan/Wdrozenie/13-…` |

Kolejność przyjęta 23.09, zmieniona 24.09: faza panelu 3 → 4 → magazyn 4–8 →
magazyn 9 → wyszukiwarka → magazyn 10 → pozostałe listy na DataTable.

## Wdrożenie (dev VPS goldentrd, instancje to development do ok. połowy października)

- `saas.goldenstar.cloud` (profil `vps-dev`), `hoofcare.goldenstar.cloud`,
  `medplano.goldenstar.cloud` — osobne stacki compose; produkty przez
  `--env-file .env.<produkt>` i `compose.<produkt>.yaml`.
- Jeden skaner plików na hoście (decyzja 24.09): `saas-core-clamav-1` jest
  podpięty do sieci `<produkt>_scanner` z aliasem `clamav`; produkty nie mają
  własnych kopii. Odtworzenie tego kontenera zrywa podpięcie — workery
  produktów nie wstaną, dopóki `docker network connect --alias clamav
  <produkt>_scanner saas-core-clamav-1` nie zostanie powtórzone.
- Kod działający na VPS i raporty wydań: `docs/operations/releases/`
  (ostatnie z 23.09: DataTable, przełącznik wizytówki i strona wizytówki w
  katalogu, bogata treść Site Studio, historia zmian, limit podstron, układy
  i recepty stron pod konwersję — Site Studio 3a i 3b; 24.09 faza 4 F4-P0, edytor WYSIWYG i
  formularz kontaktu v2, szablon strony panelu). Od 23.09 wieczorem
  HoofCare i MedPlano stoją na tym samym rdzeniu co Saas-Core (`e239f40`,
  decyzja właściciela „niech leci do produktów core”).
- Płatności we wszystkich trzech: `BILLING_PROVIDER=simulated`.
- E-mail: Saas-Core wysyła przez Resend SMTP; HoofCare i MedPlano zapisują
  pocztę do plików (`.runtime-<produkt>/emails`) — raporty dla rolników i
  potwierdzenia nie wychodzą.
- Skrypty wydań (build z `git archive`, rollback tagami, kopia bazy przed
  migracją): `.runtime/releases/<data>-<nazwa>/`.

## Otwarte — rdzeń

- **Infrastruktura** (memex follow-up, termin 30.09): staging i rollback przez
  GHCR, odbiór alertu poza VPS, szyfrowany backup offsite z odtworzeniem, test
  On-Demand TLS dla domeny klienta. Obejmuje też „dwa środowiska testowe na
  osobnych danych” (plan 13, P1).
- **Realny Stripe (W9.5.2S):** runbook aktywacji i wycofania
  (`docs/operations/billing.md:41-52`), ceny brutto dla konsumentów (ADR-040 §2),
  ścieżka 3DS/`incomplete` (`shared/billing/provider.py:398`), konto live i
  webhook z przypiętą wersją API; po stronie właściciela OSS, księgowość,
  dokumenty sprzedaży. `SubscriptionState.SUSPENDED` jest martwą wartością.
- **Kredyty:** operacje content-ops zasiane jako nieaktywne do kontraktu SCR
  (`shared/billing/migrations/0016_seed_credit_catalog.py:89-100`); brak
  `shared.assistant` (zużycie przez AI, historia).
- **Generator obrazów AI (ADR-059, gałąź `feat/image-generation`):** IG-0
  gotowe bez wywołań na żywo — moduł `shared.image-generation` (na razie bez
  modeli i URL-i) w agro, business i vps-dev, adapter OpenAI
  (`image_generation/provider.py`), sekret `image_generation_openai_api_key`,
  komenda `generate_template_photos` (kandydaci, `--verify`, `--promote`) i
  `photo-shots.v1.json` z 5 scenami pilota. Czeka na klucz właściciela: pilot
  5 scen × Flare/Sunburst, `--verify` (SynthID po `process_image`), potem ok.
  26 ujęć.
  IG-1 (pochodzenie mediów i widoczne oznaczenie z art. 50) gotowe na gałęzi:
  `MediaAsset.ai_origin` (`none`/`generated`; migracja `media.0008` oznacza
  zaimportowane zdjęcia szablonów), XMP IPTC DigitalSourceType w przetworzonym
  oryginale i wariantach WebP (PNG jako iTXt), prywatny oryginał dowodowy AI
  usuwany dopiero przez tombstone i erasure (`stored_object_keys` zbiera teraz
  też `*_object_key` i `variants[*].object_key` — luka ADR-042), pochodzenie
  zdjęć szablonów z `sample-media.v1.json` (`aiGenerated`), strażnik slotów
  dowodowych (`sites/real_media.py`, `422 ai_media_not_allowed_in_slot` w
  zapisie i publikacji stron i wpisów), `ai_media_ids` w publicznym payloadzie
  czytane przy renderze, odznaka „AI” z dopiskiem w `alt` w rendererze
  (`@saas-core/site-blocks` `withAiBadge`), panel oznacza obrazy AI „· AI” i
  ukrywa je w polach `realMediaOnly`. Odznakę dla całego deploymentu włącza i
  wyłącza tylko operator (is_staff + MFA):
  `python manage.py set_ai_badge --operator <e-mail> --off|--on --reason "…"`,
  historia `--show` (tabela `sites_aibadgeswitch`, admin tylko do odczytu);
  XMP w plikach zostaje zawsze. Niesprawdzone na uruchomionym stacku (gałąź
  niewdrożona): odznaka po hoście, XMP w `/media/<id>`, `--off`.
  IG-2 (zlecenia klientów) gotowe na gałęzi, bez wywołań na żywo: tabela
  `image_generation_imagegenerationjob` (FORCE RLS, wyzwalacz członkostwa),
  migracje modułu 0001-0004 (cecha we wszystkich planach, limit prób
  `image_generation.monthly` 50/200/1000/50, operacja `image_generation.generate`
  = 2 kredyty, uprawnienie manager/admin/owner; odwracalne), `roleGrants` i
  `beatSchedule` w deskryptorze, API `/api/v1/image-generation/` (oferta,
  zlecenie z `Idempotency-Key`, odczyt bez promptu), `worker.py` na wzór SEO
  (dzierżawa, dostawca poza transakcją, ponowienia przez beat, blokada
  dostawcy 1 h, jedna ścieżka mediów przez `stage_generated_media_asset`),
  usługa `worker-ai` (`-Q ai`, profil Compose `image-generation`,
  `stop_grace_period` 200 s) w compose, vps i skryptach deployu/rollbacku
  stagingu, przycisk „Wygeneruj obraz AI” w Site Studio (16:9, 4:3, figura
  3:2; nie w slotach dowodowych), runbook `docs/operations/image-generation.md`.
  **Kroki wdrożenia (blokujące) na każdym stosie:** plik
  `image_generation_openai_api_key` musi istnieć, także pusty, `0644`
  (`test -f F || install -m 0644 /dev/null F` w `.runtime/secrets`,
  `.runtime-hoofcare/secrets`, `.runtime-medplano/secrets`) — bez niego
  Compose nie tworzy kontenera `backend`; `COMPOSE_PROFILES=image-generation`
  w pliku env stosu uruchamia `worker-ai`. HoofCare i MedPlano po
  `core:update`: najpierw wpis `worker-ai` w overlayu produktu (obraz, env,
  sekrety jak `worker`), dopiero potem profil — inaczej `worker-ai` buduje się
  pod tagiem `saas-core-backend:local` stosu Saas-Core. Otwarte: dowód na
  uruchomionym stacku (RLS trzema odczytami, job do `succeeded` z kluczem,
  odznaka po hoście, erasure obiektów, grep logów) — nie robiony, bo host
  jest przeciążony i nie ma klucza; przed klientami: klucz, Tier ≥ 2, limit
  wydatków w projekcie OpenAI, przegląd prawnika (projekt ToS/AUP/DPA w planie
  memeksu).
- **P3 (plan 13:406-442):** powiązanie profilu osoby z witryną, konto klienta
  (`Customer.user`, „moje wizyty”), role specjalista/recepcja,
  `PolicyAcknowledgement`, skill tożsamości.
- **Wizytówka (ADR-053):** plan `profile` nadal ma `sites.enabled`
  (`shared/billing/migrations/0012_seed_profile_plan.py:26`) — decyzja cenowa
  właściciela; wyszukiwarka to jeszcze `tsvector simple`.
- **Limit podstron** działa od 23.09 (Profil 5, Witryna 15, Pro 50; liczby
  tymczasowe, do ustalenia przez właściciela). Migawka bez `pages.max` nie ma
  limitu — zmiana planu dociera do organizacji dopiero po przeniesieniu jej
  abonamentu na nową wersję (skrypt w `.runtime/releases/20260923-pages-limit/`).
- **Historia zmian:** „było → jest” zapisują główne edycje (firma, wizytówka,
  rola, gospodarstwo, zwierzę, pozycja magazynu, dane do faktury); pozostałe
  akcje pokazują listę pól albo nic. Wpisy sprzed 23.09 nie mają kanału.
- **Fixture odbioru** `sites_e2e_fixture` nadaje tylko cechy witryny; do odbioru
  wizytówki trzeba dopisać `profiles.enabled` (23.09 zrobione ręcznie na koncie
  testowym). Wszystkie prawdziwe plany tę cechę mają.
- **Rezerwacje:** wizyta zajmuje jeden zasób (jeden na wizytę, także przy
  kilku osobach) — jeden z zasobów zaznaczonych w usłudze. Ustawienia › Usługi
  i grafik (krok 3c) edytują usługi, miejsca i zasoby (`/booking/setup/…`);
  osoby i ich godziny są wyłącznie w Zespół. Stare `POST /booking/catalog/` i
  `/booking/schedule/` zostają dla fixture'ów i skryptów, panel ich nie używa.
- **Rejestr gospodarstw (backlog z przebudowy panelu):** brak slotu sekcji
  gospodarstwa dla produktu; brak GET pojedynczego zwierzęcia i filtra statusu
  (`shared/farms/views.py:139-176`); brak importu CSV; brak telefonu/miasta
  na `Organization`; płatny okres próbny wymaga Checkout; „Wiadomości”
  wymagają `notifications.manage` albo `site.content.edit`
  (`apps/frontend/src/lib/panel-navigation.ts:197-200`).
- **Workspace platformy** dostaje `sites.enabled` bez `sites.max`, więc
  założenie witryny kończy się `QuotaUnavailable`
  (`provision_platform_workspace.py:45`).
- **Dane demo stosu testowego:** `manage.py seed_demo` (30.09) zakłada firmę z
  zespołem, plan bez płatności, kalendarz z wizytami (także w „Do przydzielenia”) i
  magazyn z ruchami; tylko z `DEMO_SEED_ENABLED=1`, nigdy na produkcji; produkty
  podają własny scenariusz (`docs/development/demo-data.md`).
- **Strony marketingowe:** brak bloga i stron prawnych; formularz kontaktowy
  czeka na klucze (`contact/page.tsx:21`); SCR dla stron marketingowych
  (plan 14:133).
- **Site Studio:** testy e2e edytora WYSIWYG i całego studia są w repo
  (`site-rich-text-editor.spec.ts`, `SITE_EDITOR_E2E=1`;
  `sites-publication.spec.ts`, `SITE_STUDIO_E2E=1`: onboarding → szablon →
  płótno → publikacje → rollback); limit szablonów firmy w planach od billing
  0025: Profil 3, Starter 10, Pro 50 (`sites.templates.max`);
  błędy walidacji edytora to jeden komunikat bez wskazania elementu;
  prawdziwe zdjęcia produktu i portretów (dziś 4 ilustracje AI, recepty
  używają ich wielokrotnie); AI
  (faza 8), Content Ops v2. Realne doręczenie zapytań ze strony przez SMTP
  nieudowodnione. Publiczne zdjęcia bez wariantów responsywnych (oryginały
  PNG ~2 MB).
- **Szablon strony panelu (ADR-057, 24.09):** każda strona to `PanelPage`,
  szerokość ma układ (przełącznik „na całą szerokość” od 1536 px), podstrony
  sekcji rozwijają się w lewym menu. Zakładki edytora strony www i karty
  gospodarstwa zostają w stronie (etapy pracy nad jednym rekordem).
- **Listy na DataTable:** każda lista rekordów panelu (faza 6, 29.09): poza
  wcześniejszymi także wizyty, udostępnienia i kartoteka zdrowia w
  gospodarstwach, audyty i Search Console, wpisy bloga, zapytania, połączenia
  automatyzacji, propozycje, domeny, przekierowania, publikacje, wersje strony,
  tłumaczenia wpisu, zakupy kredytów, klucze API i webhooki, szablony
  wiadomości, sesje logowania. Świadomie poza tabelą: pozycje jednego rekordu
  (materiały wizyty, linie dokumentu), gotowość tłumaczeń, widok dnia
  kalendarza, widżety „Dziś” HoofCare, tryb terenowy. Tabela w trybie klienta
  cofa się na ostatnią stronę, gdy filtr strony zmniejszy listę. Filtry
  raportów HoofCare to formularz z „Pokaż” (API), nie pasek `DataTable`. Brak
  w panelu wycofania i rotacji klucza API (backend je ma, klient API jeszcze
  nie).
- **Magazyn v2 (ADR-055):** włączony we wszystkich profilach i planach;
  wizyty rezerwują i zdejmują produkty zawsze z magazynu głównego (bez zapasu
  osoby i innych magazynów); zakończonej wizyty nie cofa się w kalendarzu; brak
  wydruku dokumentów (PDF później), partii, alertów i raportów. Moduł może
  wyłączyć produkty kalendarza dla swoich rodzajów wizyt
  (`appointmentKindsWithOwnMaterials`, robi to HoofCare).
- **Wyszukiwarka panelu** z makiety — brak API i UI; **warianty kolorów
  produktów** (5 od właściciela) — brak.
- **Integracja SEO na instancjach (plan 14:74-91, 205):** osiem przepływów na
  żywych instancjach, realne GSC OAuth, płatny audyt i generacja, manifest
  wydania; W9.6.8 wymaga stagingu i konektora SCR.
- **Testy** `navigation-editor`/`page-editor` bywają niestabilne pod
  obciążeniem hosta; czekają na `findByText("Start")`, co nie dowodzi
  wczytania menu.
- **Nieaktualne dokumenty:** `docs/architecture/site-studio-editor.md:116-119`
  i `:209` (zamknięte 21.09); plan 13:468 (mapowanie zakleszczenia — zrobione).

## Otwarte — produkty

- HoofCare: `docs/product/HANDOFF.md` w repo HoofCare (etap 5 sprzedaży
  zwierząt, magazyn v2, tryb offline).
- MedPlano: bez własnych rozszerzeń — dostaje wyłącznie aktualizacje rdzenia
  (decyzja właściciela 23.09).

## Nierozstrzygnięte

- Obraz SCR na VPS (I6, plan 14:74) — działa od 12 dni, brak zapisanego
  digestu i SHA w planie 14.
- Plany firmowe są wspólne dla wszystkich produktów — do potwierdzenia przez
  właściciela, czy tak zostaje.
- ADR-050 i 051 mają status „proponowana”, choć są wdrożone (ADR-052
  przyjęta 24.09).

## Praca na tym VPS

- `pnpm` przez corepack: `export PATH="/usr/lib/node_modules/corepack/shims:$PATH"`;
  host ma Node 22, repo wymaga 24 — ostrzeżenie jest nieszkodliwe, obrazy
  budują się na Node 24.
- Testy backendu: kontener `saas-core-testdb` na `127.0.0.1:55432`
  (`POSTGRES_HOST`/`POSTGRES_PORT` wskazują go przy `uv run … pytest`); pełny
  backend rdzenia ~11 min, pojedynczy plik 1–3 min.
- Kilka sesji pracuje równolegle: własny worktree, commity jawnymi ścieżkami,
  a zmiany rdzenia do produktów tylko przez `pnpm core:update`.
