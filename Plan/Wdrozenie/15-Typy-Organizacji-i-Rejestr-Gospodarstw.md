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

## Etap 3 — konto rolnika, połączenie i synchronizacja — W TOKU

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

Otwarte: drzwi synchronizacji (firma pisze do rejestru przez `share_for_writing`),
publikacja wpisów korekcji jako wpisy zdrowotne zwierzęcia (domyka resztę etapu
4), pakiet rolnika z 6 miesiącami okresu próbnego, akcja obsługi „połącz bez
kodu”, ekran scalania rozjechanych sztuk.

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

Otwarte: publikacja wpisów do rejestru rolnika (czeka na etap 3), zamrożenie
katalogu v1 (pole SH do potwierdzenia), zdjęcia, materiały i leki (RACICE 13.5,
13.6, 16), tryb offline.

## Etap 5 — sprzedaż zwierząt

Ruch zwierzęcia między rejestrami z historią wpisów zdrowotnych.

## Poza planem (świadomie)

Uprawnienia zawężone do obiektu (RACICE 4.4), wspólne logowanie rolnika w wielu
aplikacjach i wydzielenie rejestru do osobnej usługi. Wracamy do nich przy
drugiej aplikacji rolniczej.
