# Przygotowanie do wizyty i mały stan w terenie — wydanie 2026-09-24

Zakres: faza 7 planu memex `magazyn-materia-o-w-od-pakietu-korektora-do-kare`
(HoofCare) i jej punkt rozszerzenia w rdzeniu (uzupełnienie ADR-055: rodzaje
wizyt z własnym materiałem). Decyzje właściciela z 24.09, odpowiedzi 1A 2A 3A
4A: potrzeba to norma firmy na krowę × krowy wizyty; mały stan w terenie
ostrzega (pasek + jednorazowy komunikat), nigdy nie blokuje; „Do zabrania” na
stronie Dziś i na ekranie wizyty; wizyty HoofCare nie biorą produktów przez
kalendarz.

| Aplikacja | Kod (backend i frontend) |
| --- | --- |
| Saas-Core / vps-dev | `5465c30` (zmiany rdzenia `ea9090b`, `cca6dce`) |
| HoofCare | `9d01963` (rdzeń `cca6dce`) |
| MedPlano | `bf2a5ef` (rdzeń `5465c30`) |

## Co się zmieniło

- Rdzeń: moduł może zadeklarować `backend.appointmentKindsWithOwnMaterials`.
  Takie wizyty nie biorą produktów z usługi kalendarza (ekran produktów ich nie
  pokazuje, API odmawia), a „Zakończ wizytę” zwalnia dawną rezerwację zamiast
  zdejmować stan. Profile bez takich rodzajów (vps-dev, MedPlano) działają jak
  dotąd.
- HoofCare, Ustawienia › Korekcja: „Normy materiału na krowę” — ustawia osoba
  prowadząca magazyn (`inventory.manage`), czytają ci, którzy widzą magazyn.
  Pole przyjmuje przecinek dziesiętny; zmiana trafia do historii zmian.
- HoofCare, Dziś: karta „Do zabrania” (dziś albo jutro) — moje wizyty, także
  rozpoczęte wcześniej i jeszcze otwarte, wobec mojego pakietu; pozycje na
  sztuki zaokrąglone w górę, braki na górze.
- HoofCare, ekran wizyty i przygotowania: lista na tę wizytę (tylko dla
  korektora i ekipy tej wizyty) i linia „Brakuje materiału” w sprawdzeniu.
- HoofCare, ekran korekcji: odznaka „Mało: …” na pasku i jednorazowy komunikat,
  gdy pakiet nie starczy na krowy pozostałe w kolejce (licząc zapisy ekipy) albo
  spadł do zera. Zapis nigdy nie jest blokowany.

## Wdrożenie

- saas: kopia bazy, bez migracji, `check_database_role`, skaner `CLEAN`, zero
  zaległych migracji, `/healthz` 200.
- HoofCare: migracja `hoofcare 0017_material_norms` (tabela
  `hoofcare_materialnorm`, RLS włączone i wymuszone, polityka
  `hoofcare_materialnorm_tenant_isolation` — sprawdzone w `pg_class` i
  `pg_policy` żywej bazy); reszta jak wyżej.
- MedPlano: bez migracji; reszta jak wyżej.
- Skaner plików: ClamAV HoofCare i MedPlano stał od ~14:00 (pamięć hosta), a
  worker produktu nie startuje bez skanera. Decyzja właściciela 24.09: jeden
  skaner — `saas-core-clamav-1` podpięty do `hoofcare_scanner` i
  `medplano_scanner` z aliasem `clamav`, własne kopie za profilem
  `own-scanner` w overlayach produktów (HoofCare `5d2621b`, MedPlano
  `02ead50`). `check_malware_scanner` CLEAN we wszystkich trzech workerach.
- Obrazy do wycofania:
  `<projekt>-{backend,frontend}:rollback-inventory-phase7-20260924`.

## Odbiór

- [x] przegląd adwersaryjny zmian (28 agentów): 17 potwierdzonych usterek, 7
  odrzuconych; wszystkie potwierdzone poprawione w HoofCare `9d01963` z testami;
- [x] backend HoofCare **1064/1064** (przed poprawkami z przeglądu) oraz 62
  testy HoofCare i kontraktów po nich; rdzeń: testy materiałów rezerwacji i
  kompozycji, także na profilu medplano 32/32; `deployment-check` 15/15;
- [x] frontend HoofCare 110/110; typecheck, lint, prettier, `core:check`,
  `deployment:check:all`;
- [x] na żywo `hoofcare.goldenstar.cloud` (konto testowe): norma „0,5” dla
  „Klocek QA” zapisana; wizyta bez rezerwacji na 3 krowy — Dziś: „1 wizyta ·
  ok. 3 krowy · Klocek QA weź 2 szt. · masz 1 szt. · brakuje 1 szt.”; ekran
  wizyty „na 3 krowy … brakuje 1 szt.”; po starcie pasek korekcji „Mało:
  Klocek QA” w jednym wierszu; historia: „Zmieniono normy materiału na krowę”;
  „Edytuj” w wierszu gospodarstwa i przełącznik szerokości przy przycisku menu
  (od 1536 px); telefon bez przewijania w bok; zero błędów strony; konto
  usunięte;
- [x] na żywo `saas` i `medplano`: przegląd panelu (szerokości, przełącznik,
  magazyn, kalendarz, telefon), zero błędów strony; konta usunięte.

Uwagi: wizyty bez rezerwacji nie da się otworzyć w gospodarstwie bez telefonu i
e-maila hodowcy (rezerwacja rdzenia wymaga kontaktu klienta) — zapisane w
otwartych HoofCare. Podpięcie skanera przetrwa restart, nie odtworzenie
kontenera `saas-core-clamav-1`; polecenie jest w komentarzu overlayu produktu.
Kilka podejść odbioru przerwało się na `ERR_NETWORK_CHANGED` (inne stacki
zmieniały sieci dockera na hoście) — skrypt ponawia teraz nawigację.

Dowody (prywatne): `.runtime/releases/20260924-inventory-phase7/`.
