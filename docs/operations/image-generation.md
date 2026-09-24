# Runbook — generator obrazów AI (ADR-059)

Klient zleca obraz w Site Studio, `worker-ai` woła OpenAI Image API na
kolejce `ai`, obraz przechodzi zwykły potok mediów (skan, XMP, warianty), a
kredyty są pobierane dopiero po `READY`. Funkcja jest fail-closed: bez klucza,
bez żywego `worker-ai`, przy nieaktywnej operacji kredytowej albo blokadzie
dostawcy oferta mówi `available=false`, a zlecenie dostaje
`503 image_generation_unavailable`.

## Przed udostępnieniem klientom

Wszystkie cztery warunki, nie mniej:

1. Klucz właściciela zainstalowany (niżej) i jeden udany obraz na instancji
   deweloperskiej: zlecenie `succeeded`, `curl /media/<id> | grep
   trainedAlgorithmicMedia`, odznaka „AI” na opublikowanej stronie.
2. Organizacja OpenAI w **Tier ≥ 2** (Tier 1 to 5 obrazów/min na całą
   organizację).
3. **Osobny projekt OpenAI na produkt** (Business, HoofCare, MedPlano) z
   **twardym limitem wydatków** ustawionym w projekcie. Wyczerpany limit
   blokuje tylko ten produkt.
4. Prawnik przejrzał projekt zmian regulaminu, AUP i DPA (plan w memeksie,
   nie w repo); pilot IG-0 pokazał, że SynthID przeżywa normalizację (inaczej
   najpierw podpis C2PA z IG-3).

## Zanim wdrożysz tę gałąź na stos (każdy stos, także bez klucza)

Plik klucza montują `backend` i `worker-ai`, więc musi istnieć przed
`up`, także pusty (pusty = funkcja wyłączona). Brak pliku: Compose nie tworzy
kontenera `backend` („bind source path does not exist”). Na hoście Linux prawa
`0644` w katalogu `0700` — usługi działają jako `app` (uid 10001), a `0600`
roota jest dla nich nieczytelne i settings padają przy starcie:

```
# vps-dev: .runtime/secrets; HoofCare: .runtime-hoofcare/secrets; MedPlano: .runtime-medplano/secrets
f=.runtime/secrets/image_generation_openai_api_key
test -f "$f" || install -m 0644 /dev/null "$f"   # nie zeruje istniejącego klucza
```

Staging: plik w `/opt/saas-core/secrets`; deploy sprawdza, że jest.

`worker-ai` jest w `compose.yaml` za profilem `image-generation`: stos bez
profilu nie ma go wcale. Włącza go `COMPOSE_PROFILES=image-generation` w pliku
env stosu (`.env` na vps-dev, `.env.<produkt>` produktu); staging nazywa usługę
wprost w skryptach deployu.

## Instalacja i rotacja klucza

1. Klucz z projektu OpenAI danego produktu zapisz do
   `${SAAS_CORE_SECRETS_DIR}/image_generation_openai_api_key` (na Linuksie
   prawa `0644`, patrz wyżej; bez historii powłoki; szczegóły w
   [secrets.md](secrets.md)).
2. Odtwórz usługi, które go czytają, **z plikami overlayu danego stosu** (samo
   `docker compose up` bierze tylko `compose.yaml`: na vps-dev backend traci
   `ALLOWED_HOSTS` i odpowiada 400, w katalogu produktu trafia w projekt
   `saas-core`):
   - vps-dev: `docker compose -f compose.yaml -f compose.vps.yaml up -d
     --force-recreate backend worker-ai`;
   - produkt: `docker compose --env-file .env.<produkt> -f compose.yaml -f
     compose.<produkt>.yaml up -d --force-recreate backend worker-ai`.
3. W ciągu minuty zadanie uzgadniające zostawia ślad życia workera; oferta
   (`GET /api/v1/image-generation/offer/`) zaczyna mówić `available: true`.

Rotacja: nowy klucz w tym samym projekcie OpenAI, podmiana pliku, ten sam
recreate, dopiero potem unieważnienie starego klucza w OpenAI. `worker-ai` ma
`stop_grace_period: 200s` (timeout dostawcy 150 s plus zapis), więc recreate
czeka, aż wywołania w toku się skończą. Gdyby jednak coś je przerwało, zlecenie
kończy się `provider_result_unknown` bez obciążenia klienta i bez drugiego
płatnego wywołania.

## `worker-ai`

Osobna usługa (`-Q ai --concurrency=2`), żeby wywołania do 150 s nie blokowały
skanowania mediów. Produkt, który ma moduł `shared.image-generation`, po
`core:update` **musi** dopisać ją do swojego overlayu (HoofCare
`compose.hoofcare.yaml`, MedPlano `compose.medplano.yaml`) z obrazem, env i
sekretami tego produktu, tak jak `worker`, i dopiero wtedy włączyć profil
`image-generation`. Kolejność ma znaczenie: z profilem, a bez wpisu w overlayu,
`worker-ai` dziedziczy obraz `saas-core-backend:local` — `--build` nadpisze nim
obraz stosu Saas-Core (ostatni build wygrywa), a bez `--build` worker ruszy na
obrazie vps-dev i padnie na niezgodności artefaktu. Bez profilu usługi nie ma
wcale, brak śladu życia trzyma ofertę na `available=false` — funkcja jest
wtedy wyłączona, nie zepsuta.

Ślad życia odświeża zarówno zadanie uzgadniające, jak i start każdego
zlecenia, więc zajęty worker nie gasi oferty. Tyknięcie uzgadniające, którego
nikt nie odebrał w 2 minuty, wygasa w kolejce, zamiast czekać na worker.

## Blokada dostawcy (`provider_blocked`)

Klucz cache `image_generation:provider_blocked` ustawia worker na godzinę, gdy
OpenAI odpowie `insufficient_quota` albo `billing_hard_limit_reached` (limit
wydatków; przychodzi jako 400 albo 429) albo odrzuci klucz (`401`/`403`). Oferta jest wtedy niedostępna dla wszystkich organizacji tego
deploymentu. Znika sama po TTL albo ręcznie, po usunięciu przyczyny:

```
docker compose exec backend python manage.py shell -c \
  "from django.core.cache import cache; cache.delete('image_generation:provider_blocked')"
```

Najpierw usuń przyczynę (podnieś limit w projekcie OpenAI, podmień klucz), bo
następne zlecenie od razu ustawi blokadę ponownie.

## Co widać w danych

- `image_generation_imagegenerationjob` (FORCE RLS): stan, `error_code`,
  `cost_usd_micros`, `provider_request_id`, `attempts`. Prompt jest czyszczony
  przy stanie końcowym; odmowa (`refused`) trzyma go 30 dni jako dowód
  nadużycia.
- Audyt organizacji: `image_generation.requested` i `image_generation.<stan>`
  z `prompt_sha256` i długością, nigdy z treścią promptu.
- Prompt ani klucz nie trafiają do logów. Po każdej zmianie w tym module:
  `docker compose logs backend worker-ai | grep -ci '<fragment promptu>'`
  musi dać 0.

## Limity

- 2 aktywne zlecenia na organizację (`429 image_generation_busy`);
- 5 odmów moderacji w 24 h blokuje organizację do końca okna
  (`429 image_generation_refusal_limit`);
- miesięczny limit prób `image_generation.monthly` liczy każdą próbę, także
  odrzuconą (`409 quota_exceeded`);
- przed zleceniem rezerwujemy 3 MiB `storage.bytes`, więc pełny dysk odmawia,
  zanim zapłacimy dostawcy. Gotowy obraz liczy się do `storage.bytes` razem z
  zachowanym oryginałem dostawcy (kopia dowodowa).

## ClamAV niedostępny

Zlecenie zostaje w `ingesting` z backoffem (do 10 min), a rezerwa storage
zasobu jest przedłużana przy każdej próbie. Gdy rezerwa mimo to przepadnie
(zwolniona, wygasła, organizacja straciła dostęp), zasób kończy jako
`rejected` z usuniętymi plikami, a zlecenie jako `failed`
(`media_quota_unavailable`) bez obciążenia klienta — nie ma doby ponowień.
Błąd storage albo bazy przy zapisie wyniku kończy zlecenie jako
`ingest_storage_error` z kosztem i `provider_request_id` do uzgodnienia z
fakturą OpenAI.

## Odznaka „AI” (przełącznik operatora)

Widoczne oznaczenie na stronach klientów przełącza wyłącznie operator
platformy (`is_staff` + potwierdzone MFA), dla całego deploymentu:

```
python manage.py set_ai_badge --operator <e-mail> --off --reason "…"
python manage.py set_ai_badge --operator <e-mail> --on --reason "…"
python manage.py set_ai_badge --show
```

Każda zmiana to nowy wiersz z autorem i powodem. Znacznik XMP w plikach zostaje
zawsze, niezależnie od przełącznika. Panel czyta stan przełącznika z oferty
(`badge_visible`): przy wyłączonej odznace nie obiecuje klientowi oznaczenia na
stronie i nie rysuje odznaki w podglądzie.
