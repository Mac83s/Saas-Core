# Formularz kontaktu v2 — wydanie 2026-09-24

Zakres: formularz kontaktu v2 z planu memex
`saas-core-site-studio-rich-content-and-full-width` (decyzja właściciela
`formularz-kontaktu-v2-w-as-ciciel-wybiera-jeden-`, odpowiedzi 1a i 2a; opis:
[site-inquiries.md](../../architecture/site-inquiries.md)). `core.contact_form`
v2 ma wariant `contact`: „Napisz do nas” (jak v1), „Oddzwonimy” (wymagany
tylko telefon), „Pełny kontakt”, „Tylko e-mail”. Serwer egzekwuje wariant z
opublikowanego bloku; skrzynka pokazuje „Zadzwoń”, gdy zapytanie nie ma
e-maila; recepta „Jedna usługa — konkret” (v2) używa „Oddzwonimy”. Wdrożono
**tylko** `saas.goldenstar.cloud`; HoofCare i MedPlano dostaną to przez
`core:update`.

| Aplikacja | Backend, worker, scheduler | Frontend |
| --- | --- | --- |
| Saas-Core / vps-dev | `7961481` | `7961481` |

## Wdrożenie

Jedno wdrożenie, 114 s: obrazy z `git archive`, poprzednie jako
`saas-core-{backend,frontend}:rollback-contact-form-v2-20260924`, kopia bazy
przed migracją, migracja `sites/0033_inquiry_contact_optional` (tylko
`blank=True` w modelu, bez zmian kolumn, odwracalna), `check_database_role`,
skaner `CLEAN`, obrazy zgodne z buildem, brak oczekujących migracji,
`/healthz` 200.

## Odbiór

- [x] bramki: backend **993** passed (2 skipped), frontend **520/520**
  (dwa pliki sypiące się pod load ~50 zielone osobno), renderer **186/186**,
  kontrakty **35/35**, lint (z `ai:validate` i `ai:eval`), typecheck,
  prettier, mypy, `backend:migrations`, `backend:imports`, `api:check`;
- [x] na żywo, w prawdziwym panelu, na koncie syntetycznym: formularz v1
  pokazuje w polach sekcji wybór „Czego formularz wymaga” z 4 wariantami i
  wartością „Napisz do nas”; po wyborze „Oddzwonimy” płótno pokazuje Imię,
  Telefon, E-mail (opcjonalnie), Wiadomość (opcjonalnie); zapis (201) daje
  blok v2 z `contact: "callback"`; publikacja;
- [x] strona publiczna przez Caddy z hostem witryny, w Chromium: pola w
  kolejności wariantu, telefon `type="tel"`; wysyłka bez telefonu zatrzymana
  w przeglądarce, „zadzwoń” jako numer odrzucone, samo imię i numer przyjęte
  (201, potwierdzenie); telefon 390 px bez poziomego przewijania;
- [x] serwer bez przeglądarki: zgłoszenie do tego bloku bez telefonu → 400
  z błędem pola `phone`, numer `12-34` → 400;
- [x] skrzynka: zapytanie bez e-maila i wiadomości pokazuje telefon i
  przycisk „Zadzwoń” (`tel:+48000000000`), bez „Odpowiedz e-mailem”; zero
  błędów JS w panelu i na stronie;
- [x] konto, organizacja i obiekty testu usunięte (obie próby).

## Uwagi

- Pierwsza próba odbioru zatrzymała się na wysyłce formularza przez
  harness, nie przez produkt: adresy platformowe `*.saas.goldenstar.cloud`
  nie mają tu certyfikatu, więc odbiór wchodzi po http, a tam przeglądarka
  nie daje `crypto.randomUUID` (klucz idempotencji). Flaga
  `--unsafely-treat-insecure-origin-as-secure` działa w pełnym Chromium
  (`channel: 'chromium'`), nie w headless shell Playwrighta. Na https
  (własne domeny, produkcja) kontekst jest bezpieczny.
- Domyślne potwierdzenie po wysłaniu mówi o „wiadomości” także w
  „Oddzwonimy”; recepta ustawia własne („Oddzwonimy, żeby ustalić termin
  wizyty”), a pole „Potwierdzenie przyjęcia wiadomości” jest edytowalne.
- Powiadomienie e-mail z pustymi polami (jako „—”) sprawdzone testem
  szablonu; konto syntetyczne nie ma `notifications.enabled`, więc na żywo
  poczta nie wychodziła.

Dowody (prywatne): `.runtime/releases/20260924-contact-form-v2/`.
