# Abonamenty i aktywacja istniejących kont — 2026-09-21

Stan odczytano z działających baz i publicznych API trzech aplikacji na VPS.
Właściciel zatwierdził przeniesienie istniejących planów na wersje z wizytówką,
bez zmiany cen, limitów oraz terminów abonamentu i okresu próbnego.

## Oferta firmowa wspólnego rdzenia

Saas-Core, MedPlano i firmy korekcyjne w HoofCare mają te same trzy plany.
Ceny są miesięczne, netto, za organizację. Panel nazywa plan `starter`
„Witryna”, podczas gdy katalog API nadal zwraca nazwę „Starter”.

| Zakres | Profil | Witryna / Starter | Pro |
| --- | --- | --- | --- |
| Cena netto / miesiąc | 99 zł | 149 zł | 299 zł |
| Okres próbny nowego abonamentu | 14 dni | 3 dni | 3 dni |
| Witryny | 1 | 1 | 3 |
| Lokalizacje | 1 | 1 | 5 |
| Osoby w zespole | 2 | 5 | 25 |
| Miejsce na pliki | 1 GiB | 5 GiB | 50 GiB |
| E-maile / miesiąc | 500 | 2 000 | 20 000 |
| Wizyty / miesiąc | 250 | 1 000 | 10 000 |
| Kredyty / miesiąc | 50 | 200 | 1 000 |
| Możliwość podpięcia własnej domeny | nie | nie | tak |

Wszystkie trzy plany udostępniają edytor i publikację stron, szablony i dekoracje,
media, rezerwacje, powiadomienia oraz wizytówkę firmy i możliwość jej publikacji
w katalogu. Działania wymagają odpowiedniej roli w organizacji. Włączenie
uprawnienia nie publikuje wizytówki automatycznie. Profil i Witryna mają dziś
ten sam zestaw cech; różnią się limitami i długością próby. Pro zwiększa limity
i dodaje własną domenę. Zakup domeny nie jest częścią tej cechy.

- **Saas-Core:** ogólny produkt dla firmy, z powyższym zestawem wspólnych funkcji.
- **MedPlano:** ten sam rdzeń pod marką dla gabinetów. Obecny pilot obejmuje
  stronę i rezerwacje. Moduł medyczny jest szkieletem; nie ma obecnie dokumentacji
  medycznej, diagnoz ani recept.
- **HoofCare, firma korekcyjna:** powyższy rdzeń oraz rejestr gospodarstw
  i zwierząt, planowanie i realizacja wizyt korekcyjnych, praca w terenie,
  historia i raporty oraz magazyn materiałów. Te moduły są dostępne we
  wszystkich trzech planach firmowych, z odpowiednimi uprawnieniami ról.

## HoofCare — gospodarstwa

To oddzielny typ organizacji i oddzielna oferta, a nie tańszy plan firmy korekcyjnej.

| Zakres | Gospodarstwo | Gospodarstwo Plus |
| --- | --- | --- |
| Cena netto / miesiąc | 0 zł | 39 zł |
| Czas bez opłat | bezterminowo | 14 dni próby |
| Osoby w zespole | 2 | 5 |
| Lokalizacje | 1 | 3 |
| Miejsce na pliki | 1 GiB | 5 GiB |
| E-maile / miesiąc | 100 | 1 000 |
| Wizyty / miesiąc | 50 | 500 |
| Kredyty / miesiąc | 0 | 200 |

Zakres gospodarstwa obejmuje rejestr stada i kartoteki zwierząt, historię
zdrowotną, współpracę z firmą korekcyjną i dostęp do powiązanych wizyt oraz
wyników, a także rezerwacje, pliki i powiadomienia. Plus zwiększa limity.
Gospodarstwo nie dostaje edytora witryn, publicznej wizytówki w katalogu,
magazynu firmy ani firmowego modułu korekcji.

Surowy katalog cech planów gospodarstw zawiera również `inventory.enabled`
i `profiles.enabled`. Nie oznacza to dostępności tych modułów: profil typu
`farm` ich nie składa, a backend odrzuca ich trasy. Przy ocenie oferty trzeba
uwzględniać równocześnie typ organizacji, plan i rolę użytkownika.

## Płatności i ograniczenia obecnej oferty

Wszystkie trzy wdrożenia używają `BILLING_PROVIDER=simulated`. Cennik i limity
działają w aplikacji, ale nie oznacza to faktycznego pobierania pieniędzy przez
Stripe. W tej operacji nie uruchamiano rzeczywistych płatności.

Kredyty są pulą rozliczeniową dla obsługiwanych operacji, a nie potwierdzeniem
dostępności Asystenta AI. Asystent edytora pozostaje późniejszą fazą. Opis
Gospodarstwo Plus wspomina AI, lecz sam wpis katalogowy nie dowodzi aktywnej
funkcji AI dla gospodarstw. Limit e-maili również nie potwierdza dostarczenia
wiadomości przez zewnętrzny SMTP; ta kontrola pozostaje osobna.

## Wykonana aktualizacja

- Saas-Core: jeden Starter, wersja planu **3 → 4**.
- HoofCare: dwa plany Profil, snapshoty **6 → 7**; powiązane abonamenty nadal
  wskazywały wersję **5**, więc wyrównano także ich mapowania do wersji **7**.
  Wersje 5, 6 i 7 mają identyczne ceny, limity i warunki czasowe.
- HoofCare: jedno Gospodarstwo bezpłatne, wersja **2 → 3**.
- MedPlano: brak istniejących organizacji i abonamentów do przeniesienia.

Łącznie zmieniono **cztery snapshoty uprawnień i trzy powiązania abonamentów**.
Każdy snapshot otrzymał `profiles.enabled`; gospodarstwa nadal ogranicza bramka
typu organizacji. Zachowano ceny, wszystkie limity, stany, okresy rozliczeniowe,
terminy prób i wygaśnięcia oraz pozostałe pola abonamentów. Nie zmieniano
niemutowalnych wersji planów. Każda aktualizowana organizacja ma jeden wpis audytu
`billing.reconciled`, z identyfikatorem operacji `20260921-plan-upgrade`.

Jedno starsze gospodarstwo ma historycznie przypisany firmowy plan Profil.
Zachowano jego plan i cenę; nie przenoszono go na inną ofertę. Platformowy
workspace HoofCare z uprawnieniami nadanymi administracyjnie oraz dwa konta
bez skonfigurowanego planu pozostały bez zmian.

Operacja była transakcyjna w każdej bazie i poprzedzona próbą z rollbackiem
oraz świeżymi kopiami PostgreSQL w formacie custom. Weryfikacja ponownego
uruchomienia potwierdziła bieżące wersje bez kolejnych zmian. Bieżące kopie
sprawdzono przez `pg_restore --list` i SHA-256; nie należy mylić tego z pełnym
odtworzeniem, wykonanym wcześniej dla osobnego wydania kontenerów.

Odbiór wykonano pod rzeczywistą rolą `saas_core_app`, bez superuser i BYPASSRLS.
Bez kontekstu organizacji odczyt organizacji zwraca zero wierszy. Dla właścicieli
dwóch istniejących firm decyzja cechy zezwala na dostęp, rola ma `profiles.manage`,
a odczyt listy profili przez widok API i bramkę modułów zwraca 200. Dla dwóch
zaktualizowanych gospodarstw ta sama bramka zwraca 404 `module_not_available`,
a rola nie ma `profiles.manage`. To kontrola widoku w procesie aplikacji,
nie nowe logowanie przeglądarkowe. Audyt zawiera dokładnie cztery wpisy operacji,
a każdy snapshot zwiększył wersję dokładnie raz. Trzy pominięte organizacje
HoofCare zachowały poprzedni stan.

Przeszło **19 kontroli publicznych po HTTPS**: cztery katalogi planów są
identyczne z odczytem sprzed zmiany, a strona główna, cennik, frontend health,
API liveness i API readiness odpowiadają 200 w każdym produkcie.

Prywatne kopie, zabezpieczony skrypt operacyjny, odczyty przed/po, kontrola
uprawnień i publicznych API: `/root/Saas-Core/.runtime/releases/20260921-plan-upgrade/`.
Nie są częścią repozytorium. Zmiana dotyczy danych, nie wymaga przebudowy
ani restartu kontenerów. Kod tego wydania pozostaje opisany w
[raporcie wdrożenia](2026-09-21-site-studio-update.md).

## Źródła katalogu

- [Saas-Core, oferta firmowa](https://saas.goldenstar.cloud/api/v1/billing/plans/?organization_type=business)
- [MedPlano, oferta firmowa](https://medplano.goldenstar.cloud/api/v1/billing/plans/?organization_type=business)
- [HoofCare, firmy korekcyjne](https://hoofcare.goldenstar.cloud/api/v1/billing/plans/?organization_type=trimming_company)
- [HoofCare, gospodarstwa](https://hoofcare.goldenstar.cloud/api/v1/billing/plans/?organization_type=farm)

Datowany odczyt zapisano lokalnie. Publiczny katalog może zmienić się przy
następnej publikacji planu; istniejące abonamenty zachowują własne wersje.
