# ADR-071 — języki treści, adresy i SEO/GEO: dwie osie języków, dostępność liczona na żywo

**Status:** Accepted — decyzje właściciela z 2026-10-02: języki treści z profilu,
panel zostaje pl/en, limit języków konfigurowalny per plan z jednym dodatkowym
językiem w najtańszym (memex `language-plan-gating-is-a-soft-quota-that-no-pla`),
poprawne SEO i GEO w każdym języku (`multilingual-customer-sites-full-page-bodies-aut`);
plan memex `saas-core-wielojezycznosc-i-tlumaczenia-ai`, decyzje TL-T1–TL-T6,
TL-T28–TL-T34, fazy TL1, TL2, TL10, TL14, TL17–TL20.
**Data:** 2026-10-02

**Zmienia częściowo** ADR-020 (`next-intl` dla PL/EN) i ADR-027 („Tłumaczenia,
adresy i SEO”); świadomie odstępuje od ADR-032:77-78, ADR-033:137 i ADR-059 pkt 9
(pkt 7). Treść podstron per język i jej publikację rozstrzyga ADR-070, silnik
tłumaczeń — ADR-069.

## Kontekst

Backend odmawia startu z językiem spoza pl/en (`config/settings/base.py:102-108`),
front ma `["pl", "en"]` na sztywno, a pola treści i panelu dzielą jeden `LocaleEnum`.
`Organization.default_locale` służy naraz panelowi, e-mailom do zespołu, klientom
rezerwacji i wizytówce. Pomiar z TL0 na lokalnym stosie: każdy kanoniczny adres
strony firmy odpowiadał 308, bo Next obcinał końcowy ukośnik przed proxy, a sitemapa
podawała stronę główną jako `/start/`. noindex był liczony, ale nie trafiał do HTML;
każde tłumaczenie wpisu ogłaszało siebie jako x-default; `/xx/` nie istniało, a
podstrona o slugu `de` zasłoniłaby `/de/`, bo podstrony są dopasowywane przed
korzeniem. Strony firm nie mają JSON-LD.

## Decyzja

### Języki

1. **Dwie osie.** Języki aplikacji (pl, en): panel, logowanie, zaproszenia, e-maile
   do zespołu, czat asystenta. Języki treści: `supportedLocales` profilu — strony
   firm, wizytówka i katalog, widget i e-maile rezerwacji, strony produktu.
   `Organization.default_locale` zostaje na osi aplikacji („Język panelu i e-maili
   do zespołu”); jego publiczne użycia przechodzą na pierwszy język firmy (pkt 4).
   Panel nie dostaje katalogów de/es/ru: ok. 3 500 kluczy w pięciu językach to
   koszt bez wartości dla gościa.
2. **Rejestr języków jako kontrakt.** `packages/contracts/locales/registry.json`:
   kod ISO 639-1, nazwa własna, `ogLocale`, kod wyszukiwarki, pismo, słowo
   „strona” w paginacji, znacznik języka aplikacji. Wersja 1: pl, en, de, es, ru;
   później cs, it, fr; czeski to `cs`, nigdy `cz`. Backend czyta go przy starcie
   (`LOCALE_REGISTRY_PATH`, kopia w obrazie, kontrola systemowa), kontrola profilu
   sprawdza `supportedLocales` i `defaultLocale`, front i `@saas-core/site-blocks`
   biorą eksport pakietu. Nowy język to wpis, sprawdzone teksty dla gości i
   wdrożenie — nie przełącznik w panelu.
3. **Język treści w API to napis `^[a-z]{2}$` sprawdzany przez serwis**, jedną
   funkcją, z kodami pól `locale_not_in_registry`, `locale_not_enabled` i
   `locale_not_seeded`; w bazie CHECK formatu zamiast listy pl/en. `LocaleEnum`
   zostaje tylko na polach osi aplikacji. — Lista dozwolonych języków zależy od
   firmy, więc nie może być enumem OpenAPI.
4. **`Organization.public_locales` — uporządkowana, nigdy pusta lista** (CHECK
   `cardinality >= 1`). Pierwszy język to język klientów: domyślny klienta
   rezerwacji, e-maili do klientów i nowej wizytówki. Nowa firma dostaje
   `[defaultLocale profilu]`, obszar platformy — wszystkie języki treści profilu.
   Istniejące firmy: `[default_locale]`, a za nim języki ich stron, wpisów,
   wizytówki i klientów rezerwacji (migracje rdzenia i modułów).
5. **Jeden serwis zmiany języków firmy**: `GET`, `POST …/preview/` i
   `PUT /api/v1/organizations/current/public-locales/` z kluczem idempotencji,
   wersją, historią `PublicLocalesChange` (FORCE RLS) i audytem z rodzajem aktora.
   Zmienia osoba z `organization.settings.manage`; usunięcie języka tylko osoba,
   a dla asystenta to polecenie wysokiego ryzyka z potwierdzeniem. Podgląd pokazuje
   decyzję limitu i adresy, które przejdą na 308. Dodanie języka niczego nie
   tłumaczy i nie wydaje kredytów (ADR-069). Języki mają własną wersję
   (`Organization.public_locales_version`, 409 `settings_version_conflict`), audyt
   to `organization.settings_changed` z grupą `organization.public_locales`
   (ADR-078 pkt 7, 9), a kody pola `public_locales`: `locale_not_in_registry`,
   `locale_not_supported` (nie ma go w produkcie), `duplicate`,
   `site_default_not_removable`, `locale_path_conflict` (prefiks `/xx/` jest już
   adresem strony albo bloga w języku źródłowym), `quota_exceeded`,
   `plan_access_denied`; podgląd usunięcia wymienia adresy przechodzące na 308 i ich
   cele (`redirects`). Asystent
   zmienia je poleceniem `organization.public_locales.update@1`; usunięcie to
   bramka osoby „Usunięcie języka firmy”, otwierana tylko zgodą z kliknięcia.
6. **Język źródłowy strony.** `Site.default_locale` odpowiada bez prefiksu, musi być
   na liście firmy i nie da się go z niej usunąć (`site_default_not_removable`), a
   po założeniu strony się nie zmienia (ADR-070 pkt 19). Wolno nim być tylko
   językowi z nasionami szablonów (dziś pl, en; inaczej `locale_not_seeded`);
   szablon importowany do treści w innym języku bierze nasiona języka źródłowego.
   Strona nie ma własnej listy języków — zawężenie da się dodać bez zmiany adresów.
7. **Limit to miękki limit `public_locales.additional.max`; tłumaczenie nie jest
   cechą planu.** Limit liczy języki poza pierwszym; wartość 1 dostaje nowa wersja
   najtańszego planu każdego typu organizacji w każdym produkcie, publikowana
   odwracalną migracją danych billing przed pierwszym klientem, a wyższe plany nie
   mają wartości, czyli bez limitu. Strażnik działa tylko przy dodawaniu języka
   (obniżony limit nie wyłącza włączonego), rejestruje go billing w
   `core.organizations` (wzór `register_seat_limit`) i woła `decide_quota` z nowym
   parametrem `operation`: `QUOTA_MISSING` — bez limitu, każdy inny powód niż
   dostępny limit — `plan_access_denied` z powodem; obszar platformy jest
   zwolniony. Odstępstwo od ADR-032:77-78, ADR-033:137 i ADR-059 pkt 9 (dostęp do
   AI jako cecha planu): wartość wyraża „jeden dodatkowy język”, zmienia się bez
   kodu i nie wymaga przenoszenia subskrypcji na nowe wersje wszystkich planów.

### Dostępność

8. **Jedna funkcja dostępności, liczona przy każdym żądaniu.** Język jest dostępny
   na stronie, gdy jest jej językiem źródłowym albo jest na liście firmy, w profilu
   i w `live_locales` migawki (ADR-070 pkt 7); wersja jest publiczna, gdy jej język
   jest dostępny, a wpis jest w migawce i nie jest wstrzymany. Korzystają z niej
   router, hreflang i x-default, menu, przełącznik, sitemapa, kanały, llms.txt i
   projekcja katalogu — jedna tabela testów. Wejście to migawka i
   `public_locales` czytane razem z `tenant_is_servable`; wyniku nie przechowujemy
   dłużej niż jedno żądanie, bo wyłączenie języka ma działać od razu.
9. **Co odpowiada adres wersji niepublicznej.** Nigdy niepubliczna — 404. Język
   wyłączony, dawna wersja z samymi metadanymi (ADR-070 pkt 8) albo wersja zdjęta
   przez osobę — 308 do tej samej strony w języku źródłowym. Wstrzymana po zmianie
   faktów — 307 (ADR-070 pkt 10). Wyłączenie języka niczego nie kasuje i nie
   publikuje; wersje wyłączonego języka przechodzą przez kolejne publikacje
   (ADR-070 pkt 9), więc ponowne włączenie przywraca 200 od razu i bez kosztów.
   Lista katalogu w języku bez przetłumaczonych kart ma `noindex,follow` i nie ma
   jej w sitemapie ani hreflang.

### Adresy

10. **Kształt adresów stron firm bez zmian, ukośnik kanoniczny.** Język źródłowy
    bez prefiksu, inne `/xx/`, slugi ASCII liczone kodem (ADR-070 pkt 18). Next ma
    `skipTrailingSlashRedirect`; proxy przekazuje rendererowi, czy gość wpisał
    końcowy ukośnik, a backend na inną pisownię adresu kanonicznego odpowiada
    jednym 308. Hosty platformy zostają bez ukośnika (proxy: 308 `/x/` → `/x`,
    względny `Location`). `/site-renderer` wywołany bezpośrednio daje 404 na każdym
    hoście, bo tylko przepisanie w proxy ustawia nagłówki, którym renderer ufa.
11. **Strony główne pod `/` i `/xx/`**, kanoniczne na siebie; adres ze slugiem strony
    głównej odpowiada 308. Reguła działa przy odczycie także dla starych migawek,
    bez przepisywania ich.
12. **Zarezerwowane pierwsze segmenty.** Slug języka źródłowego i ścieżka kolekcji
    nie mogą być żadnym segmentem dwuliterowym ani `media`, `api`, `internal`,
    `static`, `healthz`, `site-renderer` (`slug_reserved`) — dwie litery to prefiks
    języka dziś albo jutro, a reszta to ścieżki, które platforma obsługuje przed
    podstronami. Wcześniej zapisane adresy działają dalej i wypisuje je
    `sites_reserved_slugs`; włączenie języka równego istniejącemu slugowi daje
    `locale_path_conflict`.
13. **Treść nie zależy od Accept-Language, IP ani ciasteczka** — żadnych
    przekierowań na adresach treści; przełącznik języka to zwykłe linki.
    `localePrefix` profilu (`as-needed` albo `always`) dotyczy wyłącznie tras hosta
    platformy (strony produktu, katalog, rezerwacje), nigdy stron firm.
14. **Dług adresowy (świadomy):** ścieżki blogów, slugi tagów i kotwice nagłówków są
    wspólne dla wszystkich języków.

### SEO i GEO

15. **Projekcję SEO buduje backend (`shared.sites`) przy żądaniu**, z migawki i
    funkcji dostępności; renderer ją tylko drukuje, a podgląd służy panelowi i
    asystentowi. Canonical na siebie; hreflang publicznych wersji z jednym
    x-default na klaster — wersją w języku źródłowym, a dla wpisu bez niej
    rodzeństwem o pierwszym kodzie języka; `robots` noindex w HTML; `og:locale` z
    alternatywnymi; sitemapa z `xhtml:link` (z x-default) i `lastmod` per język
    ze zmiany `content_hash`; kanały `/xx/rss.xml` i `/xx/atom.xml`, każda strona
    linkuje swoje; llms.txt per język.
16. **JSON-LD z jedną tożsamością firmy.** Węzeł `#organization` jest wspólny dla
    wszystkich języków; fakty (nazwa, adres, telefon, ceny w walucie firmy) nie są
    tłumaczone. `LocalBusiness`, gdy wizytówka ma adres, inaczej `Organization`.
    Fakty dostarcza `shared.profiles` przez rejestr w `core.organizations` (wzór
    `register_resource_reference_handler`), bo moduł wizytówki zależy od stron, a
    nie odwrotnie. Strony i wpisy dostają `WebPage`/`BlogPosting` z `inLanguage`.
17. **Tekst AI ma zawsze znacznik maszynowy** (JSON-LD i meta, ze skrótu
    pochodzenia w migawce, ADR-070 pkt 8); widoczna notka to ustawienie operatora
    `sites.machine_translation_notice`, domyślnie wyłączone do opinii prawnika.
    Opublikowane tłumaczenia AI są indeksowane od razu — kto chce przeglądu,
    wybiera tryb „po akceptacji” (ADR-069).
18. **Roboty.** Wyszukiwarki i agenci użytkownika — zawsze wpuszczeni; roboty
    treningowe — wpuszczone, bez ustawienia, dopóki klient o nie nie poprosi.

### Goście, e-maile, rezerwacje, katalog

19. **Teksty interfejsu dla gości to statyczne katalogi per język**: renderera w
    `@saas-core/site-blocks` (menu, paginacja, formularz, odznaka AI, 404), stron
    platformy we froncie; kompletność wymagana dla modułów, które profil składa, i
    języków, które wymienia. Napisy składane w backendzie (tytuł archiwum tagu,
    pusty indeks, segment paginacji) biorą język z rejestru i małego słownika w
    backendzie, z zastępstwem en → pl.
20. **E-maile do klientów**: łańcuch języka żądany → en → pl rozstrzygany przy
    kolejkowaniu; `EmailTemplate.audience` (`staff` — oś aplikacji, `customer` —
    oś treści); nowe wersje szablonów z `de`.
21. **Rezerwacje**: domyślny język klienta to pierwszy język firmy; język z widgetu
    jest przycinany do listy firmy (nie odrzucany); `/xx/book/<slug>` w języku, którego
    firma nie oferuje — zlokalizowana 404.
22. **Wizytówka i katalog per język**: tłumaczenie wizytówki jest kompletne z
    własnym nagłówkiem i bio (pola zastępcze nie liczą się dla katalogu i SEO);
    projekcja katalogu niesie języki przetłumaczonych kart, karty mają canonical i
    hreflang, Meilisearch indeksuje języki profilu (ADR-064), a geolokalizacja
    działa też pod `/xx/katalog`.

## Zmiany wcześniejszych decyzji

- **ADR-020**, wiersz 21 (`next-intl` dla PL/EN): dotyczy osi aplikacji; trasy
  treści na hoście platformy obsługują języki profilu (pkt 1, 13).
- **ADR-027**, „Tłumaczenia, adresy i SEO”: locale z profilu, ale z rejestru (pkt
  2); x-default wskazuje wersję w języku źródłowym, dla wpisu bez niej — pkt 15;
  strony główne `/` i `/xx/` (pkt 11); kompletność bez zastępstw — ADR-070 pkt 6.
- **ADR-032:77-78, ADR-033:137, ADR-059 pkt 9** — odstępstwo z pkt 7.

## Konsekwencje

- Profil z pl/en/de/es/ru przechodzi kontrolę i startuje; kod spoza rejestru
  zatrzymuje start z czytelnym komunikatem.
- Osiem pól treści traci wybory pl/en (odwracalne migracje; CHECK formatu), a
  klient API przestaje dostawać enum języków treści.
- Wyłączenie języka działa bez publikacji, więc router czyta listę języków firmy
  przy każdym żądaniu — razem z odczytem wiersza firmy, który już się odbywa.
- HoofCare i MedPlano dostają to przez `core:update`; ich języki włącza linia
  profilu, a nowe wersje planów — migracja danych w każdym produkcie (`memex ops`).

## Rozważane alternatywy

- **Języki per strona zamiast per firma** — wizytówka, widget i e-maile nie należą
  do strony; **jeden enum języków na profil** — rozjeżdża wygenerowane pliki
  produktów.
- **Usunięcie języka publikacją pochodną z przekierowaniami** — wymagałoby
  publikacji za osobę przy każdej zmianie ustawień; dostępność na żywo jest tańsza
  i odwracalna.
- **Rezerwacja tylko kodów z rejestru** — nowy język wymagałby sprawdzania
  konfliktów przy każdym włączeniu.
- **Cecha planu `translation.enabled`** — nowe wersje wszystkich planów i ręczne
  przenoszenie subskrypcji.
- **Przekierowanie według Accept-Language** — wyszukiwarka widzi tylko jeden język,
  a SSA wymaga, by adres kanoniczny odpowiadał 200 w swoim języku.
- **noindex do przeglądu tłumaczeń AI** — kasuje wartość SEO tłumaczeń.

## Relacje

- **ADR-020, ADR-027, ADR-032, ADR-033, ADR-059** — zmiany i odstępstwa wyżej.
- **ADR-028** — domena i host nazywają tenanta; reguły adresów dotyczą ścieżek.
- **ADR-039, ADR-041** — `PublicLocalesChange` z wymuszonym RLS; dostępność czytana
  w tenancie nazwanym przez host, bez drzwi przed tenantem.
- **ADR-048, ADR-077** — strony produktu na hoście platformy i ich `localePrefix`.
- **ADR-053, ADR-064** — wizytówka i katalog per język.
- **ADR-069** — tłumaczenia, zgody i koszty; **ADR-070** — treść podstron per język,
  `live_locales`, wstrzymanie i zdjęcie wersji.

## Uzupełnienie 2026-10-03: graf JSON-LD i fakty firmy (TL18a, pkt 16)

Jak pkt 16 jest wykonany, żeby drugi raz tego nie rozstrzygać:

- **Rejestr faktów w rdzeniu.** `register_organization_facts` / `organization_facts`
  w `core.organizations` (`identity_facts.py`); wizytówka rejestruje
  `business_card_facts`. Fakty to nazwa, telefon, e-mail, adres, miejscowość z
  województwem i krajem ze słownika miast oraz linki (`sameAs`). Bierzemy je z
  wizytówki firmy bez względu na to, czy jest opublikowana w katalogu — tak samo jak
  telefon i e-mail w stronach z szablonu (`register_company_contact`, UX-038): to
  dane, które firma podała po to, żeby je pokazać, a trafiają na jej własną stronę.
- **Fakty są w migawce.** Publikacja strony zapisuje je pod kluczem `organization`
  (tylko to, co podane). Żądanie publiczne nie czyta tabel wizytówki, a zmiana
  wizytówki pojawia się na stronie przy następnej publikacji — jak menu i wygląd.
  Migawka bez klucza (sprzed tej zmiany, także po wycofaniu do starszej publikacji)
  daje `Organization` z nazwą strony.
- **Typ.** `LocalBusiness`, gdy wizytówka ma adres (ulicę); inaczej `Organization`.
  Podtyp to `schemaType` kategorii katalogu: w profilu produktu
  (`organizationTypes[].catalogCategories[].schemaType`, np. `LodgingBusiness`) albo
  w słowniku rdzenia. Rdzeń nazywa podtyp tylko tam, gdzie pasuje do każdego zawodu
  kategorii: usługi dla domu i budowlanka → `HomeAndConstructionBusiness`,
  motoryzacja → `AutomotiveBusiness`, gastronomia → `FoodEstablishment`, handel →
  `Store`. „Uroda i zdrowie” łączy fryzjera z lekarzem, więc zostaje samo
  `LocalBusiness` — nieprawdziwy podtyp jest gorszy niż jego brak.
- **Graf.** `sites/seo_graph.py` buduje jeden `@graph` z tych samych wartości co
  head: `WebSite` (`<origin>/#website`), firma (`<origin>/#organization` — ten sam
  węzeł, którego używa karta katalogu), `WebPage` (`<adres kanoniczny>#webpage`,
  `inLanguage`), `BreadcrumbList`, a dla wpisu `BlogPosting` z autorem (bez podpisu:
  firma), datami z `article` i firmą jako wydawcą; strona z blokiem FAQ jest też
  `FAQPage`. Ładunek strony publicznej niesie go w `structured_data`.
- **Druk tylko przez `JsonLd`.** Komponent `#components/json-ld` drukuje graf przez
  `serializeJsonLd` z `#lib/seo`, która zapisuje `<`, `>`, `&`, U+2028 i U+2029 jako
  sekwencje ucieczki; test przeszukuje źródła frontendu i nie dopuszcza innego
  `application/ld+json`. Strony marketingowe i karta katalogu używają tego samego,
  a strona główna platformy dostała własny węzeł `Organization`.
- **Poza tym etapem:** `translationOfWork` na wersjach AI (z TL19b), ceny, podgląd
  SEO dla panelu i asystenta (TL18b).

