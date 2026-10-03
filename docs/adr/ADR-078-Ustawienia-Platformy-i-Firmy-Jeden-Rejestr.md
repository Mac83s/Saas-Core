# ADR-078 — Ustawienia platformy i firmy: jeden rejestr

**Status:** Accepted — faza R0 planu memex `saas-core-ustawienia-firmy` (decyzje
techniczne agenta UF-T1…UF-T16 i UF-D1…UF-D4 z 2026-10-02), po przeglądzie sesji
rezerwacji (ADR-072 §11, faza 2), asystenta (A1b), tłumaczeń (K1) i stron firm (K2).
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
   pierwszego naruszenia albo `None`. Że polecenie jest adapterem grupy, bramka wie
   z mapy polecenie → grupa, którą rejestr ustawień zapisuje sam przy rejestracji
   adaptera — nie zgaduje po nazwie. Inne polecenia przepuszcza, a podgląd `None`
   (odczyt) znosi. Bramki działają po podglądzie w kolejności nazw (`features`,
   `settings`); wyjątek w bramce to odmowa. Wykonawca się nie zmienia.
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
`public_locales` — limit tylko przy dodawaniu, a usuwania i kolejności plan nigdy
nie blokuje (reguły ADR-071 pkt 4–6 zostają: lista nigdy pusta, języka źródłowego
strony nie da się usunąć, usunięcie jest decyzją osoby), obszar platformy zwolniony,
a obniżony limit nie wyłącza włączonego języka (ADR-071 pkt 7). Przy `fallback` i
`keep` przekroczenie limitu przycina wartość skuteczną bez zmiany zapisu. Migawki
rezerwacji się nie zmieniają. Schemat (pkt 11)
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
oferty z ADR-072 §11). Języki firmy mają własną wersję
`Organization.public_locales_version`, a pokwitowanie i historię domenową w
`PublicLocalesChange` z TL10 (ADR-071 pkt 5).

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
kliknięcia (ADR-076 pkt 6, uzupełnienie A1b-8): etykieta musi być w `person_gates`
polecenia i w suficie kanału. Funkcja żyje dziś w `shared/sites/services.py`, a
rejestr w rdzeniu nie importuje `shared`, więc pierwsza deklaracja, która jej
zażąda, przenosi ją do `core.organizations` pod tą samą nazwą (licznik etykiet w
`tests/test_command_doors.py` szuka wywołań po nazwie), a `shared.sites` ją
reeksportuje.

### 9. Jeden kontrakt zapisu, wykonuje go właściciel danych (UF-T6)

Kolejność: uprawnienie zasięgu → cecha planu, blokady, sufity → walidacja z
rejestru (typ, granice, `validate`, `depends_on`) → podgląd skutków i efektywna
klasa ryzyka → zapis w transakcji z `record_audit` i hakiem `on_changed`.
Pominięte pole albo `null` = bez zmian; powrót do dziedziczenia to jawna lista
`reset`, tak samo w API i w poleceniach (ADR-076 pkt 1: `null` w poleceniu znaczy
„bez zmiany”, więc nie może znaczyć „usuń”). W poleceniu `reset` to
`{"type": ["array", "null"], "items": {"type": "string", "enum": [klucze grupy]}}` w
`required`, bez `minItems` i `uniqueItems` (port zdejmuje granice tablic w trybie
strict); `null` i `[]` znaczą to samo — nic nie resetuj — a powtórzenia usuwa
walidacja. Dla `copy_at_creation` `reset`
kopiuje bieżącą wartość domyślną firmy — znowu jako kopię. Nieaktualny token wersji
to 409 `settings_version_conflict` (w encjach kod właściciela, np.
`booking_version_conflict`); błędy mają `errors [{field, code, message}]` z
polem = klucz.

Zasięg firmy zapisuje `change_settings(group, changes, reset, expected_version)` w
rdzeniu. Encje zapisuje serwis modułu, który woła walidację, podgląd i historię z
rejestru: oferta przez §11 (pkt 17), sklep przez `ShopMutation`, tłumaczenia przez
API `TranslationSettings` (TL6), języki przez serwis TL10. Historia: grupy firmy
(`store`, `column`, także języki z TL10) zapisują akcję
`organization.settings_changed` z kluczem grupy w `target_type` i różnicą kluczy w
metadanych (`field_changes`; klucze `personal` tylko „zmieniono”); grupy w encjach
zostają przy akcjach domenowych modułu i dopisują klucz grupy w metadanych. Historia
filtruje po grupie i kluczu; nowa akcja dostaje etykietę pl/en w
słowniku akcji historii.

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
przechodzi na fragment z rejestru bez zmiany wejścia; polecenie zapowiedziane w
`packages/contracts/commands/planned.json` znika stamtąd w commicie, który je
rejestruje. Klucze z `changes_billing` dają osobną grupę zgody ze step-upem w tokenie
(A1b-7), więc ich evale używają konta z 2FA albo oczekują
`step_up_mfa_setup_required`.

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

## Uzupełnienie 2026-10-03: jak zbudowało to R1

- **Odczyt bez pamięci na żądanie (zmienia pkt 3).** `resolve()` pyta bazę przy
  każdym wywołaniu (jedno zapytanie o wiersze firmy), a kod czytający w pętli
  owija ją w `settings_snapshot()`. Pamięć związana z kontekstem żądania przeżyłaby
  podgląd polecenia aż do jego wykonania i ukryła zmianę, która powinna unieważnić
  zgodę — wykazał to eval „zgoda nieaktualna, gdy to, co widziała, się zmieniło”.
- **Pole grupy to ostatni segment klucza** (`booking.reminders.lead_hours` →
  `lead_hours`): tak nazywa się w API grupy, w poleceniu i w `errors`; klucz grupy
  firmy ma więc postać `<grupa>.<pole>`.
- **Wartość platformy do czasu jej tabeli** to ustawienie Django o nazwie z
  `platform_env` (czytane z `.env` przy starcie i sprawdzane deklaracją); źródło
  `platform`.
- **Usunięta wartość zostaje wierszem bez wartości** z podbitą wersją, żeby token
  grupy sprzed zmiany nigdy nie pasował ponownie.
- Typ `date` dołączył do typów ustawień (`SETTING_TYPES`); typ zasięgu `operator`,
  strategie `restrict`/`lockable`, `copy_at_creation` i `settingsDefaults` wejdą z
  pierwszym kluczem, który ich potrzebuje.

## Uzupełnienie 2026-10-03 (2): R2b i odpowiedzi 34–37

- **Grupa encji (zmienia pkt 7).** Grupa z `api` deklaruje klucze w rejestrze,
  a tabelę, endpoint, potwierdzenia i polecenia zostawia modułowi; `read_explicit`
  mówi, skąd moduł bierze wartość jawnie ustawioną. Tak weszły dane podstawowe
  firmy (`organization`: język, strefa czasu, waluta; `organizations/current/`),
  oferta (`booking.offer`; `booking/setup/services/`) i tłumaczenia. Schemat
  podaje `api` grupy, więc panel wie, że nie zapisuje jej przez
  `current/settings/<grupa>/`.
- **`depends_on`** to `<pole>` (przełącznik tej grupy) albo `<pole> == '<wartość>'`;
  formularz pokazuje pole tylko przy spełnionym warunku, serwis wartości ukrytego
  pola nie odrzuca. **`strategy`** (`override`, `restrict` dla `enum` i `int`) jest
  w schemacie pola.
- **34a (pkt 8).** Rozliczeniami zarządza domyślnie tylko właściciel. Grupa
  `billing.access` (`billing.access.delegated`, `owner_only`) pozwala mu dopuścić
  role z `billing.manage`; powiadomienia o rozliczeniach trafiają do tych, którzy
  mogą działać. Zmiana tego przełącznika wymaga kodu 2FA (`step_up_reason` grupy):
  serwis woła `require_step_up` w panelu i u asystenta, a formularz po
  `step_up_required` pyta o kod i powtarza zapis (`step_up_mfa_setup_required`
  odsyła do „Twoje konto”). Od odpowiedzi 52a (03.10) firma, która ma
  subskrypcję, potwierdza kodem także zmianę danych do faktury, wejście do portalu
  płatności i zakup kredytów (`_step_up_when_paying` w serwisach rozliczeń; panel
  pyta o kod tym samym dialogiem, `useStepUp`); pierwszy zakup planu — bez
  subskrypcji — kodu nie wymaga. U asystenta zostaje modyfikator `changes_billing`.
- **35a.** `organization.security.mfa_required`: `none` (domyślnie), `managers`,
  `all`; nowa firma MedPlano startuje od `managers` przez `settingsDefaults`. Ten
  klucz ma `inheritance="copy_at_creation"` (pkt 6 dla zasięgu firmy): wartość
  produktu zapisuje się jako własna wartość firmy przy jej utworzeniu
  (`settings_at_creation()` w `create_organization` i w danych demo) i nigdy nie
  jest czytana na żywo, więc firma starsza niż ta wartość zostaje przy `none`, aż
  sama to zmieni — nikogo nie wyrzuca w środku pracy (decyzja koordynatora
  03.10, właściciel może ją zmienić). „Przywróć” wraca do wartości kodu, nie
  produktu. Rola
  zarządzająca to rola z `organization.settings.manage`, `members.manage` albo
  `members.manage_limited`. Rejestr odpowiada tylko, czy wymóg obejmuje członkostwo
  (`membership_requires_mfa`, pamiętane per firma i czyszczone przy zmianie);
  bramka przy wejściu do firmy należy do tożsamości. Włączenie wymogu nikogo nie
  wylogowuje — zatrzymuje następne żądanie, a zgody asystenta wygasają z
  `COMMAND_CONSENT_TTL`. Dlatego podgląd zmiany mówi, ile osób straci dostęp, a
  zmiana, która objęłaby zmieniającego bez potwierdzonego 2FA, jest odrzucana
  (`mfa_required_self` przy polu) — inaczej zamknąłby sobie stronę, na której
  wymóg się wyłącza. Odmowy, których deklaracja nie wyrazi, grupa podaje w
  `SettingGroup.check(before, after)`; działa w podglądzie i w zapisie, w panelu
  i u asystenta. Lista zespołu pokazuje 2FA tylko temu, kto zarządza
  zespołem albo ustawieniami firmy.
- **36a.** E-mail do klienta firmy (szablon z `audience=customer`) wychodzi z
  adresu platformy pod nazwą firmy z wizytówki (albo nazwą organizacji), a
  Reply-To to e-mail z wizytówki, inaczej właściciela. Grupa
  `notifications.customer_mail` ma jeden klucz — tekst firmy dopisywany na końcu
  każdego takiego e-maila: do 300 znaków, zwykły tekst, bez linków i adresów
  (`SettingSpec.no_links`, kod błędu `links`), nigdy dane klienta. Nadawcę, Reply-To
  i tekst ustala doręczenie, bo treść e-maila też renderuje się dopiero wtedy.
  Wizytówka należy do Profili, więc Profile podają ją powiadomieniom
  (`register_customer_sender`), a nie odwrotnie.
- **37a (zmienia ADR-036, rozstrzygnięcie 3).** Automatyczne usuwanie danych
  klientów jest domyślnie wyłączone; firma może je włączyć na 12, 24 albo 36
  miesięcy od ostatniej wizyty, z podglądem „dotyczy N osób” przed zapisem
  (D1–D2 planu). Do tego czasu anonimizacja jest wyłącznie ręczna.

## Uzupełnienie 2026-10-03 (3): R4 — obszary, strona ogólna, wyszukiwarka (zmienia pkt 13)

- **Obszar jest deklaracją modułu** (`SettingArea`, `register_setting_area`):
  klucz będący adresem, tytuł i opis pl/en, kolejność i opcjonalna własna strona.
  Grupa, której obszaru nikt nie zadeklarował, zatrzymuje start (`organizations.E102`).
  Rdzeń deklaruje „Dane firmy” i „Bezpieczeństwo”, rezerwacje „Usługi i grafik” i
  „Rezerwacje”, rozliczenia „Plan i płatności”, tłumaczenia „Języki”, powiadomienia
  „E-maile do klientów” — tekst firmy do klientów ma własny obszar, bo pisze do
  klientów także firma bez kalendarza.
- **Schemat podaje `areas`** (obszary z co najmniej jedną grupą firmy, w kolejności
  menu). Obszar bez strony rysuje `/panel/settings/<obszar>`, a menu pokazuje go
  temu, kto może zmienić którąś z jego grup. Wymóg 2FA przeniósł się więc z „Danych
  firmy” na własną stronę „Bezpieczeństwo”, a „E-maile do klientów” z „Rezerwacji”
  na swoją.
- **Wyszukiwarka** czyta ten sam schemat: obszary, grupy i klucze (etykieta, pomoc),
  bez polskich liter i w dowolnej kolejności słów; ustawienie grupy rysowanej z
  deklaracji prowadzi do pola (`#setting-<grupa>-<pole>`), grupa encji — do swojej
  strony. Nowe ustawienie modułu albo produktu jest więc w menu i w wyszukiwarce bez
  kodu frontu.
- Pod każdym formularzem grupy „Historia zmian” prowadzi do historii z filtrem
  `?group=`.
- Poza R4 zostają: „Ustawienia › Firma” z metadanych (dane podstawowe mają własny
  formularz grupy encji), sekcja ustawień w oknie usługi i strony grup produktu —
  ta ostatnia działa już przez stronę ogólną, gdy produkt zadeklaruje obszar bez
  strony.

## Uzupełnienie 2026-10-03 (4): R3a — rezerwacje online, samoobsługa, zespół, zapytania

- **Rezerwacja online (B3, B9):** `booking.online.horizon_days` (1–62, domyślnie 15 z
  dzisiejszym; górna granica to jedno okno wyszukiwania terminów,
  `BOOKING_SLOT_HORIZON_DAYS`) i `booking.online.contact` (e-mail, telefon, jedno z
  dwóch, oba; domyślnie e-mail). Publiczne terminy kończą się na ostatnim dniu
  horyzontu, start dalej → 409 `beyond_booking_horizon`; brak wymaganego kontaktu →
  400 na `customer.<pole>`. Panel nie ma tych ograniczeń.
- **Samoobsługa (B4, UF-D1):** grupa `booking.self_service` — `mode`
  (`change_and_cancel` / `cancel_only` / `none`) i `cutoff_hours` (0–168). Obie
  wartości zapisują się w wizycie przy jej tworzeniu (`Appointment.self_service_mode`,
  `self_service_cutoff_hours`) i tylko one decydują o tym, co może link klienta —
  zmiana ustawienia firmy nie zmienia warunków umówionych wizyt. Odmowa zostaje
  409 `appointment_not_changeable`; publiczna odpowiedź wizyty mówi, co link jeszcze
  może (`self_service`). Na razie zasięg firmy; poziom oferty — gdy firma o niego
  poprosi.
- **Oferta i miejsce na stronie (B2) i siatka startów (B6):** klucze oferty
  `booking.offer.online` i `booking.offer.slot_step_minutes` (5, 10, 15, 20, 30, 60;
  domyślnie 5; zmienia ADR-058 §5 zgodnie z pkt 18 — dolna granica 5 minut zostaje)
  oraz `Location.online`. Publiczny katalog pomija to, czego firma nie pokazuje
  online, a publiczny zapis traktuje to jak nieistniejące; panel widzi wszystko.
  Okno usługi ma oba pola — to „sekcja ustawień w oknie usługi” z R4.
- **Zespół (W8):** `booking.notices.office` (wył.) — każdy z
  `booking.appointment.manage` dostaje powiadomienie i e-mail o nowej rezerwacji
  online, wizycie czekającej na przydział i odwołaniu przez klienta; przypisani nie
  dostają drugi raz.
- **Zapytania ze strony (W2):** `sites.inquiries.recipients` — właściciel albo każdy,
  kto redaguje stronę; każdy w języku swojego panelu. Wybór konkretnych osób i
  zweryfikowanego e-maila czeka na typ „lista” w rejestrze.


## Uzupełnienie 2026-10-03 — słowa produktu w rejestrze (UX-082)

Teksty rejestru (tytuły i opisy obszarów i grup, etykiety, podpowiedzi i etykiety
wartości ustawień) są w pl/en w deklaracji modułu, więc produkt nie nadpisze ich
plikiem komunikatów, a gabinet czytał „E-maile do klientów” i „Klient może wybrać”.
Uzgodnione z development-15 (właściciel rejestru) i development-1b (manifest poleceń):

1. **`relabel_settings(words, organization_type=None)`** z `core.organizations.api`
   woła wertykał produktu w `AppConfig.ready` (wertykały są ostatnie w
   `INSTALLED_APPS`, więc wszystkie grupy już są). Adresy: `area:<klucz>.title|description`,
   `group:<klucz>.title|description`, `setting:<klucz>.label|help`,
   `setting:<klucz>.value:<wartość>`; każdy tekst w pl i en. Zmieniają się wyłącznie
   słowa — nigdy klucze, typy, wartości, domyślne, uprawnienia ani zasięgi. Adres,
   którego nikt nie zarejestrował, albo tekst bez pl/en zatrzymuje start, a błędna
   mapa nie zmienia niczego.
2. **Poziom produktu** (bez typu) podmienia wpisy rejestru, więc te same słowa widzą
   schemat, endpointy opcji (`schema_entry` czyta wpis rejestru, nie stałą modułu),
   historia, wyszukiwarka i polecenia asystenta — `retitle_command` zmienia im tylko
   teksty (tytuł, opis, opis dla modelu). Słowa rdzenia zostają pod
   `unrelabeled_group`, a `relabeled_group_keys` mówi, które grupy produkt zmienił:
   `manifest.json` zostaje w słowach rdzenia (`declared_command` — polecenie tak,
   jak zadeklarował je moduł), a słowa produktu trafiają do `manifest.product.json`
   pod klucz `relabeled` (polecenie, tytuł, opis, opis dla modelu). Sformułowania
   manifestu asystenta są więc per produkt.
3. **Poziom typu** (`organization_type="farm"`) to nakładka czytana tylko dla
   organizacji tego typu: schemat ustawień i opis zmian w podglądzie polecenia.
   Rejestr, polecenia i manifest zostają przy słowach produktu. Historia zmian w
   panelu bierze tytuły grup ze schematu, więc też widzi słowa typu.
5. **Kolejność wdrożenia w produkcie:** produkt woła `relabel_settings` na poziomie
   produktu dopiero wtedy, gdy generator manifestu pisze `manifest.json` słowami
   rdzenia (`unrelabeled_group`), a różnice do `manifest.product.json` — inaczej
   `commands:check` albo `core:check` w produkcie się rozjadą. Test generatora
   pilnuje, że relabel zostawia `command_manifest --check` zielonym.
4. **Czego to nie obejmuje:** wolnych tekstów w kodzie — opisów skutków
   („N osób w firmie straci dostęp”), komunikatów odmowy („Skontaktuj się z firmą”)
   i szablonów e-maili. Te zostają słowami rdzenia; gdy produkt będzie ich
   potrzebował, dostaną własny mechanizm. Teksty pomocy w kontrakcie OpenAPI
   (serializery biorą je ze stałych) zostają słowami rdzenia — to opis API, nie
   ekranu.

## Uzupełnienie 2026-10-03 (5): faza 1 ustawień platformy (zmienia pkt 16)

- **Wartość platformy w bazie.** `PlatformSettingEntry` (klucz, wartość albo null =
  z powrotem do `.env`/kodu, operator, powód, chwila) — tylko dopisywanie; najnowszy
  wpis klucza jest jego wartością, „Przywróć” to kolejny wpis, a wiersze są historią.
  Zmiana działa od zapisu; „data wejścia w życie” z pkt 16 przyjdzie, gdy pierwszy
  klucz jej potrzebuje. `platform_value()` czyta najpierw wartość operatora, potem
  `platform_env`; mapa wartości jest w pamięci podręcznej pod numerem wersji, który
  każdy zapis podbija po zatwierdzeniu transakcji, więc każdy proces widzi zmianę od
  następnego odczytu. Źródła w odpowiedzi: `platform`, `deployment`, `code`.
- **Grupa platformy.** Grupa, której wszystkie klucze mają `scopes=("platform",)`, nie
  potrzebuje `api`: nie ma jej w schemacie firmy, w jej Ustawieniach ani w adresach
  `current/settings/<grupa>/`, firma jej nie zapisze, a `resolve()` czyta ją bez
  tenanta. Grupa mieszana (klucze firmy i klucze tylko platformy) zostaje odrzucona.
  Moduł czyta wartość przez `platform_setting(key)` (z `core.organizations.api`).
- **Dwa poziomy operatora (S-T7).** `operator_level(user)`: 0, 1 (konto `is_staff` z
  potwierdzonym MFA), 2 (do tego aktywne `OperatorGrant`). Poziom 2 nadaje i odbiera
  wyłącznie komenda `operator_level --grant/--revoke --operator --reason` — pierwsze
  nadanie na wdrożeniu daje operator poziomu 1 (dostęp do serwera jest tu
  uprawnieniem), każde następne tylko poziom 2; nadanie i odebranie kończą sesje tej
  osoby. `SettingSpec.operator_level` (domyślnie 2) mówi, kto zmienia wartość
  platformy. Bramka sieci (`require_operator`) to sesja zalogowana przez MFA — panel
  „Platforma” (faza 2) wywoła ją i dla poziomu 2 `require_step_up`, jak zmiany
  rozliczeń.
- **Do czasu panelu** wartości zmienia `platform_setting list|get|set|reset|history`
  z `--operator` i `--reason`.


## Uzupełnienie 2026-10-03 (6): faza 2 — panel „Platforma” (S-T5)

- **API tylko dla operatora.** `GET /api/v1/platform/settings/` daje każdy klucz z
  `platform` w `scopes` (także klucze firm — wartość platformy jest wtedy tym, co
  dostaje firma bez własnej), pogrupowany według grup i obszarów rejestru: wartość,
  źródło (`platform`/`deployment`/`code`), poziom i `can_change` dla tego operatora.
  `POST …/<key>/` przyjmuje wartość albo `null` (z powrotem do `.env`/kodu) i powód;
  `…/preview/` (`x-dry-run`) sprawdza wartość i liczy firmy bez własnej wartości;
  `…/history/` to wpisy klucza od najnowszego. Bramka to `require_operator` (sesja po
  MFA). Klucz poziomu 2: najpierw poziom operatora (`operator_level_required`), potem
  `require_step_up(reason="platform")` — kodu nie żąda się od kogoś, kogo poziom i tak
  nie wpuści.
- **Powtórka nic nie dopisuje.** Ta sama wartość z tym samym powodem od tego samego
  operatora co najnowszy wpis zwraca stan bez nowego wpisu, więc operacja nie
  potrzebuje `Idempotency-Key` (wyjątek opisany w `x-quality-exempt`).
- **„Dotyczy N firm” bez nowych drzwi.** Drzwi ADR-041 dają tylko listę firm
  (`platform_settings.companies_following`); to, czy firma ma własną wartość, czyta
  się w jej tenancie, jak przemiatania billingu (ADR-039). Koszt: zapytanie na firmę
  przy każdym podglądzie — zapisany w planie jako sprawa skali.
- **Panel.** `/panel/platform` z wpisem „Ustawienia platformy” w osobnej grupie menu
  „Platforma”, widocznej przy `operator_level ≥ 1` (pole w `/auth/me/`). Operator bez
  firmy nie trafia do onboardingu: ma panel z samą „Platformą”, a „Dziś” prowadzi go
  tam. Formularz klucza: wartość według typu, powód, „Sprawdź skutek” (podgląd),
  „Zapisz zmianę”; klucz poziomu 2 pyta o kod przez wspólne `useStepUp`. Historia
  pokazuje kto i dlaczego, a wcześniejszą wartość można z niej ustawić ponownie —
  jako nową zmianę z nowym powodem.
- **Poza tą fazą:** grupy „AI i tłumaczenia” i „Języki” wchodzą z kluczami
  planu wielojęzyczności (TL22) — panel rysuje je bez zmian w kodzie; ścieżka
  operatora w cudzym tenancie czeka na osobny ADR.

## Uzupełnienie 2026-10-03 (7): magazyn — M3–M6 (faza 10 magazynu)

- **Grupy `inventory.alerts`, `inventory.lots`, `inventory.materials`** w obszarze
  „Magazyn” (kolejność 55, strona ogólna), uprawnienie grupy `inventory.manage`
  (pkt 4: grupa modułu ma własne), cecha `inventory.enabled`; rejestruje je tylko
  profil, który składa moduł. Po dwa polecenia na grupę z pełną baterią evali.
- **M4: powiadomienie domyślnie `off`.** Plan mówił „raz dziennie”, ale to rytm po
  włączeniu, nie wartość domyślna: dziś nic nie wychodzi, więc `daily` zaczęłoby
  pisać do każdej firmy po wdrożeniu (pkt 16, „domyślne = dziś”; decyzja koordynatora
  03.10, zgodnie z „Powiadomieniami zespołu” z W8). Odkrywalność daje panel: przy
  liście „Do uzupełnienia” link „Włącz codzienne powiadomienie”. Otwarte: czy nowe
  firmy mają startować z `daily` (`settingsDefaults`/`copy_at_creation`) — pytanie do
  właściciela, nie zmiana wartości w kodzie.
- **Zasięg „miejsce” jest kolumną modułu** (pkt 7): minimum pozycji w miejscu to
  `InventoryBalance.minimum_quantity`, a dni „kończy się ważność” kategorii to
  `InventoryCategory.expiring_days`. Magazyn rozstrzyga sam (miejsce → pozycja;
  kategoria → firma) i mówi o tym w `model_description` kluczy, żeby panel i asystent
  wiedzieli, że węższa wartość wygrywa z kluczem.
- **Godzina dnia bez jednostki:** `inventory.alerts.hour` to `int` 0–23 w strefie
  firmy; `SETTING_UNITS` nie dostaje „godziny zegara” dla jednego klucza.
- **M5 deklaruje ten, kto wykonuje regułę** (UF-D4): miejsce produktów wizyty wybiera
  magazyn (`visit_place`), więc klucz to `inventory.materials.source`, a rezerwacje
  niczego nie deklarują i nie uczą się o magazynie.
- **M6:** `inventory.lots.expired_sale` `block` (jak dotąd) albo `warn`; blokada pracy
  przy partii po terminie zostaje stałą z powodem (decyzje 21.09 i 25.09).
