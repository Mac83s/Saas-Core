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
  zrzuty sekcji nie pasowałyby do szablonów).
