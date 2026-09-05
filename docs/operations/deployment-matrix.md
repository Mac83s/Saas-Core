# Wiele produktów z jednego repozytorium

Jedno repozytorium buduje kilka produktów, a każdy aktualizuje się we własnym
tempie. Ten dokument opisuje dwie rzeczy, których to wymaga: **co odróżnia
obrazy jednego produktu od drugiego** i **co musi być osobne, żeby dwa
deploymenty stały obok siebie, nie wchodząc sobie w dane**.

Kompozycję samą w sobie opisuje [profil deploymentu](../architecture/deployment-profile.md).
Sekwencję wdrożenia i rollback na stagingu — [staging](staging.md).

## 1. Obraz należy do produktu, nie do commita

Backend i frontend niosą profil, więc jeden commit produkuje **po jednym
obrazie na profil**. Tag to `sha-<commit>-<profil>`; obrazy bez profilu (Caddy,
Redis) zostają przy `sha-<commit>`.

Do 2026-09-05 backend budował się **bez** argumentu `DEPLOYMENT`, czyli jako
`core-only`, i lądował w rejestrze obok frontendu zbudowanego jako `business`.
Nic tego nie zgłaszało, bo backend i tak instalował wszystkie moduły. Dziś taka
para nie wstanie: obraz niesie
[artefakt modułów](../architecture/deployment-profile.md) i hash profilu, a
frontend porównuje go z backendem przez `/healthz`.

## 2. Wiersz macierzy

```bash
docker compose exec backend python manage.py deployment_release \
  --image backend=sha256:… --image frontend=sha256:…
```

Komenda wypisuje JSON, który jest jednym wierszem macierzy
`deployment → wersja/digest → migracje → rollback`:

| pole                    | co znaczy                                                    |
| ----------------------- | ------------------------------------------------------------ |
| `deployment`            | profil, którym proces wstał                                   |
| `profileHash`           | odcisk palca kompozycji; musi się zgadzać we wszystkich obrazach |
| `version`               | `APPLICATION_VERSION` z obrazu                                |
| `images`                | digesty podane przez wdrażającego — proces nie zna własnego    |
| `migrations.shipped`    | ostatnia migracja każdej aplikacji **w obrazie**              |
| `migrations.applied`    | ostatnia migracja każdej aplikacji **w bazie**; `null`, gdy proces nie ma bazy |
| `migrations.pending`    | aplikacje, w których obraz wyprzedza bazę                     |
| `rollback.irreversible` | migracje, których nie da się cofnąć                           |

Wiersz zapisuje się razem z manifestem release'u (`state/` na hoście, patrz
[staging](staging.md)). Digestów nie zgaduje się z tagu `latest`: rollback
odtwarza obrazy po `repo@sha256`.

## 3. Kiedy rollback jest możliwy

Trzy warunki, wszystkie sprawdzalne przed wdrożeniem, nie po awarii:

1. **Migracje dają się cofnąć.** `rollback.irreversible` jest puste, a pilnuje
   tego test `tests/test_deployment_release.py`: migracja bez odwrotności
   odbiera rollback każdemu deploymentowi za nią, więc musi być dopisana do
   `KNOWN_IRREVERSIBLE` z powodem albo dostać odwrotność. Dziś lista jest pusta
   i wszystkie 90 migracji jest odwracalnych.
2. **Schemat wyprzedza kod, nigdy odwrotnie.** Migracje idą w trybie
   expand/contract, bo rollback aplikacji nie cofa schematu ani danych — kod
   sprzed release'u musi umieć czytać schemat po nim.
3. **Obrazy cofają się parami.** Backend i frontend tego samego profilu mają
   ten sam `profileHash`; cofnięcie jednego bez drugiego kończy się 503 na
   `/healthz` frontendu, a nie cichym menu prowadzącym w 404.

„Odwracalna" nie znaczy „nieszkodliwa": cofnięcie migracji danych przywraca
kształt wierszy, a nie wiersze, które zniknęły. Znaczy tyle, że schemat da się
przejść wstecz — i to jest ta część, na której można oprzeć decyzję.

## 4. Co musi być osobne dla każdego deploymentu

Granicą jest **projekt Compose**. `COMPOSE_PROJECT_NAME` (albo `-p`) ma
pierwszeństwo przed `name:` w pliku, a projekt daje osobne kontenery, sieć i
wolumeny — czyli osobny PostgreSQL, Redis i storage obiektowy.

Na tym poziomie wystarczy różny projekt. Zmienne poniżej są potrzebne wtedy,
gdy dwa deploymenty **dzielą infrastrukturę** (jeden serwer PostgreSQL, jedno
S3) albo jeden host:

| zasób                | zmienna                              | dlaczego osobno                                     |
| -------------------- | ------------------------------------ | --------------------------------------------------- |
| profil               | `DEPLOYMENT`                         | decyduje o całej kompozycji                          |
| baza danych          | `SAAS_CORE_POSTGRES_DB`              | dane produktów nie mieszają się nigdy                |
| rola migracyjna      | `SAAS_CORE_POSTGRES_MIGRATION_USER`  | właściciel schematu jednego produktu                 |
| rola aplikacyjna     | `SAAS_CORE_POSTGRES_APP_USER`        | `NOBYPASSRLS`, podlega politykom tej bazy            |
| rola drzwi           | `SAAS_CORE_POSTGRES_IDENTITY_USER`   | odczyty sprzed tenanta (ADR-041), też per baza       |
| sekrety              | `SAAS_CORE_SECRETS_DIR`              | osobny komplet haseł i kluczy                        |
| storage obiektowy    | `OBJECT_STORAGE_BUCKET`              | media jednego produktu nie trafiają do drugiego      |
| ciasteczko sesji     | `SESSION_COOKIE_NAME`                | dwa produkty w jednej przeglądarce nie dzielą sesji  |
| logi                 | `SAAS_CORE_LOGS_DIR`                 | rozdzielone źródła dla Loki                          |
| poczta deweloperska  | `SAAS_CORE_EMAILS_DIR`               | wiadomości jednego produktu nie mylą się z drugim    |
| region storage       | `OBJECT_STORAGE_REGION`              | może różnić się przy wymogu lokalizacji danych       |
| port HTTP            | `SAAS_CORE_HTTP_PORT`                | dwa stacki na jednym hoście                          |
| port PostgreSQL      | `SAAS_CORE_POSTGRES_PORT`            | jw.                                                  |
| port Redis           | `SAAS_CORE_REDIS_PORT`               | jw.                                                  |
| port S3              | `SAAS_CORE_S3_PORT`                  | jw.                                                  |
| port Grafany         | `SAAS_CORE_GRAFANA_PORT`             | jw.                                                  |

Listę pilnuje `tests/test_deployment_isolation.py`: zmienna sparametryzowana w
`compose.yaml`, której nie ma w tej tabeli, psuje test — i odwrotnie. Dokument,
którego nikt nie sprawdza, przestaje być prawdziwy przy pierwszej zmianie.

Domena jest osobna z definicji (`product.platformDomain` w profilu), a
obserwowalność rozdziela etykieta `deployment` w metrykach i logach — patrz
[obserwowalność](observability.md).

## 5. Czego jeszcze nie ma

- backup jest opisany dla jednego stacku ([backup i restore](backup-restore.md));
  drugi deployment potrzebuje własnego harmonogramu i własnego restore drilla;
- `deploy staging` obsługuje jeden produkt na host; drugi wymaga osobnego
  katalogu wdrożenia i osobnego GitHub Environment.
