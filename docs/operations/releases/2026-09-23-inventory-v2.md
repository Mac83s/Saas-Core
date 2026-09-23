# Magazyn uniwersalny v2 (ADR-055) — wydanie 2026-09-23

Zakres: fazy 4–5 planu memex `magazyn-materia-o-w-od-pakietu-korektora-do-kare`.
Decyzje właściciela z 23.09: magazyn w rdzeniu ma być pełnym systemem
magazynowym dla firm, z którego korzystają rezerwacje, praca w terenie HoofCare
i przyszły sklep; dane testowe v1 czyścimy; dokumenty na start tylko w panelu.

| Aplikacja | Kod (backend i frontend) |
| --- | --- |
| Saas-Core / vps-dev | `2a57749` |
| HoofCare | `197f1fe` (rdzeń `2a57749`) |
| MedPlano | `ddbc04d` (rdzeń `2a57749`) |

## Co się zmieniło

- **Rdzeń (`shared.inventory` v2):** pozycja = SKU (SKU, EAN, cena sprzedaży
  netto, VAT); kategorie należą do firmy, zestaw startowy i pozycje standardowe
  deklaruje produkt per typ organizacji (`organizationTypes[].inventory`), bez
  deklaracji — zestaw rdzenia (Produkt, Materiał, Narzędzie, Inne); magazyny
  firmy i zapasy osób; dokumenty PZ, WZ, RW, PW, MM, INW z numeracją
  `RODZAJ/RRRR/NNNN`, szkicem, zatwierdzeniem i korektą; stan z rezerwacjami
  (dostępne = stan − zarezerwowane); dostawcy; `inventory.use` dla staff i
  wyżej; historia zmian dla kategorii, magazynów, dostawców i dokumentów.
- **Operacje dla modułów:** zużycie (jeden RW na źródło, idempotentne),
  cofnięcie źródła (korekta), rezerwacja i jej zwolnienie, dostępność, zapas
  osoby. Brak towaru nie zatrzymuje pracy; sprzedaż (WZ) jest blokowana.
- **Panel magazynu** na wspólnym DataTable: Stany (dowolne miejsce), Katalog,
  Dokumenty, Ustawienia (magazyny, dostawcy, kategorie); pracownik bez
  `inventory.manage` widzi swój zapas i katalog.
- **HoofCare:** firma korekcji deklaruje kategorie Klocek, Opatrunek, Lek,
  Narzędzie, Inne i trzy pozycje standardowe (Klocek, Opatrunek, Lek —
  edytowalne i ukrywalne, nieusuwalne); zużycie z wpisu to RW z zapasu
  korektora; cofnięty wpis oddaje materiał korektą RW (zamyka follow-up
  goldentrdcom-20260921-1); `inventory.use` dla właściciela, administratora,
  biura i korektora.
- **Dane v1** (testowe z 21.09) wyczyszczone migracją `inventory 0005`.
- **Powtórka bezpieczna:** klient nadaje id dokumentowi (także przy szybkim
  przyjęciu, wydaniu, zwrocie i korekcie stanu); znane id zwraca istniejący
  dokument, a zatwierdzenie zatwierdzonego nic nie zmienia.

## Wdrożenie

- Trzy stacki po kolei: kopia bazy, migracje (`inventory 0005–0008`,
  `organizations 0047`), `check_database_role`, skaner `CLEAN`, zero zaległych
  migracji, `/healthz` 200.
- Dwie rundy: pierwsza (`299ce6f` / `ab8ebc3`) na Saas-Core i HoofCare; odbiór
  wykazał zgubioną odpowiedź na POST dokumentu (backend 201, proxy status 0 —
  szkic powstał, panel pokazał błąd). Poprawka „powtórka bezpieczna” weszła w
  drugiej rundzie na wszystkie trzy stacki; MedPlano wdrożony raz, od razu z nią.
- HoofCare na żywo: dane v1 usunięte (1 pozycja, 2 stany, 6 ruchów); role
  `trimming_company` owner, admin, office, trimmer mają `inventory.use`.
- Obrazy do wycofania: sprzed wydania
  `<projekt>-{backend,frontend}:rollback-inventory-v2-20260923` (Saas-Core,
  HoofCare) i `…:rollback-inventory-v2b-20260923` (MedPlano); po pierwszej
  rundzie `…:rollback-inventory-v2b-20260923` (Saas-Core, HoofCare).

## Odbiór

- [x] backend HoofCare **1021/1021** (cały zestaw, w tym testy magazynu
  rdzenia i pola korekcji z cofnięciem wpisu); magazyn rdzenia na profilu
  `agro` **14/14**; izolacja tenantów, historia, usuwanie organizacji, gospodarstwa
  55/55; migracje magazynu w przód, w tył i znów w przód;
- [x] frontend HoofCare **510/513** w pełnym przebiegu — 3 niestabilne testy Site
  Studio pod obciążeniem hosta przeszły osobno 39/39; lint, typecheck, mypy,
  ruff, prettier, `deployment:check:all`, `core:check`, zgodność API;
- [x] na żywo `hoofcare.goldenstar.cloud` (konto testowe z włączonym
  magazynem): kategorie block, dressing, medicine, other, tool; pozycje
  standardowe Klocek, Opatrunek, Lek w katalogu; przyjęcie 20 szt. → PZ/2026/0001
  i stan 20; RW 3 szt. zatwierdzone od razu → RW/2026/0001 i stan 17; korekta →
  RW/2026/0002 i stan 20; telefon 390 px bez poziomego przewijania, wiersze jako
  karty; zero błędów strony; konto usunięte;
- [x] `/healthz` 200 na trzech stackach, zero zaległych migracji.

Nie sprawdzone na żywo: zużycie i zwrot materiału z ekranu korekcji w oborze
(pokryte testem pola HoofCare), bo wymaga wizyty w gospodarstwie z kontem
korektora. Nagłówek panelu powtarza „Magazyn” dwa razy (etykieta i tytuł) —
do poprawy przy następnej zmianie panelu.

Dowody (prywatne): `.runtime/releases/20260923-inventory-v2/`.
