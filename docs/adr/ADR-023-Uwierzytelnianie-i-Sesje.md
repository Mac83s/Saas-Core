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

## Alternatywy odrzucone

- JWT w localStorage — większy wpływ XSS i trudniejsze natychmiastowe revocation;
- cookie na `.medplano.pl` — publiczne subdomeny rozszerzają powierzchnię ataku;
- NextAuth/Auth.js jako drugie źródło sesji — dubluje stan Django;
- wyłącznie Redis sessions — utrata cache wylogowuje wszystkich i utrudnia audyt.

## Źródła

- https://docs.djangoproject.com/en/5.2/topics/http/sessions/
- https://docs.djangoproject.com/en/5.2/howto/csrf/
- https://docs.djangoproject.com/en/5.2/ref/settings/

