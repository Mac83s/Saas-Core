# W6 — Sites, Content i Media

**Status:** blocked by W4 and ADR-017  
**Szacunek:** 2–3 tygodnie  
**Poprzednik:** W4  
**Rezultat:** wersjonowana, wielojęzyczna strona organizacji

## 1. Scenariusz demonstracyjny

Uprawniony członek organizacji tworzy stronę, dodaje kontrolowane bloki PL/EN,
przesyła obraz, podgląda draft, publikuje atomową wersję i przywraca poprzednią
publikację. Inna organizacja nie widzi draftu ani mediów.

## 2. Pakiety pracy

### W6.1 — model strony i treści

- wdrożyć `Site`, `Page`, `PageVersion`, `PageBlock` i `Publication`;
- rozdzielić draft od niezmiennego snapshotu publikacji;
- zapewnić stabilne slug, kolejność bloków i optimistic locking;
- wdrożyć kontrolowane typy bloków z `schema_version`;
- dodać migratory treści bloków i test zgodności wstecznej.

### W6.2 — tłumaczenia i SEO

- przechowywać tłumaczenia jako osobne rekordy;
- zdefiniować locale bazowe, fallback i kompletność publikacji;
- dodać title, description, canonical metadata i social preview;
- generować hreflang oraz właściwe adresy językowe;
- walidować unikalność slug w obrębie site i locale.

### W6.3 — motyw i renderer

- wdrożyć design tokens z walidowanym zestawem wartości;
- renderować tylko allowlistowane komponenty bez kodu klienta;
- oddzielić renderer publiczny od panelu edycji;
- zapewnić deterministyczny render snapshotu publikacji;
- przygotować rozszerzenie bloków przez manifest modułu/verticala.

### W6.4 — Media

- przesyłać pliki bezpośrednio lub przez signed upload zgodnie z ADR storage;
- walidować rozmiar, rozszerzenie, MIME i rzeczywisty format;
- generować losowe klucze obiektów i warianty obrazów;
- usuwać zbędne EXIF oraz blokować HTML/JS/SVG według polityki;
- skanować pliki i publikować dopiero po bezpiecznym wyniku;
- egzekwować quota storage oraz lifecycle usuwania.

### W6.5 — panel edycji i publikacja

- zbudować listę stron, edytor kontrolowanych bloków i preview;
- zastosować permissions i entitlementy do edycji/publikacji;
- wykrywać konflikt wersji i nie nadpisywać cudzej zmiany;
- publikować cały snapshot atomowo;
- rejestrować autora publikacji i umożliwić rollback.

## 3. Testy obowiązkowe

- odczyt i modyfikacja draftu innego tenanta;
- konflikt dwóch edytorów tego samego draftu;
- migracja starego `schema_version` bloku;
- publikacja z brakującym tłumaczeniem i zachowanie fallbacku;
- upload z fałszywym MIME, nadmiernym rozmiarem i złośliwą nazwą;
- rollback publikacji bez utraty nowszego draftu;
- renderer nie wykonuje danych dostarczonych jako JavaScript/HTML.

## 4. Bramka wyjścia

- [ ] draft, preview, publication i rollback są odrębnymi stanami;
- [ ] snapshot publikacji jest niezmienny i możliwy do odtworzenia;
- [ ] bloki są wersjonowane i mają testowane migratory;
- [ ] PL/EN ma poprawne URL, canonical i hreflang;
- [ ] upload przechodzi walidację, skan i limity organizacji;
- [ ] testy cross-tenant obejmują treści, publikacje i media;
- [ ] Site Renderer nie wykonuje dowolnego kodu klienta.

