# ADR-074 — Sklep www na zamówieniu i magazynie

**Status:** Accepted — decyzje właściciela 2, 4a, 7a, 12a i 16 z 01.10.2026
oraz 21 i 22 z 02.10.2026; decyzje techniczne T9, T10, T14, T16, T22 i T23
planu memex `saas-core-rezerwacje-uniwersalne-i-sprzedaz` (faza 1, ADR 3);
pozostałe szczegóły techniczne rozstrzyga ten ADR.
**Data:** 2026-10-02
**Zmienia:** ADR-027 w dwóch zdaniach — „publiczny renderer odczytuje wyłącznie
bieżącą publikację” (dane sklepu czyta na żywo, pkt 7) i usuwanie mediów, „gdy
żadna publikacja go nie referencjonuje” (także produkt sklepu, pkt 2).
**Rozszerza:** ADR-055 §1 (wariant sklepu = jedna pozycja magazynu), §8 i
§11 (sprawdzana rezerwacja i wydanie oraz przyjęcie zwrotu w `inventory.api`).
**Uzupełnia:** ADR-073 o pozycje, dostawę i realizację sklepu; ADR-072 o okno
odbioru (preset 13).
**Nie zmienia:** ADR-040 — VAT abonamentów platformy, nie sprzedaży firm.

## Kontekst

Właściciel włączył sklep www do planu rezerwacji uniwersalnych (decyzja 2) i
wyznaczył pierwszą wersję: produkty fizyczne i cyfrowe, bony, odbiór osobisty,
kurier ryczałtem i Paczkomaty, bez etykiet przewoźników (4a). Sklep jest w
każdym planie z limitem produktów (7a): Profil 20, Starter 200, Pro 2000 (12a).
Cennik firmy ma jedną walutę (PLN, EUR albo USD) i w niej firma przyjmuje
płatność (16). Pieniądze żyją w zamówieniu `shared.commerce`, wspólnym dla
rezerwacji i sklepu (T9, ADR-073); sprawy prawne nie blokują budowy (21).

Stan kodu (main e381199, ścieżki w `apps/backend/src/saas_core/`): ADR-055 §8
blokuje sprzedaż bez towaru, ale `inventory.api` tego nie umie — `reserve`
nigdy nie odmawia (`modules/shared/inventory/services.py:1414-1457`), `consume`
księguje z `allow_negative=True` i zakłada, że sprzedaż w sklepie „tędy nie
idzie” (`services.py:1271-1279, 1331`), a odmawia tylko WZ z panelu
(`services.py:802-807, 898-901, 1136-1162`). `core.product` v3: „Carries no
price, stock or cart data”
(`packages/contracts/site-blocks/core.product.v3.schema.json:5`).

## Decyzja

### 1. Moduł `shared.shop`

`dependsOn`: `core.organizations`, `shared.billing`, `shared.customers`,
`shared.commerce`, `shared.inventory`, `shared.media`, `shared.notifications`,
`shared.sites`; `urlPrefix` `/api/v1/shop`; uprawnienia `shop.read`,
`shop.manage` (katalog, ceny, dostawy) i `shop.fulfil` (realizacja, zwroty);
entitlement `shop.enabled`; `eventSchemas`, `publicTables` i `platformTables`
puste. Rezerwacje to zależność opcjonalna (pkt 6): `ACTIVE_MODULES` i leniwy
import `booking.api`, wzór `shared/booking/materials.py`. Żaden z tych modułów
nie importuje sklepu; mówią do niego przez własne rejestry. Profil wymienia
sklep z zależnościami, a typ organizacji decyduje, kto go widzi (ADR-050).
Publicznie sklep działa po włączeniu przez firmę (`ShopSettings`), które
wymaga obowiązującego regulaminu sklepu i polityki prywatności (T16).

### 2. Katalog, ceny i Omnibus

- `Product`: nazwa, `slug` (unikalny w firmie), opis, rodzaj `physical |
  digital | voucher | pass`, kategoria (`ProductCategory` — drzewo kategorii
  sklepu, osobne od kategorii magazynu), stawka VAT, zdjęcia, nazwy opcji,
  stan `draft | active | archived`, `version`. Usunięcie to archiwizacja.
- `ProductVariant`: wartości opcji (np. rozmiar, kolor), `price_minor`,
  `compare_at_price_minor` (cena przed obniżką — ogłasza obniżkę),
  `weight_grams`, `version`. Wariant fizyczny wskazuje jedną pozycję magazynu
  (`inventory_item_id`; jej SKU jest SKU wariantu), a pozycja należy do
  najwyżej jednego aktywnego wariantu (ADR-055 §1) — identyfikator bez klucza
  obcego, sprawdzany przez `describe_items` (§11).
- Cena to liczba całkowita w jednostkach mniejszych waluty firmy, brutto albo
  netto według ustawienia firmy wspólnego z cennikiem rezerwacji (ADR-072,
  ADR-073); strona pokazuje cenę końcową brutto. Stawka VAT ma kody magazynu
  `23`, `8`, `5`, `0`, `zw` (zwolnienie to nie 0%). Zdjęcia to `MediaAsset` z
  nowym właścicielem referencji `shop.product` (migracja media jak 0009);
  sprzątanie usuniętego medium, które dziś czeka tylko na publikacje
  (`modules/shared/media/services.py:892-897`), czeka też na produkty.
- Zmiana ceny wariantu (cena, cena przed obniżką, waluta, od kiedy, kto, kanał)
  to wiersz `ProductPriceChange` tylko do dopisywania; wyzwalacz odrzuca UPDATE
  i DELETE poza furtką usunięcia tenanta (ADR-042 §2, wzór billing 0022). Przy
  ogłoszonej obniżce API zwraca `lowest_price_30d_minor` — najniższą cenę z 30
  dni przed obniżką, liczoną przez serwer z historii — a strona pokazuje ją
  wszędzie, gdzie pokazuje obniżkę. Firma tej liczby nie wpisuje.

### 3. Magazyn wyłącznie przez `inventory.api` (T14)

Źródło rezerwacji i dokumentów to `shop.order` z id zamówienia, miejsce —
magazyn główny (`default_warehouse`), jak przy wizycie. Wizyty, teren i
dokumenty wewnętrzne dalej ostrzegają i zapisują (ADR-055 §8): nowe argumenty
mają wartości domyślne, a `LotExpired` dochodzi do eksportów `api.py`.

- **Zakup** rezerwuje w transakcji zakładającej zamówienie:
  `reserve(..., strict=True)` odmawia `StockShortage` (409 `stock_shortage`,
  pozycja koszyka w polu błędu), gdy stan minus zarezerwowane — przy partiach
  tylko ważne — nie pokrywa ilości. Sprawdza pod blokadą wiersza stanu, którą
  `reserve` już bierze (`modules/shared/inventory/services.py:1435`), więc o
  ostatniej sztuce rozstrzyga baza; pozycje blokujemy po id, a zakleszczenie
  to konflikt do ponowienia. Anulowanie i wygaśnięcie: `release_reservations`.
- **Wydanie** (wysyłka, odbiór) w jednej transakcji: `release_reservations`,
  potem `consume(kind="WZ", strict=True, …)`, jak rozliczenie wizyty
  (`modules/shared/booking/materials.py:167-191`). Odmawia, gdy towaru albo
  ważnej partii brakuje fizycznie (`stock_shortage`, `stock_lot_expired`);
  cudze rezerwacje go nie wstrzymują, bo zamówienie miało własną.
- **Zwrot towaru** wraca na stan tylko decyzją firmy, nową operacją ze
  źródłem `shop.return`: `cancel_source` cofa całe źródło, a zwrot bywa
  częściowy (korekta części WZ albo PZ — w fazie 9).

### 4. Koszyk i zakup

- **Wejście publiczne** `/api/v1/shop/public/…` wyznacza firmę z hosta strony
  (ADR-041) przez nowy eksport `sites.api`, sprawdza `Origin` i działa w
  kontekście `service` z minimalnym zakresem, jak formularz kontaktowy
  (`modules/shared/sites/inquiries.py:82-133`). Bramka modułów nie ocenia
  żądań bez tenanta (`config/module_gate.py:1-9`), więc serwis sam sprawdza
  moduł typu, `shop.enabled` i włączenie sklepu; limity per klient i host.
- **Koszyk** (`Cart`, `CartLine`) jest na serwerze. Token gościa (≥ 256 bitów)
  leży w ciasteczku `HttpOnly`, `Secure`, `SameSite=Lax` hosta strony, nigdy w
  `localStorage`; baza trzyma skrót. Koszyk nie trzyma cen i nie rezerwuje
  towaru; zmiana to ustawienie ilości wariantu, idempotentne z natury. Cenę
  liczy jedna funkcja serwera dla koszyka, zakupu i asystenta, zwracająca
  pozycje w kształcie pozycji zamówienia (jak `quote` z ADR-072).
- **Zakup** (`Idempotency-Key` ze skrótem żądania) w jednej transakcji wycenia
  koszyk, porównuje sumę z `expected_total_minor` widzianą przez klienta (inna
  to 409 `cart_price_changed` z nową wyceną), zakłada zamówienie z ADR-073
  (prefiks `Z/`, kanał „strona firmy”, migawka kupującego, dane do faktury z
  opcjonalnym NIP-em, wersje regulaminu i polityki, osobna zgoda marketingowa —
  T16), zapisuje dostawę i rezerwuje towar (pkt 3). Kupujący to klient z
  `shared.customers` (T10, konto dobrowolne — ADR-036 §5); płatność — ADR-073.

### 5. Dostawa, realizacja, produkty cyfrowe i zwroty

- `DeliveryMethod`: rodzaj `pickup | courier | parcel_locker`, cena ryczałtowa,
  darmowa od kwoty, progi wagowe, stawka VAT, płatność przy odbiorze (tak/nie),
  `active`, `version`. Paczkomat klient wybiera na mapie, punkt trafia do
  migawki dostawy; paczkę firma nadaje sama i wpisuje numer śledzenia.
- `Fulfillment` to tabela szczegółów zamówienia 1:1 (klucz obcy do `Order`
  przez stałą z `commerce.api`, wzór `APPOINTMENT_MODEL`): metoda, migawka
  dostawy, stan `pending | ready_for_pickup | shipped | picked_up | returned`,
  śledzenie, daty. Realizacja startuje po opłaceniu albo przy płatności przy
  odbiorze; jedno wydanie (jeden WZ) na zamówienie, potem `fulfilled`. E-maile
  „przyjęte”, „opłacone”, „wysłane” albo „gotowe do odbioru” idą trwałą kolejką
  z kluczem idempotencji, w języku klienta (plan wielojęzyczności TL10, TL17).
- **Strona zamówienia** gościa: link z tokenem (≥ 256 bitów, skrót w bazie,
  wzór ADR-030) na hoście strony — stan, śledzenie, pobrania, odstąpienie;
  działa co najmniej przez termin odstąpienia, ma `noindex` i `no-referrer`.
  Plik produktu cyfrowego leży w `shared.media` jako zasób prywatny; po
  opłaceniu pozycja dostaje link pobrania (token ze skrótem, ważność,
  unieważnienie przy zwrocie), a zamówienie wyłącznie cyfrowe jest wtedy
  zrealizowane. Media przyjmują dziś tylko JPEG, PNG i WebP
  (`modules/shared/media/services.py:81-84`) — faza 9 dodaje inne pliki.
- **Odstąpienie** (14 dni) klient zgłasza ze strony zamówienia: `ReturnRequest`
  z pozycjami i stanem `requested | accepted | received | refunded | rejected`.
  Bez śledzenia przesyłek sklep nie zna dnia doręczenia, więc zgłoszenia nie
  odrzuca sam — decyduje firma. Pieniądze oddaje `Refund` z ADR-073 tym samym
  portem płatności, a towar wraca operacją z pkt 3.

### 6. Funkcje wspólne z rezerwacjami

- **Bony, karnety i kody rabatowe** (faza 10) należą do `shared.commerce`, bo
  służą też rezerwacjom: bon to saldo w księdze, karnet to pula wejść na
  wskazane oferty, kod rabatowy to reguła ceny. Sklep sprzedaje bon i karnet
  jako produkt (`voucher`, `pass`, bez stanu; wydaje je zamówienie po
  opłaceniu) i przyjmuje kod albo bon w koszyku, jak formularz rezerwacji.
- **Okno odbioru** (preset 13, faza 9) to dostawa `pickup` wskazująca ofertę
  `slot` z ADR-072. Zakup zakłada w tej samej transakcji rezerwację okna przez
  `booking.api` jako pozycję zamówienia; anulowanie zamówienia ją odwołuje.
  Wolne okna i limit zamówień na okno liczy silnik rezerwacji, nie sklep.

### 7. Strona: bloki i strony systemowe

- `core.product` v4 dostaje opcjonalne odwołanie do produktu; cenę, dostępność,
  warianty i „Do koszyka” renderer czyta na żywo z publicznego API. Cena nie
  jest daną bloku, więc publikacja jej nie zamraża, a automatyzacja treści jej
  nie zmieni (jak `core.pricing`, `modules/shared/sites/services.py:1085`).
  Nowy `core.product_list` v1 (kategoria albo wybrane produkty, kolejność,
  liczba) linkuje do stron produktów. To addytywne wersje kontraktu bloków
  rdzenia (ADR-049), od razu z wyjątkami klasyfikatora tłumaczeń.
- Strony systemowe renderera — produkt (adres ze slugiem), koszyk, zakup,
  zamówienie — mają ścieżki wśród zarezerwowanych pierwszych segmentów (plan
  wielojęzyczności TL-T29; nazwy per język — ADR-071, zarezerwowany). Koszyk,
  zakup i zamówienie mają `noindex`; produkty są w mapie strony, z danymi
  strukturalnymi i ceną w walucie firmy (przeliczenie tylko orientacyjne, 16).
- Dane sklepu nie wchodzą do migawki publikacji — zmieniają się bez niej, jak
  wolne terminy widgetu rezerwacji (zmiana ADR-027); treść strony nadal idzie
  tylko z publikacji. Media publiczne biorą się dziś tylko z migawek
  (`modules/shared/sites/public_media.py:24-76`), więc `shared.sites` dostaje
  rejestr publicznych źródeł (zdjęcia aktywnych produktów, wpisy mapy strony),
  w który wpina się sklep.

### 8. Treść produktu jako źródło tłumaczeń

Nazwy, opisy i wartości opcji produktów oraz nazwy kategorii mają wiersz na
język (`ProductTranslation`, `ProductCategoryTranslation`; wzór
`PublicProfileTranslation` z `version`). Język to napis `^[a-z]{2}$` z języków
publicznych firmy, sprawdzany przez serwis, nie enum OpenAPI (TL-T2). Źródła
`shop.product` i `shop.category` sklep rejestruje w rejestrze rdzenia w
`AppConfig.ready`, bez importu silnika (TL-T17; ADR-069, zarezerwowany).

### 9. Limity planu

Cecha `shop.enabled` we wszystkich planach (7a) i limit `shop.products.max`:
`profile` 20, `starter` 200, `pro` 2000 (12a), w nowych, niezmiennych wersjach
planów (T23, wzór billing 0025); subskrypcje zostają na swojej wersji. Limit
liczy produkty, nie warianty, i blokuje tylko dodanie albo przywrócenie z
archiwum — `decide_quota` jak przy `pages.max`
(`modules/shared/sites/services.py:167-181`); partner dostaje więcej przez
`EntitlementGrant` (T18).

### 10. Obsługa przez asystenta AI (reguła `AGENTS.md`)

- logika w serwisach wołanych przez panel, stronę i asystenta; serializery z
  `help_text`, enumami i jednostkami; Problem Details z polem i stałym kodem
  (`stock_shortage`, `stock_lot_expired`, `cart_price_changed`,
  `shop_product_limit_reached`, `shop_variant_item_taken`,
  `shop_version_conflict`); akcje `shop.*` w `OrganizationAuditAction`
  (migracja `organizations`) z kanałem aktora, a „w imieniu” — z rejestrem
  poleceń (ADR-076, zarezerwowany);
- każdy zapis katalogu, ceny, dostawy i ustawień ma `Idempotency-Key` i
  `version` (nieaktualna to 409); konfiguracja (produkt, wariant, jedna i wiele
  cen ze skutkiem dla Omnibus, dostawa) ma podgląd bez zapisu, a wydanie, zwrot
  pieniędzy i anulowanie — docstring, czemu go nie mają (skutek zewnętrzny);
- `GET /api/v1/shop/options/` podaje rodzaje produktu, kody VAT, rodzaje
  dostawy, walutę, tryb brutto/netto, języki firmy, limit i jego zużycie;
  listy `/api/v1/shop/products/` i `/api/v1/shop/orders/` są stronicowane i
  filtrowane (nazwa, SKU, kategoria, rodzaj, stan; realizacja, data);
- ryzyko według ADR-033: szkic produktu jest odwracalny i ma pochodzenie
  „przebieg asystenta” (plan asystenta, A2); aktywacja, zmiana ceny i włączenie
  sklepu to publikacja z osobną zgodą; wydanie, zwrot pieniędzy i anulowanie
  zamówienia są nieodwracalne.

### 11. Izolacja, zadania i usuwanie

Każda tabela sklepu to `TenantScopedModel` z wymuszonym RLS, standardową
polityką i wyzwalaczem relacji między tenantami dla każdego klucza obcego
(wzór magazynu). Tokeny koszyka, zamówienia i pobrań szukamy dopiero w tenancie
wskazanym przez host — bez `PRE_TENANT_DB` i bez globalnej tabeli routingu.
Porzucone koszyki kasuje zadanie przechodzące firmy po kolei: lista z
`billing.api.billing_organization_ids()` (policzone drzwi przemiatań, ADR-041),
potem transakcja z `SET LOCAL` na firmę, jak `billing_tenant_scope` — zapytanie
przez tenanty pod RLS zwraca zero wierszy. Usunięcie tenanta kasuje tabele
sklepu, a historia cen zna furtkę `app.erasing_organization_id`. Anonimizacja
klienta czyści dane dostawy na jego realizacjach (ADR-073).

## Konsekwencje

- Nowy moduł to deskryptor, wpis `coverage` w `.agents/evals/routing.json` i
  skill z wierszem w `AGENTS.md`; profil `business` wymienia `shared.shop` z
  zależnościami. Odwracalne migracje `shop`, `billing` (wersje planów),
  `organizations` (audyt) i `media` kolejkujemy dla VPS (`memex ops add`).
- `consume` dostaje datę dokumentu z dnia firmy (`organization_today`) zamiast
  UTC (`modules/shared/inventory/services.py:1324`) — dla wszystkich wołających.
- Nieopłacone zamówienie przelewem trzyma towar do terminu wpłaty (ADR-073);
  przed botami chronią limity zapytań i ilości, a firma może je anulować.
- Poza zakresem: etykiety i integracje przewoźników, feedy Google Merchant i
  Ceneo (faza 14), Allegro i inne kanały (raczej platforma branżowa), wspólny
  koszyk produktów i rezerwacji poza oknem odbioru, częściowe wysyłki, kilka
  magazynów sklepu, cenniki B2B, faktury poza integracją (T15, faza 12).
- Otwarte: od ADR-073 sklep potrzebuje zamówienia zakładanego w transakcji
  innego modułu, pozycji ze źródłem, stałej modelu zamówienia i reakcji na
  zmianę stanu w tej samej transakcji (nie obserwatorów `on_commit`, którzy
  połykają błędy — ADR-052); od ADR-072 — definicji limitu zamówień na okno;
  w fazie 9 — widżetu mapy Paczkomatów, danych sprzedawcy i potwierdzenia, że
  limit liczy produkty. Pytania prawne (m.in. ADR-042 §7) — na listę prawną.

## Odrzucone

- **Drugi stan towaru w sklepie** albo klucz obcy do modeli magazynu — dwa
  źródła prawdy o stanie (T14, ADR-055 §11).
- **Cena w bloku, w migawce publikacji albo w pozycji magazynu** — stara cena
  po zmianie, cena w zasięgu automatyzacji treści, brak historii dla Omnibus i
  wspólna cena z wizytą (cenę netto pozycji panel daje wariantowi jako kopię).
- **Rezerwacja przy dodaniu do koszyka albo koszyk jako zamówienie `draft`** —
  porzucone koszyki i boty trzymałyby stan i numery zamówień.
- **Koszyk w przeglądarce** (`localStorage`, stan tylko w UI) — asystent go nie
  dosięgnie, a cenę i stan i tak sprawdza serwer.
- **Globalna tabela routingu tokenów sklepu** — sklep żyje na stronie firmy, a
  host już nazywa tenanta.
