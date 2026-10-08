# Kategorie i tagi na stronach firm

Reguły, których pilnuje kod `shared/sites` od fazy CT2 (ADR-079 pkt 2–14 i
„Uzupełnienie CT2”). Dokument mówi, **gdzie co wolno czytać i pisać**; powody są
w ADR.

## Model w trzech zdaniach

Pozycja (kategoria albo tag) to wiersz `ContentTag`. Tag strony nie ma
taksonomii (`taxonomy` puste) i jest wspólny dla wszystkich typów treści;
kategoria należy do taksonomii jednego typu (`ContentTaxonomy`, powstaje z
pierwszą kategorią typu), ma rodzica i kolejność. `ContentTag.slug` jest
**kluczem**: nie zmienia się i jest unikalny w stronie — migawki wskazują nim tag.

## Adres archiwum

Składa go wyłącznie `term_addresses.term_archive_path`:
`/<typ>/<segment>/<adres pozycji>/`, z prefiksem języka jak każdy adres typu.

| Część | Skąd |
| --- | --- |
| segment | tagi: `tag` w każdym języku; kategorie: `ContentTaxonomy.segment` / `locale_segments` (ze słownika `CATEGORY_SEGMENTS` przy utworzeniu) |
| adres pozycji w języku L | `locale_slugs[L]`, inaczej adres w języku strony, inaczej klucz (`term_slug`) |

Klucz, adresy we wszystkich językach i dawne adresy pozycji to **jedna
przestrzeń nazw taksonomii** (tagi strony są jedną taksonomią). Sprawdza ją
serwis pod blokadą wiersza strony; kod bierze pierwszy wolny adres
(`-2`, `-3`), nigdy cudzy dawny.

## Kiedy adres się zamyka i kiedy zmienia

| Zdarzenie | Skutek |
| --- | --- |
| tag sprzed migracji 0054 (albo zapisany starym kodem) | zamknięty na kluczu we wszystkich językach (`LEGACY_TERM_LOCK`, wartość domyślna kolumny) |
| zmiana nazwy przed zamknięciem | adres idzie za nazwą, bez śladu |
| publikacja wpisu z pozycją, w dowolnym języku | zamyka adres w języku strony — pozycji i kategorii nad nią; w języku wpisu, jeśli ma tam własny adres (`close_term_addresses`) |
| przyjęcie nazwy w języku L (osoba, zlecenie, akceptacja) | adres w L z nazwy; jeśli archiwum w L już kiedyś odpowiadało — zamknięty od razu, stary adres odpowiada jednym 308 (`settle_term_addresses`) |
| przeniesienie kategorii z opublikowanymi wpisami | zamyka adresy nowych kategorii nadrzędnych; żaden adres się nie zmienia |
| zmiana zamkniętego adresu | tylko osoba, z podglądem i — gdy archiwum odpowiadało — z powodem; stary adres do `former_slugs` |

Hak publikacji i hak przyjęcia nazwy **nigdy nie odmawiają**: działają w
transakcji, w której zlecenie tłumaczenia rozlicza kredyty.

## Co widzi gość

- Które wpisy są w archiwum, ile ich jest i czy pozycja w ogóle istnieje —
  wyłącznie z bieżących publikacji wpisów (`published_entries`, `carried_terms`).
  Migawka niesie `tags` (tagi, dzisiejszy kształt) i `terms` (wszystkie pozycje, po
  identyfikatorze). Przypisań szkicu (`ContentEntryTag`) publiczna ścieżka nie czyta.
- Drzewo i nazwy pozycji, które publikacja niesie, są czytane z wierszy: zmiana
  nazwy i przeniesienie działają od zapisu.
- Archiwum poniżej `TAG_INDEX_THRESHOLD` wpisów odpowiada z `noindex` i nie ma go
  w sitemapie.
- `article.categories` jest w odpowiedzi tylko wtedy, gdy wpis ma kategorię.

## Jedno 308

`public_archives.moved_address` (wołany jako `moved_section`) rozkłada adres na
język, nazwę typu, slug wpisu albo segment i adres pozycji, numer strony; każdą
część zamienia na dzisiejszą i daje 308, gdy wynik różni się od żądania i coś
pod nim odpowiada. Dawne są: `former_paths` typu, `former_segments` taksonomii,
`former_slugs` wpisu, klucz pozycji, jej adres w innym języku i `former_slugs`.
Nie są: segment ani nazwa typu z innego języka.

Dawnej nazwy typu ani dawnego adresu pozycji kod nie przejmuje; osoba — po
podglądzie (`takes_over`) i z `take_over_former`.

## RLS i blokady

- `sites_contenttag`, `sites_contententrytag` i `sites_contenttaxonomy` mają
  wymuszone RLS. Publiczny odczyt pozycji i taksonomii idzie **tylko** przez
  `term_addresses.site_vocabulary`, które ustawia tenanta z hosta w tej samej
  transakcji. Baza testowa RLS omija — pilnuje tego test kolejności zapytań.
- Kolejność blokad: wiersz strony, potem wpis; pozycje zawsze w kolejności
  identyfikatorów.

## Usunięty wpis

Stan `removed`. `ContentEntry.all_objects` pomija usunięte i jest jedynym
menedżerem dla odczytów; `with_removed` wolno użyć w `entry_removal`, przy
usuwaniu typu i w źródle tłumaczeń `sites.entry` (zlecenie w toku musi dostać
odpowiedź, nie wyjątek). Złączenia przez relację (`entry__…`) wykluczają stan
`removed` jawnie. Kasowanie wierszy następuje wyłącznie z usunięciem typu,
którego wszystkie wpisy są usunięte, po wpisaniu jego nazwy.
