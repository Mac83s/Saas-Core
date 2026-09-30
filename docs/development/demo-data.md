# Dane demo stosu testowego — `manage.py seed_demo`

Po zalogowaniu na stos testowy (lokalny albo staging `*.goldenstar.cloud`) jest już
firma z zespołem, wizyty w kalendarzu i magazyn ze stanem — bez klikania. Komenda
działa w kontenerze backendu i można ją uruchamiać wielokrotnie: znajduje to, co
założyła poprzednio (organizację po slugu, konto po e-mailu, dokument magazynowy po
stałym identyfikatorze, wizytę po kluczu idempotencji) i dopisuje tylko to, czego
brakuje — np. wizyty dnia, który przy poprzednim uruchomieniu nie był „dziś”.
Niczego nie usuwa.

## Uruchomienie

```bash
# staging na VPS (hasło wpisane raz przez `read -s` do pliku 0600):
docker exec -i -e DEMO_SEED_ENABLED=1 saas-core-backend-1 \
  python manage.py seed_demo --password-stdin < /root/.demo-seed-password

# lokalnie:
printf '%s\n' 'Lokalny-Test-2026!' | docker compose exec -T -e DEMO_SEED_ENABLED=1 \
  backend python manage.py seed_demo --password-stdin
```

Zabezpieczenia:

- bez `DEMO_SEED_ENABLED=1` w środowisku tego uruchomienia komenda odmawia;
- odmawia przy `APP_ENV=production` i przy Stripe w trybie live;
- hasło kont nie przechodzi przez argv ani repozytorium: `--password-stdin`, plik
  `DEMO_SEED_PASSWORD_FILE` albo `DEMO_SEED_PASSWORD`; co najmniej 12 znaków;
  istniejące konta demo dostają to hasło przy każdym uruchomieniu;
- wszystkie konta demo mają adres w domenie `.test` — scenariusz z innym adresem
  zostaje odrzucony, zanim cokolwiek powstanie.

## Co powstaje (Business)

- **Studio Testowe**: `wlasciciel@saas.test` (właściciel), `kierownik@saas.test`
  (menedżer), `pracownik@saas.test` (pracownik); konta aktywne od razu.
- **Plan pro** bez płatności: uprawnienia bieżącej wersji planu zapisane jak przez
  opłaconą subskrypcję (`billing/demo.py`); ekran rozliczeń pokazuje brak
  subskrypcji, moduły działają.
- **Kalendarz** (`booking/demo.py`): miejsce, usługi „Konsultacja” i „Sesja we dwoje”
  (dwie osoby), godziny 07–21 dla osób, które ich nie mają, 9 wizyt dziś i w dwa
  kolejne dni; wizyta usługi dwuosobowej z jedną osobą czeka w „Do przydzielenia”.
  Godzina, która już minęła, jest pomijana.
- **Magazyn** (`inventory/demo.py`): pozycje (jedna z partią i terminem ważności),
  przyjęcie PZ do magazynu głównego, wydania MM do zapasu pracownika i menedżera,
  zużycie RW i zwrot MM — liczby widać w Magazynie i na karcie osoby.

## Punkt rozszerzenia (ADR-049)

Rdzeń zakłada konta, organizacje i członkostwa (`core/organizations/demo.py`);
moduły dopisują swoje części przez `register_demo_part(name, part, order=…)` w
`ready()` (billing 10, farms 20, booking 30, inventory 40). Produkt zastępuje
scenariusz Business własnym przez `register_demo_scenario(factory)` w `ready()`
swojego modułu wertykalnego i może dodać własne części (np. wizyty w gospodarstwie).
Dane modułów leżą w scenariuszu pod nazwą części: `booking`, `inventory` w
organizacji, `farms.links` między organizacjami — kształt opisuje docstring modułu.
