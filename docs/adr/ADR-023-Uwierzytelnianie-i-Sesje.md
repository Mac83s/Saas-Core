# ADR-023 — uwierzytelnianie i sesje

**Status:** Accepted  
**Data:** 2026-08-10  
**Właściciel:** zespół SaaS Core

## Kontekst

Panel Next.js i API Django muszą działać bez tokenów w localStorage, z ochroną
CSRF, możliwością natychmiastowego unieważnienia sesji i bez współdzielenia
cookie z publicznymi stronami klientów.

## Decyzja

ADR-013 zostaje przyjęty jako **same-origin Django session**.

### Topologia

```text
browser -> https://app.medplano.pl
        -> Caddy
           /api/v1/* -> Django
           pozostałe  -> Next.js

integracje -> https://api.medplano.pl/api/v1/* -> Django
operatorzy -> osobny host Django Admin
```

Panel wywołuje relatywne `/api/v1`, więc dla przeglądarki frontend i API są
same-origin. Caddy proxy nie zmienia kontraktu ani nie przechowuje sesji.
Publiczny host API nie akceptuje cookie panelu; w W8 otrzyma scoped API keys lub
OAuth. Next.js nie wydaje własnych JWT i nie jest źródłem tożsamości.

### Sesja i cookie

- Django `cached_db`: PostgreSQL jest źródłem, Redis przyspiesza odczyt;
- session cookie: losowy opaque id, `HttpOnly`, `Secure`, `SameSite=Lax`,
  host-only, `Path=/`, osobna nazwa per deployment;
- CSRF cookie: `Secure`, `SameSite=Lax`, host-only i czytelny dla klienta, aby
  wysłać `X-CSRFToken` zgodnie z Django;
- brak `Domain=.medplano.pl`, aby publiczne subdomeny nie otrzymały cookie;
- rotacja session key po loginie, zmianie hasła i operacji podniesienia poziomu;
- logout i odebranie membership unieważniają właściwe sesje;
- aktywna organizacja jest stanem serwerowej sesji, ponownie walidowanym przy
  każdym requestcie.

### Next.js

- ochronę routingu traktujemy jako UX; autoryzacja zawsze jest w Django;
- Server Components przekazują cookie tylko do zaufanego, wewnętrznego backendu;
- Client Components używają typed clienta z `credentials: same-origin`;
- mutacje pobierają CSRF i wysyłają nagłówek, bez kopiowania session cookie;
- cache odpowiedzi prywatnych jest wyłączony lub jawnie użytkownikowy.

### Bezpieczeństwo

- dokładna allowlista hostów i `CSRF_TRUSTED_ORIGINS`;
- CORS dla panelu nie jest potrzebny i pozostaje wyłączony;
- rate limiting loginu, resetu i weryfikacji po IP oraz identyfikatorze konta;
- ogólne odpowiedzi zapobiegają enumeracji kont;
- osobny host, cookie name, 2FA i dodatkowe ograniczenia dla Django Admin;
- sesje są widoczne dla użytkownika i indywidualnie unieważnialne.

## Konsekwencje

- odpada rotacja access/refresh tokenów w przeglądarce;
- same-origin upraszcza CSRF/CORS i ogranicza ekspozycję cookie;
- `cached_db` zachowuje możliwość revocation po utracie cache;
- publiczne API wymaga osobnego mechanizmu machine-to-machine w W8;
- preview na innych hostach nie może automatycznie współdzielić cookie panelu —
  użyje krótkotrwałego, jednorazowego tokenu preview.

## Uzupełnienie 2026-10-01 — Django Admin tylko po MFA i nie z internetu

Osobny host Django Admin z 2FA nie powstał, a `/internal/admin/` miał
domyślne logowanie Django: samo hasło konta `is_staff` otwierało edycję
`User.is_staff` i superusera, a bramy VPS i stagingu przepuszczały ten adres.
Od 2026-10-01:

- admin nie ma własnego logowania: `MfaAdminSite`
  (`core/identity/admin_site.py`, instalowany przez `MfaAdminConfig`) przyjmuje
  wyłącznie sesję panelu (`identity_user_session_id`) z oznaczeniem
  `identity_mfa_verified_at`, które nadaje tylko logowanie z drugim
  składnikiem albo pierwsze włączenie MFA konta operatora; formularz
  `/internal/admin/login/` odpowiada 403;
- `ManagedUserSessionMiddleware` sprawdza także ścieżki admina, więc sesja
  spoza panelu jest wylogowywana, a nie przyjmowana;
- `Caddyfile.vps` i `Caddyfile.staging` zamykają dla internetu całe
  `/internal/*` (admin, metryki, pytanie o zgodę na certyfikat, interfejs
  Swagger) blokiem `handle @private` postawionym przed `handle @api` —
  zamknięte domyślnie, bo lista zakazanych ścieżek przeoczyła admina. Sam
  schemat OpenAPI (`/api/schema/`) pozostaje publiczny jak dotąd. Dotychczasowa reguła `respond @private 404`
  nie działała od 2026-08-12: Caddy sortuje `respond` za każdym `handle`, więc
  metryki bez uwierzytelnienia i pytanie o zgodę na certyfikat były publiczne.
  Sprawdzone `caddy adapt` i próbą na Caddy 2.11.4 (wersja z
  `infra/caddy/Dockerfile`). `Caddyfile.local` zostawia `/internal/*` otwarte,
  bo admin jest tu narzędziem dewelopera, a `observability-smoke` czyta metryki
  przez :8080.

Osobny host i nazwa cookie pozostają otwarte; operatorski panel ustawień
platformy powstaje w aplikacji (plan memex
`saas-core-ustawienia-platformy-w-panelu-administratora`), nie w Django Admin.

## Alternatywy odrzucone

- JWT w localStorage — większy wpływ XSS i trudniejsze natychmiastowe revocation;
- cookie na `.medplano.pl` — publiczne subdomeny rozszerzają powierzchnię ataku;
- NextAuth/Auth.js jako drugie źródło sesji — dubluje stan Django;
- wyłącznie Redis sessions — utrata cache wylogowuje wszystkich i utrudnia audyt.

## Źródła

- https://docs.djangoproject.com/en/5.2/topics/http/sessions/
- https://docs.djangoproject.com/en/5.2/howto/csrf/
- https://docs.djangoproject.com/en/5.2/ref/settings/

