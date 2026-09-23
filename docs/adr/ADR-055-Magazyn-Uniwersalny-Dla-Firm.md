# ADR-055: Magazyn uniwersalny dla firm (`shared.inventory` v2)

Status: zaakceptowana, 2026-09-23 (decyzje właściciela w planie memex
`magazyn-materia-o-w-od-pakietu-korektora-do-kare`). Zastępuje model magazynu
v1 z 21.09 (pakiet korektora HoofCare), zachowując jego zasady: stan to suma
ruchów, zapas należy do osoby, praca w terenie nie staje przez stan, średnia
ważona.

## Kontekst

Magazyn v1 powstał dla HoofCare: kategorie korektora (klocek, opatrunek, lek)
wpisane w rdzeń, jeden magazyn firmy i zapasy osób, ruchy bez dokumentów.
Właściciel chce z niego **uniwersalny, pełny system magazynowy dla firm**, z
którego korzystają inne moduły: rezerwacje (produkty przy wizycie), praca w
terenie HoofCare i przyszły sklep internetowy — bez przebudowy magazynu przy
każdym z nich. Moduł jest domyślnie włączony we wszystkich produktach.

## Decyzja

1. **Towar to pozycja katalogu (`InventoryItem`) = jeden SKU.** Nazwa, SKU, EAN,
   kategoria, jednostka, stan minimalny, średnia ważona cena zakupu, cena
   sprzedaży netto i stawka VAT (23, 8, 5, 0, zw). Warianty (rozmiar, kolor) to
   osobne pozycje; sklep zgrupuje je w swojej karcie. Tłumaczenia nazwy, opis i
   zdjęcia dojdą razem ze sklepem.
2. **Kategorie należą do firmy** (`InventoryCategory`), a ich zestaw startowy
   deklaruje produkt per typ organizacji: `organizationTypes[].inventory.categories`
   w profilu. Typ bez deklaracji dostaje zestaw rdzenia (Produkt, Materiał,
   Narzędzie, Inne). Firma dopisuje własne; startowych nie usuwa.
3. **Pozycje standardowe deklaruje produkt:**
   `organizationTypes[].inventory.defaultItems` (klucz, nazwa PL/EN, kategoria,
   jednostka). Powstają leniwie przy pierwszym dostępie firmy do magazynu, z
   `system_key`; można je edytować i ukryć, nie usunąć. Rdzeń nie nazywa
   żadnej branży (ADR-049) — HoofCare deklaruje Klocek, Opatrunek, Lek.
4. **Miejsca składowania** (`StockLocation`): magazyny firmy (kilka) i zapas
   osoby (jeden na człowieka). Magazyn główny i zapas osoby powstają leniwie.
5. **Dokumenty** (`StockDocument` z wierszami): PZ przyjęcie zewnętrzne, WZ
   wydanie zewnętrzne, RW rozchód wewnętrzny (zużycie), PW przychód wewnętrzny,
   MM przesunięcie między miejscami, INW inwentaryzacja. Numeracja
   `RODZAJ/RRRR/NNNN` osobno dla firmy, rodzaju i roku. Szkic można zmieniać;
   zatwierdzenie tworzy ruchy i zamraża dokument. Pomyłkę prostuje **korekta** —
   nowy dokument tego samego rodzaju, który cofa ruchy korygowanego. Wydruk PDF
   później (decyzja 23.09).
6. **Stan** (`InventoryBalance`) to suma ruchów per pozycja i miejsce, trzymana
   obok księgi; ma też `reserved`. Dostępne = stan − zarezerwowane.
7. **Rezerwacje stanu** (`StockReservation`) należą do źródła (moduł i jego
   identyfikator, np. wizyta): rezerwacja przy potwierdzeniu, zużycie przy
   zakończeniu, zwolnienie przy odwołaniu.
8. **Brak pokrycia:** zużycie w pracy (wizyty, teren) i dokumenty wewnętrzne
   ostrzegają, ale zapisują — ujemny stan jest do wyjaśnienia. Sprzedaż (WZ ze
   sklepu) jest blokowana, gdy towaru nie ma.
9. **Wycena:** średnia ważona krocząca liczona przy przyjęciu z ceną (PZ, PW);
   rozchód wyceniany średnią z chwili ruchu.
10. **Uprawnienia:** `inventory.read` (podgląd), `inventory.use` (zużycie z
    własnego zapasu, produkty przy wizycie), `inventory.manage` (dokumenty,
    ceny, katalog, inwentaryzacja).
11. **Operacje dla innych modułów** (`shared/inventory/api.py`): stan osoby,
    dostępność, rezerwacja, zwolnienie rezerwacji źródła, zużycie (dokument RW
    ze źródłem, idempotentny), cofnięcie zużycia źródła (korekta RW). Moduły nie
    importują modeli magazynu.
12. **Historia zmian:** zatwierdzenie i korekta dokumentu, zmiany katalogu,
    kategorii i dostawców mają własne akcje z „było → jest”.
13. **Dane v1** były testowe (HoofCare, 21.09) i zostają wyczyszczone migracją;
    schemat zmienia się odwracalnie.

## Uzupełnienie 2026-09-24: produkty przy wizycie (faza 6)

- Usługa rezerwacji niesie listę produktów (`Service.materials`: pozycja,
  ilość, rozliczenie „zużycie” albo „sprzedaż klientowi”). Wizyta dostaje jej
  kopię z nazwą i ceną sprzedaży z chwili zapisu (`Appointment.materials`);
  osoba z `inventory.use` może ją zmienić przy tworzeniu i do zakończenia.
- JSON zamiast kluczy obcych: magazyn nie jest zależnością rezerwacji, a produkt
  bez magazynu w profilu nie istnieje. Pozycje sprawdza `booking/materials.py`
  przez `inventory.api.describe_items`; w kopii z usługi pozycja ukryta po
  ustawieniu usługi jest pomijana, żeby nie blokować klientowi rezerwacji.
- Potwierdzenie (utworzenie) rezerwuje stan w magazynie głównym, zakończenie
  wystawia RW (zużycie) i WZ (sprzedaż) bez blokady brakiem towaru, odwołanie
  zwalnia rezerwację. Źródło dokumentów i rezerwacji: `booking.appointment`.
- Klient (strona publiczna, self-service) nie widzi produktów wizyty.
- Rdzeń dostał akcję „Zakończ wizytę” w kalendarzu panelu — wcześniej kończył
  wizyty tylko HoofCare.

## Konsekwencje

- Dziesięć tabel tenantowych z wymuszonym RLS (ADR-039): pozycja, kategoria,
  miejsce, dostawca, dokument, wiersz dokumentu, ruch, stan, rezerwacja i licznik
  numeracji. Jeden strażnik relacji sprawdza każdy klucz obcy do tabel magazynu.
- Profil produktu zyskuje opcjonalne pole `organizationTypes[].inventory`;
  profile bez niego nie zmieniają artefaktu ani hasha.
- Stare endpointy v1 (przyjęcie, wydanie, zwrot, korekta) działają dalej jako
  skróty tworzące zatwierdzone dokumenty PZ, MM oraz PW/RW (korekta stanu), dopóki panel nie
  przejdzie na dokumenty.
- Partie i terminy ważności, alerty stanu minimalnego, raporty, import CSV i PDF
  dokumentów to kolejne fazy planu.

## Odrzucone

- **Ruchy bez dokumentów** (v1): prościej, ale bez numeracji i zatwierdzania
  nie da się tego pokazać księgowej.
- **Kategorie jako stała lista w rdzeniu:** to słownik korektora w rdzeniu,
  sprzeczny z ADR-049.
- **Osobny magazyn na leki:** jedna torba korektora, dwa magazyny (decyzja
  21.09).
