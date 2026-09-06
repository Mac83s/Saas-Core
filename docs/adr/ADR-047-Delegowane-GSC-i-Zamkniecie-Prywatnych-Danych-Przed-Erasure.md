# ADR-047: Delegowane GSC i zamknięcie prywatnych danych przed erasure

Status: zaakceptowana w integracji I3, 2026-09-06.

## Kontekst

Search Console jest zgodą właściciela konta Google, a nie skutkiem utworzenia strony
w Saas Core. SSA posiada połączenie OAuth i wykonuje ograniczone do strony pobrania.
Saas Core musi udostępnić panel, utrzymać granice organizacji i uniemożliwić usunięcie
lokalnych dowodów, zanim zamknięte zostanie zewnętrzne połączenie z prywatnymi danymi.

## Decyzja

`shared.seo` udostępnia osobny kontrakt `/api/v1/seo/gsc/` oraz panel
`/panel/seo/search-console`. Nowe połączenia, zgody, synchronizacje i odczyty wymagają
jawnego `seo.gsc.enabled`; istniejące, niezmienne wersje planów nie są modyfikowane.
Właściciel otrzymuje `seo.gsc.manage` i `seo.gsc.read`, manager tylko odczyt.
API wymaga osobowego członkostwa. Cofnięcie zgody, odłączenie i minimalny odczyt
identyfikatora połączenia wymagają `manage`, ale pozostają możliwe po odebraniu feature.
Nie udostępniają wówczas metryk ani listy usług Google.

Jedno połączenie Google dotyczy całej organizacji zewnętrznej SSA. Każda strona ma
osobny SourceSiteBinding i czasową zgodę. Jawne `prepare` tworzy przypisanie przez
istniejący, zweryfikowany adres domeny Sites bez zakupu audytu. Adres nie ustala
tożsamości organizacji. Tożsamości source/product/deployment/tenant/project są
weryfikowane przy provisioningu, a grant wskazuje dokładny binding, actor i property.
W tej wersji zgoda daje wyłącznie `read` i `sync`; panel proponuje 30 dni, API dopuszcza
maksymalnie 366. Inspekcja URL jest wyłączona w Core.

Google tokens, refresh tokens i prywatne kopie metryk pozostają w SSA. Core zapisuje
cztery tenantowe tabele: konserwatywny znacznik wymaganego cleanup, próbę OAuth,
niezmienną intencję zgody i niezmienną intencję synchronizacji. Wszystkie mają FORCE
RLS i odwracalne migracje. Relacje binding/grant muszą należeć do tej samej organizacji;
zapisane identyfikatory zdalne i treść intencji nie mogą zostać podmienione.
Historia jest usuwana wyłącznie przez nazwany proces erasure z ADR-042.

OAuth start jest związany z konkretnym `UserSession.id`, hashem jej klucza, aktorem,
organizacją i stroną. Przechowujemy tylko hash state, termin do 15 minut i język.
Callback wymaga tej samej aktywnej sesji i organizacji. Konsumuje state przed wymianą
kodu, także przy odmowie Google lub błędzie źródła; kodu nie ponawiamy. Kolejny start
unieważnia wcześniejsze lokalne próby organizacji. SSA dodatkowo egzekwuje własny
jednorazowy state. Obecny middleware tenanta obejmuje żądanie transakcją; lokalny lock
trwa więc do odpowiedzi. Widok przechwytuje błędy transportu oraz wadliwe odpowiedzi,
aby nie wycofać znacznika cleanup po możliwym zdalnym skutku. Awaria procesu nadal może
wycofać lokalną transakcję; zdalny jednorazowy state pozostaje drugą barierą przed
powtórną wymianą. Jest to ograniczenie obecnej granicy transakcyjnej, a nie deklaracja
rozproszonej transakcji.

`SEO_GSC_REDIRECT_URI` musi dokładnie wskazywać callback Core i zgadzać się z mapą
operatora `SSA_INTEGRATION_GSC_REDIRECTS[sourceUUID]`. URL autoryzacji sprawdzamy pod
kątem hosta accounts.google.com, ścieżki OAuth, state i tego redirect URI. Callback
przekierowuje wyłącznie do stałej strony panelu, bez odbicia błędu dostawcy. Odpowiedzi
mają `private, no-store` i `no-referrer`. Caddy pomija access log callbacku, a formatter
Django usuwa jego query string z komunikatu i pól strukturalnych. Znaczące operacje
pozostają w audycie domenowym bez kodów, tokenów, state i prywatnych wyników.

Zgody i synchronizacje zachowują tożsamość podczas ponowień. Nieznany wynik zgody można
ponowić z zapisanej intencji (wyłącznie jej aktor). Historia synchronizacji udostępnia
ostatnie 50 zapisanych zakresów i ich client_reference do ponowienia; pełna historia
pozostaje w bazie. Odczyt każdej strony metryk i każde ponowienie synchronizacji
najpierw ponownie weryfikują aktywną zgodę w SSA. Nie ma cache metryk ani fallbacku do
wcześniejszych danych. Core nie podąża za zdalnym adresem `next`; sam numeruje strony
do 100 wierszy. Niepełny wynik zachowuje oznaczenie źródła.

Przed startem OAuth i utworzeniem zgody ustawiany jest `cleanup_required`. Błąd lub
nieznany wynik nie zeruje znacznika. Registry preconditions w `core.organizations`
pozwala modułom dołączyć lokalny warunek erasure bez importu warstwy shared do core.
Pod blokadą organizacji, po SET LOCAL i przed usuwaniem danych, GSC odmawia erasure
z kodem `seo_gsc_disconnect_required`, jeżeli marker pozostaje aktywny. Nie wykonuje
sieci w transakcji kasowania. Najpierw trzeba wykonać osobny, ponawialny disconnect.

Disconnect wymaga potwierdzenia całej organizacji i spodziewanego connection UUID.
SSA odmawia usunięcia nowszego połączenia przez starsze żądanie. Replay już usuniętego
konta może zwrócić false; Core zachowuje wtedy marker i wymaga odświeżenia oraz nowego
potwierdzenia z aktualnym pustym połączeniem. Zapobiega to automatycznemu anulowaniu
nowszej rozpoczętej autoryzacji. Dopiero potwierdzone odłączenie, również potwierdzenie
braku konta przy pustym spodziewanym ID, pozwala usunąć organizację. Zmiana source
w konfiguracji nie omija starego markera; operator musi zamknąć dawną konfigurację.

## Walidacja i granice

Testy obejmują sesję, TTL, jednorazowość callbacku, odmowę i utratę odpowiedzi,
wadliwe daty/URL odpowiedzi po zdalnej operacji, replay zgody, cofnięcie dostępu,
kolejność SET LOCAL, niedostępność metryk po cofnięciu i cleanup po odebraniu feature.
Rzeczywista rola PostgreSQL NOSUPERUSER/NOBYPASSRLS sprawdza cztery tabele bez tenanta
i z dwoma tenantami. Panel ma PL/EN, testy jawnego potwierdzenia, stabilnej intencji
ponowienia, usuwania metryk po revoke/zmianie strony oraz axe.

Pilot używa rzeczywistego HTTP Core–SSA z syntetyczną granicą wymiany Google. Nie
potwierdza konfiguracji konsoli Google, zgody rzeczywistego użytkownika, produkcyjnego
redirectu ani realnych limitów Google. Te bramki wymagają osobnego uruchomienia.

Dokumentacja dyrektywy Caddy: https://caddyserver.com/docs/caddyfile/directives/log_skip.
