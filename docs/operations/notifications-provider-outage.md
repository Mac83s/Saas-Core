# Runbook — awaria providera powiadomień

1. Potwierdź alert backlogu/dead-letter i status providera poza aplikacją.
2. Nie zmieniaj rekordów kolejki ani `app.organization_id` ręcznie. Dostawy są
   co najmniej raz i zachowują stabilny klucz idempotencji.
3. Jeśli provider nie przyjmuje żądań, pozostaw retry z backoffem. Wstrzymaj
   worker wyłącznie przy potwierdzonym ryzyku nieidempotentnej odpowiedzi.
4. Po odzyskaniu sprawdź metryki `saas_core_notification_pending_tasks`, wynik
   prób i statusy bounce/complaint. Worker przed ponowieniem sprawdza akceptację
   po kluczu idempotencji.
5. Dead-letter ponawiaj z panelu supportu na tym samym rekordzie. Wymagane są
   `notifications.support`, MFA i powód; akcja zapisuje audit bez sekretów.
6. Przy błędach podpisu zweryfikuj zegar, sekret z secret store i rotację.
   Nigdy nie wyłączaj weryfikacji podpisu ani ochrony SSRF.
7. Po incydencie potwierdź suppressions, odwrócone statusy i brak drugiej
   wiadomości, a następnie udokumentuj czas, zakres i identyfikatory korelacji.
