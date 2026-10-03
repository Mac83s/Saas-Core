# Rozmowa z asystentem — kontrakt

Wykonywalna połowa [ADR-076](../adr/ADR-076-Asystent-AI-Rejestr-Polecen.md),
uzupełnienie 2026-10-03 (A3-1). Moduł `shared.assistant`; model przez
[port modeli](model-port.md), zadanie `assistant.conversation`.

## Przebieg wiadomości

```text
osoba            panel/API                         worker `ai`                 port modeli
POST turns/  ->  tura queued, kredyt zarezerwowany
                 202                          ->   tura running
                                                   transkrypt + narzędzia  ->  complete()
                                                   <- tekst | wywołania narzędzi
                                                   wywołania = plan (step_id od serwera)
                                                   offer_plan
                                                     odmowa   -> błędy do modelu, dalej
                                                     odczyty  -> wykonane, wyniki do modelu, dalej
                                                     zapis    -> awaiting_consent (digesty grup)
GET rozmowa  <-  tura awaiting_consent, grupy
GET command-consents/{digest}   (dialog rysuje tylko to)
POST command-consents/{digest}  -> token (300 s)
POST turns/{id}/consents/       -> execute_plan w żądaniu osoby, wyniki kroków zapisane
                                                   tura running -> model raportuje z wyników
GET rozmowa  <-  tura done
```

- Tura ma stany `queued → running → (awaiting_consent → running)* → done | failed`.
  Rozmowa ma najwyżej jedną turę w toku (ograniczenie w bazie); druga wiadomość to 409
  `assistant_turn_in_progress`.
- Wywołań modelu na wiadomość jest najwyżej `assistant.limits.model_steps_per_turn`;
  po przekroczeniu tura kończy się `step_limit`.
- Tura bez ruchu przez 180 s (worker padł albo go nie ma) kończy się `timeout`
  (zadanie `assistant-reconcile`, kolejka domyślna). Otwarte wywołania narzędzi
  dostają wtedy wynik, żeby transkrypt dało się pokazać modelowi ponownie.
- Plan czekający na kliknięcie dłużej niż `COMMAND_PENDING_TTL` jest proponowany
  ponownie przy odczycie rozmowy, na stanie z tej chwili.

## Co widzi model

- Stały prompt (`prompts.py`, `assistant.operate@1`) i język panelu rozmowy.
- Wiadomości osoby z czasem wysłania w nawiasie kwadratowym (UTC).
- Narzędzia: `command_tools(context)` — polecenia, do których osoba ma uprawnienie
  i moduł; wykonawca sprawdza wszystko jeszcze raz.
- Wynik kroku jako wiadomość `tool`: `{"status": "done", "output": …}` albo
  `{"status": "refused" | "failed" | "skipped" | "declined", "error": {"code", "errors"}}`.
  Wynik dłuższy niż 24 000 znaków jest zastępowany błędem `output_too_large`.
- Klasa danych żądania to zawsze `personal`.

## API (`/api/v1/assistant/`)

| Operacja | Co robi |
| --- | --- |
| `GET offer/` | czy czat przyjmie wiadomość i dlaczego nie (`reasons`), czy jest w planie, koszt wiadomości w kredytach |
| `GET conversations/` | rozmowy zalogowanej osoby w tej firmie |
| `POST conversations/` | nowa rozmowa (`Idempotency-Key`) |
| `GET conversations/{id}/` | tury: wiadomość osoby, teksty asystenta, kroki ze statusem, grupy zgody |
| `POST conversations/{id}/turns/` | wiadomość (`Idempotency-Key`), 202 |
| `POST conversations/{id}/turns/{turn}/consents/` | tokeny zgód albo `declined`, 202 |

Kody: 503 `assistant_unavailable`, 403 `assistant_not_in_plan`, 403
`assistant_person_only` (klucz API, kontekst „w imieniu”), 429
`assistant_rate_limited`, 409 `assistant_turn_in_progress`, 409
`assistant_consent_not_awaited`, 409 `assistant_idempotency_conflict`, 404
`assistant_conversation_not_found` (cudza rozmowa wygląda tak samo jak brak), 402
`credits_exhausted`.

## Dane

`assistant_assistantconversation`, `assistant_assistantturn`,
`assistant_assistantmessage` — tabele firmy z RLS. Treść rozmowy nie trafia do
logów ani telemetrii portu. Retencja: `assistant.retention.conversation_days`
(zadanie dobowe `assistant-purge`); usunięcie firmy zabiera rozmowy.

## Ustawienia platformy

`assistant.limits.turns_per_person_per_minute` (12),
`assistant.limits.conversation_starts_per_ip_per_hour` (20),
`assistant.limits.model_steps_per_turn` (6),
`assistant.limits.daily_turns_ceiling` (2000),
`assistant.retention.conversation_days` (90). Budżety w USD: port modeli.

## Dowody

- `tests/test_assistant_chat.py`: odczyt bez kliknięcia; zapis dopiero po kliknięciu;
  plan bez tokenu i plan odrzucony nie wykonują nic; argumenty poza schematem wracają
  do modelu; rozmowę czyta tylko jej osoba; jedna tura naraz; czat zamknięty bez
  workera, modelu albo cechy planu; limity z ustawień platformy; porażka modelu
  zwraca kredyt; osoba usunięta z firmy; sprzątanie i retencja.
- `tests/test_assistant_evals.py` i `manage.py assistant_eval`: scenariusze modelu.
- Panel: `apps/frontend/src/modules/shared/assistant/assistant-panel.test.tsx`.
