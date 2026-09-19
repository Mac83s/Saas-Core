# ADR-050: Typy organizacji definiowane przez produkt

Status: proponowana, 2026-09-19. Kierunek zaakceptował właściciel; szczegóły
przyjmujemy razem z planem wdrożenia (Plan/Wdrozenie/15).

## Kontekst

W jednej aplikacji działają organizacje o różnych rolach biznesowych. W HoofCare
jest firma korekcyjna i gospodarstwo rolnika. Kolejne aplikacje przyniosą swoje
pary: firma usługowa i jej klient, lecznica i gospodarstwo. Każdy typ potrzebuje
innego zestawu funkcji, ról, usług w kalendarzu rezerwacji i planów.

Rdzeń zna dziś tylko techniczny `workspace_kind` (personal, business, platform).
Ma też pięć globalnych ról systemowych z uprawnieniami nadawanymi migracjami i
jedną listę planów na deployment (`billing.planKeys`, dokładnie trzy).
Użytkownik po rejestracji nie ma organizacji. Zakłada ją w dialogu w „Firma i
zespół”, bez wyboru, kim jest.

Produkt nie może zmieniać plików rdzenia (ADR-049), więc typy muszą być
deklaracją produktu, a nie kodem w rdzeniu.

## Decyzja

1. **Katalog typów organizacji deklaruje produkt** w sekcji `organizationTypes`
   swojego `deployments/<profil>/deployment.json`, walidowanej schematem
   `packages/contracts/deployment.schema.json`. Sekcja jest częścią profilu, więc
   trafia do obrazu bez nowych plików. Generator artefaktu rozwiązuje ją raz
   (także domyślny typ `business` dla profilu bez sekcji), a backend i frontend
   czytają ten sam wynik z artefaktu i profilu publicznego.
2. **Organizacja ma typ** (`Organization.organization_type`). Typ nadaje się przy
   zakładaniu organizacji i nie zmienia się samowolnie. Istniejące organizacje
   dostają typ domyślny profilu.
3. **Typ decyduje o:**
   - **modułach dostępnych organizacji.** Moduły typu to podzbiór modułów
     profilu. API modułu spoza typu odpowiada 404 dla tej organizacji, a menu go
     nie pokazuje. Frontend nie jest granicą bezpieczeństwa;
   - **rolach.** Typ niesie szablony ról systemowych z uprawnieniami. Role
     systemowe są per typ, niezmienialne przez organizację. Organizacja może
     tworzyć role własne z uprawnień swoich modułów (model `Role` ma już zakres
     organizacji);
   - **planach.** Typ wybiera z planów profilu od jednego do trzech, np. plany
     firmy albo pakiet rolnika z 6 miesiącami okresu próbnego. Checkout,
     przegląd abonamentu i publiczny cennik pokazują tylko plany typu. Profil
     nadal ma dokładnie trzy plany; regułę poluzujemy, gdy dojdzie pakiet
     rolnika (etap 3 planu 15);
   - **szablonach usług rezerwacji**, np. korekcja stada dla firmy, wynajem
     kombajnu i koszenie dla gospodarstwa. Organizacja zakłada z nich własne
     usługi. Organizacja każdego typu z modułem rezerwacji może oferować usługi
     innym;
   - **pierwszym uruchomieniu.** Konto bez organizacji po zalogowaniu trafia
     na ekran „kim jesteś” z typami `selfSignup` i zakłada organizację, zanim
     zobaczy panel. Sam formularz rejestracji się nie zmienia: nie ujawnia, czy
     konto istnieje, więc nie może zakładać organizacji.
4. **Uprawnienia ról systemowych pochodzą z katalogu, a nie z migracji.**
   Idempotentna komenda uruchamiana po `migrate` (`apply_organization_types`)
   zakłada i aktualizuje role systemowe typów. Każdą zmianę zapisuje w
   dzienniku audytu i podbija wersję roli. Moduł nadal deklaruje swoje
   uprawnienia w deskryptorze, a katalog może użyć tylko uprawnień modułów, które
   typ składa (walidacja w `deployment-check`). `roleGrants` z deskryptora
   (ADR-049) zostaje dla typu domyślnego i znika, gdy produkt przejdzie na
   katalog.
5. **Sesja i API bieżącej organizacji zwracają typ i jego publiczną część**:
   moduły, etykiety i szablony usług. Z nich frontend buduje menu. Pozycje
   produktu w slocie frontendu mogą wskazać typy, dla których się pokazują.

## Konsekwencje

- Pierwsze logowanie zakłada organizację. Znika stan „użytkownik bez firmy”
  z przeglądu panelu z 18.09.
- Role systemowe przestają być globalne: klucz roli jest unikalny w obrębie
  typu. Migracja przepina istniejące członkostwa na role typu domyślnego bez
  zmiany uprawnień.
- Uprawnienia zawężone do obiektu (gospodarstwo, wizyta; dokumentacja RACICE
  4.4) nie są częścią tej decyzji. Zbudujemy je na tym fundamencie, gdy będą
  potrzebne.
- Zmiana katalogu typów to zmiana wdrożenia. Komenda synchronizacji jest częścią
  każdego release'u, a jej brak oznacza role niezgodne z katalogiem, więc
  pilnuje tego system check przy starcie.
- Kształt katalogu jest punktem rozszerzenia z ADR-049. Jego zmiana jest
  zmianą łamiącą dla produktów.

## Alternatywy odrzucone

- **Typ jako osobny deployment** (np. osobna aplikacja dla rolników). Rolnik i
  firma pracują na wspólnych danych w jednej aplikacji. Rozdzielenie wymusiłoby
  synchronizację między bazami już dla jednego produktu.
- **Uprawnienia typów w migracjach produktu.** Każda zmiana szablonu roli
  wymagałaby migracji w repozytorium produktu. Deklaracja z synchronizacją jest
  czytelniejsza i nie dotyka plików rdzenia.
- **Role tylko organizacyjne (kopie szablonu w każdej organizacji).** Nowe
  uprawnienie modułu trzeba by rozsyłać do tysięcy kopii. Role systemowe per
  typ plus role własne łączą oba potrzebne przypadki.

## Relacje

ADR-049 (punkty rozszerzeń produktu), ADR-026 i ADR-032 (plany i okres próbny),
ADR-051 (rejestr gospodarstw korzysta z typów).
