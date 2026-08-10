# SaaS Core - plan bazowej platformy

**Wersja:** 0.1  
**Status:** plan bazowy do dalszego rozwijania  
**Data:** 2026-08-09

## 1. Cel dokumentacji

Zbudowanie wspólnego fundamentu dla wielu produktów SaaS, między innymi:

- MedPlano - strony i usługi dla lekarzy oraz prywatnych praktyk;
- produktu dla branży beauty;
- kolejnych systemów usługowych wykorzystujących strony klientów, rezerwacje, abonamenty i własne domeny.

Produkty korzystają ze wspólnego kodu, ale są wdrażane oddzielnie. Każdy produkt może dodawać własne moduły, konfigurację, wygląd i reguły biznesowe.

## 2. Przyjęte decyzje

1. Jedno repozytorium i wspólny SaaS Core.
2. Osobne deploymenty, bazy danych, sekrety i konfiguracje dla każdej branży lub produktu.
3. Architektura modularnego monolitu, bez mikroserwisów na pierwszym etapie.
4. Backend w Django oraz Django REST Framework.
5. Frontend, panel klienta i strony publiczne w Next.js oraz TypeScript.
6. Klienci nie otrzymują dostępu do Django Admin.
7. Django Admin jest wyłącznie wewnętrznym narzędziem technicznym operatora platformy.
8. Użytkownik jest osobą. Firma lub konto prywatne jest organizacją/workspace'em.
9. Abonament jest przypisany do organizacji, a nie bezpośrednio do użytkownika.
10. Role użytkowników są oddzielone od funkcji i limitów planu abonamentowego.
11. Wielojęzyczność obejmuje interfejs, treści stron, wiadomości i dokumenty prawne.
12. System jest uruchamiany w kontenerach Docker na własnym VPS-ie.
13. Stripe obsługuje płatności i cykl subskrypcji.
14. Aplikacja posiada własny katalog planów, funkcji, limitów i uprawnień.
15. Okres próbny jest konfigurowalny; pierwsza propozycja biznesowa to 3 dni.
16. Klient otrzymuje subdomenę platformy i może podpiąć własną domenę.
17. Caddy odpowiada za reverse proxy i automatyczne certyfikaty TLS.
18. Poczta transakcyjna korzysta domyślnie z zewnętrznego dostawcy.
19. Własny serwer skrzynek pocztowych, jeśli zostanie wdrożony, działa na osobnym VPS-ie i IP.

## 3. Model produktów

```text
Wspólne repozytorium
  SaaS Core
    Identity
    Organizations
    Permissions
    Billing
    Entitlements
    Sites
    Domains
    Content
    Notifications
    Audit
    Integrations

  Moduły wspólne
    Booking

  Moduły branżowe
    Medical
    Beauty

Osobne deploymenty
  MedPlano = Core + Booking + Medical
  Beauty   = Core + Booking + Beauty
```

## 4. Dokumenty w zestawie

| Plik | Zakres |
| --- | --- |
| `SaaS-Core-00-README.md` | cele, decyzje i mapa dokumentacji |
| `SaaS-Core-01-Architektura.md` | architektura aplikacji, repozytorium i rozszerzenia |
| `SaaS-Core-02-Moduly.md` | moduły stałe, wspólne i branżowe |
| `SaaS-Core-03-Model-Danych-i-Uprawnienia.md` | model encji, multi-tenancy, role i abonamenty |
| `SaaS-Core-04-Infrastruktura-i-Bezpieczenstwo.md` | Docker, VPS, domeny, poczta, backup i bezpieczeństwo |
| `SaaS-Core-05-Roadmapa.md` | kolejność wdrożenia, rezultaty i kryteria odbioru |
| `SaaS-Core-06-Rejestr-Decyzji.md` | zaakceptowane i otwarte decyzje architektoniczne |
| `Wdrozenie/00-MAPA-WDROZENIA.md` | wykonawcza mapa 12 fal, zależności, bramki i kamienie milowe |
| `Wdrozenie/01-W0-...` — `12-W11-...` | szczegółowe plany poszczególnych fal wdrożenia |

## 5. Słownik

| Pojęcie | Znaczenie |
| --- | --- |
| Product/Deployment | osobna działająca platforma, np. MedPlano |
| Vertical | moduł dopasowujący Core do branży |
| Organization/Workspace | konto klienta prywatnego, firmy lub gabinetu |
| User | osoba logująca się do panelu |
| Membership | członkostwo użytkownika w organizacji wraz z rolą |
| Customer/Contact | pacjent lub klient końcowy organizacji |
| Site | wizytówka lub strona internetowa organizacji |
| Entitlement | dostęp organizacji do funkcji wynikający z planu lub nadpisania |
| Quota | liczbowy limit funkcji, np. liczba pracowników lub wiadomości |

## 6. Zasady dalszego projektowania

- Zmiany wspólne trafiają do SaaS Core.
- Zmiany dotyczące całej klasy produktów mogą trafić do modułu wspólnego.
- Dane i reguły charakterystyczne dla branży trafiają do verticala.
- Nie kopiujemy modułów między produktami.
- Nie dodajemy warunków `if product == ...` w logice domenowej Core.
- Każda nowa funkcja musi określić: moduł, uprawnienia, entitlement, zdarzenia, dane i retencję.
- Każdy etap kończy się działającym, możliwym do wdrożenia przyrostem systemu.

## 7. Najbliższy następny krok

Rozpisać szczegółowo pierwszy obszar implementacyjny:

1. strukturę repozytorium;
2. modele `User`, `Organization`, `Membership` i `BillingProfile`;
3. mechanizm aktywowania modułów dla deploymentu;
4. kontrakt uwierzytelniania pomiędzy Next.js i Django;
5. bazowy `docker-compose.yml` dla developmentu i stagingu.
