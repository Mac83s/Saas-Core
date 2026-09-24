# ADR-059 — generowanie obrazów AI i pochodzenie mediów

**Status:** Accepted — decyzje właściciela z 2026-09-24 (memex
`generator-obrazo-w-openai-gpt-image-2-5-bezpos-r`). Koszty za obraz i
przetrwanie SynthID po normalizacji potwierdza pilot IG-0, gdy będzie klucz API;
do tego czasu kod powstaje i jest testowany wyłącznie z atrapą dostawcy.
**Data:** 2026-09-24

## Kontekst

Właściciel zdecydował, że generator obrazów jest częścią systemu: dla nas przy
zdjęciach szablonów i dla klientów przy tworzeniu stron w Site Studio. Art. 50
AI Act obowiązuje od 2026-08-02; okres przejściowy do 2026-12-02 dotyczy tylko
systemów wprowadzonych wcześniej, więc nowa funkcja musi oznaczać obrazy od
pierwszego dnia. Jako dostawca systemu pod własną marką odpowiadamy za
oznaczenie maszynowe (ust. 2) i ułatwiamy klientom widoczne oznaczenie (ust. 4).

Obecny potok mediów (ADR-027, `media/images.py`) koduje obraz od nowa i gubi
XMP, IPTC i C2PA. Cztery zdjęcia szablonów w
`packages/contracts/page-templates/assets/` są wygenerowane przez AI i trafiają
na strony bez żadnego znacznika. Obowiązują zasady ADR-033 (port dostawcy,
fail-closed, brak promptów w logach) i ADR-046 (integracje nie produkują
mediów; nieznany wynik płatnego wywołania nie uruchamia kolejnego).

## Decyzja

1. **Dostawca.** OpenAI GPT Image 2.5 przez bezpośrednie Image API. Klienci:
   `gpt-image-2.5-flare-2026-09-08`, `quality=high`, JPEG, dłuższy bok 1536 px.
   Szablony: `gpt-image-2.5-sunburst-2026-09-08`, mastery do 2560×1440 px.
   Model i snapshot to konfiguracja (`IMAGE_GENERATION_MODEL`,
   `IMAGE_GENERATION_TEMPLATE_MODEL`); zmiana snapshotu wymaga powtórzenia
   pilota. Zawsze `moderation=auto`, `n=1`, bez rozmiarów eksperymentalnych
   (powyżej 2560×1440).
2. **Wyjątek od agregatora z ADR-033.** OpenRouter i inni pośrednicy nie dają
   dla tej capability kontroli rozmiaru ani proporcji 4:5, maski i przetwarzania
   w UE. Adapter jest bezpośredni, napisany na stdlib `urllib` jak
   `seo/source.py` (bez przekierowań, limit odpowiedzi 25 MiB, timeout 150 s),
   bez SDK. Rejestr adapterów powstanie z drugim dostawcą. Fail-closed: brak
   klucza, wyczerpany limit wydatków albo brak workera oznacza, że funkcja jest
   niedostępna (`503 image_generation_unavailable`, `available=false` w ofercie);
   nie przełączamy się na innego dostawcę.
3. **Granice modułu.** Nowy moduł `shared.image_generation` zależy od
   `core.organizations`, `shared.billing` i `shared.media`. Nikt go nie
   importuje. Pochodzenie obrazu (`MediaAsset.ai_origin`) należy do
   `shared.media`, bo czytają je `shared.sites` (renderer, strażnik slotów) i
   panel; dzięki temu Sites zależy od Media, a nie od generatora.
   `shared.sites.json` dostaje brakujące `shared.media` w `dependsOn`.
   Uprawnienia ról i harmonogram moduł deklaruje w deskryptorze
   (`roleGrants`, `beatSchedule`, ADR-049), a uprawnienie nadaje jego własna
   migracja. Produkty (Business, HoofCare, MedPlano) dostają moduł przez profil
   i `core:update`.
4. **Tylko osoba, tylko opis.** Generowanie zleca wyłącznie członek organizacji
   (`principal_kind == "membership"`) z `image_generation.run` i `media.manage`
   oraz entitlementem `image_generation.enabled`. Klucze API i integracje nigdy
   nie generują — to dopisek do ADR-046. W tym przyroście do dostawcy idzie
   wyłącznie opis tekstowy; nie wysyłamy obrazów klienta. Edycja zdjęć wymaga
   nowego ADR z oceną DPIA, a w MedPlano pozostaje wyłączona także później.
5. **Przepływ jak w ADR-045.** Żądanie HTTP nie wykonuje połączenia sieciowego:
   sprawdza bramki, rezerwuje limity i kredyty, zapisuje zlecenie i audyt.
   Wywołanie dostawcy wykonuje worker na osobnej kolejce `ai`, poza transakcją.
   Kredyty są pobierane dopiero po `READY` assetu; odmowa, błąd i nieznany wynik
   je zwalniają.
6. **Pochodzenie i oznaczenie maszynowe (zmiana ADR-027).** `MediaAsset`
   dostaje pole `ai_origin` (`none` | `generated`). Potok nadal usuwa EXIF, ale
   mediom AI dopisuje do przetworzonego oryginału i wariantów WebP pakiet XMP z
   `Iptc4xmpExt:DigitalSourceType =
   http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`
   (dla PNG jako chunk iTXt `XML:com.adobe.xmp`). Oryginał od dostawcy z jego
   manifestem C2PA zostaje prywatnie pod `source_object_key` jako kopia dowodowa
   i znika przy tombstone oraz erasure. Nie zapisujemy danych twórcy. Warstwą w
   pikselach jest SynthID dostawcy; jego przetrwanie po naszej normalizacji
   sprawdza pilot IG-0. Znacznik maszynowy jest zawsze — przełącznik z pkt 7
   go nie dotyczy.
7. **Widoczne oznaczenie z przełącznikiem operatora.** Renderer publiczny
   pokazuje na każdym obrazie AI odznakę „AI” i dopisuje do `alt`
   „— obraz wygenerowany przez AI” (EN „— AI-generated image”). Pochodzenie jest
   czytane w chwili renderowania, więc obejmuje też publikacje sprzed zmiany.
   Klient nie może oznaczenia wyłączyć: nie ma do tego endpointu, uprawnienia
   roli ani pola w panelu. Włącza i wyłącza je **operator platformy**
   (`is_staff` z potwierdzonym MFA) dla całego deploymentu, domyślnie włączone —
   bo to operator odpowiada za przejrzystość z art. 50. Szczegóły w sekcji
   „Przełącznik operatora”.
8. **Sloty dowodowe.** Media AI są odrzucane w slotach, które udają dowód:
   portret przy cytacie (`core.quote` `image`) i zdjęcie autora
   (`core.rich_text` `author.image`). Granicą jest backend
   (`REAL_MEDIA_ONLY_SLOTS` w Sites, `422 ai_media_not_allowed_in_slot`), a flaga
   `realMediaOnly` w manifeście bloków służy panelowi tylko do ukrycia przycisku
   i odfiltrowania obrazów AI. F4-P3 dopisze warstwy realizacji.
9. **Oferta (zmiana ADR-032).** Entitlement `image_generation.enabled` we
   wszystkich planach, operacja kredytowa `image_generation.generate` za 2
   kredyty, miesięczny limit prób `image_generation.monthly`.
10. **Zdjęcia szablonów** powstają offline komendą `generate_template_photos`
    (kandydaci, arkusz kontaktowy, weryfikacja pochodzenia, promocja). Do
    kontraktu `page-templates` trafia JPEG o dłuższym boku ≤ 1920 px (ok.
    400 KB) z `sha256` i `aiGenerated: true`; mastery zostają poza repo w
    `.runtime/template-photos/`. Diff przegląda człowiek.

## Model danych

`ImageGenerationJob` (`TenantScopedModel`, FORCE RLS i wyzwalacz zgodności
relacji z migracji modułu, wzór `seo/migrations/0002_tenant_isolation.py`):
`created_by`, `membership_id`, `idempotency_key` i `request_hash` unikalne dla
(organizacja, autor, klucz), `state` (`queued`, `running`, `ingesting`,
`succeeded`, `refused`, `failed`), `aspect`, `width`, `height`, `model`,
`prompt`, `prompt_sha256`, `credit_reservation_key`, `credit_cost`,
`media_asset_id` (UUID bez klucza obcego między modułami), `cost_usd_micros`,
`provider_request_id`, `error_code`, `attempts`, `next_attempt_at`,
`lease_token`, `lease_until`, znaczniki czasu. Wiersz jest trwałą kolejką, jak
`AuditOrder` w ADR-045.

Prompt jest czyszczony przy stanie końcowym. Wyjątek to `refused`: tekst zostaje
30 dni jako dowód nadużycia, potem czyści go zadanie uzgadniające. Erasure
organizacji usuwa zlecenia razem z resztą danych tenanta (ADR-042).

`MediaAsset.ai_origin` to jedyne pole pochodzenia. Nie dodajemy
`ai_provenance`: model i data leżą w zleceniu, a dla szablonów w kontrakcie
`sample-media`. Wartość `edited` i DigitalSourceType
`compositeWithTrainedAlgorithmicMedia` dojdą z pierwszym producentem edycji.
Migracja danych oznacza jako `generated` assety zaimportowane z szablonów
(klucze `template:` i `template-photo:`); ich już przetworzone pliki nie mają
XMP — dotyczy to wyłącznie instancji deweloperskich.

Przełącznik operatora to tabela platformowa `sites_aibadgeswitch` bez klucza do
`Organization` (więc poza RLS i poza `publicTables`/`platformTables`),
append-only: `visible`, `reason`, `changed_by`, `created_at`. Stan bieżący to
najnowszy wiersz; brak wierszy znaczy „włączone”. Historia zmian jest więc
jednocześnie audytem.

## Przepływ

**Żądanie** (`POST /api/v1/image-generation/jobs/`, nagłówek `Idempotency-Key`,
body `{prompt 3–1000 znaków, aspect, expected_cost}`), jedna transakcja, w tej
kolejności: uprawnienia i entitlement; `membership`; dostępność (klucz,
aktywna operacja kredytowa, żywy worker `ai`, brak blokady dostawcy); walidacja;
blokada wiersza `Organization`; ten sam klucz z tym samym hashem zwraca
istniejące zlecenie, z innym daje 409; limit odmów (5 w 24 h → 429); limit 2
aktywnych zleceń (429); `consume_quota(image_generation.monthly)` — próba liczy
się zawsze, także odrzucona; rezerwa miejsca `storage.bytes` 3 MiB; rezerwacja
kredytów z `expected_cost`; zapis `queued`, audyt `image_generation.requested`,
po commicie wysłanie zadania na kolejkę `ai`. Operacja kredytowa nieaktywna
oznacza 503, nie darmowe generowanie.

**Worker** kopiuje `seo/worker.py`. Zadanie dostaje `(organization_id, job_id)`,
bez podpisanego kontekstu. Przejęcie to osobny, zatwierdzony blok atomowy z
`set_local_organization_id`, tokenem dzierżawy (5 min) i `attempts + 1`; przed
pierwszym wywołaniem worker ponownie sprawdza członkostwo i entitlement.
Wywołanie dostawcy odbywa się poza jakąkolwiek transakcją. Wynik zapisuje nowy
blok atomowy, który sprawdza token dzierżawy. Rozliczenie kredytów odbywa się w
utrwalonym kontekście rozliczenia zbudowanym z `membership_id` zlecenia.

Wyniki dostawcy:

- odmowa moderacji → `refused`, zwolnienie kredytów, audyt z kategoriami, bez
  ponowienia; klient dostaje ogólny komunikat po polsku;
- 429 limitu tempa, 502, 503, błąd połączenia przed wysłaniem → powrót do
  `queued` z `next_attempt_at` (backoff), ponowną wysyłkę robi zadanie
  uzgadniające, najwyżej 3 próby; bez Celery autoretry, bo dzierżawa blokowałaby
  ponowienie;
- 429 `insufficient_quota` (twardy limit wydatków) → `failed` i blokada
  dostawcy na godzinę: oferta pokazuje `available=false` wszystkim tenantom;
- timeout odczytu, 500 i 504 po wysłaniu, dzierżawa wygasła w `running` →
  `failed` z `provider_result_unknown`, bez drugiego płatnego wywołania;
- sukces → `stage_generated_media_asset` pod kontekstem członkostwa (zapis
  obiektu, rezerwa storage, audyt `media.asset.upload_initiated`, bez kolejki
  mediów), stan `ingesting`, a następnie **jedna** ścieżka przetwarzania: ten sam
  worker wywołuje `process_media_asset` (skan, normalizacja z XMP, warianty).
  Niedostępny ClamAV zostawia `ingesting` z backoffem; dostawca nie jest
  wywoływany drugi raz. `READY` → `succeeded`, obciążenie kredytów, audyt;
  `REJECTED` → `failed` i zwolnienie kredytów (koszt dostawcy ponosimy my).

Zadanie uzgadniające (`beatSchedule` modułu, co 60 s, na kolejce `ai`) iteruje
organizacje przez `billing_organization_ids()`, wysyła zlecenia z
`next_attempt_at` w przeszłości, kończy przeterminowane (`queued` starsze niż
30 min, `ingesting` starsze niż 24 h), czyści prompty odmów po 30 dniach i przy
okazji zostawia w cache ślad życia workera — bez niego oferta mówi
`available=false`, więc produkt bez konsumenta kolejki `ai` nie przyjmie
zlecenia.

Worker `worker-ai` to osobna usługa w `compose.yaml` (`-Q ai --concurrency=2`),
żeby wywołania trwające do dwóch minut nie blokowały skanowania mediów.
`concurrency=2` jest też limiterem tempa wobec Tieru OpenAI (Tier 1: 5
obrazów/min na organizację OpenAI). Overlaye produktów muszą nadać tej usłudze
swój obraz, tak jak robią to dla `worker`.

## Przełącznik operatora

Widoczne oznaczenie (odznaka i dopisek w `alt`) ma jeden przełącznik na
deployment. Zapis odbywa się wyłącznie komendą:

```
python manage.py set_ai_badge --operator <e-mail> --off --reason "…"
python manage.py set_ai_badge --operator <e-mail> --on --reason "…"
python manage.py set_ai_badge --show
```

Komenda wymaga aktywnego operatora z `is_staff` i potwierdzonym MFA — tak samo
jak `link_farm`, `erase_organization` i `provision_platform_workspace`, czyli
istniejące operatorskie wejście platformy. Każda zmiana to nowy wiersz z
uzasadnieniem i autorem oraz zdarzenie bezpieczeństwa w logu. Django admin
(`/internal/admin/`) pokazuje historię tylko do odczytu: jego logowanie omija
dziś MFA, więc nie dostaje prawa zapisu. Renderer czyta najnowszy wiersz przy
każdym renderze; przy wyłączonym przełączniku payload nie niesie listy obrazów
AI, a znacznik XMP w plikach zostaje.

Nie ma wyjątków per organizacja. Jeśli okażą się potrzebne, dojdą jako
nullable `organization_id` w tej tabeli z polityką RLS dla wierszy tenanta.

## Kredyty, limity i koszty

Koszt dostawcy liczymy z pola `usage` według stawek GPT Image 2.5 (5 USD/1M
tokenów tekstu wejściowego, 30 USD/1M tokenów obrazu wyjściowego) i zapisujemy w
`cost_usd_micros`. Według oficjalnego wzoru przy `quality=high`: 3:2
(1536×1024) ok. 0,041 USD, 4:3 (1536×1152) ok. 0,049 USD, 16:9 (1536×864)
poniżej 3:2. Klient generuje w tym przyroście tylko 16:9, 4:3 i 3:2 — 1:1 i
4:5 występują dziś wyłącznie w slotach dowodowych. 2 kredyty (0,70–0,98 zł)
pokrywają koszt z nieudanymi próbami, za które klienta nie obciążamy.

Limit prób `image_generation.monthly` (okres miesięczny, wzór
`billing/migrations/0024_pages_quota.py`): profile 50, starter 200, pro 1000,
pozostałe plany 50 — liczby tymczasowe do strojenia. Limit liczy każdą próbę,
więc pętla odrzucanych promptów nie wypali wspólnego limitu wydatków OpenAI.
Dodatkowo: 5 odmów w 24 h blokuje organizację do końca okna, a w OpenAI każdy
produkt ma osobny projekt z twardym limitem wydatków.

## Moderacja

Po stronie dostawcy zawsze `moderation=auto`. Po naszej: stały angielski
szablon wokół polskiego opisu („realistic photograph… no text, logos,
watermarks, no recognizable real or famous person”), bez dodatkowego wywołania
LLM; brak obrazów wejściowych; blokada slotów dowodowych; odznaka; w dialogu
ostrzeżenie, żeby nie wpisywać danych osobowych ani o zdrowiu i nie przedstawiać
obrazu jako realizacji, efektu usługi ani opinii. Prompt nigdy nie trafia do
logów, a do audytu idzie tylko `prompt_sha256` i długość. Szablon po angielsku
to prośba do modelu, nie kontrola: kontrolą są moderacja dostawcy, limity i
regulamin.

**Ryzyko resztkowe:** pobrany obraz można wgrać ponownie jako zwykły plik — traci
wtedy `ai_origin`, odznakę i blokadę slotu. Wykrywanie IPTC i C2PA w uploadzie
jest odłożone; do tego czasu chroni nas regulamin (zakaz usuwania oznaczeń) i
odpowiedzialność klienta jako podmiotu stosującego.

## Poza zakresem

Edycja zdjęć klienta (referencje, tło, rozszerzenie kadru), własny podpis C2PA
na pochodnych, wykrywanie IPTC/C2PA w uploadzie, drugi adapter (Vertex),
endpoint UE (wymaga zgody OpenAI na abuse monitoring controls i aneksu Modified
Retention — nie obiecujemy przetwarzania w UE w DPA bez pisemnego potwierdzenia
dla gpt-image-2.5), lista zleceń w panelu, `n > 1`, strumieniowanie podglądów,
własny klasyfikator obrazów, token bucket w Redis (dojdzie przy więcej niż
jednym `worker-ai` albo wspólnej organizacji OpenAI dla trzech produktów).

## Relacje z innymi ADR

- **ADR-027** — zmiana: potok mediów zachowuje XMP DigitalSourceType dla
  mediów AI i trzyma prywatny oryginał dostawcy do tombstone.
- **ADR-031** — Site Studio dostaje przycisk generowania przy polach obrazu;
  zdjęcia szablonów niosą pochodzenie.
- **ADR-032** — nowy entitlement, limit prób i operacja kredytowa.
- **ADR-033** — wyjątek od agregatora dla capability obrazów; fail-closed i
  brak promptów w logach obowiązują.
- **ADR-039/041** — tabela zleceń z FORCE RLS; tabela przełącznika jest
  platformowa, bez tenanta.
- **ADR-042** — erasure usuwa także zachowane oryginały i warianty (przy okazji
  naprawiamy lukę: `stored_object_keys` zbierało tylko kolumnę `object_key`).
- **ADR-045** — ten sam kształt zlecenia, dzierżawy i rozliczenia.
- **ADR-046** — dopisek: integracje i klucze API nie generują obrazów.
- **ADR-049** — `roleGrants` i `beatSchedule` w deskryptorze; moduł jedzie do
  produktów przez `core:update`, a `worker-ai` wymaga wpisu w ich overlayach.

## Konsekwencje

Plusy: najwyższa jakość w rankingach z 2026-09-21, natywne proporcje bez
upscalera, oznaczenie zgodne z art. 50 od pierwszego dnia, zamknięta luka przy
obecnych zdjęciach szablonów, brak nowej zależności Pythona, naprawione erasure.

Minusy: jeden dostawca (awaria wyłącza funkcję), szybka rotacja snapshotów,
przetwarzanie w USA do czasu zgody na region UE, koszt nieudanych wywołań po
naszej stronie, nowy kontener `worker-ai` w każdym produkcie. Indemnity OpenAI
nie jest argumentem: wyłączenie „output modified or combined” obejmuje praktycznie
każdy obraz opublikowany przez kreator stron.

## Alternatywy odrzucone

- xAI Grok Imagine 2.0: portrety, brak 4:5 i przetwarzania w UE, C2PA z
  samopodpisanym certyfikatem, brak podpisu pod kodeksem KE.
- Vertex Nano Banana 2 jako główny: ok. 190 Elo mniej w portretach, 2–3×
  drożej; zostaje jako zapas.
- BFL FLUX.2, Recraft: jakość, licencja lub cena.
- OpenRouter, fal, Replicate: brak kontroli rozmiaru i 4:5, brak UE.
- Generowanie w przeglądarce albo z kluczem po stronie klienta: sprzeczne z
  ADR-033.
- Przełącznik odznaki jako zmienna środowiskowa: zmiana wymagałaby recreate i
  nie zostawiałaby śladu, kto i dlaczego wyłączył oznaczenie.
- Przełącznik w Django admin z prawem zapisu: logowanie admina omija MFA.
- Override entitlementu per organizacja: nie ma dziś operatorskiego wejścia do
  overridów poza kodem, a decyzja dotyczy całego serwisu.

## Weryfikacja

Koszt za obraz z `usage`, odsetek odmów i błędów, p50/p95 czasu generowania,
obecność XMP na oryginale i wariantach, wynik SynthID po normalizacji (pilot),
zero promptów w logach, RLS tabeli zleceń sprawdzony na uruchomionym stacku.
Przed udostępnieniem klientom: Tier OpenAI co najmniej 2, limit wydatków w
projekcie, projekt zmian regulaminu, AUP i DPA sprawdzony przez prawnika.
