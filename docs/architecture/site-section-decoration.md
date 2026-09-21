# Dekoracje sekcji i separatory

Status: implementacja w Saas-Core, 2026-09-21. Wdrożenie stosu i aktualizacja
repozytoriów produktów pozostają osobnymi bramkami. Rozszerza kontrolowany
model ADR-027/031 bez wykonywania kodu z danych.

## Jeden wygląd niezależny od treści

Każdy blok może mieć opcjonalne pole `decoration` obok `block_type`,
`schema_version` i `data`. Wspólny kontrakt
`packages/contracts/site-blocks/section-decoration.v1.schema.json` zawiera
wyłącznie zamknięte listy wartości: tło, ramkę, ornament, rozmieszczenie,
intensywność i ruch. Nie przyjmuje CSS, HTML, ścieżek SVG, URL ani skryptu.
Kolor pochodzi z palety witryny. Grafiki i animacje są własnością renderera.

Oddzielenie ustawień od `data` pozwala obsłużyć także istniejące bloki bez
zmieniania historycznych schematów ich treści. Zmiana układu, migracja treści,
duplikacja, cofanie i zapis zachowują dekoracje. „Usuń dekoracje” usuwa tylko
ten zestaw ustawień. Brak pola lub `null` oznacza brak dodatkowej dekoracji;
normalizacja nie dodaje klucza do starych bloków, więc zachowuje ich hashe.

`PageBlock.decoration` jest nullable i objęte dotychczasową niemutowalnością
wersji oraz RLS. Migracja `sites/0031_pageblock_decoration` jest odwracalna.
Publikacja, rollback, wpisy kolekcji i zatwierdzone blueprinty zachowują pole.
Podgląd i publikacja odczytują odpowiednią wersję, a nie katalog presetów.
Brak schematu runtime wykrywa `sites.E006`; plik korzysta z istniejącego
`SITE_BLOCK_CONTRACTS_PATH` i kopii katalogu kontraktów do obrazu backendu.

## Biblioteka i edytor

Inspektor każdej sekcji zawiera rozwijane „Dekoracje sekcji”: osiem gotowych
stylów, ręczne ustawienia oraz reset. Preset kopiuje ustawienia i później nie
steruje zapisanym blokiem. Katalog `section-decoration-presets.v1.json` ma
opisy PL/EN oraz wskazówki zalecanego łączenia dla późniejszego asystenta.
Wskazówki nie są ograniczeniami dostępu ani listą jedynych zgodnych bloków.

Osobny `core.separator` ma osiem układów: odstęp, linia, podwójna linia,
kropki, fala, łuk, zygzak i akcent. Można zmieniać wysokość, szerokość i ton
z palety. Jest dekoracyjny (`aria-hidden`), bez własnej treści i nagłówka.
Katalog sekcji v4 zachowuje wszystkie 88 recept v3 i dodaje te osiem, czyli
łącznie 96. Osiem presetów dekoracji nie jest kolejnymi układami sekcji i nie
zalicza celu 20 wariantów każdej kategorii.

Osiem obecnych recept całych stron pozostaje bez zmian. Ich zamrożone schematy
v1–v3 nie dopuszczają jeszcze `decoration` w bloku recepty. Dodanie gotowej
recepty strony z dekoracjami wymaga nowej wersji schematu recepty oraz
podłączenia backendowego loadera. Użytkownik może już dekorować bloki strony
po wstawieniu dowolnej obecnej recepty.

## Ruch, czytelność i dostępność

Podglądy biblioteki, draftu i płótna edytora są statyczne. Na publikacji ruch
dotyczy tylko ozdobnika: powolne przesuwanie albo łagodne pulsowanie. Treść,
formularze i przyciski pozostają nieruchome i nad dekoracją. Warstwy graficzne
mają `pointer-events: none`; nie przechwytują kliknięć.

Każda animowana sekcja ma natywny checkbox pauzy z etykietą PL/EN, widocznym
focusem i obszarem 44 px. CSS obsługuje pauzę i wznowienie bez JavaScript.
`prefers-reduced-motion: reduce` wyłącza animację i ukrywa niepotrzebną
kontrolkę. Forced colors ukrywa ozdobniki. Dekoracja bez widocznego efektu
zwraca niezmieniony markup bloku, bez dodatkowego wrappera.

## Granica automatyzacji

Content Operations v1 pozostaje niezmienione. Zastąpienie treści zachowuje
istniejącą dekorację, podobnie jak zmiana kolejności. Brak pola w komendzie
nie oznacza resetu. Digest zatwierdzenia uwzględnia także wygląd.

Jawne ustawienie lub usunięcie dekoracji przez AI wymaga przyszłego kontraktu
Content Operations v2, walidacji i prezentacji zmiany do zatwierdzenia.
Obecna wersja odrzuca próby przemycenia dodatkowego pola w komendzie.
Katalog presetów stanowi przygotowanie dla AI, nie wdrożenie asystenta.

## Dowody i granica odbioru

Testy sprawdzają wspólną walidację, stare hashe, zapis/odczyt i publikację,
rollback, wpisy, zachowanie ustawień w content operations, review token,
niemutowalność SQL, błędny schemat oraz round-trip w edytorach strony i wpisu.
Testy katalogu obejmują zgodność wszystkich dawnych recept.

Izolowany Chromium sprawdza separatory i dekoracje przy 360/768/1440 px w PL/EN:
brak overflow, pauzę klawiaturą z wyłączonym JavaScript, reduced motion,
niezmienione tło wariantu band oraz axe z kontrastem. Inspektor sprawdzono w
12 widokach PL/EN, jasnym/ciemnym motywie, przy 344/768/1440 px. Artefakty:
`.runtime/site-studio/section-decorations/` i
`.runtime/site-studio/decoration-fields-browser/`.

To testy izolowane; nie zastępują migracji, publikacji przez Caddy ani odbioru
zalogowanego panelu we wszystkich produktach. Znane trzy błędy blueprintów
z `403 permission_denied` dla klucza `content:draft` i materiałów zdjęciowych
pozostają niezależne od dekoracji i nie zostały zmienione.
