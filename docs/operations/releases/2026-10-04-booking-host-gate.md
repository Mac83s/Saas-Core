# Bramka hostów dla odczytów formularza rezerwacji — wydanie 2026-10-04

Zakres: poprawka bezpieczeństwa do plastra 5d planu memex
`saas-core-rezerwacje-uniwersalne-i-sprzedaz`
([ADR-072](../../adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
„Zawężenie bramki hostów dla odczytów formularza”). Bez migracji, bez zmian
kontraktu API.

## Co się zmieniło

- Plaster 5d przepuszczał `GET` i `HEAD` pod `/api/v1/booking/public/` przy
  **dowolnym** nagłówku `Host`. Teraz backend odpowiada na nie poza
  `ALLOWED_HOSTS` tylko pod hostem, pod którym serwuje opublikowaną stronę
  **tej samej firmy**, której formularz nazywa adres: zweryfikowana domena
  własna albo subdomena platformy strony, firma obsługiwana, strona z
  publikacją.
- Każdy inny host dostaje 400 „Host nie należy do konfiguracji aplikacji” —
  także strona innej firmy pytająca o cudzy formularz.
- Formularz na hoście platformy i bloki na stronie firmy działają bez zmian.

## Wdrożenie

Sam kod backendu: przebudowa obrazu backendu i restart. Bez migracji.

## Kontrola po wdrożeniu

Kod odpowiedzi najpierw (podstaw host strony firmy z blokiem kalendarza i
slug jej formularza):

```
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: <host strony firmy>' https://<platforma>/api/v1/booking/public/<slug>/   # 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: nikt.example.test' https://<platforma>/api/v1/booking/public/<slug>/     # 400
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: <host strony innej firmy>' https://<platforma>/api/v1/booking/public/<slug>/  # 400
```

Baza testowa omija RLS, więc trzy powyższe odczyty na uruchomionym stacku są
częścią dowodu (odczyt firmy w `tenant_is_servable` idzie pod jej polityką).

## Dowody

- `tests/test_booking_site_blocks.py`: zweryfikowana domena własna i
  subdomena platformy (z portem i bez) — 200; nieznany host, strona innej
  firmy pytająca o ten slug, slug bez formularza, domena `pending` i
  `failed`, formularz wyłączony, strona bez publikacji, firma zawieszona —
  400; każdy odczyt bajt w bajt taki sam pod hostem strony i platformy, bez
  hosta gościa w treści i nagłówkach; kod rezerwacji nie czyta hosta żądania.
