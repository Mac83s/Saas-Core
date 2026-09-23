# Produkty z magazynu przy wizycie — wydanie 2026-09-24

Zakres: faza 6 planu memex `magazyn-materia-o-w-od-pakietu-korektora-do-kare`
(uzupełnienie ADR-055). Decyzje właściciela z 23.09: usługa rezerwacji może
mieć produkty z magazynu — każdy jako zużycie na koszt firmy albo sprzedaż
klientowi; stan rezerwuje się przy potwierdzeniu wizyty, schodzi przy jej
zakończeniu, wraca przy odwołaniu; ręcznie dowolna ilość, przez osobę z prawem
do magazynu; brak towaru ostrzega i zapisuje.

| Aplikacja | Kod (backend i frontend) |
| --- | --- |
| Saas-Core / vps-dev | `3dba8c1` |
| HoofCare | `5ad4879` (rdzeń `3dba8c1`) |
| MedPlano | `04e8f76` (rdzeń `3dba8c1`) |

## Co się zmieniło

- Ustawienia › Usługi: karta „Produkty w usługach” — produkty, ilości i
  rozliczenie (zużycie albo sprzedaż) dla każdej usługi.
- Nowa wizyta podpowiada produkty usługi; można je zmienić. Szczegóły wizyty
  pokazują produkty, sumę sprzedaży netto i pozwalają je zmienić do
  zakończenia. Ostrzeżenie, gdy wolnego stanu jest za mało.
- „Zakończ wizytę” w kalendarzu rdzenia (wcześniej kończył wizyty tylko
  HoofCare): zużycie schodzi dokumentem RW, sprzedaż dokumentem WZ, rezerwacja
  się zwalnia. Odwołanie zwalnia rezerwację.
- Klient na stronie publicznej i w self-service nie widzi produktów wizyty.
- Nagłówek panelu magazynu mówi już ogólnie („Towary i materiały”).

## Wdrożenie

- Trzy stacki po kolei: kopia bazy, migracje (`booking 0006`,
  `organizations 0048`), `check_database_role`, skaner `CLEAN`, zero
  zaległych migracji, `/healthz` 200. Abonamentów nie trzeba było przenosić.
- Obrazy do wycofania: `<projekt>-{backend,frontend}:rollback-visit-products-20260924`.

## Odbiór

- [x] backend rdzenia na profilu `vps-dev` **960 PASS, 29 SKIP** (w tym 5
  testów produktów przy wizycie: kopia z usługi z ceną, RW i WZ przy
  zakończeniu, zwolnienie przy odwołaniu, ręczna zmiana ponad stan, pozycja
  ukryta nie blokuje rezerwacji, klient nie widzi produktów); HoofCare
  **1026/1026**; MedPlano rezerwacje i magazyn 41/41;
- [x] frontend: rezerwacje, magazyn, i18n, organizacje, HoofCare —
  zielone (1 test zespołu niestabilny pod obciążeniem hosta przeszedł osobno);
  lint, typecheck, mypy, importy, zgodność API, prettier;
- [x] na żywo `saas.goldenstar.cloud` (konto testowe): produkt „Olejek” 2 szt.
  jako sprzedaż w usłudze z panelu; wizyta skopiowała go z ceną 25 zł;
  stan 10, wolne 8; w szczegółach wizyty produkty i „Sprzedaż razem: 50,00 zł
  netto”; „Zakończ wizytę” → WZ/2026/0001, stan 8, wolne 8; zero błędów strony;
  konto usunięte.

Uwagi: rezerwacja i zejście idą zawsze z magazynu głównego (zapas osoby albo
inny magazyn — gdy firma o to poprosi). Zakończonej wizyty nie da się cofnąć w
kalendarzu; pomyłkę prostuje korekta dokumentu w magazynie. Pierwsze dwa
podejścia odbioru przerwały się na skrypcie (niejednoznaczna etykieta) i na
limicie czasu strony pod obciążeniem hosta — nie na aplikacji.

Dowody (prywatne): `.runtime/releases/20260924-visit-products/`.
