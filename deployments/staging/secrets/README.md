# Sekrety stagingu

Ten katalog dokumentuje kontrakt nazw, ale nie zawiera wartości. Na hoście
stagingowym pliki znajdują się domyślnie w `/opt/saas-core/secrets`, poza
checkoutem i z prawami `0600`:

- `django_secret_key` — losowy klucz Django, co najmniej 48 bajtów entropii;
- `postgres_password` — losowe hasło użytkownika bazy;
- `redis_password` — co najmniej 32 znaki alfabetu base64url;
- `grafana_admin_password` — losowe hasło administratora lokalnej Grafany;
- późniejsze integracje dodają osobny plik na każdy sekret i przyznają go tylko
  usługom, które go potrzebują.

Nie twórz prawdziwych plików sekretów w tym katalogu.
