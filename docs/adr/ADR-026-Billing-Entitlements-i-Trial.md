# ADR-026 — Billing, entitlementy i trial pilota

**Status:** Accepted  
**Data:** 2026-08-10

## Kontekst

W5 wymaga zamknięcia decyzji produktowych przed zbudowaniem katalogu planów i
integracji Stripe. Pilot MedPlano jest usługą B2B, a lokalny stan aplikacji ma
pozostać źródłem decyzji dostępowych. Stripe obsługuje płatność i cykl
subskrypcji, lecz nie jest źródłem definicji produktu.

Publiczne cenniki porównawcze pokazują obecnie zakres około 109–299 PLN
miesięcznie dla pakietów Medfile, 139 PLN za kalendarz w Proassist oraz
399–699 PLN dla planów specjalisty ZnanyLekarz. Pilot otrzymuje konserwatywne
ceny wejściowe, które mogą być zastąpione nową niemutowalną wersją planu bez
zmiany istniejących subskrypcji.

## Decyzja

- Jednostką sprzedaży jest organizacja. Limity stron, lokalizacji i członków są
  quota organizacji, a nie osobnymi subskrypcjami.
- Pilot jest wyłącznie B2B, miesięczny i rozliczany w PLN netto. Plan roczny i
  dodatki są odłożone do danych sprzedażowych z pilota.
- `Starter v1` kosztuje 149 PLN netto miesięcznie, a `Pro v1` 299 PLN netto
  miesięcznie.
- Trzydniowy trial zaczyna się dopiero po aktywacji pierwszego produktu/strony.
  Metoda płatności i jawna data pierwszego obciążenia są wymagane przed startem
  triala.
- Nieudana płatność uruchamia siedmiodniowy `grace_period`, następnie
  `read_only`. Anulowanie zachowuje pełny dostęp do końca opłaconego okresu, a
  potem przechodzi do `read_only`.
- Dane nie są automatycznie usuwane przez Billing. Po 90 dniach anulowana
  subskrypcja może przejść do `suspended`; usunięcie wymaga osobnego,
  audytowanego procesu retencji.
- Subdomena platformy jest dostępna w obu planach. Własna domena jest funkcją
  planu Pro.
- Adapter fakturowania w W5 przyjmuje kanoniczne żądanie dokumentu i zwraca
  trwały status/wynik. Bezpośrednie połączenie z KSeF nie jest częścią pierwszej
  wersji adaptera.

## Katalog pilota v1

| Element | Starter | Pro |
| --- | ---: | ---: |
| `sites.enabled` | tak | tak |
| `storage.enabled` | tak | tak |
| `notifications.enabled` | tak | tak |
| `booking.enabled` | tak | tak |
| `medical.enabled` | tak | tak |
| `custom_domain.enabled` | nie | tak |
| `sites.max` | 1 | 3 |
| `locations.max` | 1 | 5 |
| `team_members.max` | 5 | 25 |
| `storage.bytes` | 5 GiB | 50 GiB |
| `email.monthly` | 2 000 | 20 000 |
| `appointments.monthly` | 1 000 | 10 000 |

## Konsekwencje

- Nowa oferta powstaje jako kolejny `PlanVersion`; opublikowane wersje i ich
  granty są niemutowalne.
- Permission i entitlement są sprawdzane oddzielnie. Owner bez funkcji planu
  nadal otrzymuje odmowę, a użytkownik bez permission nie korzysta z funkcji
  mimo aktywnego planu.
- Autoryzacja korzysta z lokalnego snapshotu i nie wykonuje zapytania do Stripe
  w ścieżce requestu.
- W5.3 musi mapować Stripe Price do konkretnej wersji planu i odrzucać nieznane
  mapowania.

## Źródła porównania cen

- https://www.medfile.pl/cennik
- https://proassist.pl/cennik/
- https://pro.znanylekarz.pl/cennik/znanylekarz-dla-lekarzy

