# W10 — Vertical Medical i pilot MedPlano

**Status:** blocked by W5–W9.5 and privacy review
**Szacunek:** 2–3 tygodnie  
**Poprzednicy:** W5, W6, W7, W8, W9, W9.5
**Rezultat:** pierwszy gabinet przechodzi pełny onboarding MedPlano

## 1. Granica produktu

Pilot obejmuje marketing, publikację strony i rezerwacje. Nie obejmuje EDM,
diagnozy, dokumentacji klinicznej ani przekazywania danych pacjenta do modeli
AI. Każde rozszerzenie tej granicy wymaga osobnej analizy regulacyjnej i ADR-u.

## 2. Scenariusz demonstracyjny

Operator zakłada profil pilota, Owner kończy onboarding, konfiguruje lekarza,
usługi, grafik i stronę, aktywuje plan, podpina domenę oraz przyjmuje publiczną
rezerwację. Migracja z WordPressa ma kontrolę kompletności i rollback DNS.

## 3. Pakiety pracy

### W10.1 — model Medical

- wdrożyć `DoctorProfile`, specjalizacje i typy wizyt;
- rozszerzać `StaffMember` i `Appointment` osobnymi tabelami;
- przechowywać tylko dane niezbędne do marketingu i rezerwacji;
- dodać permissions, entitlementy, retencję i audit verticala;
- udowodnić brak zależności Core od Medical.

### W10.2 — konfiguracja deploymentu

- aktywować Core + Booking + Medical w profilu MedPlano;
- zdefiniować markę, locale, domeny systemowe, plan i bloki strony;
- dodać politykę komunikacji bez danych zdrowotnych;
- wymagać silniejszego 2FA dla operatorów i wybranych właścicieli;
- zweryfikować osobną bazę, sekrety i storage deploymentu.

### W10.3 — onboarding

- zbudować checklistę organizacji, profilu lekarza, usług i grafiku;
- tworzyć bezpieczny draft strony z kontrolowanych danych;
- pokazywać status planu, publikacji, domeny i gotowości rezerwacji;
- umożliwić przerwanie oraz bezpieczne wznowienie procesu;
- nie rozpoczynać triala przed momentem zatwierdzonym w decyzji produktowej.

### W10.4 — migracja pierwszego klienta

- wykonać inwentaryzację WordPressa bez automatycznego kopiowania śmieci;
- zmapować strony, media, SEO, przekierowania i dane kontaktowe;
- przygotować import idempotentny i raport pominiętych danych;
- przetestować staging/preview z klientem przed zmianą DNS;
- zaplanować okno, TTL, rollback i monitoring po przełączeniu.

### W10.5 — privacy i akceptacja pilota

- przygotować rejestr kategorii danych i podstaw przetwarzania;
- ustalić dostawców, DPA, lokalizacje danych i retencję;
- sprawdzić eksport, anonimizację i obsługę żądań osoby;
- przeprowadzić threat modeling ścieżki rezerwacji;
- uzyskać formalną akceptację zakresu przed produkcją.

## 4. Testy obowiązkowe

- Medical wyłączony: brak modeli aktywnych w profilu i elementów UI;
- cross-tenant profilu lekarza, usług i rezerwacji;
- wiadomości bez danych o specjalizacji/wizycie, gdy polityka tego wymaga;
- import uruchomiony ponownie nie duplikuje treści ani mediów;
- przekierowania SEO i rollback DNS;
- pełna ścieżka mobilna pacjenta oraz panel Ownera;
- eksport i anonimizacja danych testowego klienta.

## 5. Bramka wyjścia

- [ ] jeden gabinet kończy onboarding na stagingu bez ręcznej ingerencji w bazę;
- [ ] profil deploymentu nie wpływa na build profilu `core-only`;
- [ ] strona, domena, plan i rezerwacja działają end-to-end;
- [ ] import ma raport, kontrolę kompletności i rollback;
- [ ] zakres danych oraz dostawcy przeszli przegląd RODO;
- [ ] właściciel produktu i pilot zaakceptowali scenariusze odbioru;
- [ ] nie wprowadzono danych klinicznych ani funkcji diagnostycznych.
