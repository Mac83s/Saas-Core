# Katalog sekcji Site Studio

Status: pierwszy przekrój implementacji, 2026-09-19. Plan wykonawczy:
`memex: desk/plans/saas-core-site-studio-templates.md`.

## Kontrakt i zgodność

Katalog `packages/contracts/site-blocks/section-templates.v1.json` ma ścisły
JSON Schema. Każda recepta sekcji ma ID/wersję, typ i wersję bloku, układ,
rodzaj default/industry, tagi, opisy PL/EN, przeznaczenie, pozycję i sąsiedztwo,
wymagane możliwości, politykę pochodzenia faktów, zgodność podmian oraz seedy
PL/EN. Limity pól i list pozostają w kanonicznym schemacie wskazanego bloku;
katalog ich nie kopiuje. Wymagania są twarde, wskazówki kompozycyjne miękkie.

Układ zapisujemy jako allowlistowane `data.layout`: hero v4, feature_list v2,
faq v2. Brak pola oznacza klasyczny renderer; migratory są kopiami danych,
więc stare publikacje zachowują wygląd. Schematy poprzednich wersji pozostają
bez zmian. Backend waliduje te same pliki co TypeScript; katalog nie nadaje
uprawnień i nie uruchamia kodu z danych. Media nadal przechodzą zwykły
lifecycle. Nowy katalog znajduje się w istniejącym katalogu kontraktów bloków,
kopiowanym do obrazu; nie wymaga nowej ścieżki runtime.

Zmiana wariantu tego samego typu zmienia tylko układ. Wszystkie pola, zdjęcia
i elementy list są zachowane. Podmiana między typami jest odrzucana; przyszłe
mapowania nie mogą usuwać treści bez wyraźnego rozstrzygnięcia użytkownika.

Szablon `core.service_landing` zawiera zamrożone bloki i `sectionRefs` z
pozycją, ID i wersją źródłowej sekcji. Test kontraktowy porównuje materializację
z seedem. Publiczny renderer odczytuje dane publikacji i nie rozwiązuje
referencji do bieżącego katalogu. Schemat recepty v2 jest kompatybilnym
rozszerzeniem v1; stary schemat i trzy historyczne recepty nie są zmieniane.

Tagi branży mają stabilne ID (`medicine`, `agriculture`, `electronics`) oraz
etykiety PL/EN. Jedna recepta może należeć do kilku branż. Wybrana branża
zawęża warianty branżowe, ale pozostawia wszystkie domyślne. Tagi nie są
entitlementami. UI pierwszego przekroju używa wyłącznie sekcji shared.sites;
gdy pojawią się recepty wymagające innych modułów, kontekst katalogu musi
pochodzić z faktycznych capabilities, przed zaoferowaniem tych recept.

Od 2026-09-23 runtime czyta `section-templates.v6.json` (120 recept): v5
bez zmian oraz 16 układów redakcyjnych `core.rich_text` v3 z metadanymi
`conversion`; rodzina redakcyjna ma 20 układów. Wcześniej v5: 96 recept v4 bez
zmian oraz 8 nowych (cztery układy `core.rich_text` v2, dwa
`core.feature_list` v4, `core.quote` i `core.product`). v5 dodaje opcjonalne
`sampleMedia.path` i metadane dopasowania; szczegóły w
[site-rich-content.md](site-rich-content.md).

## Szablony nastawione na konwersję

Decyzja właściciela z 2026-09-23: każda nowa recepta sekcji i strony powstaje
pod konwersję. Dotychczasowe szablony nie są wzorcem jakości — nie
rozbudowujemy ich i nie naśladujemy. Ich wersje pozostają czytelne dla stron,
które już z nich powstały; nowe recepty zastępują je w bibliotece.

Kryteria odbioru każdej nowej recepty:

1. **Jeden cel strony.** Recepta wskazuje główne działanie (formularz
   zapytania, telefon, rezerwacja, e-mail). Przyciski nazywają efekt
   („Umów bezpłatną wycenę”, „Sprawdź termin”), nie mechanizm („Wyślij”).
2. **Pierwszy ekran sprzedaje** — na 390 i 1440 px: dla kogo i co zyskuje,
   jedno zdanie uzupełnienia, główne działanie oraz zdjęcie lub sygnał
   zaufania. Bez „Witamy na naszej stronie”.
3. **Ścieżka decyzji:** potrzeba → oferta i korzyści → dowody → jak to
   przebiega / co stanie się po kontakcie → obiekcje (FAQ, ograniczenia,
   widełki cen) → końcowe wezwanie. Główne działanie wraca w punktach
   decyzji; najwyżej jedno cichsze działanie pomocnicze, nigdy dwa
   konkurujące przyciski w jednej sekcji.
4. **Dowody bez zmyślania.** Seedy nie zawierają wymyślonych opinii, ocen,
   logotypów klientów, statystyk, cen ani certyfikatów. Mają wyraźne miejsca
   `[Uzupełnij: …]` na prawdziwy materiał właściciela. Automat nie pisze
   cytatów ani dowodów.
5. **Niski próg kontaktu:** krótki formularz (imię, kontakt, wiadomość),
   informacja, co stanie się po wysłaniu i jak szybko, bez zakładania konta.
6. **Bez ciemnych wzorców:** bez liczników czasu, sztucznej rzadkości i
   zaznaczonych z góry zgód.
7. **Telefon i szybkość:** działanie osiągalne na pierwszym ekranie telefonu,
   pola dotyku 44 px, zdjęcie otwierające w budżecie LCP.
8. **Metadane:** sekcja deklaruje etap ścieżki (uwaga, zainteresowanie,
   dowód, obiekcja, działanie) i to, czy niesie główne działanie; recepta
   strony — główne działanie i kolejność etapów. Pola wejdą w następną wersję
   katalogu i recepty (faza 3 planu rich content).

Każda recepta przechodzi przegląd z listą powyżej i zrzutami 390/1440 px,
zanim trafi do katalogu. Zdjęcia do nowych recept generuje właściciel
(Gemini/ChatGPT); do tego czasu recepty używają zatwierdzonych ilustracji z
`packages/contracts/page-templates/assets` albo zastępczych.

## Macierz docelowych wariantów domyślnych

Poniższe listy są specyfikacją kierunków projektowych, a nie listą gotowych
komponentów. Każdy numer ma otrzymać osobny projekt, opis wymagań i odbiór
mobile/dostępności. Zmiana koloru nie zalicza nowego wariantu. Warianty
wymagające dodatkowych pól (np. fotografie zespołu) potrzebują nowej wersji
schematu. Odrzucony podczas prototypowania kierunek zastępujemy innym układem,
bez zmniejszania celu 20 na kategorię.

| Typ | Warianty 01–10 | Warianty 11–20 |
|---|---|---|
| Hero | klasyczny; wyśrodkowany; dwie kolumny; portret specjalisty; panorama nad tekstem; panorama pod tekstem; tło fotograficzne; galeria mozaikowa; komunikat typograficzny; oferta z listą korzyści | z obszarem działania; z godzinami pracy; z profilem zespołu; z wyróżnioną usługą; z dwoma celami CTA; z podsumowaniem procesu; układ redakcyjny; ze wskaźnikami; z listą kategorii; z cytatem źródłowym |
| Rich text / o nas | pojedyncza kolumna; wstęp i rozwinięcie; dwie kolumny; tekst ze zdjęciem; zdjęcie z podpisem; wyróżniony cytat; tekst z boczną notą; historia w osi; manifest z punktami; profil autora | z panelem faktów; pytanie i odpowiedź; tekst z listą etapów; z galerią; z dokumentami; z wyróżnionym zakończeniem; numerowane akapity; z indeksem tematów; krótkie karty narracyjne; tekst i podsumowanie |
| Oferta | lista; karty; układ redakcyjny; wiersze naprzemienne; katalog ze zdjęciami; oferta wyróżniona; grupy usług; siatka ikon; kafle z numerami; lista kompaktowa | tabela zakresów; oferta i korzyści; zastosowania; proces współpracy; pakiety opisowe; pytania do usługi; oferta z dokumentami; podział według odbiorcy; zestawienie problem–rozwiązanie; sekcja usługi z CTA |
| FAQ | lista odpowiedzi; akordeon; tytuł obok pytań; grupy tematyczne; dwie kolumny pytań; wyróżnione pytanie; pytania z numerami; pytania z ikonami; indeks i odpowiedzi; FAQ z kontaktem | pytania przed wizytą; FAQ według etapu; karty pytań; krótkie odpowiedzi kompaktowe; sekcje rozdzielone nagłówkami; FAQ z dokumentami; pytania według odbiorcy; odpowiedź z ilustracją; odpowiedzi i terminy; wyszukiwane pytania |
| Kontakt | dane pionowo; dane w kolumnach; wizytówka osoby; dane ze zdjęciem; adres z mapą statyczną; lista lokalizacji; godziny i kontakt; kontakt z dojazdem; wyróżniony telefon; wyróżniony e-mail | działy firmy; osoby kontaktowe; dane i instrukcja; kontakt po usłudze; kanały kontaktu; kontakt z FAQ; dane z CTA; dane korespondencyjne; kontakt z obszarem obsługi; karta lokalizacji z udogodnieniami |
| Opinie | lista cytatów; siatka kart; jeden wyróżniony cytat; cytat z portretem; opinie w dwóch kolumnach; cytat obok wprowadzenia; opinie z usługą; opinie ze źródłem; krótkie rekomendacje; długa historia klienta | mozaika opinii; opinie z datą; opinie według tematu; rekomendacje partnerów; opinia i rezultat; cytat pełnej szerokości; sekwencja opinii; list referencyjny; opinie i kontakt; zestawienie ze zweryfikowaną oceną |
| Cennik | lista cen; karty pakietów; tabela porównawcza; pakiet wyróżniony; kategorie cen; cena z zakresem; warianty usługi; cennik kompaktowy; ceny z opisem czasu; cena i dodatki | cena z FAQ; proces wyceny; zakres od–do; cena z jednostką; pakiet i pojedyncze usługi; abonamenty opisowe; cennik lokalizacji; ceny według odbiorcy; cena i warunki; oferta wymagająca wyceny |
| Rezerwacja | proste CTA; CTA z opisem; CTA obok ilustracji; wybór usługi; wybór specjalisty; wybór lokalizacji; etapy rezerwacji; przygotowanie i CTA; CTA z godzinami; rezerwacja i kontakt | CTA z FAQ; rezerwacja grupowana; konsultacja wstępna; powtórna wizyta; rezerwacja z podsumowaniem; rezerwacja terenowa; panel instrukcji; termin i CTA; rezerwacja kategorii; rezerwacja z informacją o dostępności |
| Stopka | tekst; tekst i linki; dwie kolumny; wielokolumnowa mapa strony; dane firmy; stopka z kontaktem; stopka z godzinami; stopka z lokalizacjami; stopka z CTA; stopka z portretem | kategorie usług; dane i dokumenty; nawigacja grupowana; dane z obszarem działania; marka obok linków; panel kontaktowy nad linkami; stopka z partnerami; stopka z opisem działalności; kontakt i kanały społecznościowe; indeks podstron |
| Lista wpisów | lista tytułów; lista ze skrótem; karty; siatka zdjęć; wpis wyróżniony; układ magazynowy; oś czasu; lista kompaktowa; kategorie tematyczne; wpisy z autorami | archiwum dat; wpisy z tagami; poradnik i materiały; katalog dokumentów; lista pytań; mozaika; układ naprzemienny; artykuł i powiązane; lista z metadanymi; układ indeksowy |

Dla pól zależnych od faktycznej funkcjonalności (dostępność terminów, formularz,
mapa, wyszukiwanie, ocena) najpierw weryfikujemy możliwości backendu. Sam
wariant nie może pozorować działającej integracji ani generować faktów.

## Pierwszy przekrój i dodatki branżowe

Gotowe w kodzie: hero klasyczny/wyśrodkowany/dwie kolumny, oferta
lista/karty/redakcyjna i FAQ lista/akordeon/dwie kolumny — 9 domyślnych.

| Branża | Kategoria | Dodatki pierwszego przekroju | Dalsza macierz |
|---|---|---|---|
| Medycyna | Oferta | oś konsultacji; zakres konsultacji w dwóch kolumnach | Po odbiorze rozważyć hero i profile specjalistów: 2–3 na wybraną parę |
| Rolnictwo | Oferta | etapy terenowe; obszary obsługi | Po odbiorze rozważyć hero i kontakt z dojazdem: 2–3 na wybraną parę |
| Elektronika | Oferta | zestawienie parametrów; wyróżniony początek serwisu | Po odbiorze rozważyć hero i FAQ serwisowe: 2–3 na wybraną parę |

Każdy dodatek ma własną strukturę i seed PL/EN bez zmyślonych kwalifikacji,
cen, opinii i danych firmy. Łącznie pierwszy przekrój ma 15 recept sekcji.
Branżowe nie wliczają się do celu 200 domyślnych. Nie deklarujemy 200 gotowych
wariantów na podstawie samej macierzy.

## Granica przyrostu i następny krok

Biblioteka jest w edytorze strony: filtr branży i kategorii, miniatury,
responsywny podgląd, dodanie sekcji oraz wybór układu w inspektorze. Dodatkowa
recepta całej strony komponuje trzy warianty i kontakt. Jej seed pozostaje PL;
seedy sekcji i interfejs katalogu są PL/EN. Stare szablony nadal
działają. Ten przyrost nie jest jeszcze docelowym edytorem wizualnym.

Dalej: ocena wizualna na uruchomionym stacku, metadane ilości treści/mediów i
kontekstowe rekomendacje, próba edytora wizualnego, biblioteka własnych szablonów,
pełne 20 wariantów każdej kategorii i rollout produktów. AI pozostaje osobną
odroczoną fazą; kontrakt katalogu jest już maszynowo czytelny.

## Dekoracje i katalog v4 — 2026-09-21

Bieżący katalog v4 zawiera 96 sekcji: zachowane 88 z v3 i osiem separatorów
(space/line/double/dots/wave/curve/zigzag/accent). Każdy separator ma opisy
PL/EN, wskazówki kompozycji i edytowalną wysokość, szerokość oraz ton.
Osiem presetów dekoracji jest osobnym katalogiem wspólnego wyglądu, dostępnym
dla wszystkich bloków; nie zwiększa liczby układów i nie zamyka macierzy 20 wariantów.
Pełny kontrakt: [site-section-decoration.md](site-section-decoration.md).
