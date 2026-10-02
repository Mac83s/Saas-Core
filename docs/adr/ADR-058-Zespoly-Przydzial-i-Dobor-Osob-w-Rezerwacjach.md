# ADR-058 — Zespoły, przydział i dobór osób w rezerwacjach

**Status:** Accepted
**Data:** 2026-09-24
**Właściciel:** zespół SaaS Core
**Zmienia:** ADR-030 (jedna osoba na wizytę, dobór osoby, limit wyników);
wdraża w minimalnym zakresie ADR-036 §4 (osoba z kalendarza z profilem
publicznym).

## Kontekst

Właściciel 24.09.2026: Saas-Core zmierza ku CRM — narzędziu do codziennej
pracy firmy. Pierwszy krok to zespół: jedna lista ludzi firmy (z kontem i bez),
stałe zespoły, wybór osób albo zespołu przy wizycie, rezerwacja ze strony z
wyborem albo bez, przydział przez osobę z uprawnieniem, która widzi, kto jest
wolny, oraz historia i wydajność pracownika mierzona tym, co deklaruje produkt.
Koncepcja widoków i odpowiedzi na pytania 1–8 żyją w planie memex
`saas-core-zespol-pracownicy-i-przydzial-wizyt`.

Stan przed decyzją (odczyt main 735a224):

- `Appointment.staff` to jedno wymagane FK; tabela `AppointmentStaffAllocation`
  z `EXCLUDE` dopuszcza wiele wierszy na wizytę, ale kod zapisuje jeden;
- „dowolny pracownik” w panelu i formularz publiczny biorą pierwszy slot
  posortowany po `(starts_at, staff_id)`. Identyfikatory to uuid7, więc wizytę
  dostaje zawsze najdawniej dodana wolna osoba, a wybór robi przeglądarka;
- `available_slots` przerywa pętlę po 250 wynikach w środku dnia. Przy jednej
  osobie z grafikiem 9–17 i usłudze 30 min wyszukiwanie 14 dni kończy się po
  trzecim dniu, a `create_appointment` i przełożenie sprawdzają termin tą samą
  funkcją, więc mogą odrzucić wolny termin osoby o wysokim id;
- zakończenie wizyty nie skraca blokad: walk-in HoofCare rezerwujący 12 h
  zostawia osobę „zajętą” do wieczora;
- przypomnienie niesie kontrakt zadania podpisany członkostwem twórcy wizyty.
  Po odejściu tej osoby kontrakt jest nieważny, trasa nigdy nie zostaje
  oznaczona i zostaje na czele kolejki `order_by("due_at")[:100]`;
- publiczny payload wizyty zwraca `staff_id`, `staff_name` i
  `staff_membership_id`, a publiczny katalog — każdego aktywnego pracownika.

## Decyzja

### 1. Rekord pracownika

Pracownikiem jest istniejący `booking.StaffMember`. Konto (`Membership`) jest
opcjonalne: podwykonawca bez loginu, osoba z biura i lekarz-właściciel to ten
sam rodzaj wiersza. Nie powstaje osobna tabela `Employee` w rdzeniu. Dochodzą
pola `phone` (kontakt wewnętrzny, widoczny dla zarządu i samej osoby),
`invitation` (FK, żeby osoba dodana z e-mailem połączyła się z kontem po
przyjęciu zaproszenia) i `profile` → `PublicProfile(person)` (ADR-036 §4: kogo
wolno pokazać klientom).

### 2. Wiele osób na wizycie

> Zmienione przez [ADR-072](ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
> §2 (2026-10-02): oferta, której rezerwacja nie zajmuje osoby (jednostka,
> miejsce w wydarzeniu), ma `staff_count` 0, a jej rezerwacje puste
> `Appointment.staff` (`staff_required = 0`). Rezerwacji z osobami ten punkt
> dotyczy bez zmian.

`Appointment.staff` zostaje `NOT NULL` i znaczy „prowadzący”. Kolejne osoby to
kolejne wiersze `AppointmentStaffAllocation`. Arbitrem kolizji pozostaje
`EXCLUDE` (ADR-030). Usługa mówi, ilu ludzi trzeba (`Service.staff_count`,
1–10). Zespół (`StaffTeam` + `StaffTeamMember`, bez koloru i lidera) to
zapisany zestaw osób: wybranie zespołu przydziela tylu jego wolnych członków,
ilu wymaga usługa. Każda zmiana składu przechodzi przez jedną funkcję
serwisu, która pilnuje niezmiennika „prowadzący ma aktywną alokację albo
wizyta ma znacznik wakatu”.

### 3. Rezerwacja bez wyboru osoby potwierdza się od razu

> Zawężone przez [ADR-072](ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
> §9 (2026-10-02): oferta z wpłatą przed potwierdzeniem (przelew, zadatek,
> całość; odpowiedź właściciela 13a: „dopóki nie ma płatności online — zadatek
> przelewem w 3 dni, inaczej rezerwacja wygasa”) tworzy `pending_payment`, a
> oferta „na prośbę” (oś „Potwierdzenie” planu i decyzja techniczna T8) —
> `pending_request`; obie trzymają termin jak potwierdzona, bez wyprzedzania.
> Ofert z potwierdzeniem od razu i bez wpłaty przed potwierdzeniem ten punkt
> dotyczy bez zmian.

Odpowiedź właściciela 1 (24.09): rezerwacja, w której nikt nie wskazał osób
(formularz, panel „dowolna osoba”, zespół jako wybór klienta), jest
potwierdzona od razu. System sam dobiera osoby, a biuro może później zmienić
skład. Dwa znaczniki na wizycie:

- `needs_assignment` — wakat: nieobecność, odejście osoby, za mało osób.
  Czas pozostałych osób zostaje zablokowany; wizyta trafia do kolejki
  „Do przydzielenia”;
- `auto_assigned` — skład dobrał system. Biuro widzi takie wizyty w kolejce
  i może je zostawić albo zmienić skład; klient nic nie widzi.

Nie ma zgłoszeń czekających na potwierdzenie ani „wstępnych” blokad, więc nie
ma też wyprzedzania ich przez pracę doraźną.

### 4. Dobór najmniej obciążonej osoby wybiera serwer

Gdy wołający nie podaje osoby, `create_appointment` sam wybiera spośród
aktywnych osób wykonujących usługę, wolnych w danym terminie: najpierw
najmniej minut aktywnych alokacji tego lokalnego dnia, potem tygodnia, potem
id. Przeglądarka nie decyduje, kto dostaje wizytę. Przegrany wyścig o jedną
osobę (`EXCLUDE`) próbuje następnej w kolejności, w punkcie zapisu
(savepoint), zanim zwróci konflikt terminu.

### 5. Silnik terminów w trzech częściach

- **dni** — dzień po dniu, zatrzymany na pierwszym wolnym starcie danego dnia,
  bez globalnego limitu wyników; zasila wybór dnia;
- **godziny** — pełne wyliczenie jednego dnia (dzień jest ograniczony):
  unikalne starty i lista wolnych osób dla każdego startu (tylko w panelu);
- **walidacja** — sprawdzenie konkretnego startu dla konkretnych osób:
  pokrycie regułą grafiku z siatką 5 min od początku reguły, minimalne
  wyprzedzenie, nieobecności, alokacje osób i zasobu. `create_appointment` i
  przełożenie używają walidacji, nie listy slotów, więc żaden limit nie
  odrzuci wolnego terminu.

Istniejąca lista slotów zostaje dla zgodności, ale limit liczy się po
zakończeniu dnia, nigdy w jego środku. Pozostałe reguły ADR-030 (UTC, DST,
bufory, horyzont 62 dni) bez zmian.

### 6. Zakończenie wizyty skraca blokady

`complete_appointment(ended_at)` przycina aktywne alokacje wizyty do
faktycznego końca (plus bufor po usłudze, zero dla walk-in). Domyślnie
`ended_at` to chwila zakończenia; produkt może podać własną (HoofCare: czas
wyjazdu z gospodarstwa). Przycięcie tylko skraca zakres, więc nie może naruszyć
`EXCLUDE`. Snapshot planowanego czasu wizyty zostaje bez zmian.

### 7. Zadania przypomnień działają jako usługa

Kontrakt trasy przypomnienia jest podpisywany jako zasada `service` z
zakresem `booking_reminder`, nie członkostwem twórcy. Kontrakt trasy nie
wygasa po `TENANT_TASK_CONTEXT_TTL_SECONDS`: wizytę umawia się dalej niż ten
TTL, a przy otwarciu i tak sprawdza się organizację (starej trasy — członkostwo).
Trasa, której kontrakt jest nieważny (nie da się go odszyfrować, wskazuje
nieaktywną organizację, stare trasy podpisane członkostwem, które wygasło),
zostaje oznaczona i zalogowana jako odrzucona, zamiast zostać na czele kolejki.

### 8. Klient nie dostaje danych pracowników

Publiczny payload wizyty (POST publiczny, strona samoobsługi) nie zawiera
`staff_id`, `staff_membership_id` ani składu. Nazwę osoby pokazuje się
klientowi tylko wtedy, gdy osoba ma włączony profil publiczny (odpowiedź 2).
Publiczny katalog nie wymienia pracowników, a publiczna lista terminów zwraca
same godziny. Krok „Do kogo?” na formularzu ustawia firma przy usłudze:
nikogo, zespół albo osoba (osoba tylko przy usługach jednoosobowych i z
profilem publicznym). Uwagi klienta są czyszczone przy anonimizacji.

### 9. Kto widzi i kto zmienia

- „kto jest wolny” to jeden odczyt dla tablicy dnia, dialogu przydziału i
  kolumny „Dziś”; cudze wiersze tylko z `organization.members.read`; powód
  nieobecności widzi tylko zarząd i sama osoba;
- przydział: `POST …/assign/` z oczekiwaną wersją składu; niezgodna wersja to
  409 z nazwą ostatniej osoby, która zmieniła skład;
- wyniki i historia innych osób: nowe uprawnienie
  `booking.staff.performance.read`, nadawane właścicielowi i administratorowi
  (odpowiedź 3); swoje wyniki każdy widzi zawsze;
- własny grafik: uprawnienie `booking.schedule.own`, które rdzeń daje roli
  Pracownik, a produkt może nie dać (HoofCare: Korektor go nie ma; odpowiedź 7);
- powiadomienia pracownika o przydziale, zdjęciu z wizyty, przełożeniu i
  odwołaniu: w aplikacji i e-mailem, tylko do aktywnych kont (odpowiedź 6);
- limit planu `team_members.max` liczy aktywne członkostwa i otwarte
  zaproszenia, sprawdzany przy zaproszeniu; pracownicy bez konta bez limitu
  (odpowiedź 5).

### 10. Miary pracownika deklarują moduły

Rejestr `register_staff_facts(name, permission, metrics, history)` w
`booking/api.py`: każdy moduł i produkt dokłada miary i zdarzenia historii,
każdy pod własnym uprawnieniem. Rdzeń rysuje z nich kartę i porównanie, nie
znając produktu (ADR-049). HoofCare liczy krowy i korekcje autorowi wpisu
(odpowiedź 4). Materiały usługi przy zakończeniu schodzą z zapasu
prowadzącego, gdy ma pozycję, inaczej z magazynu głównego (odpowiedź 8), więc
„Zużyte” staje się miarą rdzenia.

## Konsekwencje

- Kalendarz, przydział i wyniki opierają się na jednej prawdzie: aktywnych
  alokacjach. Godziny pracy liczy się z przyciętych zakresów.
- Formularz publiczny nie wybiera osoby w przeglądarce, więc praca rozkłada
  się równo, a zmiana doboru nie wymaga zmiany frontu.
- Przy jednej osobie wybór ludzi, kolejka i tablica chowają się same (liczone z
  danych, nie z produktu) — MedPlano nie potrzebuje kodu.
- Każde wejście zmieniające skład (tworzenie, przydział, przełożenie,
  nieobecność, odejście, walk-in i pomocnik w HoofCare) musi przejść przez
  jedną funkcję serwisu; nowa ścieżka obok niej złamie niezmiennik.
- Stare trasy przypomnień podpisane członkostwem, które wygasło, zostaną
  odrzucone zamiast wysłane; na instancjach deweloperskich to pojedyncze trasy.

## Alternatywy odrzucone

- nowa tabela `Employee` w rdzeniu — backfill łączący trzy repozytoria i dwa
  źródła prawdy dla jednej osoby;
- `Appointment.staff` jako pole opcjonalne — zmiana serializerów, przypomnień,
  samoobsługi i raportu bez zysku, skoro wakat opisuje znacznik;
  > Wraca w ADR-072 §2 (2026-10-02) dla rezerwacji bez żadnej osoby.
- zgłoszenie czekające na potwierdzenie z „wstępną” blokadą — odrzucone przez
  właściciela (odpowiedź 1), a technicznie wymagało trzech stanów i
  wyprzedzania blokad;
  > Wraca w ADR-072 §9 (2026-10-02) dla ofert „na prośbę” albo z wpłatą przed
  > potwierdzeniem (13a dla wpłaty; dla „na prośbę” oś planu i T8), z pełną
  > alokacją i bez wyprzedzania blokad.
- wybór osoby w przeglądarce — nieautorytatywny i zawsze ten sam;
- większy limit wyników — przesuwa problem, nie usuwa ucięcia dnia.

## Ustalenia fazy 2 (26.09.2026)

Faza 2 (lista Pracownicy, karta osoby, Moja karta) doprecyzowała §1 i §9;
odpowiedzi właściciela z 26.09 są w planie memex i w decyzji
`zespo-faza-2-grafik-na-karcie-osoby-blokada-zako`.

- §1: `StaffMember.phone` i `invitation` weszły w fazie 2. `profile`
  (przełącznik „Pokazuj klientom”) wchodzi z krokiem „Do kogo?” w fazie 3 —
  wcześniej nie miałby żadnego skutku.
- Konto łączy się z wpisem przy przyjęciu zaproszenia. Rdzeń daje rejestr
  `organizations.joining.register_invitation_accepted`, rezerwacje wpinają
  `staff.link_on_join`: wpis wskazany zaproszeniem, po ponownym wysłaniu —
  wpis z zaproszeniem na ten sam e-mail; bez wpisu powstaje nowy, jeśli
  firma ma aktywną usługę. Limit kont z §9 sprawdza rdzeń przez
  `register_seat_limit`, w który billing wpina `team_members.max` — przy
  zaproszeniu i przy przywróceniu zawieszonego konta.
- Zmiana roli nie kończy sesji: uprawnienia liczą się z roli przy każdym
  żądaniu, więc nowa rola działa od następnego kliknięcia. Zawieszenie,
  odebranie członkostwa i przekazanie firmy kończą sesje jak dotąd (ADR-023).
- Godziny pracy i nieobecności zmienia zarząd (`booking.appointment.manage`)
  albo sama osoba z `booking.schedule.own` (w rdzeniu rola Pracownik; produkt
  może jej tego nie dać). Nowy tydzień wyłącza stare reguły, zamiast je
  kasować.
- Zakończenie współpracy jest odrzucane (409
  `staff_has_upcoming_appointments`), dopóki osoba prowadzi zaplanowane
  wizyty; w fazie 3 zamieni się to w wakat.

## Ustalenia fazy 3 (28.09.2026)

Faza 3 (zespoły, wiele osób na wizycie, przydział, formularz „Do kogo?”)
doprecyzowała §1–§3, §5, §8 i §9; odpowiedzi właściciela 1A–4A z 28.09 są w
planie memex i w decyzji `zespo-faza-3-uwagi-klienta-zawsze-zmiana-osoby-z`.

- §2: skład wizyty zmienia **wyłącznie** `crew.set_crew` — tworzenie, przydział
  biura, przełożenie, nieobecność, odejście, dołączenie i opuszczenie wizyty w
  produkcie. Niezmiennik: prowadzący (`Appointment.staff`, NOT NULL) ma
  aktywną alokację albo wizyta jest wakatem (`needs_assignment`); prowadzący
  zdjęty z wakatu zostaje tylko nazwą — „Moje”, filtr osoby i
  `crew_member_filter` liczą go wyłącznie przez zablokowany czas. Wizyta
  zapamiętuje `staff_required` z chwili rezerwacji; każda zmiana podbija
  `crew_version`, a przydział biura podaje wersję, którą widział (409
  `crew_changed` z nazwiskiem osoby, która zmieniła skład).
  > Zmienione przez [ADR-072](ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md)
  > §2 (2026-10-02): rezerwacja bez osoby (`staff_required = 0`) nie ma
  > prowadzącego, a `Appointment.staff` jest w niej puste.
- §3: „Dobrano automatycznie” tylko, gdy system miał wybór, a osób nie
  wskazał nikt z firmy; takie wizyty i wakaty czekają w „Do przydzielenia”
  z powodem (strona, przełożenie przez klienta, nieobecność, odejście, za mało
  osób, dołączenie do innej wizyty) i czasem. Nieobecność i „Usuń z firmy”
  zdejmują osobę z wizyt — reszta składu zachowuje swój czas.
  > Doprecyzowane przez [ADR-075](ADR-075-Synchronizacja-Kalendarzy-Zewnetrznych-iCal.md)
  > pkt 1 (2026-10-02): dotyczy nieobecności wpisanej przez człowieka; blokada z
  > importu kalendarza zewnętrznego nikogo z wizyty nie zdejmuje.
- Produkt dokłada osoby przez `booking.api`: `join_visit_crew` (dołączenie do
  trwającej wizyty blokuje czas od chwili dołączenia do końca wizyty, a
  kolidująca wizyta tej osoby traci ją i czeka jako wakat — odpowiedź 3A),
  `leave_visit_crew`, `crew_people`, `crew_member_filter`, `on_crew`.
- §5: terminy — w panelu i na stronie — liczą `Service.staff_count` osób naraz;
  wybrany zespół albo osoba zawężają, kogo liczyć.
- §1, §8: „Pokazuj klientom” tworzy profil osoby w `profiles` (przez jego
  `api.py`) z nazwą dla klientów; wyłączenie go usuwa. Klient widzi zespół,
  który wybrał, albo „Przyjmie Cię” (prowadzący z profilem) — nigdy listy
  pracowników. Zmiana osoby, którą klient wybrał albo widział, wysyła mu krótki
  e-mail bez nazwisk (2A).
- Uwagi klienta (`Appointment.customer_notes`, 1A) są we wszystkich produktach,
  widzi je tylko panel przy wizycie; nie trafiają do e-maili, logów ani
  historii zmian, a anonimizacja klienta je czyści.
- §9: strony przydziału („Do przydzielenia”, „Zespoły”) pokazują się, gdy
  wizyty przyjmują co najmniej dwie osoby albo coś czeka / zespół istnieje —
  liczone z danych, nie z nazwy produktu. Ustawienia › Usługi i grafik
  edytują usługi, miejsca i zasoby; osoby i ich godziny są w Zespół.

## Wdrożenie

Fazy żyją w planie memex. Faza 1 (bez widocznych zmian): §4, §5, §6, §7 i §8
w części payloadu, katalogu i listy terminów, plus okno czasu na liście
wizyt. Kolejne fazy: lista Pracownicy i karta osoby (§1, §9), zespoły, wiele
osób i przydział (§2, §3), tablica dnia, historia i wydajność (§10).
