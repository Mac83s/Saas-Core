# Sekrety stagingu

Ten katalog dokumentuje kontrakt nazw, ale nie zawiera wartości. Na hoście
stagingowym pliki znajdują się domyślnie w `/opt/saas-core/secrets`, poza
checkoutem i z prawami `0600`:

- `django_secret_key` — losowy klucz Django, co najmniej 48 bajtów entropii;
- `postgres_password` — losowe hasło oddzielnej roli migracyjnej PostgreSQL;
- `postgres_app_password` — niezależne losowe hasło roli aplikacyjnej
  `NOSUPERUSER NOBYPASSRLS`;
- `redis_password` — co najmniej 32 znaki alfabetu base64url;
- `email_host_password` — hasło SMTP, udostępniane wyłącznie workerowi;
- `grafana_admin_password` — losowe hasło administratora lokalnej Grafany;
- `stripe_secret_key` — klucz API Stripe właściwy dla trybu test/live wdrożenia;
- `stripe_webhook_secret` — sekret podpisu przypisany wyłącznie do endpointu
  webhooka tego wdrożenia;
- `object_storage_access_key_id` — identyfikator poświadczenia ograniczonego do
  stagingowego bucketa mediów;
- `object_storage_secret_access_key` — odpowiadający sekret S3, udostępniany
  wyłącznie procesom backendu;
- późniejsze integracje dodają osobny plik na każdy sekret i przyznają go tylko
  usługom, które go potrzebują.

Nie twórz prawdziwych plików sekretów w tym katalogu.
