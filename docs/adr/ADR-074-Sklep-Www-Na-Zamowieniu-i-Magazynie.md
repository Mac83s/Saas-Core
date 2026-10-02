# ADR-074 — Sklep www na zamówieniu i magazynie

**Status:** Accepted — decyzje właściciela (plan rezerwacji uniwersalnych,
odpowiedzi 1–24 z 01–02.10.2026) i decyzje techniczne agenta (T1–T23 planu);
pozostałe rozstrzygnięcia techniczne tego ADR-u (z powodem w tekście):
sprawdzana rezerwacja i wydanie w `inventory.api`, koszyk na serwerze, tokeny
szukane w tenancie hosta, zdjęcia na wersji produktu, cena w wariancie, API i
strony systemowe sklepu na hoście firmy, dzień firmy w dokumentach magazynu.
**Data:** 2026-10-02
**Zmienia:** ADR-027 — „publiczny renderer odczytuje wyłącznie bieżącą
publikację” (pkt 7), usuwanie mediów „gdy żadna publikacja go nie
referencjonuje” (pkt 2) i przyjmowane pliki w „Media i storage” (pkt 5);
ADR-028 — „Renderer używa wyłącznie kontrolowanego registry
`@saas-core/site-blocks`” i „jego jedynym źródłem danych pozostaje zatwierdzony
snapshot” (pkt 7).
**Doprecyzowuje:** ADR-055 §1 — cena i stawka VAT pozycji magazynu są ceną przy
wizycie; w sklepie cenę niesie wariant, a stawkę produkt (pkt 2).
**Rozszerza:** ADR-055 §8 i §11 (pkt 2, 3, 5); ADR-071 pkt 12 o segmenty sklepu
(pkt 7). **Uzupełnia:** ADR-073 (źródło zamówień `Z`, dostawa, realizacja) i
ADR-072 §10 (okno odbioru, pkt 6).
**Nie zmienia:** ADR-040 — VAT abonamentów platformy, nie sprzedaży firm.

## Kontekst

Właściciel włączył sklep www do planu rezerwacji uniwersalnych (memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`, decyzja 2): produkty fizyczne i
cyfrowe, bony, odbiór osobisty, kurier ryczałtem i Paczkomaty, bez etykiet
przewoźników (4a); sklep w każdym planie z limitem produktów (7a) — Profil 20,
Starter 200, Pro 2000 (12a); jedna waluta cennika i płatności firmy (16).
Pieniądze żyją w zamówieniu `shared.commerce` (T9, ADR-073), towar w magazynie
rdzenia (ADR-055); sprawy prawne nie blokują budowy (21).

## Decyzja

### 1. Moduł `shared.shop`

`dependsOn`: `core.organizations`, `shared.billing`, `shared.customers`,
`shared.commerce`, `shared.inventory`, `shared.media`, `shared.notifications`,
`shared.sites`; `urlPrefix` `/api/v1/shop`; uprawnienia `shop.read`,
`shop.manage` (katalog, ceny, dostawy, ustawienia) i `shop.fulfil` (realizacja,
zwrot towaru), nadawane jak w magazynie; zwrot pieniędzy wymaga
`commerce.payments.*` (ADR-073). Entitlement `shop.enabled`. Rezerwacje są
zależnością opcjonalną (`ACTIVE_MODULES` i leniwy import `booking.api`, wzór
`shared/booking/materials.py`). Żaden moduł nie importuje sklepu; sklep wpina
się w ich rejestry. Publicznie sklep działa po włączeniu przez firmę
(`ShopSettings`), które wymaga obowiązującego regulaminu sklepu i polityki
prywatności (T16, ADR-073 §9). Tabela klienta zostaje w migracjach booking
(ADR-073 §2), więc `deployment-check` odrzuca profil z `shared.customers` bez
`shared.booking`; pierwszy profil ze sklepem bez rezerwacji czeka na
odwracalną migrację, która odda customers tabelę, politykę i strażnika.

### 2. Katalog, ceny i Omnibus

- `Product`: nazwa, `slug`, opis, rodzaj `physical | digital | voucher | pass`,
  kategoria (drzewo `ProductCategory`, osobne od magazynu), stawka VAT, nazwy
  opcji, stan `draft | active | archived` (usuwanie to archiwizacja), `version`.
- Zdjęcia należą do niezmiennej wersji produktu (`ProductVersion` jak
  `PageVersion`; właściciel referencji `shop.product_version`, migracja media
  jak 0009): referencje są tylko do dopisywania, a inny zestaw zdjęć tego samego
  właściciela to `ResourceReferenceConflict` (`media/references.py:40-43`).
  Publicznie widać zdjęcia bieżącej wersji aktywnego produktu (pkt 7), a obiekt
  usuniętego medium (`media/services.py:892-897`) czeka, poza publikacjami, na
  bieżącą wersję niezarchiwizowanego produktu, o którą media pytają rejestr.
- `ProductVariant`: wartości opcji, `price_minor`, `compare_at_price_minor`
  (cena przed obniżką), `weight_grams`, `version`. Wariant fizyczny wskazuje
  jedną pozycję magazynu (id bez klucza obcego, sprawdzane przez
  `describe_items` z ADR-055 §11, który dostaje `sku` — SKU pozycji jest SKU
  wariantu), a pozycja należy do najwyżej jednego aktywnego wariantu
  (`shop_variant_item_taken`); filtr po SKU daje nowa operacja `inventory.api`.
- Cena to liczba całkowita w jednostkach mniejszych waluty firmy, brutto albo
  netto według ustawienia wspólnego z cennikiem rezerwacji (ADR-072 §6); kody
  VAT jak w magazynie (`23`, `8`, `5`, `0`, `zw`). Cena i stawka pozycji
  magazynu zostają ceną przy wizycie (`booking/materials.py:116`; komentarze
  `inventory/models.py:161, 179` zmienia ta sama zmiana), a serwis zapisu
  wariantu podpowiada je jako domyślne — jedna ścieżka dla panelu i asystenta.
- Zmiana ceny wariantu to wiersz `ProductPriceChange` tylko do dopisywania
  (furtka usunięcia tenanta, ADR-042 §2). Przy ogłoszonej obniżce API zwraca
  `lowest_price_30d_minor` — najniższą cenę z 30 dni przed obniżką, liczoną z
  historii — a strona pokazuje ją przy każdej obniżce.

### 3. Magazyn wyłącznie przez `inventory.api` (T14)

Dziś `reserve` nigdy nie odmawia, a `consume` księguje z `allow_negative=True`
(`inventory/services.py:1271-1279, 1414-1457`). Oba dostają `strict` z domyślnym
`False`, więc wizyty, teren i dokumenty wewnętrzne dalej ostrzegają i zapisują
(ADR-055 §8). Źródło to `shop.order` z id zamówienia, miejsce — magazyn główny.

- **Zakup** rezerwuje w swojej transakcji z `strict=True`: 409 `stock_shortage`
  (pozycja koszyka w polu błędu), gdy stan minus zarezerwowane — przy partiach
  tylko ważne — nie pokrywa ilości. O ostatniej sztuce rozstrzyga blokada
  wiersza stanu, którą `reserve` już bierze; pozycje blokujemy po id.
- **Wydanie** (wysyłka, odbiór): `release_reservations` i `consume(kind="WZ",
  strict=True)` w jednej transakcji, jak rozliczenie wizyty; odmawia, gdy towaru
  albo ważnej partii brakuje fizycznie (`stock_shortage`, `stock_lot_expired`;
  `LotExpired` dochodzi do eksportów `api.py`).

### 4. Koszyk, zakup i źródło zamówień

- **Wejście publiczne** `/api/v1/public/shop/…` (jak `/api/v1/public/site/`, w
  trasach modułu) wyznacza firmę z hosta strony (ADR-041) nowym eksportem
  `sites.api`, sprawdza `Origin` i działa w kontekście `service` sklepu z
  minimalnym zakresem, jak `public_booking_context`. Prefiks dochodzi do tras
  adresowanych hostem w `http/hosts.py` (dziś spoza `ALLOWED_HOSTS` przechodzi
  tylko `/api/v1/public/site/…`), z testem kolejności `SET LOCAL` (ADR-039 §3).
  Bramka modułów nie ocenia żądań bez tenanta, więc serwis sam sprawdza moduł
  typu, `shop.enabled` i włączenie sklepu; limity per klient i host.
- **Koszyk** (`Cart`, `CartLine`) jest na serwerze, bez cen i rezerwacji;
  zmiana to ustawienie ilości wariantu. Token gościa (≥ 256 bitów, w bazie
  skrót) leży w ciasteczku `HttpOnly`, `Secure`, `SameSite=Lax` hosta strony;
  kanał i podpisany token pochodzenia idą w adresie albo w stanie strony, nigdy
  w ciasteczku. Cenę liczy jedna funkcja serwera dla koszyka, zakupu i
  asystenta, w kształcie pozycji zamówienia (jak `quote`, ADR-072 §7).
- **Zakup** w jednej transakcji wycenia koszyk i porównuje skrót wyceny
  widzianej przez klienta (`cart_digest`: pozycje, dostawa, rabaty, waluta; inny
  to 409 `cart_price_changed` z nową wyceną, jak `quote_digest`), zakłada
  zamówienie z ADR-073 (prefiks `Z/`, kanał `company_site` albo `catalog` z
  tokenem pochodzenia, migawka kupującego, dane do faktury z opcjonalnym
  NIP-em, wersje dokumentów, osobna zgoda marketingowa — T16), zapisuje dostawę
  i rezerwuje towar. Kupujący to klient z `shared.customers` (T10, konto
  dobrowolne). Zakup i płatność ze strony zamówienia wołają `commerce.api` w tym
  kontekście z zakresem `commerce.public.pay`; kwoty liczy serwer, a token
  strony wiąże płatność z jednym zamówieniem.
- **Źródło zamówień:** `commerce.api.register_order_source("shop.order", "Z",
  handler)` (ADR-073 §1); pozycje towaru i dostawy niosą to źródło. Handler
  działa w transakcji zmiany stanu, w punkcie zapisu: przy anulowaniu i
  wygaśnięciu zwalnia towar, po opłaceniu zakłada realizację i linki pobrań. Gdy
  zmiany przyjąć nie może (wpłata po wygaśnięciu, towaru brak), zwraca odmowę
  zamiast wyjątku — wpłata zostaje zapisana, a commerce zleca zwrot i zgłoszenie
  operatora (ADR-037 §6). Przejścia zlecone przez sklep go nie wołają.
- **Termin przelewu** (dni w `ShopSettings`) daje `Payment.due_at`; po nim
  zadanie terminów commerce wygasza płatność i anuluje zamówienie, a handler
  sklepu w tej samej transakcji zwalnia towar (ADR-073 §5).

### 5. Dostawa, realizacja, produkty cyfrowe i zwroty

- `DeliveryMethod`: nazwa, rodzaj `pickup | courier | parcel_locker`, cena
  ryczałtowa, darmowa od kwoty, progi wagowe, stawka VAT, płatność przy
  odbiorze, `active`, `version`. Paczkomat klient wybiera na mapie; paczkę firma
  nadaje sama i wpisuje numer śledzenia.
- `Fulfillment` to szczegóły zamówienia 1:1 (klucz obcy przez stałą
  `ORDER_MODEL` z `commerce.api`, wzór `APPOINTMENT_MODEL`): metoda, migawka
  dostawy, stan `pending | ready_for_pickup | shipped | picked_up | returned`,
  śledzenie. Startuje po opłaceniu albo przy płatności przy odbiorze; jedno
  wydanie (WZ) na zamówienie, potem sklep zgłasza `fulfilled` (ADR-073 §3).
  E-maile „przyjęte”, „opłacone”, „wysłane”, „gotowe do odbioru” idą trwałą
  kolejką z kluczem idempotencji, w języku klienta (ADR-071 pkt 20).
- **Strona zamówienia** gościa na hoście strony (stan, śledzenie, płatność,
  pobrania, odstąpienie) działa co najmniej przez termin odstąpienia, z
  `noindex` i `no-referrer`. Token (≥ 256 bitów) baza trzyma jako skrót i
  szyfrogram do kolejnych e-maili (`encrypt_secret` z `notifications.api`, jak
  `self_service_token_ciphertext`). Tokenu strony i pobrań nie ma w ścieżce ani
  w logach (AGENTS.md): API bierze go z nagłówka albo treści `POST`, link z
  e-maila niesie go we fragmencie adresu, a ścieżki stron zamówienia i pobrań
  mają `log_skip` w Caddy i maskę w `JsonFormatter` (jak iCal, ADR-075 §5).
- Plik produktu cyfrowego to prywatny zasób `shared.media` spoza obrazów: bez
  dekodowania, EXIF i wariantów, nigdy publiczny (zmiana ADR-027; dziś media
  przyjmują tylko JPEG, PNG i WebP). Typy, skaner i limit rozmiaru ustala faza 9
  przed kodem. Po opłaceniu pozycja dostaje link pobrania (skrót tokenu,
  ważność, unieważnienie przy zwrocie), a zamówienie wyłącznie cyfrowe jest
  wtedy zrealizowane.
- **Odstąpienie** (14 dni) klient zgłasza ze strony zamówienia (`ReturnRequest`:
  `requested | accepted | received | refunded | rejected`); dnia doręczenia
  sklep nie zna, więc decyduje firma. Pieniądze oddaje `Refund` z ADR-073, a
  towar wraca na stan nową operacją `inventory.api` ze źródłem `shop.return`
  (`cancel_source` cofa całe źródło, a zwrot bywa częściowy; kształt — faza 9).

### 6. Funkcje wspólne z rezerwacjami

- **Bony, karnety i kody rabatowe** (faza 10) należą do `shared.commerce`, bo
  służą też rezerwacjom; sklep sprzedaje bon i karnet jako produkt (`voucher`,
  `pass`, bez stanu) i przyjmuje kod albo bon w koszyku.
- **Okno odbioru** (preset 13, faza 9 po wydarzeniach z fazy 8) to dostawa
  `pickup` wskazująca wystąpienie oferty `session` presetu `core.pickup_window`:
  limit zamówień na okno to liczone miejsca, które T3 dopuszcza tylko w
  wydarzeniu (odstępstwo od tabeli planu „slot + sklep” — decyzja techniczna
  ADR-072 §10). Jedno zamówienie zajmuje jedno miejsce. Zakup rezerwuje je w tej
  samej transakcji przez `booking.api.create_appointment` z nowym, opcjonalnym
  argumentem zamówienia (addytywnie, HoofCare bez zmian), więc nie powstaje
  osobne zamówienie `R/`, a potwierdzenie okna idzie w e-mailu zamówienia.
  Anulowanie zamówienia odwołuje rezerwację handlerem jej źródła (ADR-073 §1).

### 7. Strona: bloki, strony systemowe i dane na żywo

- `core.product` v4 dostaje opcjonalne odwołanie do produktu, a nowy
  `core.product_list` v1 listę; cenę, dostępność, warianty i „Do koszyka”
  renderer czyta na żywo z publicznego API, więc publikacja ceny nie zamraża, a
  automatyzacja treści jej nie zmieni (jak `core.pricing`). To addytywne wersje
  kontraktu bloków rdzenia (ADR-049) z wyjątkami klasyfikatora tłumaczeń.
- Strony systemowe (produkt ze slugiem, koszyk, zakup, zamówienie) mają własne
  pierwsze segmenty, wspólne dla języków jak ścieżki blogów (ADR-071 pkt 14),
  które ten ADR dopisuje do zarezerwowanych w ADR-071 pkt 12 (`slug_reserved`).
  Starsze strony firm o tych slugach wypisuje `sites_reserved_slugs`, a firma z
  taką stroną nie włączy sklepu przed zmianą slugu. Trasy składa warstwa
  aplikacji (`app/site-renderer/…`), a renderer `shared.sites` nie importuje
  sklepu. Koszyk, zakup i zamówienie mają `noindex`, a produkty są w mapie
  strony z danymi strukturalnymi w walucie firmy.
- Dane sklepu nie wchodzą do migawki publikacji (zmiana ADR-027 i ADR-028); to
  pierwsze dane na żywo w rendererze strony firmy, bo widget rezerwacji żyje na
  hoście platformy (`app/[locale]/book/[publicSlug]`). Media publiczne biorą się
  dziś tylko z migawek, więc `shared.sites` dostaje rejestr publicznych źródeł
  (zdjęcia aktywnych produktów, wpisy mapy strony), w który wpina się sklep.

### 8. Treść sklepu jako źródło tłumaczeń

Nazwy, opisy i wartości opcji produktów oraz nazwy kategorii i metod dostawy
mają w sklepie wiersz tłumaczenia na język (`ProductTranslation` i pokrewne,
jak `PublicProfileTranslation`: język, wersja, flagi zastępstw), który silnik
tylko wypełnia — plan rezerwacji, TL12, tak samo booking (ADR-072 §11). Źródła
rejestrują się w rejestrze tłumaczeń rdzenia w `AppConfig.ready`, bez importu
silnika (TL-T17; ADR-069, zarezerwowany, w przygotowaniu). Język to `^[a-z]{2}$`
sprawdzany w serwisie (TL-T2), do czasu rejestru języków (ADR-071, faza TL1).

### 9. Limity planu

Cechę `shop.enabled` publikuje migracja modułu przez `publish_feature` (wzór
`inventory` 0003) we wszystkich planach (7a); limit `shop.products.max`
(`profile` 20, `starter` 200, `pro` 2000 — 12a) trafia do nowych wersji planów
(T23, wzór billing 0025), tymczasowo wbrew „konfigurowalne w panelu” z 12a.
Subskrypcja na starszej wersji nie ma sklepu, dopóki nie przejdzie na nową
(`billing/feature_migrations.py:23-25`); przeniesienie istniejących, także kont
testowych, to krok w `memex ops`. Limit liczy produkty, nie warianty (odczyt
12a, otwarty dla właściciela), i blokuje tylko dodanie albo przywrócenie
(`decide_quota`, jak `pages.max`); więcej daje `EntitlementGrant` (T18).

### 10. Obsługa przez asystenta AI (reguła `AGENTS.md`)

- Logika w serwisach dla panelu, strony i asystenta; serializery z `help_text`
  i enumami; Problem Details z polem i kodem (`stock_shortage`,
  `stock_lot_expired`, `cart_price_changed`, `shop_product_limit_reached`,
  `shop_variant_item_taken`, `shop_version_conflict`); akcje `shop.*` w
  `OrganizationAuditAction` z kanałem aktora, „w imieniu” z ADR-076.
- Mutacje, także zakup, zapisują `Idempotency-Key` ze skrótem żądania w
  `ShopMutation` (kształt `BookingSetupMutation` z ADR-072, tabela z RLS), a
  zapis niesie `expected_version` — nieaktualna to 409. Konfiguracja (produkt,
  wariant, ceny ze skutkiem dla Omnibus, dostawa) ma podgląd bez zapisu.
  Ryzyko (ADR-033): szkic produktu jest odwracalny, aktywacja, zmiana ceny i
  włączenie sklepu wymagają osobnej zgody, a wydanie, zwrot pieniędzy i
  anulowanie są nieodwracalne i mówią w docstringu, czemu nie mają podglądu.
- Produkt, wariant, kategoria i metoda dostawy założone przez asystenta niosą
  id jego przebiegu i są nieaktywne do uruchomienia (plan asystenta, AI-T6).
- `GET /api/v1/shop/options/` podaje rodzaje, kody VAT, dostawy, walutę, tryb
  brutto/netto, języki, limit i zużycie; listy `products/` i `fulfillments/`
  (zamówienia listuje commerce, ADR-073 §11) są stronicowane i filtrowane.

### 11. Izolacja, zadania i usuwanie

Tabele sklepu to `TenantScopedModel` z wymuszonym RLS i wyzwalaczem relacji
między tenantami dla każdego klucza obcego. Tokeny koszyka, zamówienia i pobrań
szukamy w tenancie wskazanym przez host — bez `PRE_TENANT_DB` i globalnej tabeli
routingu. Porzucone koszyki kasuje zadanie raz na dobę: firmy z
`billing.api.billing_organization_ids()` (drzwi przemiatań, ADR-041), potem
własna transakcja z `SET LOCAL` na firmę (wzór `image_generation/tasks.py`).
Usunięcie tenanta kasuje tabele sklepu, a anonimizacja klienta czyści dane
dostawy przez `register_customer_anonymizer` (ADR-073 §2).

## Konsekwencje

- Deskryptor, `coverage` w `.agents/evals/routing.json` i skill z wierszem w
  `AGENTS.md` (własny albo `develop-commerce-payments` — faza 9); profil
  `business` wymienia `shared.shop` z zależnościami (do migracji z pkt 1 także
  `shared.booking`). Odwracalne migracje `shop`, `billing`, `organizations` i
  `media`, `log_skip` w Caddyfile'ach i przeniesienie subskrypcji idą do VPS
  przez `memex ops add`.
- `consume`, korekta (`_correct`, przez którą `cancel_source` cofa anulowania i
  zwroty) i domyślna data dokumentu w panelu biorą dzień firmy
  (`organization_today`) zamiast UTC (`inventory/services.py:767, 941, 1324`) u
  wszystkich wołających: `_next_number` liczy rok z tej daty, więc dokument z
  00:30 1 stycznia dostaje dziś numer z poprzedniego roku.
- Nieopłacone zamówienie przelewem trzyma towar do `Payment.due_at`; przed
  botami chronią limity zapytań, ilości i nieopłaconych zamówień na klienta i
  host (liczby — faza 9), a firma może zamówienie anulować.
- Poza zakresem: etykiety przewoźników i feedy produktów (faza 14), Allegro,
  koszyk wspólny z rezerwacjami (poza oknem odbioru), częściowe wysyłki, kilka
  magazynów sklepu, cenniki B2B, faktury poza integracją (T15).
- Otwarte dla właściciela: czy limit 12a liczy produkty, czy warianty (do
  odpowiedzi — produkty). Faza 9: widżet Paczkomatów (CSP, klucz, dane
  osobowe), dane sprzedawcy na stronie zakupu i w e-mailach, pliki cyfrowe,
  liczby limitów, pamięć podręczna stron produktów. Na listę prawną m.in.: czy
  WZ ze sprzedaży jest dowodem księgowym (ADR-042 §7; zamówienie i księga nim
  nie są, ADR-073 §9).

## Odrzucone

- **Drugi stan towaru w sklepie** albo klucz obcy do modeli magazynu — dwa
  źródła prawdy o stanie (T14, ADR-055 §11).
- **Cena w bloku, w migawce albo w pozycji magazynu** — stara cena po zmianie,
  cena w zasięgu automatyzacji treści, brak historii dla Omnibus i wspólna cena
  z wizytą (wartości domyślne z pozycji podpowiada serwis zapisu wariantu).
- **Zdjęcia jako referencje zmiennego produktu** — pierwsza zmiana zdjęć dałaby
  `ResourceReferenceConflict`.
- **Rezerwacja przy dodaniu do koszyka albo koszyk jako zamówienie `draft`** —
  porzucone koszyki i boty trzymałyby stan, a szkice zaśmiecałyby zamówienia
  firmy (numer i tak powstaje przy złożeniu, ADR-073 §3).
- **Koszyk w przeglądarce** — asystent go nie dosięgnie, a cenę i stan i tak
  sprawdza serwer.
- **Token w ścieżce adresu** (jak link samoobsługi `/[locale]/booking/[token]`)
  — ścieżkę zapisują logi Caddy i backendu.
- **Globalna tabela routingu tokenów sklepu** — host już nazywa tenanta.
