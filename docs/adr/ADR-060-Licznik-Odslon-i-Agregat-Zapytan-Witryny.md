# ADR-060 — licznik odsłon i agregat zapytań witryny

**Status:** Accepted — faza K0a planu memex `scr-narzedzie-marketingowe-koncepcja-i-plan`
(kolejność E0 → E1 z K0a przyjęta przez właściciela 24.09, wykonanie zlecone
26.09). Odbiór wymaga co najmniej czterech tygodni działania na wskazanej stronie.
**Data:** 2026-09-26

## Kontekst

SeoContentRank mierzy skutek zmian treści (faza E1: CTR z Search Console), a faza
K0b ma oceniać zmiany wezwań do działania po konwersjach. SaaS Core nie miał
dotąd własnej liczby odsłon, więc oba pomiary nie miały po naszej stronie nic do
porównania.

Plan wybrał najtańszą warstwę pomiaru: **bez skryptu w przeglądarce**. Liczba
odsłon po stronie serwera, bez adresu IP i identyfikatorów, plus zdarzenia, które
serwer i tak zapisuje. Nic nie jest odczytywane z urządzenia odwiedzającego, więc
nie ma o co pytać w banerze zgód. Plan zastrzega potwierdzenie prawne; Condictor
wdrożył swój licznik przed opinią (decyzja właściciela 3 z 24.09).

Stan zastany, który przesądza kształt rozwiązania:

- renderer publiczny (Next.js, `site-renderer`) renderuje każdą stronę dynamicznie
  i woła backend `/api/v1/public/site/` z hostem odwiedzającego. `cache()` łączy
  wywołania layoutu, metadanych i strony w jedno, o ile pytają tak samo;
- strony klientów nie używają nawigacji klienckiej Next, więc każda odsłona jest
  osobnym żądaniem dokumentu;
- zapytanie z formularza (`SiteInquiry`) już zapisuje publikację, ścieżkę
  kanoniczną i pozycję bloku formularza.

## Decyzja

1. **Czym jest odsłona.** Żądanie GET dokumentu opublikowanej strony (podstrony,
   wpisu, indeksu kolekcji albo archiwum tagu), które zwróciło treść. Nie liczymy:
   HEAD, prefetchu i prerenderu (`Sec-Purpose`, `Purpose`), żądań innych niż
   dokument (`Sec-Fetch-Dest`), żądań bez user agenta i z user agentem narzędzia
   (roboty wyszukiwarek, nasz `SEOSiteAuditBot`, podglądy linków, monitory,
   testy wydajności, przeglądarki bezgłowe, skrypty), przekierowań, 404 ani
   podglądów w panelu. Przeglądarka bez nagłówków fetch metadata jest liczona —
   inaczej gubilibyśmy prawdziwych czytelników.
2. **Kto decyduje.** Renderer, bo tylko on widzi żądanie odwiedzającego. Proxy
   przenosi metodę nagłówkiem `x-saas-core-site-method` (jak ścieżkę), strona
   ocenia żądanie (`countsAsPageView` w `modules/shared/sites/page-view.ts`) i
   przekazuje backendowi wyłącznie werdykt: `x-saas-core-count-view: 1`. User
   agent i adres IP nie trafiają ani do backendu, ani do bazy.
3. **Jedno wywołanie, jedna odsłona.** Layout, metadane i strona budują ścieżkę tą
   samą funkcją (`publicSitePath`, zdekodowane segmenty, bez końcowego ukośnika)
   i przekazują ten sam werdykt, więc `cache()` łączy je w jedno wywołanie
   backendu. Przy okazji layout przestaje pytać o ścieżkę w postaci
   zakodowanej, dla której nie znajdował stron z polskimi znakami w adresie.
4. **Magazyn.** Tabela `sites_pageviewday`: organizacja, witryna, dzień UTC,
   ścieżka kanoniczna, rodzaj (`page`, `entry`, `collection`), `publication_id`,
   liczba. Jeden wiersz na dzień, adres i publikację; zapis to jedno
   `INSERT … ON CONFLICT DO UPDATE views = views + 1`, więc równoczesne odsłony
   się nie gubią. Zapis idzie pod `SET LOCAL` tenanta, którego nazwał hostname;
   tabela ma wymuszone RLS i strażnika, który nie przyjmie witryny innej
   organizacji. Błąd licznika jest logowany i nie odbiera odwiedzającemu strony.
   Przełącznik `SITES_PAGE_VIEW_COUNTER_ENABLED` (domyślnie włączony) wyłącza
   liczenie bez wydania.
   - Klucz zawiera publikację, bo zmiana staje się widoczna od publikacji, która
     ją niesie; okna przed i po zmianie wynikają wtedy z danych, nie z dat.
   - Dzień w UTC, jak licznik Condictora i dzienne dane, z którymi porównujemy.
   - Dla indeksu kolekcji i archiwum tagu `publication_id` to identyfikator
     kolekcji — te strony są projekcją, nie mają własnej publikacji.
5. **Odczyt.** `GET /api/v1/sites/{site_id}/metrics/?since=…&until=…` (od 1 do 92
   dni) zwraca `page_views` (dzień, ścieżka, rodzaj, publikacja, liczba),
   `inquiries` (dzień, ścieżka, publikacja, pozycja bloku, liczba) i
   `counter_enabled`. Zapytania są liczone, nigdy czytane: odpowiedź nie niesie
   żadnych danych osoby, która je wysłała.
   - Osoba: uprawnienie `site.content.edit` (odczyt) i funkcja `sites.enabled`.
   - Klucz API: nowy zakres `content:metrics`. To jedyny zakres, który
     middleware przyjmuje na tej trasie, i nie otwiera żadnej innej — klucz
     wydany do treści nie dowiaduje się, jak witrynie idzie, a klucz do liczb nie
     czyta treści. Do tego grant na całą witrynę (dowolny tryb, także
     `suggest_only`); grant jednej kolekcji nie wystarcza, bo liczby dotyczą
     całej witryny.
6. **Czego świadomie nie robimy.** Skryptu w przeglądarce, ciasteczek,
   identyfikatorów sesji, unikalnych użytkowników, ścieżek wewnątrz wizyty,
   źródeł ruchu i wykresów w panelu. Heatmapy i zachowanie za zgodą to faza K2,
   a widok w panelu — osobna decyzja.

## Konsekwencje

- Liczba odsłon to nie liczba osób: odświeżenie strony liczy się ponownie.
  Prerender, który przeglądarka potem pokazała, nie jest policzony (zaniżenie),
  a robot podszywający się pod przeglądarkę jest (zawyżenie).
- Każdy może zawyżyć licznik, otwierając stronę wiele razy — jak w każdej
  analityce po stronie serwera. Nagłówek werdyktu nie jest zabezpieczeniem, tylko
  sposobem, by roboty i prefetch nie trafiały do liczby.
- Nie przetwarzamy danych osobowych i nie sięgamy do urządzenia odwiedzającego,
  więc licznik nie wymaga zgody. Potwierdzenie prawne zostaje otwarte, jak w
  planie; do tego czasu przełącznik pozwala przestać liczyć bez wydania.
- Tabela rośnie z liczbą dni, odwiedzanych adresów i publikacji. Retencji na
  razie nie ma; wraca przy pierwszym kliencie z dużym ruchem.
- Usunięcie organizacji (ADR-042) obejmuje tabelę samo, przez klucz obcy do
  `Organization`.
- Liczymy tylko strony renderowane przez SaaS Core. Witryna z własnym frontendem
  (Condictor) ma własny licznik o tej samej definicji odsłony.

Odbiór (z planu): na wskazanej stronie licznik i agregat działają co najmniej
cztery tygodnie, a liczby jednego dnia zgadzają się z ręczną kontrolą.
