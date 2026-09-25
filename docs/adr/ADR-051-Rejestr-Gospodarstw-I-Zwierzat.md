# ADR-051: Rejestr gospodarstw i zwierząt z kopiami firm i synchronizacją

Status: proponowana, 2026-09-19. Model zaakceptował właściciel (karty firm +
rejestr rolnika + synchronizacja); szczegóły przyjmujemy z planem wdrożenia.

## Kontekst

HoofCare potrzebuje gospodarstw i inwentarza, a kolejne aplikacje rolnicze będą
potrzebować tych samych danych rolnika. Decyzje właściciela z 19.09:

- właścicielem gospodarstwa i inwentarza jest rolnik;
- firma usługowa może wprowadzić gospodarstwo i sztuki sama, zanim rolnik
  założy konto;
- po utracie dostępu firma zachowuje kopię swojej pracy;
- gospodarstwo identyfikuje numer siedziby stada, NIP jest opcjonalny;
- przejęcie przez rolnika odbywa się kodem aktywacji od firmy, a bez kodu przez
  obsługę;
- po połączeniu firma zmienia dane od razu, a rolnik widzi, kto i kiedy dodał
  lub zmienił wpis;
- historia zdrowia idzie za zwierzęciem przy sprzedaży;
- przygotowujemy wiele gatunków, startujemy z bydłem.

Każda tabela tenantowa należy dziś ściśle do jednej organizacji (RLS,
ADR-039/041). Moduł wertykalny nie może importować innego wertykału, więc dane
wspólne dla kilku aplikacji rolniczych muszą leżeć w warstwie `shared`.

## Decyzja

1. **Moduł `shared.farms` w Saas-Core** z rejestrem gospodarstw i zwierząt.
   Składają go tylko profile produktów rolniczych. HoofCare dokłada korekcję na
   nim.
2. **Dwie warstwy danych, obie w zwykłych tenantach:**
   - **karta gospodarstwa firmy.** Gospodarstwo i sztuki w organizacji firmy.
     Każda firma ma własną kartę, a firmy nie widzą się nawzajem. Pola prywatne
     firmy (notatki, osoba kontaktowa, cennik) zostają zawsze tylko u niej;
   - **rejestr rolnika.** Gospodarstwa i sztuki w organizacji typu
     „gospodarstwo” (ADR-050). Źródło prawdy po połączeniu.
3. **Identyfikatory:** gospodarstwo to numer siedziby stada (unikalny wśród
   rejestrów rolników) plus opcjonalny NIP. Zwierzę to gatunek i numer
   identyfikacyjny (unikalny wśród rejestrów: zwierzę ma w danej chwili jednego
   właściciela). Kopie firm mogą się powtarzać.
4. **Gatunki** to katalog w kontrakcie modułu: klucz, format numeru dla kraju,
   katalog zmian dla modułów branżowych i flaga aktywności. Aktywne jest tylko
   bydło. Nowy gatunek to wpis w katalogu, nie migracja modelu.
5. **Połączenie.** Firma generuje dla swojej karty jednorazowy kod aktywacji z
   terminem ważności. Rolnik zakłada konto z kodem albo podaje go później. Powstaje
   wtedy rejestr z danych karty, a karta zostaje z nim połączona. Sztuki
   dopasowujemy po gatunku i numerze, a różnice rolnik zatwierdza na jednym
   ekranie. System wskazuje rolnikowi karty innych firm z tym samym numerem
   siedziby stada i łączy je po jego zgodzie. Bez kodu połączenie zakłada
   obsługa platformy (akcja operatora z audytem).
6. **Udział.** Połączenie niesie zakres (odczyt, zapis stada, publikacja wpisów
   zdrowotnych), datę i podstawę. Rolnik widzi, kto ma dostęp, i może go
   cofnąć. Każda organizacja widzi tylko swoją stronę udziału.
7. **Synchronizacja.**
   - Zmiana w rejestrze trafia przez outbox do kart połączonych firm.
   - Zmiana od firmy z zakresem zapisu trafia do rejestru od razu, w tej samej
     operacji, z autorem, datą i organizacją. Rolnik widzi to w historii
     zwierzęcia.
   - Zapis w cudzym tenancie idzie wyłącznie przez nazwane drzwi synchronizacji.
     Mają listę dozwolonych operacji, audyt i test, tak jak `PRE_TENANT_DB`.
   - Cofnięcie udziału zatrzymuje synchronizację, a karta firmy zostaje z
     ostatnim stanem.
8. **Wpisy zdrowotne należą do autora, a właściciel dostaje kopię.**
   - Moduł branżowy (np. korekcja w HoofCare) zapisuje wpis w organizacji firmy.
   - Przy udziale z publikacją kopia wpisu trafia do rejestru jako „wpis
     zdrowotny zwierzęcia”: rodzaj, data, autor, streszczenie i dane rodzaju.
   - Firma zachowuje swoje wpisy po cofnięciu udziału.
9. **Sprzedaż i przemieszczenie** to ruch zwierzęcia między rejestrami.
   Zwierzę przechodzi z historią wpisów zdrowotnych, a poprzedni właściciel
   zachowuje wpisy z okresu, gdy był właścicielem.
10. **Dostęp innych aplikacji przez API.** Inna aplikacja to osobne wdrożenie z
    własną bazą. Dane rolnika dostaje przez wersjonowane API rejestru i
    webhooki, za zgodą rolnika: zakres, termin i możliwość cofnięcia, wzorem
    zgód SeoContentRank (ADR-035). Wspólne logowanie rolnika w wielu
    aplikacjach i ewentualne wydzielenie rejestru do osobnej usługi rozstrzygamy
    przy drugiej aplikacji rolniczej.

## Konsekwencje

- Reżim RLS się nie zmienia: każdy wiersz ma jednego właściciela.
- Pojawia się nowy rodzaj drzwi (synchronizacja międzytenantowa). Jej izolację
  trzeba udowodnić na działającym stacku, bo baza testowa omija RLS.
- Dane między rejestrem a kartami są spójne po chwili, nie natychmiast. Zapis
  firmy do rejestru jest natychmiastowy, a rozsyłka do innych firm jest
  asynchroniczna.
- Obecne `Farm` i `Animal` z `vertical.hoofcare` przechodzą do `shared.farms`
  jako karty firm (dane deweloperskie przenosimy migracją).
- Tryb offline korektora (dokumentacja RACICE 2.2) może oprzeć się na tej samej
  lokalnej kopii.

## Wdrożenie etapu 2 (2026-09-19)

- `shared.farms` w Saas-Core: `Farm` (nazwa unikalna w organizacji, numer
  siedziby stada znormalizowany i unikalny w organizacji, gdy podany, NIP 10
  cyfr), `Animal` (gatunek z katalogu `species.py`, numer znormalizowany i
  sprawdzany wzorcem gatunku, unikalny w gospodarstwie). Wymuszone RLS i
  strażnik relacji zwierzę→gospodarstwo tej samej organizacji. Uprawnienia
  `farms.read`/`farms.manage` (role globalne przez `roleGrants` i migrację),
  cecha planu `farms.enabled` publikowana migracją modułu. API `/api/v1/farms/`
  i ekrany „Gospodarstwa” w panelu. `api.py`: `FARM_MODEL`, `farm_for_tenant`.
- Po przeglądzie (`95acd54`): numer siedziby stada przechowywany bez
  separatorów (`PL012345678001`), bo jedno stado wpisywano w kilku zapisach;
  duplikaty rozstrzyga constraint bazy; `animal_count` liczy baza.
- Profil wzorcowy `agro` (Business + rejestr) jest profilem głównym Saas-Core
  w `product.json`: testy obejmują rejestr. Obrazy (`images`) nadal tylko
  `business` i `core-only`. Typecheck i kontrakt obejmują cały katalog
  modułów w każdym repozytorium, więc także produkty bez rejestru.
- HoofCare przeniósł swoje `Farm`/`Animal` do rejestru (HC-ADR-001).

## Uzupełnienie 2026-09-25: karencja na wpisie kartoteki

- Wpis kartoteki (`AnimalHealthEntry`) ma `withdrawal_milk_until` i
  `withdrawal_meat_until`: do kiedy mleka i mięsa od zwierzęcia nie wolno
  sprzedać. Zwierzę jest „w karencji”, dopóki któryś wpis trwa — liczone z
  wpisów przy liście zwierząt, nie flaga, którą ktoś musiałby zdejmować.
- Wertykał pisze taki wpis w rejestrze rolnika (`publish_health_entry`) i na
  własnej karcie zwierzęcia (`record_own_health_entry`, cofany przez
  `drop_own_health_entry`); cofnięty po publikacji wpis zdejmuje z rejestru
  `unpublish_health_entry` (ta sama bramka udziału co publikacja). Karta firmy
  nie pokazuje drugi raz kopii z rejestru (ten sam autor, źródło i
  identyfikator). Odznaka „w karencji” na karcie firmy liczy wpisy firmy; wpisy
  innych autorów w rejestrze rolnika widać w historii karty, nie w odznace.
- Decyzja właściciela z 25.09 (faza 9 planu magazynu, 3a): hodowca i firma
  widzą „w karencji do …” na liście zwierząt i na karcie.

## Alternatywy odrzucone

- **Jeden wspólny rekord gospodarstwa z dostępem przez udział w RLS.** Wymagałby
  nowego reżimu polityk („własne albo udostępnione”) w rdzeniu. Nie dawałby też
  firmie kopii po cofnięciu dostępu bez osobnego mechanizmu.
- **Przeglądalna lista wszystkich gospodarstw w systemie.** Firma widziałaby
  klientów konkurencji, co jest nie do przyjęcia konkurencyjnie i w świetle
  RODO. Dopasowanie odbywa się dopiero przy rolniku, po numerze siedziby stada i
  za jego zgodą.
- **Automatyczne połączenie po samym numerze siedziby stada.** Numer nie jest
  tajny, więc ktoś obcy mógłby przejąć cudze stado. Wymagamy kodu od firmy albo
  obsługi.

## Relacje

ADR-050 (typ „gospodarstwo”), ADR-039/041 (reżimy RLS), ADR-035 (wzorzec zgód),
ADR-049 (moduł wspólny w rdzeniu, produkt dokłada branżę).
