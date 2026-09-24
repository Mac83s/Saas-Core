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
| `saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka` | standard list panelu, szablon strony panelu, wizytówka, historia zmian, limit podstron, wyszukiwarka katalogu | fazy 1–4 i 7 zrobione (DataTable, przełącznik wizytówki, historia zmian, limit podstron; 24.09 szablon strony panelu, ADR-057, w trzech aplikacjach); faza 6 częściowo; dalej magazyn faza 7, potem Meilisearch |
| `magazyn-materia-o-w-od-pakietu-korektora-do-kare` | uniwersalny magazyn firm (`shared.inventory` v2, ADR-055): dokumenty, miejsca, rezerwacje, rezerwacje stanu przy wizytach, przyszły sklep | fazy 4, 5, 6 i 8 zrobione 23–24.09 (rdzeń v2, HoofCare przepięty, panel na DataTable, włączony wszędzie, produkty przy wizycie); dalej przygotowanie do wizyty i alert małego stanu w HoofCare |
| `saas-core-site-studio-templates`, `saas-core-site-studio-rich-content-and-full-width` | Site Studio: szablony, warianty, bogata treść | bogata treść, pełna szerokość, wygląd strony i 3 strony demonstracyjne scalone i wdrożone 23.09 (saas, a wieczorem też HoofCare i MedPlano) (`docs/architecture/site-rich-content.md`, raport `2026-09-23-rich-content`); faza 3a (20 układów redakcyjnych pod konwersję, `core.rich_text` v3, katalog v6, ostrzeżenie o miejscach `[Uzupełnij: …]`) i 3b (8 stylów strony, kotwice sekcji i przyciski „do formularza”, 9 recept stron v5 z celem i ścieżką konwersji, 8 dawnych szablonów wycofanych z galerii) scalone 23.09; etap 2b — edytor WYSIWYG (TipTap, ADR-056) w panelu i na pełnym ekranie, panel ze składnią `**` usunięty — scalony i wdrożony na saas 24.09 (raport `2026-09-24-wysiwyg-editor`); formularz kontaktu v2 (4 warianty wymaganych pól, m.in. „Oddzwonimy” z wymaganym telefonem, egzekwowane przez serwer) wdrożony na saas 24.09 (raport `2026-09-24-contact-form-v2`); faza 4 (paczki F4-P0…P5, 24 sekcje, 3 strony, 6 dodatków branżowych): F4-P0a (katalog v7, najnowsza wersja sekcji w bibliotece, harness zrzutów) i F4-P0b (bez zmyślonych faktów w receptach, strażnik cytatów dla automatu, 503 przy zajętym skanerze, Manrope 800) wdrożone na saas 24.09 (raport `2026-09-24-phase4-p0`); dalej F4-P1 (listy, Poradnik, sekcje gabinetu i gospodarstwa). Generator obrazów AI (OpenAI GPT Image 2.5, ADR-059) wdrożony na saas 24.09 bez klucza (raport `2026-09-24-image-generation`): oznaczanie AI, odznaka i sloty dowodowe działają; generowanie czeka na klucz, pilot SynthID i prawnika |
| `domkna-c-saas-core-po-audycie-realna-kompozycja-` | baza P0–P3 po audycie | treść w `Plan/Wdrozenie/13-…` |

Kolejność przyjęta 23.09: faza panelu 3 → 4 → magazyn 4–8 → wyszukiwarka →
magazyn 9–10 → pozostałe listy na DataTable.

## Wdrożenie (dev VPS goldentrd, instancje to development do ok. połowy października)

- `saas.goldenstar.cloud` (profil `vps-dev`), `hoofcare.goldenstar.cloud`,
  `medplano.goldenstar.cloud` — osobne stacki compose; produkty przez
  `--env-file .env.<produkt>` i `compose.<produkt>.yaml`.
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
- **Rezerwacje:** wizyta bez rezerwacji obsługuje jeden wymagany zasób
  (`shared/booking/services.py:340`); karta „Konta pracowników kalendarza”
  pokazuje błąd zamiast się ukryć, gdy plan nie ma rezerwacji (403).
- **Rejestr gospodarstw (backlog z przebudowy panelu):** brak slotu sekcji
  gospodarstwa dla produktu; brak GET pojedynczego zwierzęcia i filtra statusu
  (`shared/farms/views.py:139-176`); brak importu CSV; brak telefonu/miasta
  na `Organization`; płatny okres próbny wymaga Checkout; „Wiadomości”
  wymagają `notifications.manage` albo `site.content.edit`
  (`apps/frontend/src/lib/panel-navigation.ts:197-200`).
- **Workspace platformy** dostaje `sites.enabled` bez `sites.max`, więc
  założenie witryny kończy się `QuotaUnavailable`
  (`provision_platform_workspace.py:45`).
- **Strony marketingowe:** brak bloga i stron prawnych; formularz kontaktowy
  czeka na klucze (`contact/page.tsx:21`); SCR dla stron marketingowych
  (plan 14:133).
- **Site Studio:** test e2e edytora WYSIWYG w repozytorium (dziś harness i
  skrypt odbioru wydania; follow-up memex do 30.09); błędy walidacji edytora
  to jeden komunikat bez wskazania elementu; prawdziwe zdjęcia produktu i
  portretów (dziś 4 ilustracje AI, recepty używają ich wielokrotnie);
  `core:update` produktów o fazę 3b, etap 2b i formularz v2; własne
  szablony (faza 4), AI (faza 8), Content Ops v2. Styl `studio`/`product` chce nagłówków 800,
  a dołączony Manrope kończy się na 700. Realne doręczenie zapytań ze strony przez SMTP nieudowodnione. Import
  szablonu ze zdjęciem zwraca 500, gdy ClamAV nie zdąży w 30 s (obciążony host)
  — powinien być błąd „spróbuj ponownie”; publiczne zdjęcia bez wariantów
  responsywnych (oryginały PNG ~2 MB).
- **Szablon strony panelu (ADR-057, 24.09):** każda strona to `PanelPage`,
  szerokość ma układ (przełącznik „na całą szerokość” od 1536 px), podstrony
  sekcji rozwijają się w lewym menu. Zakładki edytora strony www i karty
  gospodarstwa zostają w stronie (etapy pracy nad jednym rekordem).
- **Listy na DataTable:** zespół, historia, magazyn, gospodarstwa, zwierzęta,
  zwierzęta gospodarstwa, lista kalendarza, raporty HoofCare; własne tabele
  nadal w `seo/audits-panel` i `seo/gsc-panel`. Filtry raportów HoofCare to
  formularz z „Pokaż” (API), nie pasek `DataTable`.
- **Magazyn v2 (ADR-055):** włączony we wszystkich profilach i planach;
  wizyty rezerwują i zdejmują produkty zawsze z magazynu głównego (bez zapasu
  osoby i innych magazynów); zakończonej wizyty nie cofa się w kalendarzu; brak
  wydruku dokumentów (PDF później), partii, alertów i raportów.
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
