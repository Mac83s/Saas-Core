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
