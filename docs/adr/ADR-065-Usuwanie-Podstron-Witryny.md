# ADR-065 — usuwanie podstron witryny: ukrycie zamiast kasowania, zdjęcie z publikacji od razu

**Status:** Accepted — decyzja właściciela 7 z 2026-09-30 (odpowiedzi 7.1–7.9 = a),
plan memex `saas-core-site-studio-pages-crud`.
**Data:** 2026-09-30

## Kontekst

Site Studio pozwalało dodać podstronę, ale nie usunąć — brak wyszedł przy
zakładaniu stron firm testowych (29.09). Wersje podstrony (`PageVersion`), jej
bloki (`PageBlock`) i publikacje (`Publication`) są historią append-only:
rollback serwuje stare snapshoty, audyt je czyta, a baza otwiera te tabele
wyłącznie przy usuwaniu całej organizacji (ADR-042). Skasowanie wiersza podstrony
zerwałoby tę historię albo wymagałoby otwarcia strażników.

Właściciel 30.09: usunięcie ma działać od razu dla odwiedzających, nie zostawiać
martwych adresów i dać się cofnąć; lista podstron ma wyglądać i działać jak
pozostałe listy panelu (ADR-054, ADR-057).

## Decyzja

1. **Ukrycie, nie kasowanie.** `Page` dostaje `deleted_at`, `deleted_by`,
   `deletion_idempotency_key` i `deleted_slugs` (migracja `sites 0039`,
   odwracalna). Usunięta podstrona znika z listy panelu, menu, limitu
   `pages.max`, change setów, inwentarza i każdej kolejnej publikacji; jej wersje,
   bloki i publikacje zostają. Unikalny klucz podstrony obowiązuje tylko wśród
   nieusuniętych (`sites_page_org_site_live_key_uq`).
2. **Adres wolny od razu.** Slug usuniętej podstrony zamienia się na nagrobek
   `<slug>-usunieta-<8 znaków id>` (nigdy publiczny), a dawne slugi zostają w
   `deleted_slugs` — nowa podstrona może wziąć adres usuniętej.
3. **Od razu poza stroną publiczną (7.1).** Jeśli podstrona jest w bieżącej
   publikacji, usunięcie tworzy nową publikację z **opublikowanego** snapshotu
   bez tej podstrony — nie ze szkiców, więc cudza niedokończona praca nie wychodzi
   razem z nią. Taka publikacja nie ma `source_publication`: to nie rollback, a
   historia publikacji nie pokazuje jej jako powrotu (odstępstwo od pierwszego
   szkicu planu, który zakładał `source_publication` = bieżąca). Zdarzenie
   `sites.site.published` i unieważnienie TLS idą jak przy zwykłej publikacji.
4. **301 zamiast martwego adresu (7.2).** Każdy język dostaje `SiteRedirect` ze
   starej ścieżki na podstronę wybraną w oknie usuwania — domyślnie stronę główną
   (`/`). Przekierowania, które prowadziły do usuwanej podstrony, są przepinane
   na nowy cel, więc łańcuch ma zawsze jeden skok. Przekierowania trafiają do
   snapshotu publikacji z pkt 3.
5. **Menu i linki (7.3).** Pozycja menu znika w nowej wersji nawigacji (dzieci
   przechodzą piętro wyżej). Treści innych podstron nie są zmieniane; okno
   usuwania pokazuje, które podstrony linkują do usuwanej
   (`GET pages/<id>/incoming-links/`), a przekierowanie z pkt 4 utrzymuje ich
   linki przy życiu.
6. **Strażnicy (7.4, 7.6, 7.7).** Nie da się usunąć strony głównej
   (`page_is_homepage`) ani ostatniej podstrony witryny (`page_is_last`).
   Usunięcie podstrony opublikowanej wymaga prawa publikacji (`site.publish`),
   nieopublikowanej — prawa edycji treści. Usuwa i przywraca tylko osoba
   (`assert_person_required`, ADR-035): automat — grant czy change set — nigdy.
   Oznaczenie podstrony jako głównej zamienia dotychczasową główną w zwykłą
   (`landing`), więc witryna ma jedną stronę główną.
7. **Przywrócenie (7.5).** Filtr „Usunięte” listy bez limitu czasu. Przywrócona
   podstrona wraca jako szkic — poza menu i poza stroną publiczną do następnej
   publikacji. Dawne adresy wracają, jeśli są wolne, a przekierowania z nich
   ustępują podstronie; zajęty adres zwraca `page_restore_slug_taken` i panel
   prosi o nowy. Zajęty klucz dostaje kolejny wolny sufiks.
8. **Rollback pomija usunięte.** Powrót do starszej publikacji kopiuje jej
   snapshot bez podstron usuniętych od tamtej pory, z przekierowaniami z pkt 4 —
   usunięta podstrona nie wraca na stronę tylnymi drzwiami.
9. **Audyt i idempotencja.** `sites.page.deleted` i `sites.page.restored` w
   historii organizacji; obie operacje wymagają `Idempotency-Key`, a usunięcie
   także `expected_version` (konflikt: `draft_version_conflict`).
10. **Panel (7.8, 7.9; ADR-054, ADR-057).** „Strona internetowa” to adresy w
    `PANEL_SECTIONS`, nie zakładki: Podstrony (`/panel/sites`), Menu, Blog,
    Publikacja, Adres i domeny, Integracje, a edytor podstrony ma własny adres
    `/panel/sites/pages/<id>` (`?preview=1` otwiera go z podglądem). Lista
    podstron to `DataTable` z kolumnami nazwa, adres (strona główna jako `/`),
    typ, stan (opublikowana / zmiany nieopublikowane / nieopublikowana), menu i
    ostatnia zmiana; akcje wiersza: Edytuj (zawsze widoczne), Podgląd, Otwórz na
    stronie, Ustaw jako główną, Zmień adres, Usuń — bez „Duplikuj”. Typ podstrony
    i polityka automatyzacji są w „Ustawieniach strony” edytora.

## Konsekwencje

- Każde zapytanie o podstrony „żywe” musi filtrować `deleted_at__isnull=True`;
  nowy kod czytający `Page` bez tego filtra pokaże usunięte. Lista i fakty
  (`page_listing_facts`) biorą adres z tłumaczenia w języku domyślnym, a dla
  usuniętej — z `deleted_slugs`.
- Usunięcie opublikowanej podstrony to publikacja: liczy się do historii
  publikacji i wysyła `sites.site.published` do jego odbiorców.
- Kasowanie na stałe pozostaje wyłącznie częścią usunięcia organizacji
  (ADR-042); pojedynczej podstrony nie da się wymazać.
- Produkty (HoofCare, MedPlano) dostają to przez `core:update`; migracja
  `sites 0039` idzie przez `memex ops`.
