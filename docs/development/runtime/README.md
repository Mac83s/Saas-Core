# Lokalny test publicznej strony business

Te dwa skrypty są przeznaczone dla izolowanego stosu integracyjnego, nie dla bazy
użytkowników. `business-public-fixture.py` wymaga równocześnie `APP_ENV=local`,
`DEPLOYMENT=business` i jawnego `SEO_RUNTIME_SMOKE=synthetic-local`.

Fixture tworzy nową organizację z kontem bez hasła, właścicielem, uprawnieniami
testowego planu, stroną i obrazem PNG w rzeczywistym lokalnym S3. Publikację wykonuje
usługa domenowa z kontekstem osobowego właściciela. Domena jest oznaczana jako
zweryfikowana, a obraz jako gotowy na potrzeby testu. Nie jest to dowód działania
DNS, onboardingu, uploadu ani skanera malware. Każde wykonanie tworzy osobną fixture;
nie podaje się istniejącego identyfikatora organizacji. Nie są wykonywane żądania
do zewnętrznych dostawców.

Przykład PowerShell dla przygotowanego projektu `seo-core-pilot` na porcie 8896:

```powershell
. .runtime/seo-stack/env.ps1
if ($env:COMPOSE_PROJECT_NAME -ne 'seo-core-pilot') { throw 'Unexpected project' }
docker compose up -d --no-build caddy object-storage scheduler
Get-Content -Raw docs/development/runtime/business-public-fixture.py |
  docker compose exec -T -e SEO_RUNTIME_SMOKE=synthetic-local backend python - >
  .runtime/seo-stack/public-fixture.json
if ($LASTEXITCODE -ne 0) { throw 'Fixture failed' }

python docs/development/runtime/business-public-smoke.py `
  --fixture .runtime/seo-stack/public-fixture.json `
  --output .runtime/seo-stack/evidence-business.json
```

Smoke wykonuje wyłącznie odczyty HTTP na loopback, zachowując syntetyczny Host.
Sprawdza HTML i zawarty w nim rzeczywisty adres obrazu `/media/{id}`, sitemap,
identyczność bajtów PNG przez frontend i API, 404 obrazu dla obcego hosta oraz
gotowość backendu i frontendu. Przekierowania nie mogą wyjść poza lokalny stos;
ewentualny kanoniczny host fixture nadal jest odpytywany fizycznie przez loopback.

Opcjonalne `--source-hashes` wskazuje JSON mapujący ścieżkę każdego `.py` pod
`/app/src` na SHA-256, pobrany z uruchomionego backendu. Wtedy skrypt porównuje go
z `apps/backend/src` i odmawia zielonego wyniku przy różnicach. Uzupełnieniem jest
wiersz `deployment_release --image backend=sha256:... --image frontend=sha256:...`
z rzeczywistymi identyfikatorami obu uruchomionych obrazów. Przechowuj go obok
dowodu HTTP. Lokalne identyfikatory obrazu nie oznaczają opublikowania w registry.

Nie commitujemy `.runtime`: może zawierać lokalne sekrety i logi. W dowodach
pozostają tylko publiczne identyfikatory fixture, hashe, statusy, polityka roli
bazodanowej i jawne ograniczenia testu. Stos i syntetyczne dane są zachowane do
przeglądu; ich usunięcie powinno dotyczyć wyłącznie tego projektu Compose.
