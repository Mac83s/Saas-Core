# ADR-044 — baza zmiany treści i ważność podglądu

**Status:** Accepted — doprecyzowanie §5 ADR-035 przy pierwszej integracji SCR.
**Data:** 2026-09-06

## Problem

Numer draftu strony i hash opublikowanego serwisu nie opisują tego samego stanu.
Tłumaczenie ma ponadto własny numer wersji: ręczna zmiana opisu SEO nie musi
zmienić `Page.version`. Sprawdzanie samego numeru strony pozwalałoby nadpisać
taki opis propozycją przygotowaną wcześniej. Podgląd wydawał również digest z
datą ważności, której zapis nie weryfikował, oraz deklarował wykonanie komend,
których ścieżka zapisu nie realizowała.

## Decyzja

`GET /api/v1/sites/content-base/` przyjmuje jawny target: `kind`, `site_id`,
`locale` oraz `page_id` albo `collection_id` i `entry_id`. Usługa sprawdza
tenant, permission, entitlement i aktywny grant zasobu przed odczytem bloków.
Odpowiedź zawiera `target`, `base`, `blocks`, `translation_fields`, `observed_at`;
`base` zawiera `version`, `snapshot_hash`, `observed_at`. Jest prywatna i nie
może być cache'owana. SCR kopiuje bazę z odpowiedzi i nie rekonstruuje jej hasha.

Hash SHA-256 wiąże target z locale, bieżący numer wersji, rzeczywiste bloki
draftu i lokalizowane metadane. Dla strony obejmuje również numer tłumaczenia,
slug, flagi fallbacku i istnienie tłumaczenia. Dla wpisu obejmuje jego title,
excerpt i locale. Czas odczytu nie wpływa na hash. Hash publikacji pozostaje
informacją o publikacji; nie jest bazą operacji na drafcie.

Preview oraz apply sprawdzają oba istniejące pola kontraktu v1: numer i hash.
Niezgodność daje `409 change_set_stale`. Zapis blokuje agregat w tej samej
transakcji, w której sprawdza bazę i wykonuje zapis draftu oraz metadanych.
`translation.update` dla strony używa istniejącej usługi tłumaczenia, zachowując
slug i flagi fallbacku. Na powierzchni `proposed` zmiana od automatyzacji czeka
w propozycji na decyzję człowieka; zapis draftu nie zmienia jeszcze metadanych.
Limity pól wynikają z docelowego modelu. Referencje do mediów przechodzą do
nowego draftu.

`approval_digest` pozostaje deterministycznym skrótem efektu. Wiąże także
tenant, aktora, credential, cały target z locale, bazowy hash i klucz zamiaru.
Preview dodaje `approval_token`, podpisany przez Core i ograniczony istniejącym
TTL. Apply z digestem wymaga tokenu; token musi zgadzać się z bieżącym efektem
i nie może być przeterminowany. Zapis draftu bez zatwierdzenia pozostaje
dozwolony tam, gdzie pozwala na niego grant. Token podglądu nie dowodzi zgody
człowieka i nigdy nie udziela prawa do publikacji. Zastosowanie zmiany nadal
zwraca `published: false`; aktualna baza uniemożliwia ponowne zastosowanie
zatwierdzonego efektu po utworzeniu nowej wersji.

`commands` w capabilities nadal opisuje słownik kontraktu. Nowe
`change_set_commands` wskazuje wykonywany podzbiór: komendy blokowe oraz
`translation.update`. `page.create`, `entry.create`, `internal_link.add` i
`publication.schedule` są na tym endpointcie jawnie odrzucane kodem
`422 change_set_command_unsupported`. Tworzenie i harmonogram mają osobne
usługi. Wpis nie ma modelu social metadata, dlatego jego `translation.update`
jest również odrzucane: nie utożsamiamy automatycznie description z excerpt.

## Konsekwencje i granice

Propozycja przechowuje target z locale, pełne metadane przed i po zmianie wraz
z numerem tłumaczenia, stan przeglądu i wynik decyzji. Detail API wydaje osobny
`review_token`, związany z osobą, tenantem i rzeczywistym zapisanym diffem.
`POST /proposals/<id>/accept/` wymaga tego tokenu i kontekstu człowieka. Blokuje
stronę oraz tłumaczenie, sprawdza aktualny draft i metadane, zapisuje metadane
istniejącą usługą oraz decyzję i audyt w jednej transakcji. Nie publikuje.
Powtórzenie zaakceptowanej decyzji nie zapisuje metadanych drugi raz.

Dotychczasowy `discard/` pozostaje adresem odrzucenia, lecz `restored_version`
oznacza numer **nowego** draftu zawierającego wcześniejsze bloki. Numer wersji
nigdy nie cofa się. Zamkniętej propozycji nie usuwamy: znika z listy oczekujących,
a jej detail i audyt pozostają dostępne. Powtórzenie odrzucenia zwraca ten sam
wynik. Późniejsza ręczna zmiana draftu albo metadanych powoduje `409`, zamiast
nadpisania pracy człowieka. Odrzucenie propozycji oczekującej pozostawia
dotychczasowe metadane bez zmiany; odrzucenie już wykonanego zapisu draftowych
metadanych odtwarza poprzednie pola nową wersją tłumaczenia.

Apply rozróżnia `applied_commands` i `pending_commands` oraz zwraca
`proposal_id`. Publikacja witryny jest zablokowana, jeśli jej aktualny draft
ma propozycję z metadanymi czekającymi na decyzję. Nie można więc przypadkowo
opublikować nowych bloków i starego opisu, pomijając przegląd.

Nowe pola i endpoint są dodatkami do API v1. Obowiązek zgodnego hasha już
istniał w schemacie — dotychczasowe fixture'y z dowolnym hashem przestają
przechodzić, bo nie przedstawiały stanu odczytanego z Core. Integracja musi
pobrać prawdziwą bazę przed przygotowaniem propozycji. Digest bez podpisanego
tokenu nie jest akceptowany jako ważny podgląd; nie utrzymujemy zgodności z
wcześniejszym nieweryfikowalnym czasem ważności.

Migracja `sites.0025` rozszerza istniejącą tabelę ContentProposal i zachowuje
jej wymuszone RLS. Cofnięcie schematu jest dozwolone przed użyciem nowych pól;
guard odmawia usunięcia istniejącej historii przeglądu. Rollback aplikacji musi
zachować rozszerzony schemat, a po rozpoczęciu przeglądów wymaga sprawdzenia
zgodności poprzedniego kodu z nowym stanem kolejki — samo cofnięcie obrazu nie
dowodzi bezpiecznego powrotu. Historia draftów nadal jest niemutowalna,
publikacja pozostaje osobną granicą, a polityka powierzchni i grant mogą
wyłącznie ograniczać operację. Automatyczna publikacja nie jest uruchamiana.

## Uzupełnienie 2026-10-04 — baza per (podstrona, język)

Wdrożenie ADR-070 pkt 17 (plan TL13). Decyzja pozostaje ta sama; zmienia się to,
czym jest „baza” dla podstrony w języku innym niż źródłowy witryny.

- **Język w kontrakcie to kształt, nie lista.** `target.locale` w
  `content-change-set.v1` przyjmuje wzorzec `^[a-z]{2}(-[A-Z]{2})?$` zamiast
  wyliczenia `pl`/`en`. Które języki ma witryna, odpowiada serwer: język spoza
  listy firmy daje `400 locale_not_enabled` — ten sam kod i status co w zapisie
  wersji językowej z panelu — w odczycie bazy, w podglądzie i przy zastosowaniu,
  po sprawdzeniu grantu. `contract_version` zostaje 1: nadawca wysyłający język
  źródłowy witryny działa bez zmian.
- **Język źródłowy:** bez zmian — baza to `Page.version` i bloki szkicu.
- **Inny język:** `base.version` to `PageTranslation.body_version`, a `blocks` to
  bloki, w które składa się robocza wersja językowa. Podstrona bez wersji w tym
  języku (bez adresu i tytułu) daje `404 change_set_target_not_found`. Zapis w
  jednym języku nie unieważnia bazy odczytanej w innym.
- **Komendy w innym języku:** najpierw, dla całego zestawu, komendy
  niewykonywane przez te drzwi (`422 change_set_command_unsupported`); potem
  `block.insert`, `block.remove` i `block.reorder` — `422 locale_structure_locked`.
  `block.replace` przechodzi, gdy wynik jest nadal treścią źródła z innym tekstem:
  ten sam typ i wersja bloku, te same pola, wygląd, zdjęcia i cele linków.
  Oznaczone fragmenty zdania (pogrubienie, kursywa, link) mogą zamienić się
  miejscami. Zmiana pola wspólnego dla języków (adres, imię i nazwisko) też jest
  zmianą struktury. Fragment, który nie pasuje do miejsca w bloku, wraca jak z
  panelu: `400 locale_unit_invalid` z kluczem fragmentu.
- **Zapis:** zmienione fragmenty trafiają do nowej `PageLocaleVersion`
  (`origin = change_set`, pochodzenie fragmentu `integration`); `Page.version`
  się nie zmienia i nie powstaje `PageVersion`. Na powierzchni `proposed`
  automatyzacja zapisuje wersję czekającą (`body_pending`, powód `change_set`),
  w pozostałych przypadkach roboczą. Każdy zastosowany zestaw podnosi
  `body_version` o jeden — także sam `translation.update`, tak jak w języku
  źródłowym podnosi `Page.version`. Blokada edytora źródła
  (`Page.editing_locked_until`) tego zapisu nie zatrzymuje.
- **Tłumaczenie czekające na decyzję** (wersja z silnika tłumaczeń w
  `body_pending`) zatrzymuje zestaw zmian dla tego języka:
  `409 locale_version_waiting`. Własną wersję czekającą zestaw zmian zastępuje
  następnym.
- **Propozycje:** `ContentProposal` ma `locale` w kluczu unikalności (migracja
  `sites.0051`), więc propozycja PL i DE tej samej podstrony mogą mieć ten sam
  numer wersji; kolejka pokazuje jedną pozycję na (zasób, język). Przyjęcie i
  odrzucenie propozycji w innym języku idą przez wersję językową: przyjęcie
  wersji czekającej robi z niej roboczą i publikuje ją tam, gdzie podstrona jest
  już publiczna w tym języku (`published: true` w odpowiedzi); odrzucenie ją
  usuwa albo — gdy była już robocza — zapisuje nową wersję z poprzednim tekstem.
  Blokada publikacji witryny przy czekających metadanych liczy wersję per język.
- **Odczyty dla konektora:** inventory podaje per (podstrona, język) ścieżkę
  (strona główna: `/` i `/xx/`), adres, `base_version`, stan tłumaczenia i
  publikację; capabilities — języki witryny i `language_version_commands`.
  `sites.page.draft_saved` niesie `locale`, a `version` jest wersją tego języka.
