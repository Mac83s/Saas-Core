# ADR-062 — korekty wpisów kartoteki zwierzęcia: wersje zamiast nadpisywania

**Status:** Accepted — decyzja właściciela 2026-09-28 (odpowiedzi 1a, 2a, 3a),
plan memex `korekty-wpisow-po-zakonczeniu-wizyty`.
**Data:** 2026-09-28

## Kontekst

Wpis zdrowotny w kartotece zwierzęcia (`AnimalHealthEntry`, ADR-051 pkt 8) był
kluczowany parą (źródło, referencja), a ponowna publikacja tej pary **nadpisywała**
wiersz. Cofnięty wpis z lekiem był z rejestru hodowcy **kasowany**
(`unpublish_health_entry`), a z karty firmy — `drop_own_health_entry`. Hodowca
mógł zobaczyć karencję, zacząć według niej działać, a potem wpis znikał albo
zmieniał treść bez śladu. Kasowanie przez drzwi rejestru nie było też na liście
zadeklarowanych przejść (`tests/test_registry_door.py`).

Właściciel 28.09: to, co trafiło do hodowcy, nie może zniknąć ani zmienić się po
cichu; pomyłkę poprawia dodatkowy wpis nawiązujący do pierwotnego.

## Decyzja

1. **Wersje.** Linią wpisu jest (źródło, referencja); każdy zapis to wersja
   (`revision`). Obowiązuje jedna wersja na linię — ta bez `retracted_at`
   (unikalny indeks częściowy `farms_health_current_uq`). Korekta to następna
   wersja z `corrects` (wskazanie poprzedniej), `correction_reason` i
   `corrected_by`; poprzednia dostaje `retracted_at` i zostaje w historii.
2. **Publikacja bez korekty niczego nie zmienia.** `publish_health_entry` i
   `record_own_health_entry` bez `correction` zapisują linię tylko, gdy jej nie
   ma; powtórka (ponowne wysłanie, drugie zamknięcie wizyty) zostawia to, co
   czytelnik już ma. Z `correction` zapisują nową wersję tylko wtedy, gdy treść
   się różni — ta sama korekta dwa razy to jedna wersja. `require_current`
   koryguje tylko to, co już jest: wycofanie czegoś nigdy nieopublikowanego nie
   pisze nic.
3. **Nic nie jest kasowane.** `unpublish_health_entry` i `drop_own_health_entry`
   znikają. Firma cofająca własny wpis przed przekazaniem go hodowcy oznacza go
   na swojej karcie (`retract_own_health_entry`). Wyzwalacz
   `farms_animalhealthentry_append_only` pozwala po zapisie tylko ustawić
   `retracted_at`, raz; usunąć wiersz może wyłącznie usunięcie organizacji
   (`app.erasing_organization_id`), tak jak wpisy korekcji HoofCare.
4. **Karencja** liczy się tylko z wersji obowiązujących: lek wpisany nie tej
   krowie po korekcie przestaje trzymać ją „w karencji”.
5. **Hodowca wie.** Korekta opublikowana w rejestrze daje powiadomienie w
   aplikacji (`farms.health_corrected`) osobom z `farms.manage` — jedno na
   gospodarstwo, dzień i powód, więc wizyta skorygowana na dziesięciu krowach to
   jedna wiadomość (odpowiedź 2a).
6. **Widok.** Kartoteka pokazuje wersję zastąpioną przekreśloną, z „Nieaktualny
   od …”, bez jej karencji; wersja korygująca ma odznakę „Korekta” (albo
   „Uzupełnienie”, gdy nie zastępuje niczego) i „Powód: … · kto”.
7. **Te same drzwi.** Korekta idzie przez `publish_health_entry`, więc lista
   zadeklarowanych przejść przez `registry_door` się nie wydłuża — przejście
   kasujące po prostu znika.

## Konsekwencje

- Wertykał decyduje, *kiedy* publikuje korektę i z jakim powodem; rdzeń pilnuje,
  że nie da się tego zrobić inaczej niż nową wersją. HoofCare: granica to
  „Zakończ wizytę” (HC-ADR-002, uzupełnienie 28.09).
- Lista kartoteki firmy łączy kartę i rejestr per wersja: korekta, którą ma
  tylko rejestr (wycofanie opublikowane po wizycie), pokazuje się także firmie.
- Migracja `farms 0014` jest odwracalna strukturalnie; cofnięcie jej przy
  istniejących wersjach > 0 zatrzyma się na przywracanym unikalnym kluczu —
  celowo, bo zgubiłoby historię.
- Zdjęcia nadal są odwołaniami do mediów autora (decyzja z 20.09): wersja nie
  kopiuje plików.

## Alternatywy odrzucone

- **Kasowanie przez zadeklarowane drzwi** (wariant rozważany 28.09 rano) — lista
  drzwi rosłaby o operację, której właściciel nie chce wcale.
- **Oznaczanie „wycofany” bez nowego wpisu** — hodowca nie dowiedziałby się,
  dlaczego i kto; właściciel chciał dodatkowego wpisu nawiązującego do
  pierwotnego.
- **Osobna tabela korekt** — dwa źródła prawdy o jednym wpisie; wersja w tej
  samej tabeli czyta się jednym zapytaniem i liczy karencję tym samym filtrem.
