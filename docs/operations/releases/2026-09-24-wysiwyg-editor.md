# Edytor tekstu WYSIWYG w Site Studio (etap 2b) — wydanie 2026-09-24

Zakres: etap 2b planu memex `saas-core-site-studio-rich-content-and-full-width`
(decyzja: [ADR-056](../../adr/ADR-056-Edytor-Tekstu-WYSIWYG-Na-Kontrakcie-Rich-Text.md),
opis: [site-rich-content.md](../../architecture/site-rich-content.md#edytor)).
Pola bogatej treści piszą się jak w edytorze tekstu (TipTap 3 na schemacie
równym kontraktowi `core.rich_text`), także na pełnym ekranie; zapisywany jest
nadal wyłącznie JSON węzłów. Panel ze składnią `**` usunięty. Wdrożono
**tylko** `saas.goldenstar.cloud`; HoofCare i MedPlano dostaną to przez
`core:update`.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `03103b9` | `03103b9` |

## Wdrożenie

Pięć wdrożeń tego samego dnia — cztery ostatnie to poprawki z odbioru na
żywo (niżej): `e0ddf45` (166 s), `75a574f` (143 s), `25cb72c` (112 s),
`716f47d` (107 s), `03103b9` (167 s). Za każdym razem: obrazy z `git archive`,
poprzednie jako `saas-core-{backend,frontend}:rollback-wysiwyg-editor…-20260924`,
kopia bazy, brak migracji, `check_database_role`, skaner `CLEAN`, obrazy
zgodne z buildem, `/healthz` 200. W trakcie `main` dostał magazyn i produkty
na wizycie innej sesji (`3dba8c1`, wdrożone przez nią przed tym wydaniem);
wdrażany commit jest zawsze przodkiem `main`.

## Odbiór

- [x] bramki na drzewie wdrożonym (`03103b9`): frontend **517/517**,
  renderer **182/182**, UI **61/61**, kontrakty **35/35**, lint, typecheck,
  prettier; wcześniej po scaleniu `main` także zgodność API i `ai:validate`;
  backend bez zmian w tym wydaniu;
- [x] konwersja: każda treść dostarczana z produktem (seedy 20 układów i
  wszystkie recepty stron, PL/EN, treść i ramka boczna) przechodzi przez
  edytor bez zmian, a schemat edytora ją przyjmuje (128 przypadków);
- [x] interakcje w Chromium na stronie-harnessie: pisanie, Ctrl+B, nowy
  śródtytuł z kotwicą, Tab i odmowa trzeciego poziomu, link spoza listy
  adresów odrzucony, cytat/uwaga/ilustracja z polami, Enter wychodzi z
  cytatu, F8, wklejka z Worda, pełny ekran w kroju strony, cofanie strony,
  kursor i pełny ekran zachowane po przemontowaniu w modalnym oknie; zero
  błędów JS;
- [x] na żywo, w prawdziwym panelu, na koncie syntetycznym: dopisanie
  tekstu, pogrubienie, śródtytuł H2 z kotwicą `nowy-rozdzial`, F8 zastępuje
  `[Uzupełnij: kwota]`, link `#kontakt` z okna, pisanie na pełnym ekranie,
  Ctrl+Z i Ctrl+Shift+Z po kolei, zapis (201) daje dokładnie oczekiwany JSON,
  publikacja; telefon 390 px bez poziomego przewijania; zero błędów JS;
- [x] strona publiczna przez Caddy z hostem witryny: 200, `<h2
  id="nowy-rozdzial">`, `<strong>odbioru.</strong>`, `<a href="#kontakt">`,
  lista, cytat, wypełnione miejsce, kotwica formularza;
- [x] konta, organizacje i obiekty testu usunięte (każda próba).

## Znalezione przy odbiorze na żywo i poprawione

- Sekcja z treścią i ramką boczną miała dwa przyciski „Pisz na pełnym
  ekranie” o tej samej nazwie — nazwa dostępna mówi teraz, które pole
  otwiera (`13fa3c7`); podpowiedź `#kotwica` nie łamie się w środku (tamże).
- **Utrata tekstu** na obciążonym hoście: zapis po pauzie mógł wpaść między
  render a efekt, a edytor ładował wtedy starszą wartość na świeżo wpisany
  tekst. Edytor porównuje teraz bieżącą wartość formularza (`25cb72c`).
- Cofanie przemontowuje pola sekcji: edytor tracił kursor (Ctrl+Z, potem
  Ctrl+Y nie działało) i zamykał pełny ekran — teraz przekazuje kursor i
  pełny ekran następnemu edytorowi tej ścieżki (`716f47d`), a po klatce, w
  której modalne okno edytora strony zabiera fokus, bierze go z powrotem
  (`03103b9`).
- Nie błąd edytora: szybki skrypt klawiszy na hoście z load ~20 wyprzedza
  asynchroniczne czytanie zaznaczenia przez ProseMirror (End, zaraz Enter —
  zaznaczenie jeszcze stare). Z ludzkim tempem (pauza 200 ms) wynik jest
  poprawny także przy 6× i 12× spowolnieniu CPU w Chromium.

## Uwagi

- Test e2e edytora w repozytorium jeszcze nie istnieje (jsdom nie pisze w
  `contentEditable`, e2e repo zakłada lokalny stos) — follow-up memex do
  30.09; do tego czasu interakcje pilnuje skrypt odbioru wydania.
- Błędy walidacji edytora to jeden komunikat pod polem (pierwszy błąd
  treści), bez wskazania, którego elementu dotyczą.
- Po Ctrl+B i Enter nowy akapit pisze się dalej pogrubieniem (jak w edytorach
  tekstu); w śródtytule znaczniki i tak znikają.

Dowody (prywatne): `.runtime/releases/20260924-wysiwyg-editor*/`.
