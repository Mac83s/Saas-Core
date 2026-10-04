# Przegląd katalogu sekcji (F4-P0a)

`site-catalog.spec.ts` publikuje prawdziwe strony z katalogu sekcji i receptur
stron na działającym stosie, robi zrzuty w kilku szerokościach i w każdym stylu
strony, sprawdza je automatycznie i zapisuje stronę przeglądu w HTML.

Zasada właściciela: szablon trafia do katalogu dopiero po obejrzeniu zrzutów w
390 i 1440 px.

## Kiedy uruchamiać

- przed dodaniem do katalogu nowego szablonu sekcji albo nowej wersji szablonu;
- przed dodaniem albo zmianą receptury strony (`SITE_CATALOG_PAGES=1`);
- w każdym pakiecie fazy 4, przed odbiorem.

Nie jest częścią zwykłego przebiegu e2e: bez `SITE_CATALOG_HARNESS=1` test jest
pomijany, bo publikuje wiele stron na żywym stosie.

## Jak uruchomić

Na VPS (dev: `https://saas.goldenstar.cloud`), z katalogu głównego repozytorium:

```bash
SAAS_CORE_BASE_URL=https://saas.goldenstar.cloud \
SITE_CATALOG_STYLES=editorial,technical \
bash apps/frontend/e2e/site-catalog-run.sh
```

Skrypt:

1. zakłada syntetyczne konto `w6-e2e-catalog-<losowe>@example.test`
   (`sites_e2e_fixture prepare` w kontenerze backendu; hasło idzie przez
   zmienną środowiskową, nie w linii poleceń);
2. uruchamia spec w kontenerze `mcr.microsoft.com/playwright:v1.62.1-noble`
   (`--network host`), przekazując mu gotowe dane logowania;
3. zawsze, także po błędzie, usuwa konto i jego tenant
   (`purge_test_tenants --apply`), kasuje pliki z pokwitowania usunięcia
   (`purge_erased_objects`) i wypisuje `site-catalog cleanup: {...}`. Poprawny wynik to
   `accountRemoved: true`, `organizationRemoved: true`, `pendingObjects: 0`.

Kontener Playwright nie ma dostępu do `docker exec`, dlatego fiksturę prowadzi
skrypt na hoście. Dodatkowe argumenty skryptu trafiają do `playwright test`.

Na maszynie, gdzie Playwright i Docker działają na tym samym hoście, spec może
sam przygotować i sprzątnąć konto (wywołuje ten sam skrypt z `prepare` /
`cleanup`):

```bash
cd apps/frontend
SITE_CATALOG_HARNESS=1 pnpm exec playwright test e2e/site-catalog.spec.ts
```

Ręczne sprzątanie po przerwanym przebiegu (dane konta z logu):

```bash
SITE_CATALOG_SLUG=w6-e2e-catalog-… SITE_CATALOG_EMAIL=w6-e2e-catalog-…@example.test \
bash apps/frontend/e2e/site-catalog-run.sh cleanup
```

### Zmienne

| Zmienna                                                            | Znaczenie                                                                                                         |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `SITE_CATALOG_HARNESS=1`                                           | włącza test (skrypt ustawia sam)                                                                                  |
| `SAAS_CORE_BASE_URL`                                               | panel i API; domyślnie `http://127.0.0.1:8080`, na VPS `https://saas.goldenstar.cloud`                            |
| `SITE_CATALOG_STYLES`                                              | style strony po przecinku; domyślnie wszystkie 8 z `page-presentation.v2`                                         |
| `SITE_CATALOG_ALL=1`                                               | wszystkie oferowane szablony; domyślnie tylko wpisy, których `(id, version)` nie ma w `section-templates.v6.json` |
| `SITE_CATALOG_PAGES=1`                                             | dodatkowo każda oferowana (nie wycofana) receptura strony, importowana tym samym endpointem co w panelu           |
| `SITE_CATALOG_ONLY`                                                | prefiksy id po przecinku (np. `core.gallery,core.studio_portfolio`): tylko te szablony i receptury                |
| `SITE_CATALOG_PROXY`                                               | Caddy stosu, przez który idzie opublikowana witryna; domyślnie `127.0.0.1:8080`                                   |
| `SAAS_CORE_BACKEND_CONTAINER`                                      | kontener backendu dla fikstury; domyślnie `saas-core-backend-1`                                                   |
| `SITE_CATALOG_EMAIL`, `SITE_CATALOG_PASSWORD`, `SITE_CATALOG_SLUG` | gotowe konto; gdy są ustawione, spec nie zakłada ani nie usuwa konta sam                                          |

Koszt: jedna strona na każdą paczkę do 20 sekcji (albo recepturę) i styl, każda
w 5 szerokościach (320, 390, 768, 1024, 1440; strony z szerokością `full`
także 3440). Przy obciążonym hoście uruchamiaj z dwoma stylami, pełną macierz
tylko przed odbiorem.

## Gdzie jest wynik

W katalogu wyjściowym Playwright (`.runtime/playwright/`, poza drzewem repo,
czyszczony przy każdym przebiegu):

- `site-catalog/index.html` — strona przeglądu: na górze lista problemów,
  potem każdy szablon (`id@wersja`, układ, etap konwersji) ze zrzutami sekcji
  obok siebie per szerokość i styl, na końcu całe strony;
- `site-catalog/<styl>/<strona>-<szerokość>.png` — zrzut całej strony;
- `site-catalog/<styl>/<strona>/<id szablonu>-<szerokość>.png` — zrzut jednej sekcji.

## Co sprawdza

Dla każdej strony i szerokości; problemy są zbierane (test nie staje na
pierwszym) i na końcu test pada z ich listą:

- **poziomy overflow** — `scrollWidth` dokumentu większy niż szerokość okna o
  więcej niż 1 px: coś wystaje poza ekran, zwykle na 320/390 px;
- **pageerror** — nieprzechwycony błąd JavaScript na opublikowanej stronie;
- **kotwice** — każdy link `href="#…"` musi wskazywać istniejący `id`
  (szablon, którego przycisk prowadzi do `#kontakt`, potrzebuje sekcji z tą
  kotwicą — na stronie przeglądu jej nie ma, więc zobaczysz to jako problem);
- **`[object Object]`** w tekście — obiekt wyrenderowany zamiast tekstu;
- **alt obrazów** — każdy `img` ma atrybut `alt` (pusty jest dozwolony dla
  dekoracji);
- **najwyżej jedna główna akcja na sekcję** — liczone są
  `.site-section__action` bez modyfikatora `--secondary` w każdym bezpośrednim
  dziecku `main` (jedno dziecko = jedna sekcja);
- liczba wyrenderowanych sekcji równa liczbie szablonów na stronie (inaczej
  zrzuty sekcji nie pasowałyby do szablonów);
- **kopie zdjęć nie zmieniają układu** — po zrzutach każde zdjęcie traci
  `srcset` i wczytuje oryginał, jak przed F4-P3; jego pudełko musi zostać to
  samo (±1 px). Inaczej ramka układu zależy od `sizes`, np. opakowanie odznaki
  „AI” kurczy się do szerokości slotu.

## Test edytora tekstu (`site-rich-text-editor.spec.ts`)

Prowadzi edytor WYSIWYG (TipTap, ADR-056) w prawdziwym panelu na działającym
stosie — jsdom nie pisze w `contentEditable`, więc tylko tu sprawdzane są:
pisanie, Ctrl+B, nowy śródtytuł H2 z kotwicą (niezmienną po zmianie tekstu),
Tab na liście i odmowa trzeciego poziomu, link `#kontakt` z okna linku
(podpowiada kotwice strony), F8 zastępujące `[Uzupełnij: …]`, wklejka z Worda
(zdarzenie `paste` z HTML-em Worda), pisanie na pełnym ekranie w kroju strony,
Ctrl+Z, Ctrl+Shift+Z i Ctrl+Y jako cofanie strony z zachowaniem kursora, zapis
„Zapisz stronę” i dokładny JSON bloku odczytany z API, zero błędów JS.

Lokalnie (stos na `:8080`, Docker na tym samym hoście):

```bash
cd apps/frontend
SITE_EDITOR_E2E=1 pnpm test:e2e e2e/site-rich-text-editor.spec.ts
```

Bez `SITE_EDITOR_E2E=1` test jest pomijany. Spec sam zakłada konto
`w6-e2e-editor-<losowe>@example.test` (`site-catalog-run.sh prepare`) i zawsze
je usuwa (`cleanup`; w logu `site-catalog cleanup: {...}` z
`accountRemoved: true`). `pnpm test:e2e` dokłada biblioteki Chromium z
`.runtime/playwright-deps` — samo `pnpm exec playwright test` na WSL nie
uruchamia przeglądarki. Gdy `.runtime/playwright/` po przebiegu w kontenerze
należy do roota, dodaj `--output <katalog>`. Trwa ok. 15 s.

## Test studia strony (`sites-publication.spec.ts`)

Prowadzi prawdziwe Site Studio od zera do opublikowanej i przywróconej
strony: onboarding witryny w panelu (adres, dane, utworzenie), nowa podstrona,
szablon całej strony „Jedna usługa — konkret” (sekcje i zdjęcie), metadane
strony, a na płótnie: edycja nagłówka wybranej sekcji w miejscu (Enter
zatwierdza), przeniesienie sekcji strzałką na uchwycie, „+” przed pierwszą
sekcją i „Dodaj sekcję na końcu strony”, Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y z
fokusem na płótnie, widok „Telefon” i z powrotem, „Zmień zdjęcie” otwierające
pole „Obraz” w panelu edycji. Potem „Zapisz stronę” i odczyt draftu z API
(kolejność bloków, nagłówek), publikacja, sprawdzenie opublikowanej strony pod
jej własnym hostem (przeglądarka jak w `site-catalog.spec.ts`; jedyna podstrona
witryny jest jej stroną główną, więc stoi pod `/`, a adres z jej slugiem —
z ukośnikiem i bez — odpowiada jednym 308, ADR-071 pkt 11), druga
publikacja ze zmienionym nagłówkiem i przywrócenie pierwszej publikacji
(„Przywróć jako nową publikację”); draft zostaje nietknięty. Zero błędów JS w
panelu i na opublikowanej stronie.

Lokalnie (stos na `:8080`, Docker na tym samym hoście):

```bash
cd apps/frontend
SITE_STUDIO_E2E=1 pnpm test:e2e e2e/sites-publication.spec.ts --output <katalog>
```

Bez `SITE_STUDIO_E2E=1` test jest pomijany. Konto
`w6-e2e-studio-<losowe>@example.test` zakłada i usuwa `site-catalog-run.sh`
(`prepare` / `cleanup`), jak w teście edytora tekstu.

## Test tłumaczenia strony (`site-translation.spec.ts`)

Prowadzi automatyczne tłumaczenie strony od zlecenia do opublikowanej wersji
językowej (TL15d): firma włącza niemiecki i tryb „po akceptacji”, publikuje
polską witrynę z jedną stroną, w trybie języka edytora nadaje wersji
niemieckiej adres („Nadaj adres i tytuł”), zleca „Przetłumacz (AI)” — okno
podaje liczbę znaków, koszt 1 kredytu i to, że gotowy tekst poczeka — worker
tłumaczy, wersja czeka na decyzję — pola pokazują już jej tekst (tylko do
odczytu), nic nie proponuje drugiego zlecenia, a `/de/` nie odpowiada 200 — osoba
klika „Zaakceptuj i opublikuj”, pola pokazują tekst obok źródła, a opublikowana
witryna odpowiada po niemiecku pod `/de/` (`lang="de"`, nagłówek i tekst atrapy,
link „Deutsch” na polskiej stronie). Zero błędów JS w panelu i na stronie.

Tłumaczy atrapa (`fake/echo`: każdy fragment wraca z „[de] ” na początku),
włączona tylko dla syntetycznej firmy tego biegu — żaden prawdziwy model nie
jest wołany i nic nie kosztuje. Wymaga stosu z `MODEL_PORT_TEST_DOUBLE=true`
(lokalna nakładka `.runtime/compose.local.yaml`; nigdy na stosie serwowanym po
https — kontrola startowa `model_port.E003`). Bez przełącznika `prepare`
odmawia, usuwa konto i test kończy się błędem przed pierwszym krokiem.

```bash
cd apps/frontend
SITE_TRANSLATION_E2E=1 pnpm test:e2e e2e/site-translation.spec.ts --output <katalog>
```

Bez `SITE_TRANSLATION_E2E=1` test jest pomijany. Konto
`w6-e2e-translate-<losowe>@example.test` zakłada i usuwa
`site-translation-run.sh` (`prepare` / `cleanup`): to konto z
`site-catalog-run.sh` plus wpis na listę atrapy (`translation_e2e_fixture on`,
operator `operator@saas.test` albo `SITE_TRANSLATION_OPERATOR`) i miesięczna
pula 50 kredytów, z której zlecenie blokuje swój koszt. Trwa ok. 20 s.

## Test centrum tłumaczeń (`translation-centre.spec.ts`)

Prowadzi „Strona internetowa → Tłumaczenia” od zlecenia do decyzji (TL16g), z tą
samą atrapą i tym samym kontem pomocniczym (`site-translation-run.sh`): firma
włącza niemiecki i tryb „po akceptacji”, publikuje polską witrynę z jedną stroną
i wypełnia wizytówkę; w przeglądzie widzi stronę, a pod „Rodzaj: Nagłówek i
stopka, wizytówka, usługi” — wizytówkę; „Przetłumacz brakujące i nieaktualne
(AI)” zleca obie naraz, okno podaje znaki i koszt i prowadzi zlecenie do
„Tłumaczenie gotowe”; propozycję wizytówki osoba czyta obok źródła i akceptuje
z komórki przeglądu (wizytówka ma potem teksty atrapy), wersję strony odrzuca w
„Do akceptacji” (filtr powodu pyta serwer, `/de/` nie odpowiada 200), zleca ją
jeszcze raz z wiersza, akceptuje w „Do akceptacji” — `/de/` odpowiada po
niemiecku, a komórka prowadzi „Otwórz na stronie” pod `/de/`; „Zadania” pokazują
oba zlecenia, „Wstrzymane” jest puste; włączenie automatu zmian w „Języki i
tłumaczenia” zapisuje zgodę osoby. Zero błędów JS w panelu.

```bash
cd apps/frontend
SITE_TRANSLATION_E2E=1 pnpm test:e2e e2e/translation-centre.spec.ts --output <katalog>
```

Bez `SITE_TRANSLATION_E2E=1` test jest pomijany. Konto
`w6-e2e-centre-<losowe>@example.test`; trwa ok. 25 s.
