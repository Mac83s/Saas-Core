# ADR-061 — rodzaj linku (`rel`) w blokach

**Status:** Accepted — faza L0 planu memex `scr-narzedzie-marketingowe-koncepcja-i-plan`;
zakres i reguły przyjęte przez właściciela 2026-09-26 (odpowiedzi 1a, 2a, 3a).
**Data:** 2026-09-26

## Kontekst

Wyszukiwarki czytają link jako polecenie strony docelowej, chyba że link mówi
inaczej: `rel="sponsored"` (płatny albo partnerski), `rel="ugc"` (treść od
użytkowników), `rel="nofollow"` (bez polecenia). Bloki SaaS Core nie miały na to
miejsca — renderer dodawał do linków wychodzących tylko `noreferrer`. Plan
narzędzia marketingowego potrzebuje tego pola, zanim powstanie kolejka linków
(L3), a właściciel przyjął reguły dla naszych własnych serwisów: linki z naszych
blogów i katalogu są redakcyjne, podpis „wykonanie” na stronach klientów ma
`nofollow`.

Schematy bloków są niezmienne, więc nowe pole to nowa wersja schematu.

## Decyzja

1. **Zakres (1a).** Pole dostają bloki, w których naprawdę trafiają się linki
   partnerskie i podpisy: `core.rich_text` v4 (przebieg z linkiem), `core.link_list`
   v2 i `core.footer` v2 (pozycje listy). Pozostałe bloki z linkami (hero, produkt,
   cytat, kontakt, rezerwacja) dostaną je, gdy pojawi się taka potrzeba.
2. **Kształt.** Opcjonalne `rel` z jedną wartością: `sponsored`, `ugc` albo
   `nofollow`. Brak pola to link redakcyjny — dokładnie to, co było dotąd, więc
   istniejące treści nie wymagają migracji, a migratory z poprzednich wersji
   kopiują dane bez zmian. W tekście `rel` wymaga `href`.
3. **Renderer.** `linkRel(href, rel)` łączy dotychczasowe `noreferrer` linku
   wychodzącego z wybranym rodzajem.
4. **Panel.** W oknie linku edytora tekstu wybór „Rodzaj linku” pojawia się dla
   adresów `https://`; na listach linków i w stopce to pole wyboru z pierwszą
   opcją „Redakcyjny”, która nic nie zapisuje. Edytor zapisuje tylko nasze trzy
   wartości — domyślnych atrybutów edytora ani `rel` z wklejonej strony nie
   przenosi.
5. **Automatyzacja (3a).** Link do innej strony wstawiony przez automatyzację
   dostaje `nofollow`, jeśli sam nie nazwał rodzaju. Link, który automatyzacja
   przepisuje z wersji roboczej, zachowuje wybór człowieka: redakcyjny zostaje
   redakcyjny, a `rel` ustawiony przez człowieka wraca, jeśli kopia automatu go
   zgubiła. Dzieje się to w planie zmiany (podgląd pokazuje wynik) i przy
   bezpośrednim zapisie szkicu strony albo wpisu. Linki do własnych domen
   witryny, ścieżki, kotwice, `mailto:` i `tel:` zostają bez zmian. Zapis
   człowieka nigdy nie jest poprawiany.

## Konsekwencje

- Katalog sekcji v7 zostaje przy tekście v3; szablony dochodzą do v4 przez
  migrator tożsamościowy przy pierwszej edycji. Test katalogu nazywa to wprost.
- Automatyzacja może linkować do innych stron tylko w granicach grantu (hosty
  z `allowed_link_hosts`) i nie „poleca” niczego w imieniu klienta bez jego
  wiedzy; klient może zmienić rodzaj linku w panelu.
- W blokach bez pola (np. przycisk hero) link automatyzacji do innej strony
  pozostaje bez `rel` — to granica zakresu 1a, nie reguła.
- Reguły dla naszych serwisów żyją w memeksie (decyzja
  `links-from-our-own-services-are-editorial-only-a`); podpisu „wykonanie” w
  rendererze dziś nie ma, więc pierwsza implementacja podpisu musi użyć
  `nofollow`.
