# Domeny, DNS i wycofanie publikacji

## Zakres

Procedura dotyczy subdomen platformy oraz domen własnych obsługiwanych przez W7.
Źródłem decyzji jest ADR-028. Publiczny certyfikat na stagingu lub production
wymaga prawdziwego DNS i dostępu Caddy do ACME; test lokalny potwierdza politykę,
ale nie jest dowodem issuance przez zewnętrzny urząd certyfikacji.

## Konfiguracja środowiska

Backend otrzymuje:

- `DOMAIN_DNS_CNAME_TARGET` — stabilny target CNAME platformy;
- `DOMAIN_DNS_EXPECTED_IPV4` i opcjonalnie `DOMAIN_DNS_EXPECTED_IPV6` — adresy
  origin do weryfikacji domen głównych bez CNAME;
- `PUBLIC_SITE_SCHEME=https` poza lokalnym runtime;
- limity czasu i częstotliwości z prefiksem `DOMAIN_`; wartości domyślne są w
  `settings/base.py`.

Caddy pyta prywatny endpoint backendu. Publiczne żądanie do
`/internal/caddy/domains/authorize/` musi zwracać `404`. Awaria backendu oznacza
odmowę nowego handshake, nigdy fail-open.

## Dodanie domeny własnej

1. W panelu wybierz site i dodaj hostname bez protokołu, portu ani ścieżki.
2. Skopiuj dokładny TXT `_saas-core.<hostname>` i jego pełną wartość. Token
   innego rekordu nie potwierdza własności.
3. Dla subdomeny ustaw CNAME na `DOMAIN_DNS_CNAME_TARGET`. Dla apex ustaw A/AAAA
   zgodne z adresami pokazanymi przez support.
4. Uruchom „Sprawdź DNS”. `pending` i błędy resolvera są ponawiane przez worker;
   `verified` oznacza zgodność TXT i routingu.
5. Opublikuj site. Dopiero po publikacji i przy aktywnej organizacji endpoint
   Caddy zezwala na certyfikat.
6. Wejdź na domenę przez HTTPS, sprawdź canonical, oba locale i metryki Caddy.
   Status `requested` w aplikacji oznacza, że Caddy poprosił o zgodę; faktyczne
   issuance potwierdza handshake i log/metryka Caddy.

Nie usuwaj TXT po pierwszej weryfikacji. Worker sprawdza domenę ponownie i
jednoznaczna zmiana rekordów odbiera zgodę na nowe certyfikaty. Timeout/SERVFAIL
pozostaje przejściowy tylko przez skonfigurowany okres grace.

## Migracja canonical i rollback DNS

Migrację wykonujemy w kolejności bezpiecznej dla cache DNS:

1. pozostaw dotychczasową zweryfikowaną domenę aktywną;
2. dodaj i zweryfikuj nową domenę, ale nie ustawiaj jej jeszcze jako canonical;
3. sprawdź nowy host jako alias, TLS, ścieżki locale i brak treści innego site;
4. ustaw nową domenę jako canonical — stara zacznie zwracać stały redirect;
5. dopiero potem przełącz pozostałe rekordy i odczekaj co najmniej poprzedni TTL.

Rollback: najpierw ustaw poprzednią zweryfikowaną domenę (albo subdomenę
platformy) jako canonical, następnie cofnij DNS i ponownie sprawdź HTTPS. Domenę
problematyczną wyłącz. Zwolnij ją dopiero po zakończeniu obserwacji; zwolnienie
jest nieodwracalne dla rekordu i uruchamia siedmiodniową kwarantannę hostname.

## Diagnostyka supportu

- panel i wewnętrzny Django Admin pokazują status DNS/TLS oraz daty kontroli;
- `saas_core_domain_dns_verification_total{result=...}` rozdziela sukces,
  mismatch, NXDOMAIN i awarię resolvera bez etykiety hostname;
- `saas_core_domain_tls_authorization_total{decision=...}` pokazuje zgody,
  odmowy, cache i rate limiting bez ujawniania domen;
- logów nie uzupełniamy tokenem TXT, cookie ani snapshotem treści;
- przy `routing_mismatch` porównaj CNAME/A/AAAA z konfiguracją backendu, przy
  `txt_mismatch` porównaj cały token, a przy `resolver_unavailable` sprawdź
  egress workera i resolver systemowy.
