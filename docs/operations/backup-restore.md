# Backup i restore drill PostgreSQL

## Lokalna próba

Uruchomiony runtime pozwala sprawdzić cały bezpieczny przebieg:

```bash
pnpm runtime:backup
pnpm runtime:restore-drill
```

Backup używa klienta PostgreSQL 18 z kontenera bazy i formatu custom
`pg_dump -Fc`. Artefakt, checksum SHA-256 i raport trafiają do ignorowanego
przez Git katalogu `.runtime/`. Restore drill:

1. weryfikuje checksumę;
2. tworzy wyłącznie tymczasową bazę `saas_core_restore_*`;
3. uruchamia `pg_restore --exit-on-error --no-owner`;
4. wykonuje migracje Django i system check;
5. kontroluje tabelę migracji, zapisuje czas i usuwa bazę testową także przy
   błędzie.

Raport mierzy techniczny czas odtworzenia. Nie jest jeszcze dowodem RPO, dopóki
backup nie działa według harmonogramu poza laptopem.

## Staging

RPO stagingu wynosi 24 godziny, a RTO 4 godziny. Sam plik na VPS-ie nie spełnia
tej bramki. Operator musi:

- uruchamiać codzienny `pg_dump -Fc` klientem tej samej linii major;
- szyfrować artefakt przed wysłaniem;
- kopiować go na osobne konto/bucket S3 poza VPS-em;
- egzekwować retencję i alarmować o braku świeżej kopii;
- przynajmniej raz na falę odtwarzać pobrany artefakt do izolowanej bazy oraz
  archiwizować raport czasu, checksumy i wyniku kontroli.

Wybór dostawcy bucketa i systemu zarządzania kluczem wymaga danych docelowej
infrastruktury. Do tego czasu nie należy oznaczać zewnętrznej kopii ani RPO jako
wdrożonych.

