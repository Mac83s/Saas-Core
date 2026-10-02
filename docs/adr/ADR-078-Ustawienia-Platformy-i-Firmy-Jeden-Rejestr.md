# ADR-078 — Ustawienia platformy i firmy: jeden rejestr

**Status:** Proposed — faza R0 planu memex `saas-core-ustawienia-firmy` (decyzje
techniczne agenta UF-T1…UF-T16 i UF-D1…UF-D4 z 2026-10-02), w przeglądzie sesji
rezerwacji (ADR-072 §11), asystenta (A1b), tłumaczeń (K1) i stron firm (K2).
**Data:** 2026-10-02

**Rozszerza:** ADR-076 pkt 1 i 4 (rejestr ustawień obok rejestru poleceń; polecenia
ustawień jako adaptery; bramka przez `register_command_gate`) i ADR-072 §11
(`BookingSetupMutation` jest magazynem idempotencji i wersji ustawień oferty).
**Zmienia:** ADR-058 §5 — siatka startów 5 minut przestaje być stałą (pkt 18);
ADR-073 §8 — lista walut jest wartością platformy z rejestru, a `currency_in_use`
obejmuje też wycenione pozycje magazynu (pkt 18).
**Rozszerza też:** ADR-072 §8 — polityki oferty kopiują się przy utworzeniu z
wartości domyślnej firmy, a przełącznik 28a jest kluczem rejestru (pkt 6, 17);
zamknięcia firmy i miejsca (B11) to nowa encja obok reguł, więc ADR-072 §5 zostaje
bez zmian (pkt 17).
**Doprecyzowuje:** ADR-069 pkt 12 (wartość startowa trybu tłumaczeń z profilu to
`settingsDefaults`, nie osobne pole `ai.translationDefaultMode`) i pkt 30 (nadpisania
operatora dla firmy są źródłem `operator` rejestru).
**Nie zmienia jeszcze:** ADR-057 pkt 5 — dopisek „listy w module, progi i
przełączniki w Ustawieniach” przyjdzie uzupełnieniem, jeśli właściciel odpowie 33 a.
**Stosuje:** ADR-039 i ADR-041 (RLS), ADR-042 (usunięcie firmy), ADR-046:31-36
(pokwitowanie idempotencji), ADR-049 i ADR-050 (produkty, typy organizacji),
ADR-071 pkt 5 i 7 (historia języków, miękki limit), ADR-076 pkt 1–6 (polecenia,
`errors`, „w imieniu”, step-up z uzupełnienia 30a/31b).

## Kontekst

Odczyt kodu 02.10 (plan, „Stan dziś”) znalazł czternaście sposobów, którymi firma
coś „ustawia”: kolumny `Organization` z jedną wersją, tabele 1:1 obok firmy, pola
encji z CHECK-ami, preferencje osoby bez audytu, rewizje od publikacji, opcje w
danych bloku, istnienie wiersza jako przełącznik, plan, komendy operatora, `.env` i
profil, stałe w kodzie powielone we froncie, `owner_only`, statyczne menu i skutki
uboczne innych akcji. Każdy ma inne reguły wersji, idempotencji, audytu i odczytu
wariantów. W rezerwacjach nie ma ani jednego ustawienia całej firmy: przypomnienie
24 h (`config/settings/base.py:540`) i siatka 5 minut
(`shared/booking/availability.py:30`) są wspólne dla całego wdrożenia.

Jednocześnie powstają ustawienia nowego typu: języki firmy (TL10), tryb tłumaczeń
(TL6), polityki oferty i przełącznik 28a (ADR-072 §8), `ShopSettings` (ADR-074),
rachunek i tryb płatności (ADR-073) — a plan ustawień platformy (S-T1) zapowiada
rejestr dla poziomu „platforma lub firma”. Właściciel 02.10: przegląd opcji, które
firma mogłaby zmieniać, i uwzględnienie tego w programowaniu jako osobny refaktor.
Odpowiedzi 11a (ustawienia platformy w UI administratora), 28a (jawny przełącznik
progów zwrotu w ustawieniach oferty), 30a i 31b (step-up tylko przy dokumentach
prawnych i rozliczeniach, wyłącznie kodem 2FA) oraz 32a (polecenia usług po ADR-072
§11, bez tymczasowych `@1`) wiążą kształt.

## Decyzja

### 1. Jeden rejestr dla platformy i firmy, w `core.organizations` (UF-T1)

Rejestr ustawień żyje w `core.organizations` obok rejestru poleceń
(`command_registry.py`), bo rdzeń nie importuje `shared`. Moduły i wertykały
rejestrują deklaracje w `AppConfig.ready()`; błędna deklaracja zatrzymuje start
(`ImproperlyConfigured`, wzór `_declaration_problems` z
`command_registry.py:207`). To ten sam rejestr co S-T1 planu ustawień platformy:
klucz, którego wartość domyślną ustala administrator platformy (klasa A), a wybór
w jej granicach — firma (klasa B), jest jedną deklaracją. Klasa C (infrastruktura,
bezpieczeństwo, limity ochronne, sekrety) nie jest ustawieniem.

Cztery szwy z planem platformy i rejestrem poleceń:

1. **Bramka.** Rejestr rejestruje bramkę `settings` przez `register_command_gate`
   (`command_executor.py:232`). Dla polecenia, które jest adapterem grupy ustawień
   (pkt 12), sprawdza każdy klucz z niepustą wartością albo w `reset`: uprawnienie
   zasięgu, cechę planu, blokadę (operator, `lockable`) i sufity; zwraca kod odmowy
   pierwszego naruszenia albo `None`. Inne polecenia przepuszcza. Wykonawca się nie
   zmienia.
2. **Polecenia.** Moduł rejestruje polecenia ustawień zwykłym `register_command`;
   rejestr ustawień daje fragment schematu wejścia, walidację, podgląd z
   `observed_versions`, eskalację ryzyka i pole wersji (pkt 12).
3. **Historia.** Każdy zapis przechodzi przez `record_audit`, który sam kopiuje
   `acting_via`, `acting_ref` i `acting_trigger` z kontekstu
   (`core/organizations/audit.py`); także historia wartości platformy, inaczej
   zmiana asystenta wyglądałaby jak decyzja osoby.
4. **Klasa C poza rejestrem.** TTL zgody (`COMMAND_CONSENT_TTL`), okno step-upu
   (`STEP_UP_MAX_AGE`) i podobne granice bezpieczeństwa zostają stałymi w kodzie.

### 2. Deklaracja (UF-T1, UF-T2)

```python
SettingSpec(
    key="booking.reminders.lead_hours",   # niezmienny; pierwszy segment = przestrzeń modułu
    module="shared.booking",              # właściciel; klucz istnieje tylko, gdy profil go składa
    group="booking.reminders",            # formularz, token wersji, polecenie, jeden właściciel zapisu
    type=Int(minimum=1, maximum=168, unit="hour"),
    default=24,                           # kod = dzisiejsze zachowanie
    scopes=("platform", "organization"),  # zasięgi od najszerszego
    platform_env="BOOKING_REMINDER_LEAD_HOURS",  # wartość startowa A do czasu tabeli platformy
    permission={"organization": "organization.settings.manage"},
    effect="rearm",
    label={"pl": "Przypomnienie przed wizytą", "en": "Reminder before the visit"},
    help={...}, model_description="…",
)
```

Pola: `key`; `module`; `group`; `type` — `Bool`, `Int`/`Decimal` z granicami i
jednostką, `Enum` (wartości, etykiety pl/en, kolejność), `EnumFrom` (warianty z
innego klucza albo funkcji modułu, np. waluty z listy platformy), `Text` z limitem,
`ListOf`, `Ref` (członkostwa, miejsca — nie wolny tekst), `Email` (tylko
zweryfikowany); `default`; `bounds_from` i `ceilings` (pkt 4); `validate` — dodatkowa
reguła z kodem pola (ADR-076 pkt 5); `depends_on` — warunek widoczności i
skuteczności na innym kluczu; `scopes`; `inheritance` (`live` albo
`copy_at_creation`); `strategy` (`override`, `restrict`, `lockable`); `permission`
per zasięg; `entitlement`; `on_downgrade` (`fallback`, `keep`, `keep_shrink_always`);
`data_class` (`public`, `public_personal`, `personal`; `health` zabronione); `risk`
(klasy ADR-076 pkt 2) i `escalate`; `modifiers` (`changes_billing` dla rozliczeń,
pkt 8); `effect` (pkt 15); `storage` (pkt 7); `label`, `help` (pl, en) i
`model_description` (en); `ui` (obszar, widżet, „zaawansowane”); `platform_env`.

Grupa (`SettingGroup`) ma klucz, moduł, tytuł pl/en, obszar panelu, magazyn i
jednego właściciela zapisu (pkt 7), funkcję podglądu skutków (`preview_effects`,
np. „przeliczy N przypomnień”) i hak `on_changed` wołany w transakcji zapisu (dla
`rearm`). Jedna grupa ma jeden mechanizm idempotencji.

Kontrola przy starcie odrzuca: klucz bez etykiet pl/en albo opisu dla modelu;
domyślną poza granicami albo spoza wariantów; uprawnienie, którego nie deklaruje
żaden złożony moduł; cechę spoza katalogu deskryptorów; grupę z kluczami dwóch
modułów albo dwóch magazynów; `health`; przestrzeń nazw zajętą przez inny moduł;
`copy_at_creation` bez zasięgu poniżej firmy; `restrict` bez porządku wartości.

### 3. Zasięgi i warstwy (UF-T3)

Zasięgi od najszerszego: `platform`, `organization`, `location`, `offer`, `staff`
(osoba w firmie); moduł może dodać własny pod `organization` (HoofCare: karta
gospodarstwa). Wartość skuteczną liczą trzy warstwy:

1. **Jawna** — najbardziej szczegółowa ustawiona: osoba → oferta → miejsce → firma.
   Klucze, które ma też `BookingRule` (okno, wyprzedzenie, zamknięcie), dostają nad
   ofertą warstwę datowaną z pierwszeństwem ADR-072 §5 (jednostka, grupa, oferta;
   przy remisie późniejszy sezon) — źródło `rule`.
2. **Domyślna**, gdy jawnej brak: wartość startowa produktu (`settingsDefaults`
   profilu i typu organizacji, pkt 14) → wartość platformy (klasa A) → kod.
3. **Sufity**: granica A, cecha i limit planu, nadpisanie operatora, sufit
   wdrożenia.

`override` — jawna albo domyślna, przycięta granicami. `restrict` — najsurowsza z
tej wartości i sufitów; profil daje tylko wartość domyślną, nigdy sufit (MedPlano
startuje z `review`, a firma wybierze `automatic`, jeśli nie zabrania sufit —
ADR-069 pkt 12). `lockable` — wyższy poziom może zablokować niższy (HoofCare H2:
standard firmy z blokadą dla korektora).

Źródło `operator` to nadpisanie dla jednej firmy z powodem, zapisywane komendą z
`--operator --reason` (konto `is_staff` z MFA) i wpisem w historii firmy; działa
jak blokada: wygrywa z wartością firmy, a firma widzi pole zablokowane z powodem.
Pierwszy przypadek to `translation_org_override` z TL6 (ADR-069 pkt 30). Panel
operatora w cudzym tenancie przychodzi z ADR-em fazy 2 planu platformy.
`EntitlementGrant` zostaje mechanizmem planu.

`resolve(key, scope=…)` zwraca wartość, źródło (`code`, `platform`, `product`,
`plan`, `organization`, `location`, `offer`, `rule`, `staff`, `operator`), granice,
warianty i powód blokady. Ustawienia firmy wczytuje raz na żądanie albo zadanie
(pamięć w kontekście żądania, unieważniana zapisem), więc między procesami nie ma
czego unieważniać. Błąd odczytu wartości firmy kończy żądanie — zapas z kodu
dotyczy wyłącznie poziomu platformy (plan platformy, „Outcome”), bo cicha wartość
domyślna w miejsce wyboru firmy to błąd, którego nikt nie zauważy.

### 4. Granice i warianty

`bounds_from` wskazuje klucz platformy, który zawęża warianty albo zakres (lista
walut, górny sufit okna rezerwacji). Twarde granice bezpieczeństwa (dolna granica
siatki 5 minut, sufit horyzontu zapytania 62 dni) są w deklaracji jako stałe klasy
C i nie da się ich przekroczyć żadną warstwą.

### 5. Tańszy plan niczego nie kasuje (UF-T5)

`fallback` — wartość firmy zostaje zapisana, działa domyślna, pole jest tylko do
odczytu z powodem; `keep` — wartość działa dalej; `keep_shrink_always` dla
`public_locales` — limit tylko przy dodawaniu, usuwanie i kolejność zawsze, obszar
platformy zwolniony (ADR-071 pkt 7). Przekroczenie limitu przycina wartość
skuteczną bez zmiany zapisu. Migawki rezerwacji się nie zmieniają. Schemat (pkt 11)
podaje stan cechy, więc panel zna blokadę przed kliknięciem.

### 6. Dziedziczenie: na żywo albo kopia przy utworzeniu

`live` — niższy zasięg bez jawnej wartości czyta wyższy przy każdym odczycie, a
podgląd zmiany pokazuje „dotyczy N ofert”. `copy_at_creation` — wartość kopiuje się
do encji przy jej utworzeniu (z presetu albo z wartości domyślnej firmy) i zmiana
firmy jej nie przepisuje. **Polityki oferty z ADR-072 §8** — potwierdzenie,
płatność, zadatek, terminy, progi zwrotu, przełącznik 28a, miejsce — mają
`copy_at_creation`, jak preset-kopia (ADR-072 §10, ADR-063 §2). Pozostałe klucze
oferty (przypomnienie, siatka, okno, samoobsługa) dziedziczą na żywo.

### 7. Kontrakt wspólny, magazyn nie (UF-T2, UF-T7)

Wspólne są: warianty i domyślne z API, rozstrzyganie ze źródłem, kontrakt zapisu,
polecenia i formularz. Magazyn zależy od deklaracji:

- `store` — tabela `organization_setting` w `core.organizations` (organizacja,
  klucz, wartość JSON sprawdzana typem, źródło `organization` albo `operator`,
  wersja, kto, kiedy), **tylko dla zasięgu firmy**; FORCE RLS, testy izolacji,
  usuwanie z firmą (ADR-042); brak wiersza = brak jawnej wartości;
- `column:<app.Model.field>` — istniejąca kolumna, gdy potrzebny CHECK albo SQL
  (`Organization.currency` i `currency_in_use`);
- `entity:<app.Model>` — tabela modułu z kluczem obcym; tu żyje **każda wartość
  zasięgu niższego niż firma** (miejsce, oferta, osoba, karta gospodarstwa) oraz
  tabele ustawień modułu (`TranslationSettings`, `ShopSettings`);
- `revision:<…>` — rewizja od publikacji (wygląd strony).

Wersja jest per wiersz wartości. Grupa ma jeden **token wersji**: skrót
(kanoniczny JSON, `core/organizations/canonical.py`) par klucz → wersja dla kluczy
grupy (brak wiersza = 0) — kształt `Preview.observed_versions`. Niezależne grupy
się nie blokują; jedna `Organization.version` przestaje chronić ustawienia, które
nie są kolumnami firmy. Grupa w encji ma za token wersję encji (`expected_version`
oferty z ADR-072 §11). Języki firmy mają własną wersję i `PublicLocalesChange` z
TL10 (ADR-071 pkt 5).

Idempotencję zapisu grupy `store` trzyma pokwitowanie w `core.organizations`
(organizacja, principal, grupa, klucz, skrót żądania, wynik; unikalne jak
`booking_mutation_idem_uq`; RLS) z semantyką ADR-046:31-36. Grupy w encjach używają
pokwitowania właściciela: oferty, miejsca, jednostki i tydzień godzin osoby —
`BookingSetupMutation` (ADR-072 §11; token godzin osoby to
`StaffMember.hours_version`), sklep — `ShopMutation` (ADR-074). Dat wejścia w życie na poziomie firmy nie
ma (datowane są tylko `BookingRule` i wartości platformy); „Przywróć tę wartość” w
historii to nowa zmiana.

### 8. Uprawnienia i step-up (UF-T4)

Uprawnienie jest per zasięg i sprawdza je serwis: firma — `organization.settings.manage`,
a grupy modułów własnym uprawnieniem (`notifications.manage`,
`integrations.manage`, `profiles.manage`, `translation.manage`, `site.publish`);
oferta — `booking.appointment.manage`; osoba — sama. Klucze rozliczeń mają
modyfikator `changes_billing`, więc serwis woła `require_step_up` w panelu i u
asystenta jednakowo (ADR-076, uzupełnienie 30a/31b); kto w ogóle może je zmienić,
rozstrzyga odpowiedź na pytanie 34. Deklaracja może zażądać bramki „tylko osoba”
(`assert_person_required`), wtedy kontekst z `acting` przejdzie tylko po zgodzie z
kliknięcia (ADR-076 pkt 6, uzupełnienie A1b-8).

### 9. Jeden kontrakt zapisu, wykonuje go właściciel danych (UF-T6)

Kolejność: uprawnienie zasięgu → cecha planu, blokady, sufity → walidacja z
rejestru (typ, granice, `validate`, `depends_on`) → podgląd skutków i efektywna
klasa ryzyka → zapis w transakcji z `record_audit` i hakiem `on_changed`.
Pominięte pole albo `null` = bez zmian; powrót do dziedziczenia to jawna lista
`reset`, tak samo w API i w poleceniach (ADR-076 pkt 1: `null` w poleceniu znaczy
„bez zmiany”, więc nie może znaczyć „usuń”). Dla `copy_at_creation` `reset`
kopiuje bieżącą wartość domyślną firmy — znowu jako kopię. Nieaktualny token wersji
to 409 `settings_version_conflict` (w encjach kod właściciela, np.
`booking_version_conflict`); błędy mają `errors [{field, code, message}]` z
polem = klucz.

Zasięg firmy zapisuje `change_settings(group, changes, reset, expected_version)` w
rdzeniu. Encje zapisuje serwis modułu, który woła walidację, podgląd i historię z
rejestru: oferta przez §11 (pkt 17), sklep przez `ShopMutation`, tłumaczenia przez
API `TranslationSettings` (TL6), języki przez serwis TL10. Historia: akcja
`organization.settings_changed` z grupą w `target_type` i różnicą kluczy w metadanych
(`field_changes`; klucze `personal` tylko „zmieniono”), filtr historii po grupie i
kluczu.

### 10. Klasa danych (UF-T8)

`data_class` steruje maskowaniem w historii, wycinaniem wartości dla modelu
(ADR-076 pkt 1) i logami. Odbiorcy (zapytania ze strony, alerty, raporty) to
członkostwa albo zweryfikowane adresy, nie wolny tekst. Sekret nigdy nie jest
ustawieniem.

### 11. API typowane per grupa (UF-T9)

- `GET /api/v1/organizations/current/settings/schema/` — grupy, klucze, typy,
  warianty z etykietami pl/en, domyślne, granice, zależności, uprawnienia, stan
  cechy i blokady. Jedyne źródło wariantów ustawień; `GET /api/v1/booking/presets/`,
  `/commerce/options/` i `/shop/options/` zostają, ale swoje części o ustawieniach
  biorą z rejestru.
- `GET …/settings/<grupa>/` — wartości ze źródłem, blokady i token wersji;
  `POST …/settings/<grupa>/preview/` z `x-dry-run: true`; `PATCH
  …/settings/<grupa>/` — osobna operacja na grupę z serializerem budowanym z
  deklaracji i jawnym `operationId` (`organization_settings_<grupa>_update`), pola
  = klucze, `reset` jako lista z enumem kluczy, `expected_version`, wymagany
  `Idempotency-Key`. Każda operacja spełnia podłogę ADR-076 pkt 7. Nowy klucz
  zmienia odcisk operacji, więc widzi go `pnpm api:check`.
- Grupy w encjach mają API właściciela, z tym samym kształtem pól, `reset` i
  błędów. Rezerwacje: zapis `/booking/setup/{services|locations|resources}/…` i
  `/booking/staff/{id}/hours/`, podgląd `POST …/preview/` (tworzenie) i
  `…/{id}/preview/` (zmiana) z `x-dry-run: true`; odpowiedź podglądu to rekord, jaki
  zostałby zapisany, `changes` w kształcie `field_changes` i `version`.

### 12. Polecenia piszą moduły (UF-T9)

Polecenie ustawień to cienki adapter modułu z nazwą już przyjętą:
`organization.read@1`/`organization.update@1` (A1b-9),
`organization.public_locales.update@1` (TL10), `translation.settings.update@1`
(TL6), `booking.offer.update@1` (A1b-12, po §11); nowa grupa bez polecenia —
`<przestrzeń>.settings_<grupa>.read@1` i `.update@1`. Rejestr daje fragment schematu
strict (pole = klucz, unia z `null`, `additionalProperties: false`), walidację,
podgląd z `observed_versions`, eskalację i pole wersji. **Zestaw kluczy jest
zamrożony w wersji polecenia**: nowy klucz w grupie to nowa wersja albo nowe
polecenie (ADR-076 pkt 1), a dryf łapie `pnpm commands:check`. Każde polecenie ma
pełną baterię evali (ADR-076 pkt 1). Polecenie istniejące przed rejestrem (A1b-9)
przechodzi na fragment z rejestru bez zmiany wejścia.

### 13. Panel z metadanych (UF-T10)

Obszary i menu ustawień przychodzą z API na dynamicznej trasie
`/panel/settings/[obszar]` na `PanelPage` (ADR-057 pkt 2); widżet wynika z typu;
pole pokazuje źródło i „Przywróć”, zablokowane — powód; zapis przechodzi przez okno
podglądu. Własne strony zostają dla danych podstawowych, edytorów list i „Języków i
tłumaczeń” (TL10, TL16). Zwykłe ustawienie produktu nie wymaga kodu frontu. Gdzie
dokładnie stoją obszary w menu, rozstrzyga odpowiedź na pytanie 33.

### 14. Produkty i profil (UF-T11)

Wertykał rejestruje klucze w swoim `AppConfig.ready` (HoofCare: `hoofcare.*`) i może
dodać zasięg (karta gospodarstwa); `TrimmingPreferences` staje się warstwą osoby nad
standardem firmy, jeśli właściciel odpowie 38 a. Profil i typ organizacji dostają
`settingsDefaults` (`{"<klucz>": wartość}`; także wartości startowe nowej firmy —
język, strefa, waluta — dziś na sztywno w serializerze), sprawdzane przy starcie i
przez `deployment-check` na manifeście `packages/contracts/settings/manifest.json`
(`manage.py settings_manifest`, wzór `command_manifest`). Wartość startowa trybu
tłumaczeń to `settingsDefaults["translation.settings.mode"]` (MedPlano: `review`);
osobnego pola `ai.translationDefaultMode` z ADR-069 pkt 12 nie wprowadzamy. Kto
pierwszy potrzebuje `settingsDefaults` (TL6 albo R1), dopisuje je do
`deployment.schema.json` w tym kształcie.

### 15. Moment działania (UF-T14)

`live` (siatka, okno, pauza) — od następnego odczytu; `rearm` (przypomnienia) —
przelicza tylko niewysłane; `at_creation` (nowa usługa, polityki oferty, preset);
`snapshot` (warunki klienta w rezerwacji, ADR-030, ADR-072 §7–8) — dotyczy nowych
rezerwacji; `on_publish` (strona). Podgląd mówi, czego zmiana dotknie.

### 16. Platforma, `.env` i stałe (UF-T12, UF-T15, UF-T16)

Wartość klasy A trzyma tabela platformy z planu ustawień platformy (faza 1:
wpisy tylko do dopisywania z datą wejścia w życie, autorem i powodem, S-T2; zapis
przez bramkę operatora S-T7 i komendę `platform_setting --operator --reason`).
Do czasu tej tabeli wartością platformy jest zmienna `platform_env` z deklaracji,
czytana przy starcie — env z regułą biznesową staje się wartością A ze startem z
`.env` (np. `BOOKING_REMINDER_LEAD_HOURS`). W `.env` zostają sekrety, infrastruktura
i limity ochronne klasy C (`BOOKING_PUBLIC_RATE`). Domyślne = dzisiejsze zachowanie,
poza nazwanymi błędami (M1, M2, data wpisu zdrowia, `GET` preferencji przypinający
„pl”, okno formularza B3).

Do czasu rejestru (R1) obowiązuje reguła tymczasowa w `AGENTS.md`: nowa reguła
biznesowa żyje w jednej nazwanej stałej modułu (wartość, granice, warianty,
etykiety pl/en), wystawionej przez API; R1 przenosi ją do deklaracji bez zmiany
wejścia API i poleceń.

### 17. Rezerwacje: §11, reguły, zamknięcia, presety i 28a (UF-T13)

- **ADR-072 §11 jest magazynem idempotencji i wersji ustawień konfiguracji
  rezerwacji** — ofert, miejsc, jednostek i godzin osoby. Klucze
  zasięgu `offer` deklaruje `shared.booking` (do R1 w stałej modułu); wartości są
  kolumnami encji (`entity:booking.Service`), puste = dziedziczy (`live`) albo
  skopiowane przy utworzeniu (`copy_at_creation`). Zapis: `BookingSetupMutation`,
  `expected_version` oferty, 409 `booking_version_conflict`, `dry_run`; walidację,
  podgląd i różnicę do historii bierze z rejestru (do R1 — z serializerów booking
  i stałej modułu `OFFER_SETTINGS`).
- **`BookingRule` jest warstwą datowaną** nad ofertą (pkt 3), z własną wersją; nie
  jest zasięgiem rejestru i nie trzyma niedatowanych wartości firmy.
- **Zamknięcia (B11) to osobna encja `BookingClosure`** (zasięg firma albo
  miejsce, zakres dat lokalnych, notatka; własna wersja i pokwitowania §11, „skopiuj
  na kolejny rok” jak sezony reguł). Zamknięcie zawsze ogranicza — terminy `slot`,
  okresy `range` i wystąpienia `session` — i żadna bardziej szczegółowa reguła go
  nie znosi. ADR-072 §5 zostaje bez zmian. — Reguła rozstrzyga „wygrywa bardziej
  szczegółowy”, więc reguła oferty zniosłaby zamknięcie firmy; zamknięcie Wigilii
  ma też zamknąć kalendarz osób, którego reguły nie dotyczą (uzgodnione z sesją
  fazy 2 rezerwacji).
- **Warianty oferty do czasu R1** podaje `GET /api/v1/booking/setup/options/` z
  jednej stałej modułu; wpis ma kształt wpisu schematu z pkt 11 (`key`, `type`,
  `minimum`, `maximum`, `unit`, `values` z etykietami, `default`, `label`, `help`,
  `description` dla modelu, `scopes`, `depends_on`), więc po R1 ten sam endpoint
  czyta rejestr bez zmiany kształtu.
- **Polityki §8 mają `copy_at_creation`** (pkt 6). Przełącznik 28a to klucz
  `booking.offer.cancellation.applies_to` (`deposit` | `paid`, jak w kontrakcie
  presetów), grupa `booking.offer_payment`, domyślnie `deposit`, widoczny tylko
  przy polityce `deposit` (przy `transfer` i `full` skutecznie `paid`), `snapshot`;
  w panelu od fazy 3, działa od fazy 4.
- **Preset** to nazwany zestaw wartości kluczy oferty i treść; zastosowanie
  kopiuje je do nieaktywnej oferty z `preset_id@wersja`. Test kontraktu presetów
  waliduje każdą wartość deklaracją rejestru (ta sama nazwa i typ). Domyślne
  presetów stają się potem wartościami A (ADR-072 §10).

### 18. Zmiany w innych ADR-ach

- **ADR-058 §5:** siatka startów to klucz `booking.offer.slot_step_minutes` (B6;
  oferta, domyślna firmy; warianty 5–60, domyślnie 5); dolna granica 5 minut zostaje
  w kodzie jako klasa C.
- **ADR-073 §8:** lista walut (PLN, EUR, USD) to wartość platformy
  `organization.currency.allowed` i `bounds_from` klucza waluty firmy; walutę pozycji
  magazynu kopiuje się z firmy przy utworzeniu (UF-D3), więc `currency_in_use`
  obejmuje też wycenione pozycje magazynu. Brutto albo netto (wspólne dla rezerwacji,
  sklepu i zamówień) deklaruje rdzeń obok waluty (UF-D4).
- **ADR-072 §8:** jak w pkt 6 i 17; §5 bez zmian.

## Konsekwencje

- Fazy planu: R1 — rejestr z kontrolą przy starcie, `organization_setting` (FORCE
  RLS), pokwitowania, `resolve()` z warstwami i źródłem, `change_settings()`, API per
  grupa, filtr historii, bramka `settings`; pilot „Rezerwacje”: przypomnienie na
  poziomie firmy (B5) i wstrzymanie rezerwacji online (B1); wspólny rdzeń z fazą 1
  planu platformy. R2a — ustawienia, które istnieją, a nie działają (waluta
  magazynu, daty w strefie firmy, lista walut z API, `GET` preferencji bez zapisu);
  R2b — rozproszone ustawienia przez adaptery; R3 — kandydaci według priorytetu;
  R4 — panel z metadanych; R5 — reguła w `AGENTS.md`, skill, test rejestru, manifest.
- Migracje `core.organizations` dostają numer po rebase (0054 zajęte). Produkty
  dostają rejestr przez `core:update` i rejestrują swoje klucze nowymi plikami.
- Zasada dla nowych funkcji: co firma mogłaby chcieć inaczej, jest ustawieniem;
  reguła stała dostaje wpis „stałe z powodem” (świadome nie-ustawienia planu: odznaka
  AI, „Uwagi”, stawki VAT, bramki osoby, autoresponder formularza kontaktu, roboty
  AI, zawężanie grantu SCR, samoczynne odwołanie przy niewpłaconej dopłacie i inne
  z listy planu).
- Grupy w encjach mają własne pokwitowania i wersje, więc ustawienie oferty i
  ustawienie firmy nie dzielą transakcji; zmiana firmy i oferty naraz to dwa
  polecenia w jednym planie zgody.
- Odpowiedzi właściciela 33–38 (miejsce ustawień, role rozliczeń, 2FA wymagane przez
  firmę, nadawca i tekst e-maili, automatyczne usuwanie, standard firmy w HoofCare)
  nie blokują R0 ani R1; kluczy, które od nich zależą, nie budujemy przed odpowiedzią.

## Odrzucone

- **Wszystkie ustawienia w jednej tabeli klucz–wartość** — odbiera ograniczenia SQL
  (`currency_in_use`, CHECK-i usług), a niższe zasięgi wymagałyby polimorficznego id
  bez klucza obcego, strażnika relacji między tenantami i sprzątania.
- **Osobny rejestr dla platformy i dla firmy** — rozjechałyby się przy pierwszym
  kluczu z wartością platformy i wyborem firmy.
- **Rejestr w `shared`** — rdzeń (waluta, język, strefa) nie mógłby z niego
  korzystać.
- **Jeden endpoint `PATCH …/settings/` z mapą `changes`** — nietypowany, bez odcisku
  per grupa, wbrew zasadzie typowanego API.
- **Polecenia generowane automatycznie „na grupę”** — nie dałyby przyjętych nazw, a
  dopisanie klucza łamałoby wejście istniejącej wersji.
- **`null` jako powrót do dziedziczenia** — w poleceniu `null` znaczy „bez zmiany”;
  jedna semantyka nie zastawia pułapki na model.
- **Polityki oferty dziedziczone na żywo** — zmiana firmy przepisałaby warunki
  ofert, jak preset-odwołanie odrzucone w ADR-072.
- **Daty wejścia w życie dla wartości firmy** — firma zmienia ustawienie dziś, a
  sezonowość wyraża `BookingRule`; daty mają tylko wartości platformy (S-T2).
- **Zamknięcia jako nowe zasięgi `BookingRule`** (firma, miejsce) z zamknięciem
  liczonym jako ograniczenie — jedna tabela dat, ale zmiana pierwszeństwa ADR-072
  §5 tylko dla jednego pola i reguła, której silnik terminów `slot` dziś nie czyta.
- **Cichy powrót do wartości domyślnej przy błędzie odczytu wartości firmy** — firma
  dostałaby przypomnienie, które wyłączyła, i nikt by tego nie zauważył.
- **Reguły biznesowe w `.env`** — zmiana wymaga odtworzenia kontenera, nie zostawia
  historii i nie da się jej ustawić per firma.
