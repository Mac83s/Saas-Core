# ADR-031 — panel klienta i wizualny Site Studio

**Status:** Accepted
**Data:** 2026-08-13
**Właściciel:** zespół SaaS Core
**Zastępuje:** regułę nazwy subdomeny platformowej z ADR-028; pozostałe reguły
DNS, TLS i routingu ADR-028 pozostają obowiązujące

## Kontekst

Fale W3–W9 dowiodły działania modułów, ale ich panel eksponuje język
implementacji (`site`, `slug`, entitlement, snapshot) i formularze techniczne.
Nie jest to właściwy interfejs dla właściciela małej firmy. Użytkownik ma
wykonywać zadania produktowe: uruchomić obecność online, ułożyć strukturę
strony, przyjmować rezerwacje i komunikować się z klientami.

ADR-027 nadal obowiązuje: strona składa się z kontrolowanych, wersjonowanych
bloków, a renderer nie wykonuje HTML, CSS ani JavaScriptu dostarczonego przez
tenanta. Zmieniamy doświadczenie edycji, nie granicę bezpieczeństwa.

## Decyzja

### Architektura informacji panelu

- panel klienta używa responsywnego dashboard shell z lewym menu, paskiem
  kontekstu organizacji i mobilnym odpowiednikiem;
- główna nawigacja opisuje cele użytkownika: Start, Strona, Kalendarz,
  Wiadomości, Asystent AI, Zespół, Integracje oraz Plan i płatności;
- diagnostyka entitlementów, kolejki i narzędzia operatorskie nie są częścią
  głównego menu klienta. Pozostają w osobnej, uprawnionej przestrzeni supportu;
- UI stosuje progressive disclosure: ekran pokazuje następny potrzebny krok,
  a ustawienia techniczne są dostępne dopiero w kontekście zadania;
- frontend filtruje nawigację według deploymentu, roli i entitlementu, lecz API
  pozostaje jedyną granicą bezpieczeństwa.

### Utworzenie strony i adres platformowy

- organizacja bez aktywnego entitlementu `sites.enabled` widzi porównanie
  planów i CTA do Checkout zamiast formularza tworzenia strony;
- kreator pierwszej strony pyta o nazwę widoczną dla klientów i preferowany
  adres `<subdomena>.<platformDomain>`. Termin `slug` nie jest używany w UI;
- nazwa jest claimem unikalnym dla pary `(platformDomain, normalized_label)`, a
  wynikowy hostname jest unikalny globalnie. Etykieta jest normalizowana do
  bezpiecznego DNS; lista nazw systemowych i podobnych do marki jest
  zastrzeżona, a próby są rate-limitowane;
- jeżeli użytkownik pominie wybór lub nazwa jest zajęta, backend zachowuje
  zgodny fallback `<slug>-<stabilny-skrót-id>`. Zmiana czytelnej nazwy po
  publikacji wymaga jawnego workflow z przekierowaniem i audytem. Poprzedni
  hostname pozostaje aliasem przez okres polityki przekierowań; siedmiodniowa
  kwarantanna zaczyna się dopiero po jego faktycznym zwolnieniu;
- subdomena platformy jest pełnoprawnym adresem strony i nie wymaga własnej
  domeny. Własna domena jest opcjonalnym ulepszeniem planowym;
- kreator prowadzi kolejno przez plan, szablon, podstawowe dane, podgląd i
  publikację. Każdy krok można bezpiecznie wznowić.

### Szablony i katalog bloków

- `PageTemplate` jest wersjonowaną, niemutowalną receptą: metadane PL/EN,
  kategoria, miniatura, wymagane entitlementy oraz lista kontrolowanych bloków
  z przykładową treścią i referencjami do zatwierdzonych mediów;
- zastosowanie szablonu kopiuje receptę do nowej `PageVersion`. Dalsza edycja
  strony nie zmienia szablonu, a aktualizacja szablonu nie nadpisuje klienta;
- media recepty są idempotentnie materializowane jako tenantowe `MediaAsset`
  organizacji i podlegają jej quota storage. Fizyczny blob może być
  deduplikowany, lecz rekord, autoryzacja i referencja publikacji pozostają
  tenantowe;
- najniższy plan może używać jednej zablokowanej rodziny wizualnej. Wyższe plany
  odblokowują kolejne szablony, warianty i tokeny personalizacji;
- katalog bloków jest filtrowalny według kategorii, np. Start, O mnie, Oferta,
  Zaufanie, Cennik, FAQ, Kontakt, Rezerwacja i Stopka. Vertical może dopisać
  bloki przez manifest zgodny z ADR-021 i ADR-027;
- użytkownik nie buduje dowolnych siatek, kolumn ani modułów wykonujących kod.

### Studio struktury i edytor wizualny

- Site Studio ma osobne tryby: **Struktura**, **Edytuj**, **Wygląd**,
  **Podgląd** i **Publikuj**;
- Struktura pokazuje synchronizowane drzewo podstron i mapę nawigacji. Drag and
  drop zmienia kolejność i rodzica pozycji nawigacji, nie stabilny URL strony;
  każda operacja ma równoważną akcję klawiaturową. Zmiana URL jest osobnym,
  audytowanym workflow z historią przekierowań;
- nawigacja otrzymuje własny wersjonowany draft. Publikacja umieszcza ją w tym
  samym atomowym snapshotcie co strony, tłumaczenia i motyw;
- Edytuj używa trzech obszarów: biblioteki sekcji, responsywnego canvasu oraz
  inspektora zaznaczonego bloku. Kliknięcie treści otwiera edycję w kontekście;
- przeciąganie zmienia wyłącznie kolejność kontrolowanych bloków. Zapis nadal
  tworzy niemutowalną wersję, stosuje optimistic lock i umożliwia rollback;
- undo/redo działa na lokalnym dzienniku komend, a zapis do API pozostaje
  jawny i idempotentny;
- widoki desktop/tablet/mobile, focus, reduced motion, PL/EN i WCAG 2.2 AA są
  częścią bramki odbioru.
- prymitywy shell, drag and drop i formularzy należą do publicznego API
  `@saas-core/ui`; formularze zachowują kontrakt RHF + Zod + Problem Details z
  ADR-020, a Storybook, axe i Playwright obejmują klawiaturę oraz mobile.

## Konsekwencje

- istniejący model draftów i publikacji pozostaje źródłem prawdy;
- wymagane są nowe kontrakty szablonów i nawigacji oraz większy katalog bloków;
- formularze techniczne mogą pozostać czasowo jako narzędzia wewnętrzne, ale
  nie mogą być domyślną ścieżką klienta;
- import szablonu i każda komenda edytora muszą przechodzić przez te same
  permission, entitlement, audit i idempotency co ręczne API.

## Relacje

- rozszerza ADR-020 i ADR-027;
- nie zezwala na dowolny page builder odrzucony przez ADR-027;
- wykonanie opisuje fala W9.5.
