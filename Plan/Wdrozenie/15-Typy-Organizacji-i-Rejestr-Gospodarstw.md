# 15 — Typy organizacji i rejestr gospodarstw

Decyzje: ADR-050 (typy organizacji), ADR-051 (rejestr gospodarstw), w HoofCare
HC-ADR-001. Każdy etap kończy się czymś do przeklikania na dev VPS i testem,
który dowodzi zakresu. Izolację między organizacjami dowodzimy na działającym
stacku.

## Etap 1A — typy organizacji (Saas-Core) — ZROBIONE 2026-09-19

Stan: Saas-Core `a0a6078`, `0c1f504`; HoofCare `25e7ac4` (typy firma korekcyjna
i gospodarstwo). Dowód na stosie hoofcare.goldenstar.cloud: konto bez
organizacji trafia na ekran „kim jesteś” (dwa typy do wyboru); organizacja typu
gospodarstwo dostaje 404 `module_not_available` z API stada, stron i SEO, a z
rezerwacji 403 (plan); firma korekcyjna przechodzi bramkę modułów (403 za
brak planu); przegląd abonamentu pokazuje gospodarstwu 1 plan, firmie 3; menu
gospodarstwa bez „Stado” i „Witryna”. Deklaracja typów leży w sekcji
`organizationTypes` profilu (nie w osobnym pliku), a organizację zakłada ekran
pierwszego uruchomienia (formularz rejestracji zostaje bez zmian).

Zakres:
1. Kontrakt `packages/contracts/organization-types.schema.json`. Opcjonalny
   plik profilu `deployments/<p>/organization-types.json`. Bez pliku: jeden typ
   `business`. Walidacja w `deployment-check`: moduły typu ⊆ moduły profilu,
   plany typu (1–3) istnieją, uprawnienia ról należą do modułów typu.
2. `Organization.organization_type`. Migracja nadaje istniejącym typ domyślny.
   API tworzenia organizacji wymaga typu z katalogu.
3. Bramka modułów per typ: moduł spoza typu organizacji odpowiada 404. Jedno
   miejsce w rdzeniu (middleware po tenancie), nie w każdym widoku.
4. Plany per typ: katalog publiczny i checkout filtrowane typem. Cennik na
   stronie marketingowej pokazuje plany typu wybranego na stronie.
5. Rejestracja z pytaniem „kim jesteś” (typy z `selfSignup`) i założeniem
   organizacji w tym samym przepływie. Koniec stanu „użytkownik bez firmy”.
6. Sesja i `organizations/current` zwracają typ i jego publiczną część. Menu
   panelu filtruje pozycje rdzenia i produktu typem.

Dowód: testy kompozycji i walidatora. Na stacku: organizacja typu A nie dostaje
API modułu spoza typu, rejestracja zakłada organizację wybranego typu, a
checkout odrzuca plan innego typu.

## Etap 1B — role i usługi per typ (Saas-Core) — ZROBIONE 2026-09-19

Stan: Saas-Core `e3ce6fc` (+ poprawki testów `4e36962`, `ed9be79`, logu
`637a005`); HoofCare `8082c3e` (role i szablony obu typów). Role typu zapisuje
`post_migrate` po każdym `migrate` (nie osobna komenda). Dowód na stosie
hoofcare: migrate zsynchronizował role (w bazie 9 ról typów obok 6
globalnych), właściciele obu organizacji testowych przepięci na role swoich
typów, firma widzi 5 ról typu i 23 nadawalne uprawnienia (w tym stada),
gospodarstwo 4 role i 14 uprawnień (bez stada); rola własna 201, rola z
przekazaniem własności 400, zaproszenie „korektor” 201, globalny „manager”
403.

1. Role systemowe per typ z katalogu. Komenda `apply_organization_types` po
   `migrate`: idempotentna, z audytem i system checkiem zgodności. Migracja
   przepina członkostwa na role typu domyślnego bez zmiany uprawnień.
2. Role własne organizacji: tworzenie z uprawnień modułów typu, przypisanie
   członkom, UI w „Zespół”.
3. Szablony usług rezerwacji per typ: szybkie zakładanie usług z szablonu w
   „Usługi i grafik”.

Dowód: rola własna ogranicza API na stacku; zmiana katalogu po redeployu
aktualizuje role bez migracji.

## Etap 2 — `shared.farms`: karty firm (Saas-Core + HoofCare) — ZROBIONE 2026-09-19

Stan: Saas-Core `56696c4` (moduł, profil `agro`) + `95acd54` (poprawki po
przeglądzie: kontrola statyczna całego katalogu, `billing.feature_migrations`,
jedna postać numeru siedziby stada, wyścigi → 400, licznik zwierząt w bazie);
HoofCare `bff4d49` (migracja 0007, planowanie wizyty, panel „Wizyty w
gospodarstwach”); MedPlano bierze rdzeń bez składania rejestru. Punkt 3 bez
rozszerzenia formularza rezerwacji rdzenia: wizytę planuje ekran wertykału
przez `booking.api.create_appointment` i wolne terminy z `/booking/slots/`.
Dowody w HANDOFF.

1. Moduł `shared.farms`: gospodarstwo (numer siedziby stada, NIP opcjonalny,
   adres, hodowca, kontakt), zwierzę (gatunek, numer identyfikacyjny, numer
   roboczy, imię, płeć, data urodzenia, status), katalog gatunków (bydło
   aktywne).
2. HoofCare: przeniesienie `Farm`/`Animal` do `shared.farms` (migracja danych
   deweloperskich) i typy `trimming_company` i `farm` w katalogu.
3. Wizyta korekcyjna z wyborem karty gospodarstwa w kalendarzu. Rdzeń potrzebuje
   punktu rozszerzenia „szczegóły wizyty modułu” w formularzu rezerwacji.

## Etap 3 — konto rolnika, połączenie i synchronizacja — ZROBIONE 2026-09-20

Zrobione (kod aktywacji i udział): firma generuje jednorazowy kod do swojej
karty (ważny 30 dni, w bazie tylko digest), rolnik przejmuje nim stado do
własnego rejestru (karta bez prywatnej notatki firmy, zwierzęta dopisane),
powstaje `FarmShare` z zakresem (`can_write_herd`, `can_publish_health`), który
rolnik cofa jednym kliknięciem. Zakładka „Dostęp” w karcie gospodarstwa i
przejmowanie kodem na liście gospodarstw. Cross-tenant bez RLS: kody i udziały
nie mają klucza do `Organization`, więc każdy odczyt idzie przez `sharing.py`,
które filtruje po organizacji wywołującego (test
`test_a_share_belongs_to_the_two_it_names`). Samo przekazanie jedzie w kodzie
(`FarmActivationCode.handover`), bo rolnik realizuje kod we własnym tenantcie,
gdzie RLS zasłania wiersze firmy — wyszło dopiero na żywym stacku.

Zrobione (synchronizacja i historia): firma z aktywnym udziałem zapisuje stado
do rejestru rolnika (`can_write_herd`) i publikuje tam historię zwierzęcia
(`can_publish_health`). Oba zapisy idą przez drzwi `registry_door` w
`herd_sync.py`: kontekst rejestru aktywny dokładnie na czas tych instrukcji,
jedno uprawnienie, aktor z firmy i przywrócenie organizacji wywołującego na
wyjściu, bo `SET LOCAL` żyje do końca transakcji. HoofCare publikuje przy
zamknięciu wizyty, kluczem jest wizyta, więc ponowne zamknięcie poprawia
historię zamiast ją dublować. Tabela historii ma wymuszone RLS i strażnika
relacji; to domyka też ostatnią otwartą pozycję etapu 4.

Zrobione (kartoteka i plany): kartoteka zwierzęcia to feed z rodzajami wpisów
(notatka, uwaga, zabieg, lek lub szczepienie, wizyta specjalisty), autorem i
znacznikiem prywatności; filtry liczy baza. Firma z aktywnym udziałem czyta
kartotekę w rejestrze rolnika poza wpisami prywatnymi. Organizacja dostaje przy
założeniu darmowy plan swojego typu — w HoofCare `farm_free`, obok płatnego
`farm_plus` z kredytami na funkcje wspierane przez AI. Pakiet rolnika z 6
miesiącami darmowymi zastąpiony modelem darmowy + płatny (decyzja z 20.09).

Zrobione (rozjazd stada): sztuka wpisana przez firmę czeka na przejrzenie —
licznik i filtr przy liście zwierząt, znacznik przy sztuce, potwierdzenie w jej
karcie. Nic nie jest kasowane, a zapis bez zmiany nie stawia znacznika.

Zrobione (domknięcie etapu): akcja firmy „wyślij stado do rejestru" (domyka
okno między wydaniem a realizacją kodu), dobowe powiadomienie w panelu dla osób
z prawem do stada (jedna wiadomość na gospodarstwo, bez e-maila) oraz komenda
operatorska `link_farm` łącząca gospodarstwo bez kodu — z MFA, powodem i
audytem po obu stronach.

**Etap 3 zamknięty.**

## Etap 4 — korekcja i wpisy zdrowotne (HoofCare) — ZROBIONE 2026-09-19/20 (bez publikacji do rejestru)

Stan: HoofCare `6777930` (kontrakt), `c3df0d2` (praca w terenie), `2fe1910`
(raport), `2330d22` (poprawki po przeglądzie), `25ed22a` (katalog ICAR);
Saas-Core `b7433d7` (uprawnienia członkostwa, imię, pracownik kalendarza),
`d4cb6db` (zamknięcie wizyty, krowa spoza kolejki), `dec9d5d` (szablony i
załączniki powiadomień, kontakt firmy, fpdf2), `5ee16aa` + `b8d7c42`
(poprawki po przeglądzie). Decyzje w HC-ADR-002, projekt w
`docs/product/Etap-4-Korekcja-W-Terenie-Projekt.md` (HoofCare).

Zrobione: wpis korekcji z katalogiem ICAR v1 (wersjonowany, przypinany do
wizyty), kolejka i przebieg wizyty, kontrole wyliczane z wpisów, panel „Dziś”,
zakończenie wizyty zamykające rezerwację, raport z PDF, archiwum i wysyłką
e-mailem z załącznikiem, zamrożenie wizyty po wysyłce.

Domknięte 20.09: publikacja wpisów do kartoteki zwierzęcia w rejestrze rolnika,
zamrożenie katalogu ICAR v1 („nadmierny róg” to korekcja funkcjonalna, SH
zostaje krwawieniem podeszwy) oraz zdjęcia przy wpisie — przekazywane rolnikowi
jako dostęp do pliku firmy, nie kopia.

Otwarte: tryb offline w terenie. Zdjęcia przy wpisie domknięte 20.09, materiały
i leki (RACICE 13.6, 16) mają własny etap 6.

## Etap 5 — sprzedaż zwierząt

Ruch zwierzęcia między rejestrami z historią wpisów zdrowotnych.

## Etap 6 — magazyn materiałów i leków (Saas-Core + HoofCare) — M1/M2 ZROBIONE 2026-09-21

Firma kupuje materiał, wydaje go ludziom, a ci zużywają go przy krowie. Trzy
zdania, które muszą się zgadzać do sztuki, bo z nich wychodzi zarówno koszt
korekcji, jak i odpowiedź na pytanie „czy korektorowi wystarczy do końca obory".

Decyzje (21.09, Maciej):

- leki to **kategoria materiału**, nie osobny byt: jeden katalog, kategorie
  `block`, `dressing`, `medicine`, `tool`, `other`. Ekran korekcji ma z góry
  trzy domyślne (klocek, opatrunek, lek), reszta wchodzi z listy „wybierz
  materiał";
- **zapas należy do osoby**, nie do samochodu ani wizyty. Korektor wyjeżdża z
  bazy z pakietem i to jego stan schodzi przy pracy;
- **brak pokrycia ostrzega, ale zapisuje**. Praca w oborze nie czeka na
  magazyn; ujemny stan jest tym, co właściciel ma wyjaśnić;
- przyjęcie niesie **ilość i cenę zakupu**; rozchód wycenia się średnią ważoną
  kroczącą, więc koszt zabiegu wychodzi z magazynu, a nie z cennika;
- magazynem zarządza właściciel i administrator firmy; biuro, korektor i
  podgląd widzą stany (rola `trimmer` musi widzieć swój pakiet).

Model: stan to suma ruchów (`InventoryMovement` dopisywalne, `InventoryBalance`
trzymane obok dla ekranu). `holder` pusty to magazyn firmy, `holder` z osobą to
jej pakiet. Wydanie i zwrot to dwa ruchy, zużycie jest idempotentne po
`(organizacja, źródło, referencja, pozycja, posiadacz)` — wpis korekcji
zapisany dwa razy to jeden klocek.

**M1 — rdzeń (`shared.inventory`), zrobione.** Katalog pozycji, przyjęcie z
ceną, wydanie osobie, zwrot, korekta z powodem, stany i ruchy; RLS, uprawnienia
`inventory.read` / `inventory.manage`, cecha planu `inventory.enabled`; panel
`/panel/inventory` (magazyn firmy, mój zapas, przyjęcie, wydanie korektorowi z
podglądem, co ta osoba ma przy sobie). Saas-Core: panel i wydanie `9cf7895`,
zwrot zużycia przy cofnięciu wpisu `6a7ab42`.

**M2 — zużycie przy korekcji (HoofCare), zrobione.** `workspace` niesie pakiet
korektora, wpis przyjmuje `materials`, zużycie schodzi z jego zapasu w tej samej
transakcji co wpis. Ekran korekcji pokazuje stan przy zabiegu, pozwala dobrać
materiał spoza trzech domyślnych i ostrzega, gdy schodzi poniżej zera. HoofCare:
`808e44e` (backend), `9d24fbe` (teren), `7435aad` (uprawnienia ról typu).

Dowód na żywym stacku (21.09): przyjęcie 20 szt. po 12,50 → magazyn firmy 20,
wydanie 5 korektorowi → firma 15 / korektor 5, wpis z klockiem → korektor 4,
powtórka tego samego wpisu → nadal 4, wpis na 10 szt. → −6 i zapis przechodzi.

**M3 — leki, otwarte.** Partie i daty ważności, karencja na mleko i mięso,
ewidencja podania i wpis karencji w kartotece zwierzęcia (to ostatnie przez
`publish_health_entry`, bo rolnik musi to widzieć u siebie).

**M4 — stan minimalny i koszty, otwarte.** Alert progu tym samym mechanizmem co
„do przejrzenia" oraz raport zużycia i kosztu per korektor, gospodarstwo i
okres.

Do wzięcia przy najbliższym `core:update` w HoofCare: panel wydania (M1) i
`release` w „Cofnij" — cofnięty wpis ma oddać materiał do zapasu; sam serwis
rdzenia już to potrafi, wertykał jeszcze go nie woła.

Uwaga wdrożeniowa: `publish_feature` wydaje nową wersję planu, ale subskrypcje
zostają na poprzedniej — po wdrożeniu modułu trzeba przenieść je na bieżącą
wersję, inaczej moduł jest ciemny mimo wdrożenia (na dev zrobione ręcznie).

## Poza planem (świadomie)

Uprawnienia zawężone do obiektu (RACICE 4.4), wspólne logowanie rolnika w wielu
aplikacjach i wydzielenie rejestru do osobnej usługi. Wracamy do nich przy
drugiej aplikacji rolniczej.
