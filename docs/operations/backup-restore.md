# Kopia bazy PostgreSQL: harmonogram, kontrola świeżości i odtwarzanie

Każdy stack (projekt Compose: `saas-core`, `hoofcare`, `medplano`) ma własną bazę
i własną serię kopii. Obsługuje je jeden skrypt z dowolnego checkoutu rdzenia —
stack wskazuje się nazwą, a nie katalogiem:

```bash
sh infra/postgres/backup.sh run <stack>      # zrzut, odczyt kontrolny, rotacja
sh infra/postgres/backup.sh check <stack>    # wiek najnowszej dobrej kopii
sh infra/postgres/backup.sh rotate <stack>   # sama rotacja; wypisuje, ile kopii usunęła
sh infra/postgres/restore-drill.sh <stack>   # próba odtworzenia do bazy tymczasowej
```

Bez nazwy stacku skrypty biorą `saas-core` (albo `BACKUP_STACK`); tak działają
`pnpm runtime:backup`, `pnpm runtime:backup:check` i `pnpm runtime:restore-drill`.

## Co robi `backup.sh run`

1. znajduje kontener `postgres` projektu po etykietach Compose i uruchamia w nim
   `pg_dump --format custom` — klient ma tę samą wersję major co serwer, a login,
   nazwa bazy i hasło pochodzą ze środowiska kontenera (`POSTGRES_USER`,
   `POSTGRES_DB`, `POSTGRES_PASSWORD_FILE`). Na hoście skrypt nie czyta żadnego
   sekretu i żaden nie trafia do crona ani do wpisu kolejki;
2. pisze do `<stack>-<czas UTC>.dump.partial` w `BACKUP_DIR` (katalog hosta, poza
   wolumenami kontenerów; domyślnie `.runtime/backups` w checkoucie);
3. czyta archiwum z powrotem do końca (`pg_restore --file=/dev/null`) i liczy
   wpisy `TABLE DATA` w spisie. Sam spis leży na początku pliku i przeżywa
   ucięcie, dlatego liczy się dopiero pełny odczyt;
4. zapisuje sumę SHA-256, a na końcu nadaje plikowi nazwę `.dump` (`mv` w tym
   samym katalogu). Plik `.partial` nigdy nie jest kopią: przerwany przebieg
   zostawia go do usunięcia przez następny, a `check` go nie widzi;
5. rotuje: zostają wszystkie kopie z 7 najnowszych dni, w których kopia powstała
   (`BACKUP_KEEP_DAYS`), a spoza nich ostatnia kopia każdego z 4 najnowszych
   tygodni ISO (`BACKUP_KEEP_WEEKS`). Przy jednym zrzucie na dobę daje to około
   10 plików na stack. Rotacja biegnie tylko po udanym zrzucie, więc nieudany
   niczego nie kasuje.

Jeden przebieg na stack naraz (`flock`); pliki mają tryb 600, a katalog
założony przez skrypt 700 — zrzut zawiera dane osobowe.

## Kontrola świeżości

```bash
BACKUP_DIR=/root/backups/db sh /root/Saas-Core/infra/postgres/backup.sh check hoofcare
# OK hoofcare: newest good dump hoofcare-20261007T003000Z.dump, 6 h 12 min old (limit 26 h), 3392564 bytes; 4 kept in /root/backups/db
```

| Pierwsze słowo | Kod wyjścia | Znaczenie |
| --- | --- | --- |
| `OK` | 0 | najnowsza dobra kopia jest młodsza niż `BACKUP_MAX_AGE_HOURS` (26) |
| `STALE` | 1 | dobra kopia istnieje, ale jest starsza niż limit |
| `MISSING` | 2 | w katalogu nie ma żadnej dobrej kopii tego stacku |

Dobra kopia to plik `.dump` z pasującą sumą SHA-256 (suma jest liczona przy
każdej kontroli, więc uszkodzony plik przestaje się liczyć). Wiek liczy się od
czasu w nazwie, czyli od startu zrzutu — to jest stan danych, który kopia
zawiera. Kontrola nie potrzebuje działającego stacku ani Dockera.

## Harmonogram: cron hosta

Na VPS-ie plik `/etc/cron.d/saas-core-backup` (właściciel root, tryb 644):

```cron
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
BACKUP_DIR=/root/backups/db
30 2 * * * root sh /root/Saas-Core/infra/postgres/backup.sh run saas-core >>/root/backups/db/backup.log 2>&1
40 2 * * * root sh /root/Saas-Core/infra/postgres/backup.sh run hoofcare >>/root/backups/db/backup.log 2>&1
50 2 * * * root sh /root/Saas-Core/infra/postgres/backup.sh run medplano >>/root/backups/db/backup.log 2>&1
```

Trzy stacki obsługuje skrypt z `/root/Saas-Core`, więc produkty nie czekają na
swoją aktualizację rdzenia. Katalog trzeba założyć raz
(`install -d -m 700 /root/backups/db`), bo przekierowanie logu działa przed
skryptem.

Dlaczego cron hosta, a nie usługa w Compose ani zadanie schedulera:

- **scheduler odpada.** Kontener celery beat ma limit 256 MiB i sam zajmuje
  129–153 MiB, czyli 50–60% (szczyt od startu 135–159 MiB; `docker stats`
  i `memory.peak` na trzech lokalnych stackach, 06.10.2026, zero zdarzeń OOM).
  Usługa nie jest więc blisko limitu i limit zostaje. Jedyny proces w kontenerze
  — beat z załadowaną aplikacją — ma 148–173 MiB RSS, więc drugi taki proces
  obok niego (`docker exec … manage.py`) przekracza 256 MiB i ginie z kodem 137,
  co było widać na VPS-ie. Jednorazowe komendy `manage.py` uruchamia się
  w osobnym kontenerze;
- **usługa w Compose** oznaczałaby nowy, stale działający kontener w każdym
  z trzech stacków, własny obraz albo pętlę `sleep`, montowanie katalogu hosta
  i przebudowę przy każdej zmianie skryptu. Kopia zatrzymywałaby się razem ze
  stackiem;
- **cron** to trzy linie poza gitem (dlatego są we wpisie kolejki `memex ops`
  i tutaj), zero zmian w obrazach i w `compose.yaml`. `pg_dump` działa
  w kontenerze bazy, który nie ma limitu pamięci, a plik powstaje na hoście.

Zrzut trzyma na tabelach blokadę `ACCESS SHARE`: nie zatrzymuje odczytów ani
zapisów, a migracja uruchomiona w trakcie poczeka na jego koniec (lokalnie
zrzut trwa sekundę).

## Czego ta kopia nie obejmuje

- **Pliki firm (object storage).** Zdjęcia, załączniki i media stron leżą
  w wolumenie `object-storage-data`, nie w bazie. **Nic ich nie kopiuje według
  harmonogramu.** Jedyna dotąd kopia to ręczny `tar` wolumenu przed wdrożeniem
  (krok K2 instrukcji `desk/runbook-vps-2026-10-05.md` w memeksie).
- **Kopia poza hostem.** Zrzuty leżą na tym samym dysku co baza. Chronią przed
  złą migracją, błędem operatora i uszkodzeniem danych, nie przed utratą dysku
  lub hosta. ADR-025 wymaga dla stagingu szyfrowanej kopii poza VPS-em — ta
  bramka pozostaje niespełniona (niżej: decyzja właściciela).
- **Sekrety i konfiguracja**: katalog sekretów stacku, pliki `.env*`, linie
  crona. Bez sekretów odtworzona baza jest nieczytelna tam, gdzie pola są
  szyfrowane.
- **Role PostgreSQL.** Zrzut jednej bazy nie zawiera ról ani haseł; tworzy je
  usługa `database-bootstrap` z sekretów.
- **Redis** (kolejka zadań, cache, pamięć podręczna sesji), **indeks
  wyszukiwarki** (odbudowuje go `reindex_catalog`,
  [wyszukiwarka katalogu](catalog-search.md)), certyfikaty Caddy, logi, poczta
  zapisana do plików.

## Próba odtworzenia

```bash
BACKUP_DIR=/root/backups/db sh /root/Saas-Core/infra/postgres/restore-drill.sh hoofcare
```

Skrypt sprawdza sumę, zakłada bazę `restore_drill_<czas>_<pid>` obok bazy stacku
(`createdb` odmawia istniejącej nazwy, więc próba nie może trafić w istniejącą
bazę), odtwarza do niej zrzut (`pg_restore --exit-on-error --no-owner`),
porównuje ze źródłem i usuwa bazę tymczasową — także przy błędzie. Nie uruchamia
żadnego kontenera aplikacji.

- **Schemat musi być identyczny**: liczba tabel, indeksów, ograniczeń, sekwencji,
  wyzwalaczy, polityk RLS, tabel z wymuszonym RLS i zastosowanych migracji.
  Różnica kończy próbę błędem.
- **Wiersze** są liczone w każdej tabeli po obu stronach. Źródło żyje, więc
  tabele zapisane po zrzucie mogą się różnić: skrypt je wypisuje i nie uznaje
  tego za błąd. Kto chce równości co do wiersza, robi zrzut tuż przed próbą.

Raport trafia do `.runtime/reports/restore-drill-<stack>-<czas>.json`.

Próba z 06.10.2026 na lokalnym stacku `:8080` (baza `saas_core_w3`): zrzut
3 760 738 bajtów w 1 s, odtworzenie i porównanie 10 s; 194 tabele, 986 indeksów,
2973 ograniczenia, 149 polityk RLS, 144 tabele z wymuszonym RLS, 284 migracje —
identycznie; 17 183 wiersze po obu stronach, 0 tabel z inną liczbą wierszy
(trzy przebiegi, 7–10 s każdy).
Sprawdzone też ścieżki błędu: ucięty plik (odczyt kontrolny i `pg_restore`
kończą się błędem), zła suma, zrzut ze starszym schematem (różnica schematu) —
za każdym razem baza tymczasowa została usunięta.

## Odtworzenie bazy stacku

Odtwarza się do **nowej bazy obok**, a dopiero po kontroli zamienia nazwy. Stara
baza zostaje pod nazwą `<baza>_replaced`, dopóki ktoś jej świadomie nie usunie:
nieudane odtworzenie niczego nie niszczy.

Odtworzenie cofa stack do chwili zrzutu — wszystko, co ludzie zapisali później,
znika z bazy. To decyzja właściciela, nie operatora.

```bash
s=hoofcare                                          # saas-core | hoofcare | medplano
dump=/root/backups/db/hoofcare-20261007T003000Z.dump
# wywołanie Compose tego stacku na VPS-ie:
#   saas-core: cd /root/Saas-Core && C="docker compose -f compose.yaml -f compose.vps.yaml"
#   hoofcare:  cd /root/HoofCare  && C="docker compose --env-file .env.hoofcare -f compose.yaml -f compose.hoofcare.yaml"
#   medplano:  cd /root/MedPlano  && C="docker compose --env-file .env.medplano -f compose.yaml -f compose.medplano.yaml"
pg() { docker exec -i "$s-postgres-1" sh -c 'export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" PGHOST=127.0.0.1 PGUSER="$POSTGRES_USER"; '"$1"; }

# 1. kopia jest cała
(cd "$(dirname "$dump")" && sha256sum --check "$(basename "$dump").sha256")

# 2. zatrzymaj wszystko, co pisze do bazy (worker-ai tylko tam, gdzie działa)
$C stop backend worker scheduler frontend

# 3. zachowaj stan obecny — osobny katalog, żeby nie wszedł do serii z harmonogramu
BACKUP_DIR=/root/backups/db/before-restore sh /root/Saas-Core/infra/postgres/backup.sh run "$s"

# 4. odtwórz do nowej bazy obok i policz
pg 'createdb "${POSTGRES_DB}_restored"' </dev/null
pg 'pg_restore --exit-on-error --no-owner --dbname "${POSTGRES_DB}_restored"' <"$dump"; echo "pg_restore: $?"
pg 'psql -X -At -d "${POSTGRES_DB}_restored" -c "select count(*) from pg_tables where schemaname = current_schema()" -c "select count(*) from django_migrations"' </dev/null

# 5. zamień nazwy (wymaga, żeby nikt nie był połączony z żadną z dwóch baz)
pg 'psql -X -v ON_ERROR_STOP=1 -d postgres -c "ALTER DATABASE \"$POSTGRES_DB\" RENAME TO \"${POSTGRES_DB}_replaced\"" -c "ALTER DATABASE \"${POSTGRES_DB}_restored\" RENAME TO \"$POSTGRES_DB\""' </dev/null

# 6. wyczyść Redis: kolejka i cache opisują stan, którego baza już nie ma
docker exec "$s-redis-1" redis-cli FLUSHALL

# 7. uruchom stack (database-bootstrap i migrate wykonają się ponownie) i sprawdź
$C up -d
curl -s -o /dev/null -w '%{http_code}\n' https://<domena stacku>/healthz
```

Po odbiorze:

- przebuduj indeks wyszukiwarki (`reindex_catalog`, w osobnym kontenerze —
  [wyszukiwarka katalogu](catalog-search.md));
- pliki dodane po zrzucie zostają w object storage jako nieużywane, a pliki
  usunięte po zrzucie nie wrócą — baza będzie na nie wskazywać;
- starą bazę usuń dopiero na decyzję właściciela:
  `pg 'dropdb "${POSTGRES_DB}_replaced"' </dev/null`.

Jeśli krok 5 odmawia („database is being accessed by other users”), ktoś jest
połączony — zwykle eksporter metryk (`postgres-exporter`, profil
`observability`); zatrzymaj go na czas zamiany.

Co z tej procedury było ćwiczone: kroki 1, 3, 4 i 5 lokalnie 06.10.2026, przy
czym zamiana nazw na dwóch bazach tymczasowych, nie na bazie działającego
stacku. Kroki 2, 6 i 7 nie były ćwiczone w tej sekwencji; pierwsze użycie na
VPS-ie przeczytaj razem z właścicielem.

### Nowy host

Na pustym serwerze potrzebne są najpierw sekrety i pliki środowiska stacku
(nie ma ich w zrzucie ani w gicie). Potem: `$C up -d postgres`,
`$C run --rm database-bootstrap` (role, na które wskazują uprawnienia i polityki
RLS w zrzucie — bez nich `pg_restore --exit-on-error` zatrzyma się na pierwszym
`GRANT`), `pg_restore` wprost do pustej `$POSTGRES_DB` jak w kroku 4 i `$C up -d`.
Ta ścieżka nie była ćwiczona.

## Kopia poza hostem — decyzja właściciela

Nie jest skonfigurowana: kosztuje i przenosi dane osobowe do podmiotu trzeciego.

- **a) zostaje jak jest** — kopie tylko na dysku VPS-a. Koszt zero, żadnego
  nowego podmiotu przetwarzającego. Utrata dysku, hosta albo konta u dostawcy
  VPS-a zabiera bazę razem z kopiami; bramka ADR-025 pozostaje niespełniona;
- **b) zaszyfrowana kopia w buckecie S3 w UE** — zrzut szyfrowany na hoście
  kluczem publicznym (klucz prywatny poza VPS-em), wysyłany po każdym udanym
  przebiegu, z własną retencją i kontrolą świeżości po stronie bucketa. Wymaga
  wyboru dostawcy, umowy powierzenia przetwarzania i dopisania go do listy
  podmiotów przetwarzających, miesięcznej opłaty za przechowywanie oraz
  miejsca na klucz prywatny. Dostawca widzi tylko szyfrogram.

Rekomendacja: **b**, zanim w którymkolwiek stacku pojawią się dane firmy, która
płaci albo której nie da się poprosić o ponowne wpisanie danych — razem z kopią
plików z object storage, bo dziś nie chroni ich nic. Skrypt jest na to gotowy:
wysyłka to jeden krok po `backup.sh run`, a `check` zostaje bez zmian.
