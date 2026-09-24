# Szablon strony panelu (ADR-057) — wydanie 2026-09-24

Zakres: faza 7 planu memex
`saas-core-panel-i-katalog-listy-wizytowka-historia-wyszukiwarka`. Decyzje
właściciela z 24.09: jedna szerokość wszystkich stron z opcją rozszerzenia,
podstrony w rozwijanym lewym menu, prawy panel na pomoc, kolumna akcji
(wybrane widoczne, reszta pod „…”), widok Lista w kalendarzu, gospodarstwa i
zwierzęta na nowej tabeli, uporządkowany pasek filtrów magazynu; od razu w
HoofCare i MedPlano.

| Aplikacja | Kod | Co wdrożone |
| --- | --- | --- |
| Saas-Core / vps-dev | `3f28b43` | sam frontend — rdzeń bez zmian backendu |
| HoofCare | `2108659` pełne (rdzeń `735a224`), potem `d64d651` frontend (rdzeń `3f28b43`) | backend, migracja `sites 0033` z rdzenia, frontend |
| MedPlano | `cf1ea6d` (rdzeń `3f28b43`) | backend, migracja `sites 0033` z rdzenia, frontend |

Aktualizacja rdzenia w produktach przyniosła też wcześniejsze zmiany innej
sesji, dotąd tylko na saas: edytor WYSIWYG (ADR-056) i formularz kontaktu v2
(migracja `sites 0033`).

## Co się zmieniło

- **Układ panelu:** jeden `<main>` na wszystkie strony, 80 rem; przełącznik w
  nagłówku (od 1536 px) rozciąga go na całą szerokość i zapamiętuje wybór w
  cookie. Jedno ładowanie przy przejściach (`panel/loading.tsx`).
- **`PanelPage`:** sekcja nad tytułem (na stronie zagnieżdżonej link w górę),
  tytuł, opis, akcje strony po prawej, komunikat po czynności, opcjonalny prawy
  panel pomocy. 25 stron rdzenia i 4 strony HoofCare na nim.
- **Menu:** podstrony rozwijają się pod pozycją (sekcja bieżąca otwarta). Magazyn
  ma cztery adresy (Stany, Katalog, Dokumenty, Ustawienia), Wiadomości dwa
  (Zapytania, Powiadomienia automatyczne), Strona internetowa dostała Search
  Console. Na telefonie te same strony są zakładkami nad treścią.
- **Listy:** pasek w jednym rzędzie (szukaj z ikoną, filtry z etykietą w
  linii), akcje strony w nagłówku, akcje wiersza: codzienne jako przyciski,
  reszta pod „…” (na telefonie wszystko pod „…”). Gospodarstwa, zwierzęta,
  zwierzęta gospodarstwa, raporty HoofCare i widok Lista w kalendarzu na
  `DataTable`; wiersz gospodarstwa prowadzi do karty, telefonu, zwierząt tego
  gospodarstwa i edycji; wiersz stanu magazynu — do przyjęcia, wydania i zwrotu
  z wybraną pozycją; dokumenty mają obok pomoc „rodzaje dokumentów”.

## Odbiór

- [x] frontend Saas-Core **526/526**, UI **64/64**, lint, typecheck, prettier,
  `ai:validate`;
- [x] HoofCare: frontend **620/621** w pełnym przebiegu — `page-editor`
  (znana niestabilność pod obciążeniem, load ~47) przeszedł osobno 36/36;
  zapytania ze strony na profilu `hoofcare` **56/56**; `core:check`,
  `deployment:check:all`, `makemigrations --check`;
- [x] MedPlano: frontend **528/529** — `site-inquiries` (limit czasu pod
  obciążeniem) przeszedł osobno 13/13; `core:check`, `deployment:check:all`,
  `makemigrations --check`;
- [x] na żywo `saas.goldenstar.cloud` (konto syntetyczne): Magazyn rozwinięty w
  menu, bieżąca podstrona oznaczona, pasek filtrów w jednym rzędzie, akcje w
  wierszu, pomoc obok dokumentów; kalendarz → Lista → szczegóły wizyty z
  wiersza; Ustawienia rozwinięte, Magazyn zwinięty; szerokość 1184 px na
  magazynie, kalendarzu i ustawieniach; na 2560 px 1280 → 2304 px i po
  przeładowaniu nadal 2304 px; telefon 390 px bez przewijania w bok; zero
  błędów strony;
- [x] na żywo `hoofcare.goldenstar.cloud`: gospodarstwa (otwórz, zadzwoń,
  edycja z „…”), „Zwierzęta tego gospodarstwa” → lista zwierząt z filtrem z
  adresu, karta zwierzęcia z wiersza, karta gospodarstwa z linkiem w górę;
  Raporty, Wizyty, Magazyn i Dziś w tej samej szerokości; telefon bez
  przewijania w bok; zero błędów strony;
- [x] na żywo `medplano.goldenstar.cloud`: ten sam przebieg co na saas
  (magazyn, kalendarz → Lista, ustawienia, 2560 px z przeładowaniem, telefon)
  — wszystkie warunki spełnione, zero błędów strony;
- [x] `/healthz` 200 i zero zaległych migracji w HoofCare i MedPlano; konta
  syntetyczne usunięte po odbiorze we wszystkich trzech.

Druga runda na HoofCare (`3f28b43`) poprawiła pole statusu zwierzęcia na
karcie gospodarstwa (strzałka odjeżdżała od pola) i dała liście zwierząt
nagłówek rejestru. Skrypt odbioru czeka na uruchomienie strony logowania — na
obciążonym hoście kliknięcie przed hydracją wysłało formularz jako GET.

Pierwsza runda na saas (`2c614a7`) wykazała, że wybór szerokości nie
przetrwał przeładowania: nazwa cookie pochodziła z modułu `"use client"`, więc
serwer dostawał referencję zamiast tekstu. Poprawka `735a224`.

Nie zrobione w tej fazie: filtry w adresie strony, tytuł karty przeglądarki per
strona, globalna wyszukiwarka z makiety HoofCare, zakładki edytora strony www
jako podstrony (to etapy pracy nad jedną witryną), listy SEO na `DataTable`.

Dowody (prywatne): `.runtime/releases/20260924-panel-page/`.
