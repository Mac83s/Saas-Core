# Sekrety stagingu i rotacja

## Kontrakt

Sekrety aplikacji są zwykłymi plikami montowanymi przez Docker Compose do
`/run/secrets`. Kod odczytuje je przez zmienne `<NAZWA>_FILE`. Jednoczesne
ustawienie wartości i wariantu `_FILE` zatrzymuje start aplikacji.

Na stagingu katalog `/opt/saas-core/secrets`:

- należy do dedykowanego operatora deploymentu;
- ma prawa `0700`, a każdy plik `0600`;
- nie jest częścią checkoutu, obrazu, backupu logów ani artefaktu CI;
- zawiera wyłącznie nazwy opisane w
  `deployments/staging/secrets/README.md`.

## Opcjonalne integracje

Pusty plik oznacza, że integracja jest wyłączona, a nie źle skonfigurowana.
`scripts/runtime-secrets.mjs` tworzy je puste.

| Plik                              | Zmienna                                | Kto używa                                                                                  |
| --------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------ |
| `seo_ssa_service_key`             | `SEO_SSA_SERVICE_KEY_FILE`             | audyty SEO (SSA)                                                                           |
| `seo_ssa_callback_secret`         | `SEO_SSA_CALLBACK_SECRET_FILE`         | callbacki SSA                                                                              |
| `image_generation_openai_api_key` | `IMAGE_GENERATION_OPENAI_API_KEY_FILE` | generowanie obrazów (ADR-059); osobny projekt OpenAI na produkt z twardym limitem wydatków |

## Utworzenie

1. Wygeneruj wartości kryptograficznym generatorem na zaufanej stacji.
2. Przenieś je szyfrowanym kanałem bez zapisywania w historii powłoki.
3. Ustaw właściciela i prawa przed uruchomieniem Compose.
4. Sprawdź `docker compose config`, nie wypisując zawartości plików.
5. Uruchom migrator i usługi, następnie smoke przez Caddy.

## Rotacja

1. Ustal usługi używające sekretu i wpływ utraty starej wartości.
2. Utwórz nowy plik obok starego z prawami `0600`.
3. Dla poświadczeń z okresem przejściowym najpierw dopuść obie wartości u
   dostawcy, potem atomowo podmień plik i odtwórz tylko właściwe usługi.
4. Wykonaj healthcheck i smoke, a następnie unieważnij starą wartość.
5. Zapisz czas, operatora, zakres i wynik bez wartości sekretu.

Rotacja `DJANGO_SECRET_KEY` unieważnia podpisane dane zależne od klucza i
wymaga zaplanowanego okna lub przyszłego mechanizmu kluczy zapasowych. Hasła
`postgres_password` roli migracyjnej oraz `postgres_app_password` roli
aplikacyjnej rotuje się niezależnie, po stronie bazy w tej samej kontrolowanej
operacji co podmiana właściwego pliku. Backend, worker i scheduler nie otrzymują
sekretu migratora.

## Awaryjne unieważnienie

W razie podejrzenia wycieku zatrzymaj nowe wdrożenia, unieważnij wartość u
źródła, wydaj nową, odtwórz zależne usługi i sprawdź logi audytowe. Nie wklejaj
wartości do issue, komunikatora, logu CI ani raportu incydentu.
