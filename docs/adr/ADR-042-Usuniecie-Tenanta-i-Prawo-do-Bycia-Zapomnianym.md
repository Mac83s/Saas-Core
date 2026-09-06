# ADR-042 — usunięcie tenanta i prawo do bycia zapomnianym

- Status: Accepted
- Data: 2026-09-06
- Rozstrzygnięcie właściciela: 2026-09-06 — usuwamy dane, nie anonimizujemy
- Kontekst decyzji: plan 13 pozycja P3, ADR-036 §8, ADR-030 (anonimizacja
  `Customer`), ADR-039 i ADR-041 (izolacja tenantów)

## Kontekst

Dziś **nie da się usunąć organizacji**. Dziesięć wyzwalaczy odmawia `DELETE`
bezwarunkowo, a osiem z nich stoi na tabelach tenantowych: wpisy audytowe
organizacji, księga kredytów, referencje mediów oraz pięć tabel Sites (bloki,
wersje strony, publikacje, mutacje tłumaczeń i onboardingu). Sprawdzone
2026-09-03 przy sprzątaniu tenantów testowych: organizacja, która kiedykolwiek
załączyła plik albo zapisała wpis audytowy — czyli każda prawdziwa — jest
nieusuwalna.

Append-only powstało z dobrego powodu: log, który aplikacja może przepisać, nie
jest logiem. Ale w tej samej bazie leżą dane osobowe **klientów naszych
klientów**: kontakt i wizyty w Booking, adresaci powiadomień, autorzy treści,
zrzuty publikacji, metadane audytu. Prawo do usunięcia (RODO art. 17) dotyczy
ich tak samo jak nas, a wykonawcą jest platforma, nie tenant.

Inwentaryzacja na działającej bazie: **77 tabel z `organization_id`**, dane
osobowe w co najmniej 20 z nich, w tym w kolumnach swobodnych i w JSON-ie
(`snapshot`, `payload`, `metadata`).

## Decyzja

### 1. Usunięcie znaczy usunięcie

Wykonujemy fizyczny `DELETE` wierszy i kasujemy obiekty ze storage. **Nie
anonimizujemy.**

Anonimizacja została odrzucona nie dlatego, że jest trudna, tylko dlatego, że
jest **niesprawdzalna** tam, gdzie dane osobowe leżą w tekście swobodnym i w
JSON-ie. Zrzut publikacji zawiera treść strony razem z nazwiskami; payload
powiadomienia zawiera adres i bezpieczny link; metadane audytu zawierają to, co
zapisała komenda. O każdym takim polu trzeba by udowodnić, że po wyczyszczeniu
**nie identyfikuje już nikogo** — a tego nie da się udowodnić regułą, tylko
przejrzeniem każdego wiersza. Usunięcie wiersza jest sprawdzalne policzeniem
wierszy.

To zmienia ADR-030 tylko w zakresie usuwania tenanta: anonimizacja `Customer`
zostaje jako operacja **wewnątrz działającej organizacji** (klient prosi o
usunięcie swoich danych, firma dalej działa). Usunięcie całego tenanta jest
czym innym i idzie tą ścieżką.

### 2. Jedna nazwana furtka, zawężona do jednej organizacji

Wyzwalacze append-only dostają jeden wyjątek: przepuszczają `DELETE`, gdy
zmienna sesyjna `app.erasing_organization_id` równa się `organization_id`
kasowanego wiersza. Nie flaga logiczna — **identyfikator**. Różnica jest
istotna: flaga włączona przez pomyłkę otwiera całą historię wszystkich
tenantów, a identyfikator otwiera dokładnie tę organizację, którą ktoś nazwał.

Wiersze bez `organization_id` furtki nie mają. To dane platformy (wersje planów,
role systemowe) i nie znikają razem z klientem.

Zmienną ustawia **dokładnie jedno miejsce** w kodzie, a pilnuje tego test
liczący użycia — ten sam mechanizm, którym ADR-041 pilnuje drzwi pre-tenant.

Piszemy wprost, czego ta konstrukcja **nie** daje: nie broni przed kimś, kto ma
już poświadczenia bazy aplikacyjnej — taka osoba ustawi zmienną sama. Żadna
warstwa w bazie tego nie zrobi. Broni przed **błędem w kodzie** i sprawia, że
zamiar jest widoczny w przeglądzie i w audycie.

### 3. Kolejność: wiersze, potem obiekty

PostgreSQL nie umie wycofać usunięcia z object storage, więc kolejność jest
rozstrzygnięciem, nie szczegółem:

1. w jednej transakcji: zebrać klucze obiektów, usunąć wiersze przejściami po
   modelach (jak w `purge_test_tenants`), usunąć organizację;
2. commit;
3. dopiero teraz kasować obiekty ze storage, zapisując te, których nie udało się
   skasować;
4. przemiatanie ponawia niedokończone, aż zostanie zero.

Odwrotna kolejność — obiekty przed commitem — kasowałaby pliki także wtedy, gdy
transakcja padnie. Ta kolejność zostawia krótkie okno, w którym plik żyje dłużej
niż jego wiersz; okno jest jawne, zapisane w pokwitowaniu i zamykane przez
przemiatanie.

### 4. Pokwitowanie: co zostaje po usunięciu

Zostaje **pokwitowanie**, poza usuniętym tenantem, w tabeli platformowej:
identyfikator organizacji, kto zlecił, powód, znaczniki czasu, liczba wierszy
per tabela, liczba skasowanych obiektów i lista jeszcze nieskasowanych.

Nie zostaje **nic z usuniętych danych**: ani nazwa, ani adres, ani żaden e-mail.
Identyfikator organizacji to UUID, który sam z siebie nikogo nie identyfikuje, a
jest potrzebny, żeby dało się wykazać, że usunięcie się odbyło (RODO art. 5 ust.
2). Pokwitowanie bez danych jest dowodem; pokwitowanie z danymi byłoby kopią.

### 5. Kto może to uruchomić

Operator: `User.is_staff` z potwierdzonym MFA, przez komendę z jawną nazwą
organizacji, obowiązkowym powodem i wpisanym potwierdzeniem. Domyślnie **suchy
przebieg** — komenda wypisuje, co zniknie, i nie robi nic, dopóki nie dostanie
`--apply`.

Panel nie dostaje tego endpointu w tym kroku. Samodzielne usunięcie firmy przez
właściciela jest osobną decyzją produktową (P3) i pójdzie przez ten sam serwis,
nie przez drugą implementację.

### 6. Konta ludzi zostają ich

Usunięcie tenanta kasuje członkostwa, nie konta. Konto jest własnością osoby i
znika własną ścieżką (ADR-036 §8: unieważnienie sesji, tombstone `User`).
Osoba, której jedyne członkostwo zniknęło, zostaje z kontem bez organizacji —
to jest poprawny stan, nie sierota do posprzątania.

### 7. Nic nie zostaje po naszej stronie z dokumentów sprzedaży

Sprawdzone: nie przechowujemy dokumentów księgowych. `BillingInvoiceDocument`
jest rekordem **zadania** przekazującego fakturę do zewnętrznego wystawcy —
niesie identyfikator faktury u dostawcy i wynik, nie sam dokument. Faktury żyją
w Stripe i u wystawcy, którzy mają własne obowiązki retencyjne jako odrębni
administratorzy.

Dlatego nasze usunięcie może być kompletne. **Gdybyśmy kiedykolwiek zaczęli
przechowywać dokument księgowy u siebie, ten ADR wymaga rewizji** — zniszczenie
dokumentacji księgowej jest osobnym naruszeniem i nie wolno go zrobić przy
okazji wykonywania art. 17.

### 8. Dowód

Usunięcie jest skończone, gdy:

- dla każdej tabeli z `organization_id` liczba wierszy tej organizacji wynosi 0;
- przeszukanie kolumn JSON (`snapshot`, `payload`, `metadata`) po identyfikatorze
  organizacji nie zwraca nic;
- storage nie ma obiektów pod prefiksem tenanta;
- pokwitowanie istnieje i nie ma nieskasowanych obiektów.

Cztery warunki, każdy sprawdzalny zapytaniem. Bramka P3 („przetestowana polityka
usunięcia") znaczy dokładnie ten zestaw, wykonany na uruchomionym stacku — baza
testowa łączy się właścicielem i o wyzwalaczach powie prawdę, ale o RLS nie.

## Konsekwencje

- append-only przestaje być bezwarunkowe. Jest teraz warunkowe wobec **jednej
  nazwanej operacji**, a nie wobec uznania aplikacji — i to jest cena, którą
  płacimy świadomie za możliwość wykonania prawa, którego nie da się obejść;
- pojawia się operacja nieodwracalna z prawdziwego zdarzenia. Dlatego suchy
  przebieg jest domyślny, powód obowiązkowy, a wykonanie wymaga MFA;
- rośnie koszt każdej nowej tabeli tenantowej: musi dać się usunąć, a jeśli jest
  append-only — musi znać furtkę. Test przejścia usunięcia to wychwyci;
- `purge_test_tenants` przestaje być osobną ścieżką i staje się cienką nakładką
  na ten sam serwis, zawężoną do zastrzeżonych domen testowych.

## Alternatywy odrzucone

- **anonimizacja zamiast usunięcia** — tańsza i nie rusza append-only, ale
  niesprawdzalna w tekście swobodnym i w JSON-ie, a przy danych klientów naszych
  klientów to właśnie sprawdzalność jest produktem. Decyzja właściciela z
  2026-09-06;
- **zdjęcie wyzwalaczy append-only** — rozwiązuje usunięcie i psuje wszystko
  inne: log, który aplikacja może przepisać, przestaje być dowodem czegokolwiek;
- **flaga logiczna zamiast identyfikatora** — o jedną pomyłkę od otwarcia
  historii wszystkich tenantów naraz;
- **osobna rola bazodanowa dla usuwania** (jak drzwi z ADR-041) — mocniejsza w
  teorii, w praktyce jej hasło leży w tym samym katalogu sekretów co aplikacyjne,
  więc kupuje mało za trzeci sekret w każdym środowisku;
- **baza per tenant, żeby usunięcie było `DROP DATABASE`** — rozwiązuje ten
  problem i tworzy kilkanaście innych; odrzucone w ADR-022 i nadal odrzucone;
- **odroczenie decyzji do pierwszego prawdziwego klienta** — moment, w którym
  jest najdroższa i najbardziej pilna naraz.

## Relacje

- realizuje pozycję P3 planu 13 i jej bramkę „usunięcie lub anonimizacja ma
  przetestowaną politykę retencji";
- zmienia ADR-030 w zakresie usuwania tenanta; anonimizacja `Customer` wewnątrz
  działającej organizacji zostaje bez zmian;
- korzysta z mechanizmu liczonych miejsc użycia z ADR-041;
- ADR-036 §8 (usunięcie konta) pozostaje osobną ścieżką i osobnym zakresem.
