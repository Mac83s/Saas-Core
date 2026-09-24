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

## Instalacja i rotacja klucza

1. Klucz z projektu OpenAI danego produktu zapisz do
   `${SAAS_CORE_SECRETS_DIR}/image_generation_openai_api_key` (prawa `0600`,
   bez historii powłoki; szczegóły w [secrets.md](secrets.md)).
2. Odtwórz usługi, które go czytają:
   `docker compose up -d --force-recreate backend worker-ai`.
3. W ciągu minuty zadanie uzgadniające zostawia ślad życia workera; oferta
   (`GET /api/v1/image-generation/offer/`) zaczyna mówić `available: true`.

Rotacja: nowy klucz w tym samym projekcie OpenAI, podmiana pliku, ten sam
recreate, dopiero potem unieważnienie starego klucza w OpenAI. Zlecenia w toku
nie giną: wywołanie przerwane restartem kończy się `provider_result_unknown`
bez obciążenia klienta i bez drugiego płatnego wywołania.

## `worker-ai`

Osobna usługa (`-Q ai --concurrency=2`), żeby wywołania do 150 s nie blokowały
skanowania mediów. Musi istnieć w overlayu każdego produktu, który ma moduł
`shared.image-generation` (HoofCare `compose.hoofcare.yaml`, MedPlano
`compose.medplano.yaml`) z obrazem tego produktu, tak jak `worker`. Dopóki go
nie ma, brak śladu życia trzyma ofertę na `available=false` — funkcja jest
wyłączona, nie zepsuta.

## Blokada dostawcy (`provider_blocked`)

Klucz cache `image_generation:provider_blocked` ustawia worker na godzinę, gdy
OpenAI odpowie `429 insufficient_quota` (limit wydatków) albo odrzuci klucz
(`401`/`403`). Oferta jest wtedy niedostępna dla wszystkich organizacji tego
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
  zanim zapłacimy dostawcy.

## Odznaka „AI” (przełącznik operatora)

Widoczne oznaczenie na stronach klientów przełącza wyłącznie operator
platformy (`is_staff` + potwierdzone MFA), dla całego deploymentu:

```
python manage.py set_ai_badge --operator <e-mail> --off --reason "…"
python manage.py set_ai_badge --operator <e-mail> --on --reason "…"
python manage.py set_ai_badge --show
```

Każda zmiana to nowy wiersz z autorem i powodem. Znacznik XMP w plikach zostaje
zawsze, niezależnie od przełącznika.
