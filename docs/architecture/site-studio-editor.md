# Site Studio — interakcje edytora

Status: przyrost fazy 3, 2026-09-19. Nie jest to odbiór wdrożenia.

## Stan i zapis

React Hook Form pozostaje źródłem edytowanego draftu: canvas, inspektor,
formularze i lokalne undo/redo używają tych samych bloków i referencji mediów.
Zapis nadal przechodzi przez JSON Schema/Zod, API z optimistic lockiem oraz
idempotency key. Historia lokalna nie cofa publikacji.

`ReorderList` z publicznego API `@saas-core/ui` przenosi istniejący element
po jego lokalnym ID. Dopiero drop wykonuje `useFieldArray.move`; przeciąganie
nie tworzy serii wpisów historii. Uchwyt przyjmuje ArrowUp/ArrowDown,
odtwarza focus i ogłasza pozycję przez aria-live. Na ekranie dotykowym można
użyć przycisków góra/dół inspektora; natywny drag dotykowy nie jest bramką
potwierdzoną przez ten przyrost. Drop nie importuje tekstu, plików ani bloków
z innego edytora. Anulowany gest, zmieniona lista i blokada podczas zapisu
unieważniają źródło operacji.

„Dodaj sekcję poniżej” używa tej samej biblioteki i wstawia receptę za
zaznaczonym blokiem. Wstawienie i jego cofnięcie zachowują sąsiednie treści;
wybrana sekcja otwiera się w inspektorze.

## Tekst w miejscu

`registry.render(block, key, editor?)` przyjmuje opcjonalny adapter kodu panelu.
Adapter nie jest częścią JSON ani snapshotu. Komponent przekazuje dokładną
ścieżkę danych i wartość do `editor.text(path, value)`. Panel dopuszcza wyłącznie
pola text/textarea z manifestu; indeks listy jest częścią ścieżki. Identyczne
teksty nie są używane do identyfikowania pola.

`InlineText` używa natywnych input/textarea, nie HTML ani contentEditable.
Kliknięcie otwiera bufor lokalny; blur/Enter zatwierdza, Escape anuluje.
Textarea zachowuje Enter dla nowego wiersza; Ctrl/Cmd+Enter zatwierdza.
Enter podczas kompozycji IME nie zatwierdza. Jedno zatwierdzenie daje jeden
krok historii. Niepoprawna sekcja wraca do inspektora, a zapis API nadal
odrzuca dane niespełniające schematu.

W trybie edycji linki są neutralnymi elementami, żeby kontrolki tekstu nie
były osadzone w aktywnych linkach. Nagłówki zachowują wygląd, ale mają rolę
presentation, ponieważ nie definiują struktury nagłówków panelu. FAQ jest
otwarte, aby odpowiedź dało się edytować. Bez adaptera publiczne linki,
nagłówki i zamknięte FAQ zachowują wcześniejszy markup; test snapshotu nie
został zmieniony. Renderer nie importuje pakietu UI.

## Prototyp porównawczy Puck

Próba użyła `@puckeditor/core` 0.23.0 zainstalowanego wyłącznie w `/tmp`, bez
zmiany lockfile projektu. Adapter opakował blok w `props.block` i dodał
lokalne `props.id`. Wynik:

- 15 recept przechodzi konwersję do modelu Puck i z powrotem bez utraty danych;
- prawdziwy `Render` Puck wywołuje kanoniczny registry i zachowuje markup
  sekcji, dodając jeden zewnętrzny div;
- zmieniona kolejność i tekst po konwersji przechodzą kanoniczną walidację;
- źródłowe recepty nie są modyfikowane.

To próba adaptera i renderera, nie pełny test interakcji ani benchmark Puck.
Kod próby i raport lokalnie: `.runtime/site-studio/puck-prototype/`.
Dokumentacja opisuje własny model danych, historię, callback onChange oraz
inicjalizacyjne data, którego zmiana po montażu nie przeładowuje edytora:
[Puck — komponent edytora](https://puckeditor.com/docs/api-reference/components/puck),
[Puck — model danych](https://puckeditor.com/docs/api-reference/data-model/data).

Dla tego przyrostu wybieramy interakcje na istniejącym RHF i prymitywach UI.
Puck jest technicznie możliwy, lecz jego przyjęcie wymagałoby przeniesienia
lub synchronizacji pól, lokalnej historii i resetów po odpowiedzi serwera.
Obecny zakres to liniowa lista kontrolowanych sekcji, bez zagnieżdżonych
slotów. Nie utrzymujemy dwóch stanów edytora tylko dla zmiany ich kolejności.
Decyzję można wrócić do porównania, gdy zakres wyjdzie poza tę listę.

## Otwarty odbiór

Nadal wymagane: prywatny podgląd mediów (API nie udostępnia jeszcze downloadu
assetów dla panelu), docelowy układ biblioteka/canvas/inspektor, odbiór
zalogowanego panelu i publikacji po hostname oraz synchronizacja produktów.
Testy Chromium używają rzeczywistych komponentów i syntetycznego API;
nie zastępują tych bramek.
