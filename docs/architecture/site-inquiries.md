# Zapytania z publicznej strony

`core.contact_form` ma stały zestaw pól — imię, e-mail, telefon, wiadomość —
a wariant `contact` (od v2) mówi, które są wymagane (decyzja właściciela z
24.09; tabela `CONTACT_FORM_FIELDS` w `@saas-core/site-blocks`, lustro w
`inquiries.py`):

| `contact` | Nazwa w panelu | E-mail | Telefon | Wiadomość |
| --- | --- | --- | --- | --- |
| `email` (brak = v1) | Napisz do nas | wymagany | opcjonalny | wymagana |
| `callback` | Oddzwonimy | opcjonalny | wymagany, pierwszy | opcjonalna |
| `full` | Pełny kontakt | wymagany | wymagany | wymagana |
| `email_only` | Tylko e-mail | wymagany | brak pola | wymagana |

Imię jest zawsze wymagane, a każdy wariant wymaga co najmniej jednej drogi
odpowiedzi. Zgody (checkbox) nie ma. Cztery układy zmieniają kompozycję, nie
schemat zgłoszenia. Edytowalne są wprowadzenie, wariant, zdjęcie, etykieta
przycisku, potwierdzenie oraz link do informacji o prywatności. Podgląd biblioteki i edytora ma wyłączone pola i nie
zawiera aktywnego formularza. Dopiero renderer publikacji podłącza komponent
wysyłający z identyfikatorem publikacji, ścieżką i pozycją bloku.

## Przyjęcie wiadomości

`POST /api/v1/public/site/inquiries/` przyjmuje JSON i `Idempotency-Key`.
Host oraz aktualny snapshot wskazują organizację i konkretny formularz; klient
nie wybiera organizacji ani odbiorcy wiadomości. Origin musi odpowiadać hostowi.
Nowy zapis wymaga zgodności wersji publikacji, ścieżki i pozycji bloku. Stary
adres po przeniesieniu strony oraz zmieniona publikacja zwracają kontrolowany
konflikt. Nieopublikowana lub niedostępna strona nie przyjmuje wiadomości.

Publiczne role serwisowe są rozdzielone. `public_site_inquiry` ma wyłącznie
`sites.inquiry.submit`; podpisany kontekst zadania nie może rozszerzyć tego
zakresu. Po rozwiązaniu hosta transakcja ustawia `SET LOCAL app.organization_id`
przed odczytem prywatnych danych. Tabela `sites_siteinquiry` ma wymuszone RLS,
a trigger pilnuje zgodności organizacji i witryny w powiązaniach z publikacją
i powiadomieniem. Audyt zawiera identyfikatory, nie treść zgłoszenia.

Serwer stosuje reguły wariantu z bloku w opublikowanym snapshocie, nie z
przeglądarki: brak wymaganego pola to 400 z błędem pola, a telefon wysłany do
formularza bez pola telefonu jest pomijany przy zapisie. Telefon, jeśli podany, to znaki
telefonu (`+`, cyfry, spacje, `()./-`) i 6–15 cyfr — ta sama reguła w
przeglądarce i w serializerze. Zapytanie „Oddzwonimy” bez e-maila ma w skrzynce
przycisk „Zadzwoń” zamiast odpowiedzi e-mailem, a w powiadomieniu puste pola
jako „—”.

Granice wejścia: nazwa 120 znaków, e-mail 254, telefon 32, wiadomość 5000,
całe żądanie 64 KiB. Dodatkowe pole honeypot ma pozostać puste. Limity
częstotliwości dotyczą klienta i znormalizowanego hosta. Nie jest to CAPTCHA.

Unikalny klucz w obrębie witryny i hash danych dają jeden zapis przy retry.
Ten sam klucz z inną treścią daje konflikt. Przeglądarka zachowuje klucz dla
identycznej ponownej próby; zmienione dane dostają nowy klucz.

## Skrzynka i powiadomienie

W panelu „Wiadomości → Zapytania ze strony” dostęp wymaga `site.content.edit`
i `sites.enabled`. Dostęp do automatycznych powiadomień jest niezależny.
Klucze automatyzacji nie mogą czytać prywatnej skrzynki. Lista jest stronicowana;
oznaczenie przeczytania wymaga sesji, CSRF i klucza idempotencji. Odpowiedź
otwiera ręcznie program pocztowy; panel nie wysyła jej samodzielnie.

Powiadomienie trafia przez istniejącą kolejkę Notifications do aktywnego
właściciela organizacji. Adres odbiorcy nie jest zapisywany w publicznym bloku.
Brak właściciela lub `notifications.enabled` nie blokuje zapisu zapytania:
skrzynka pokazuje wtedy niedostępność powiadomienia. Sukces formularza oznacza
zapis, a nie dowód dostarczenia e-maila. Osobny status pokazuje kolejkę, próbę
wysyłki, potwierdzenie dostarczenia albo błąd.

Istniejąca kolejka może zgłosić awarię brokera w callbacku już po commit.
W takim przypadku zapytanie i outbox pozostają trwałe, a identyczny retry
potwierdza ten sam zapis bez duplikowania powiadomienia. Interfejs mówi wtedy
o niepotwierdzonej wysyłce i zachowuje treść. Nie wysyłamy autorespondera na
adres podany przez anonimowego odwiedzającego.

## Wdrożenie i zakres

Migracja `sites/0030_site_inquiry` jest odwracalna. Sites deklaruje zależność
od Notifications; obrazy backendu i frontendu wymagają tego samego odświeżonego
artefaktu profilu. Należy wdrożyć backend, migrację, workera i frontend jako
jeden przyrost, a po wdrożeniu sprawdzić własną domenę przez Caddy, zapis
w skrzynce oraz rzeczywistą drogę powiadomienia. Testy fixture nie dowodzą
wysyłki na działającym środowisku.

Nie dodano załączników, samodzielnego budowania pól, automatycznej odpowiedzi,
osobnego ustawienia odbiorcy ani okresu retencji zapytań. Usuwanie danych całej
organizacji pozostaje w istniejącym procesie erasure; nie dodano kasowania
pojedynczych zapytań w panelu.
