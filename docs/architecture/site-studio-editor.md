# Site Studio — interakcje edytora

Status: przyrost fazy 3, 2026-09-21. Nie jest to odbiór wdrożenia.

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

## Obszary pracy

Od 1200 px lewy panel, canvas i inspektor tworzą trzy kolumny z osobnym
przewijaniem. Lewy panel ma 300 px, prawy 340 px; od 1800 px odpowiednio
320 i 360 px. Pasek zapisu pozostaje nad nimi. Lewa nawigacja przełącza
strukturę sekcji, bibliotekę, całe strony i wygląd witryny. Metadane i media
otwierają się w osobnych oknach, z błędami widocznymi wewnątrz nich.
Poniżej 1200 px dolna nawigacja pokazuje jeden wybrany panel. Wybór sekcji
przenosi focus na canvas, a błąd walidacji otwiera inspektor i błędne pole.
Preferencja ograniczenia animacji wyłącza płynne przewijanie.

Boczna biblioteka używa tego samego katalogu, kart, filtrów i podglądu co
okno „Dodaj sekcję poniżej”. Pola filtrów mają lokalne ID, więc okno może być
otwarte obok biblioteki bez kolizji etykiet. Dodanie wariantu lub pustego
bloku w bocznym panelu wstawia go za wybraną sekcją, wybiera nowy blok i
pozostaje jednym krokiem undo. W formularzach dodawanie działa nadal na końcu.
Nie ma osobnego modelu treści dla bocznego panelu.

## Tekst w miejscu

`registry.render(block, key, editor?, imageRenderer?)` przyjmuje opcjonalny adapter kodu panelu.
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
nagłówki i zamknięte FAQ zachowują semantykę publikacji. CTA hero i rezerwacji
mają wspólną klasę wyglądu `site-section__action` na linku publikacji i span
edytora. Snapshot zmienił się wyłącznie o tę klasę w istniejących CTA. Renderer nie importuje pakietu UI.

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

## Prywatne obrazy

Panel pobiera `GET /api/v1/media/{asset_id}/preview/` przez wygenerowany klient
same-origin. Usługa sprawdza `media.read`, `storage.enabled` i aktywnego tenanta
przed odczytem assetu. Udostępnia tylko gotowy, nieusunięty wariant preview WebP
pod kanonicznym kluczem tego assetu, z limitem odczytu 10 MiB. Brak pliku,
obca organizacja i niegotowy asset dają 404; awaria magazynu daje 503.
Odpowiedzi widoku mają `Cache-Control: private, no-store` i `nosniff`.

Adapter `imageRenderer` jest kodem panelu, niezależnym od edytowania tekstu.
Canvas oraz zapisany podgląd używają tymczasowych blob URL; nie zapisują ich
w danych strony ani historii. Zmiana assetu i odmontowanie anulują pobranie,
usuwają URL i ignorują spóźnione odpowiedzi. Błąd pobrania/dekodowania ma
lokalizowany stan i przycisk ponowienia. Panel jest kluczowany ID organizacji,
więc refresh po jej przełączeniu usuwa poprzedni draft i podglądy.
Publiczne publikacje nadal używają istniejącego renderera i `/media/{id}`.

Dowody: media API 35/35 (w tym kolejność SET LOCAL przed SELECT assetu,
zero odczytów domenowych dla odmów i macierz RLS na roli bez bypass),
renderer 23/23, testy komponentu PL/EN z anulowaniem i cleanupem 4/4.
Chromium dekoduje WebP w canvas i zapisanym podglądzie przy 1440/390 px;
fixture ma syntetyczne API, więc nie dowodzi działania sesji na wdrożeniu.
Artefakty lokalne: `.runtime/site-studio/private-media/`.

## Otwarty odbiór

Nadal wymagane: odbiór
zalogowanego panelu i publikacji po hostname oraz synchronizacja produktów.
Testy Chromium używają rzeczywistych komponentów i syntetycznego API;
nie zastępują tych bramek.


## Pełnoekranowy edytor i wspólny wygląd witryny

`PageStudio` otwiera edytor w pełnoekranowym Dialog. Biblioteka, canvas i
inspektor korzystają z dostępnej szerokości, a na telefonie/tablecie dolny
pasek przenosi focus do narzędzi. Zamknięcie z niezapisanym draftem lub wyglądem
wymaga świadomego odrzucenia; podczas zapisu wyjście jest zablokowane.

Wygląd jest odrębny od listy bloków. `SiteAppearanceRevision` przechowuje
niemutowalne rewizje zgodne z `site-appearance.v1.schema.json`: tokeny, font,
szerokość, przyciski, header, footer i sposób nawigacji na mniejszych ekranach.
PUT blokuje wiersz witryny, sprawdza expected_version i idempotency key.
Uprawnienia/entitlement/kontekst tenanta są sprawdzane przed odczytem domeny;
nowa tabela wymusza RLS i zakazuje UPDATE oraz DELETE poza erasure.

Publikacja kopiuje wygląd do snapshotu razem z design_tokens. Publiczne strony
nie odczytują roboczych rewizji. Brak appearance w starej publikacji zachowuje
wcześniejsze zachowanie. Header i footer są stałymi układami renderera, bez
swobodnych slotów, HTML, CSS ani zewnętrznych URL fontów. Fonty są kontrolowanymi
stosami systemowymi, a trzy presety stylu tylko ustawiają edytowalne wartości.

Podgląd menu canvas odczytuje konfigurację i raport lokalizacji, używa domyślnego
języka witryny i pomija brakujące tytuły/ścieżki. Podgląd viewportu steruje
menu niezależnie od szerokości okna panelu. Na publicznej stronie CSS wybiera
telefon (<768 px), tablet (768–1023 px) lub desktop. Dolny pasek pokazuje do
czterech głównych linków; natywne details udostępnia pełne menu z dziećmi.
Wcześniejsze bloki stopki zachowujemy; wybór globalnej stopki nie usuwa treści
użytkownika. Przy przenoszeniu starej strony trzeba usunąć jej blok stopki,
jeżeli ma go zastąpić wariant wspólny.


## Katalog i przykładowe zdjęcia — 2026-09-20

Katalog v2 ma po 20 bazowych układów hero, oferty/listy cech i FAQ oraz
12 dodatków branżowych: po dwa hero i dwie oferty dla medycyny, rolnictwa
i elektroniki. Łącznie 72 recepty sekcji. To nie zamyka katalogu pozostałych
typów bloków. Osiem bieżących recept całych stron ma treść PL/EN i przypięte
wersje sekcji. Historyczne schematy oraz recepty pozostają dostępne.

Cztery lokalne, wygenerowane zdjęcia demonstracyjne mają manifest SHA-256
i opis pochodzenia w contracts/page-templates/assets. Miniatury używają
statycznych plików; tymczasowe identyfikatory podglądu nie trafiają do draftu.
POST /api/v1/sites/template-media/{photo_id}/materialize/ przyjmuje wyłącznie
identyfikator z katalogu. CSRF, sites.enabled/site.content.edit oraz zwykłe
media.manage/storage.enabled chronią import. Zdjęcie przechodzi normalne
limity, skanowanie i tworzenie wariantów; idempotency key jest ograniczony
do organizacji i aktora. Błąd nie wstawia sekcji, ponowienie zachowuje klucz.

Import całej strony wiąże mediaBindings z rzeczywistymi MediaAsset po
materializacji, a następnie zapisuje jedną wersję draftu. Konflikt wersji
kompensuje nowo utworzone media. Zdjęcia można zmieniać zwykłym polem obrazu;
publikacja udostępnia tylko media uwzględnione w jej snapshotcie. Locale importu
jest opcjonalne (domyślnie PL), dzięki czemu stare żądania zachowują działanie.

Biblioteka pokazuje początkowo 12 wariantów i przycisk kolejnych; filtr branży
umieszcza dopasowane dodatki przed bazowymi. Opisy, reguły kompozycji i wskazówki
objętości treści przygotowują późniejszy etap AI, który pozostaje odrębny.


## Typografia i Google Fonts — 2026-09-21

Kontrakt appearance v2 rozszerza wybór o Inter, Manrope, DM Sans, Nunito,
Lora i Playfair Display. Wersja v1 jest niezmieniona i nadal walidowana;
zmiana fontu w panelu zapisuje v2. Presety modern/editorial/compact wybierają
odpowiednio Manrope/Lora/Inter. Pozostałe ustawienia zachowują dotychczasowe
znaczenie; nie ma migracji danych ani automatycznej podmiany zapisanych fontów.

WOFF2 (Latin i Latin Extended, wagi 400–700) oraz oryginalne licencje OFL
są w packages/ui/src/styles/fonts. Źródła i SHA-256 zawiera sources.json.
CSS jest wspólny dla edytora i publicznego renderera; fonty są serwowane lokalnie,
bez zależności od sieci Google przy buildzie czy wyświetleniu strony.

Skala nagłówków i tekstu używa szerokości kontenera strony, nie viewportu
panelu. Telefon na dużym monitorze ma więc te same rozmiary tekstu co wąskie
okno. Ujednolicono interlinię, łamanie nagłówków, odstępy FAQ i zabezpieczenie
szerokości list. Podgląd krótkiej sekcji nie wymusza pełnej wysokości okna.

Przegląd katalogu: osiem recept pełnych podstron (Wizytówka, Strona specjalisty,
Strona firmy, Oferta usługowa, Gabinet i opieka, Usługi dla gospodarstwa,
Serwis elektroniki, Pracownia i realizacje). Każda ma cztery sekcje: hero,
feature_list, FAQ i kontakt, z PL/EN oraz zdjęciami. Wybór w zakładce „Całe
strony” jest dostępny również dla istniejącego draftu. Zastąpienie treści
wymaga potwierdzenia i tworzy nową wersję przez istniejący endpoint importu.
Anulowanie zachowuje niezapisane treści; sukces rozpoczyna nową lokalną
historię. To nie są zestawy wielostronicowych witryn ani ukończona biblioteka
wszystkich kategorii. Otwarte: bogatsze kompozycje i pozostałe kategorie.
Osobno pozostaje zdiagnozowany 403 automatyzacji blueprintów ze zdjęciami.


## Odbiór przebudowy edytora — 2026-09-21

Biblioteka ma wyszukiwanie nazw, opisów i zastosowań, liczbę wyników,
filtry kategorii i branży oraz większe miniatury. Kliknięcie miniatury otwiera
osobny podgląd sekcji z wariantem telefonu. Zamknięcie przywraca focus;
import zdjęcia blokuje zmianę zakładki i zamknięcie podglądu. Błąd importu
pozostawia treść strony i pozwala ponowić tę samą operację.

Strona ustala własne jasne kolory niezależnie od motywu panelu. CTA zachowują
wypełnienie, obrys lub zaokrąglenie także podczas edycji etykiety; Enter nie
uruchamia nawigacji. Nakładki wyboru sekcji nie zmieniają odstępów renderera.
Widok formularzy ma jeden przewijany obszar obejmujący również wygląd.

Dowody: PageEditor 33/33, PageStudio 5/5, biblioteka 8/8 (axe PL/EN),
renderer i katalog 24/24; TypeScript, ESLint i Prettier. Chromium:
3440/1440/1280/768/390 px, oba motywy, pełne przyciski zapisu, brak przepełnienia
pasków, mobilny focus, podgląd biblioteki i potwierdzenie podmiany strony.
Osobno 162 porównania stylów CTA publikacji i edycji przy 360/1440 px.
Artefakty: `.runtime/site-studio/redesign-browser/` i `cta-browser/`.
To rzeczywiste komponenty z syntetycznym API, bez dowodu wdrożenia.


## Kontakt i zapytania — 2026-09-21

Katalog v3 zachowuje wcześniejsze 72 sekcje i dodaje 16: kontakt bez formularza
(6), kontakt z formularzem (4), social media i linki (6). Każdy wariant ma
lokalizowane dane startowe, opis zastosowania i kontrakt kompozycji. Kontakt v1
nadal renderuje dotychczasowy markup; v2 dopuszcza dodatkowe układy, godziny,
zdjęcie i akcję. Linki mają walidowane protokoły i ikony z kodu.

Formularz jest stałym blokiem, edytowalnym treściowo i wizualnie. Podgląd ma
wyłączone pola bez zagnieżdżonego formularza. Renderer publikacji wstrzykuje
adapter ze snapshotem i pozycją sekcji; kod pakietu nie wysyła żądań sieciowych.
Kontrakt zapisu, izolacji, skrzynki i powiadomienia opisuje
[site-inquiries.md](site-inquiries.md).

Dowody tego przyrostu: 63 testy renderera, 96 komponentów/nawigacji/edytora,
50 nowych testów API i 49 testów zgodności. Chromium obejmuje 16 nowych układów
oraz aktywny formularz/skrzynkę przy 360/768/1440 px w PL/EN. Weryfikacja była
izolowana; synchronizacja produktów i odbiór runtime pozostają otwarte.

## Dekoracje wspólne i separatory — 2026-09-21

Każdy blok ma „Dekoracje sekcji” w inspektorze: osiem presetów i ręczne
ustawienia tła, ramki, ornamentów i ruchu. Zmiany korzystają z istniejącego
stanu formularza, historii i zapisu. Biblioteka v4 dodaje osiem separatorów.
Szczegóły kontraktu, pauzy, wersjonowania oraz ograniczeń AI i recept całych
stron: [site-section-decoration.md](site-section-decoration.md).

## Bogata treść i wygląd strony — 2026-09-23

Pole `richText` otwiera w inspektorze panel pisania (`rich-text-field.tsx`):
wstawianie akapitów, śródtytułów, list, cytatów, uwag i ilustracji, spis
śródtytułów, przesuwanie i usuwanie węzłów, wklejanie z Google Docs/Worda
normalizowane do dozwolonych węzłów. Formatowanie w polu tekstowym zapisuje
się jako przebiegi JSON; pola z buforem zapisują zmianę po pauzie lub opuszczeniu
pola, co daje jeden krok cofania. Płótno edytuje w miejscu każdy przebieg,
śródtytuł i podpis pod dokładną ścieżką danych. Formularz strony jest w
`FormProvider`, a normalizacja zapisu nie przycina spacji wewnątrz przebiegów.

„Szerokość i tło sekcji” to druga koperta obok dekoracji. „Wygląd tej strony”
(zakładka Wygląd, pod wyglądem witryny) należy do formularza draftu: cofanie,
stan niezapisany i ochrona wyjścia obejmują go automatycznie, a zapis wysyła
`page_presentation` tylko po zmianie. Kontrakt i zasady: [site-rich-content.md](site-rich-content.md).
