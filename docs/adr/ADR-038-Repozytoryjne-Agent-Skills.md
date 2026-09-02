# ADR-038 — repozytoryjne Agent Skills: cykl życia i granice autonomii

**Status:** Accepted
**Data:** 2026-09-02
**Zatwierdzono:** 2026-09-02 — rozstrzygnięcia właściciela zapisane na końcu
**Właściciel:** zespół SaaS Core
**Uzupełnia:** ADR-033 § „Runtime i rozszerzalność" — Codex CLI, Claude Code i
repozytoryjne skills są narzędziami developmentu, nie produktu

## Kontekst

Repozytorium rozwijają agenci (Claude Code, Codex) z jednym właścicielem
produktu. Każda sesja zaczyna od ponownego poznawania kontraktów: ADR-ów,
`docs/architecture/`, deskryptorów modułów, OpenAPI i komend jakościowych.
Koszt jest stały i rośnie z repozytorium; skutkiem są też omijane kontrakty —
import Core → Shared w `provision_platform_workspace` przetrwał kilka sesji,
mimo że `AGENTS.md` zakazuje go w pierwszej zasadzie.

Dziś istnieją trzy skills (`memex`, `memex-tidy`, `memex-worklog`) w
`.agents/skills/` z dokładnymi mirrorami w `.claude/skills/` i
`.claude/commands/`, utrzymywanymi przez integrację Memex. Nie ma walidatora,
mapy ścieżek ani cyklu aktualizacji. Plan poaudytowy (P2) wymaga, aby skills
były utrzymywane przez agentów bez ręcznej edycji przez właściciela, ale bez
prawa do zmiany ADR-ów, użycia sekretów, wdrożeń produkcyjnych ani operacji
nieodwracalnych.

## Decyzja

### 1. Dwa systemy skills, dwa katalogi

- **repozytoryjne skills** (ten ADR) służą zmianie kodu i administracji
  repozytorium; żyją w `.agents/skills/` i nigdy nie są ładowane do runtime'u
  produktu;
- **produktowe skills** asystenta klienta (ADR-033) żyją w `shared.assistant`
  jako wersjonowane recepty w `TenantContext`, z permission, entitlementem,
  zgodą i audytem; nie czytają `.agents/`;
- żaden mechanizm nie synchronizuje treści między tymi katalogami. Automatyczna
  aktualizacja skilla repozytoryjnego nie rozszerza autonomii asystenta klienta.

### 2. Źródło prawdy i adaptery

- kanonicznym plikiem skilla jest `.agents/skills/<name>/SKILL.md`; `AGENTS.md`
  pozostaje jedynym zawsze ładowanym plikiem reguł i nie duplikuje treści skills;
- klient, który wykrywa skills gdzie indziej, dostaje **cienki adapter**: dla
  Claude Code `.claude/skills/<name>/SKILL.md` z **identycznym** frontmatterem
  `name` i `description` oraz treścią wskazującą plik kanoniczny. Opis decyduje
  o automatycznym doborze skilla, więc adapter będący samym linkiem wyłączyłby
  routing po cichu;
- adaptery generuje `pnpm ai:sync` z plików kanonicznych; ręcznie edytowany
  adapter jest błędem walidacji;
- wyjątkiem są dokładne mirrory zarządzane przez integrację Memex (`memex*`),
  których integralność sprawdza ta integracja, nie nasz walidator.

### 3. Anatomia skilla

Każdy `SKILL.md` ma frontmatter:

```yaml
---
name: develop-booking
description: Zmiana usług, grafiku, klientów lub wizyt w shared.booking. Użyj przy każdej zmianie pod modules/shared/booking.
sources:
  - docs/adr/ADR-030-Booking-Czas-Blokady-i-Self-Service.md
  - docs/architecture/data-model-and-tenancy.md
paths:
  - apps/backend/src/saas_core/modules/shared/booking/**
  - apps/frontend/src/app/[locale]/panel/calendar/**
requires_human: false
---
```

i treść ograniczoną do: kiedy, co przeczytać najpierw (linki do `sources`),
procedura, bramki (dokładne komendy z `package.json`), czego nie robić. Limit
to 150 linii; szczegół, który się nie mieści, trafia do `docs/` i jest
linkowany. `sources` i `paths` są danymi dla walidatora i routingu, nie ozdobą.

### 4. Routing

- domyślnie działa implicit invocation: opisy są krótkie i rozłączne, aby agent
  wybrał właściwy skill sam;
- `AGENTS.md` dostaje sekcję „Mapa ścieżek" generowaną z pól `paths`: zmiana
  pliku pod daną ścieżką wymaga przeczytania wskazanego skilla. To reguła, nie
  sugestia, i jest sprawdzalna po fakcie: diff dotyka ścieżki, więc sesja
  powinna była użyć skilla;
- brak skilla dla ścieżki wysokiego ryzyka (`modules/**`, `deployments/**`,
  `infra/**`, `packages/contracts/**`) jest błędem walidacji, chyba że ścieżka
  jest jawnie przypisana do skilla ogólnego.

### 5. Walidator `pnpm ai:validate`

Deterministyczny skrypt (`scripts/ai-validate.mjs`), uruchamiany lokalnie i
jako job CI. Odrzuca:

- brakujący albo niepełny frontmatter, `name` niezgodny z nazwą katalogu lub z
  kebab-case, zduplikowane nazwy;
- `description` dłuższy niż 200 znaków albo identyczny z innym skillem;
- link, ścieżkę w `sources`/`paths` albo komendę, które nie istnieją w
  repozytorium lub w `package.json`;
- adapter `.claude/skills/*` z innym `name`/`description` niż plik kanoniczny
  oraz skill kanoniczny bez adaptera;
- ścieżkę wysokiego ryzyka bez przypisanego skilla i skill, którego `paths` nie
  pasują do żadnego pliku (osierocony);
- wzorce sekretów (klucze, tokeny, DSN z hasłem) i wzorce obejścia bramek
  (`--no-verify`, `--no-gpg-sign`, `DANGEROUSLY`, „pomiń testy");
- skill dotykający `deployments/**`, `infra/**` albo `.github/**` bez
  `requires_human: true`;
- plik dłuższy niż limit.

Zielony walidator jest warunkiem merge'u. Nie jest warunkiem dostępności
uruchomionego produktu: skills nie są zależnością runtime'u.

### 6. Cykl utrzymania — `maintain-saas-core-skills`

Meta-skill wykonuje zamknięty cykl:

1. **wykrycie** — zmiana pliku wymienionego w `sources` któregokolwiek skilla
   (diff w PR albo cykliczny przegląd), zmiana `scripts` w `package.json`,
   deskryptora modułu, OpenAPI, albo powtórzona porażka agenta zapisana w
   worklogu Memex;
2. **zakres** — lista skills, których `sources` obejmują zmieniony plik; nic
   poza nią;
3. **zmiana** — wyłącznie instrukcje i referencje wynikające ze zmiany źródła;
   bez przeredagowywania;
4. **walidacja** — `pnpm ai:validate` i `pnpm ai:sync`;
5. **scenariusze** — `docs/ai/evals/<skill>.md`: deterministyczne listy
   kontrolne („po zmianie endpointu skill każe uruchomić `api:schema`,
   `api:client` i `api:check`"), sprawdzane przez skrypt, nie przez model;
6. **dowód i commit** — osobny commit `chore(skills): …` z diffem, wynikiem
   walidatora i wpisem worklogu; cofnięcie to zwykły `git revert`;
7. **powiadomienie** — wpis w worklogu Memex i jedno zdanie w HANDOFF
   („zmieniono skill X, bo zmieniło się Y"), żeby właściciel widział zmianę
   bez czytania diffu.

Meta-skill nie może: zmienić statusu ADR-u, dodać permission lub entitlementu,
wpisać sekretu, przestawić `requires_human` z `true` na `false` ani wyłączyć
walidacji. Przejście parsera nie jest dowodem poprawności — walidator i
scenariusze są niezależną bramką, a diff pozostaje przeglądalny dla człowieka,
choć jego przegląd nie jest warunkiem merge'u (rozstrzygnięcie nr 1).

### 7. Granice autonomii

Skill może instruować agenta, jak zmieniać kod i uruchamiać bramki. Skill nie
może:

- zmieniać ani rozszerzająco interpretować zaakceptowanego ADR-u — zmiana
  decyzji to nowy ADR;
- używać sekretów, łączyć się z produkcją, wykonywać `git push`, wdrożenia,
  migracji na środowisku dzielonym ani operacji nieodwracalnej bez wyraźnej
  zgody właściciela w tej sesji;
- nadawać uprawnień, entitlementów ani omijać `TenantContext`;
- oznaczać bramki jako zaliczonej bez artefaktu dowodowego.

`requires_human: true` oznacza, że procedura kończy się pytaniem do człowieka
przed krokiem nieodwracalnym; walidator wymusza to pole dla ścieżek deploymentu
i infrastruktury.

### 8. Pomiar

Do worklogu Memex trafia per sesja: użyte skills, czy dobór był automatyczny,
liczba korekt po review, nieudane bramki i regresje, których źródłem była
nieaktualna instrukcja. Bez zewnętrznej telemetrii i bez danych osobowych.

## Rozstrzygnięcia właściciela (2026-09-02)

1. zmiany skills przez meta-skill wchodzą na `main` **bez przeglądu**, z
   revertem jako bezpiecznikiem i z powiadomieniem (worklog Memex + zdanie w
   HANDOFF) — punkt 7 cyklu;
2. adapter dla Codex — do sprawdzenia w P2 na realnym kliencie; decyzja
   techniczna bez udziału właściciela;
3. limity przyjęte: 150 linii na skill, 200 znaków opisu.

## Konsekwencje

- pojawia się nowy artefakt jakości (`ai:validate`) i nowy job CI; koszt
  utrzymania to głównie aktualność `sources` i `paths` we frontmatterze;
- każdy skill odpowiada za listę swoich źródeł; brak wpisu w `sources` oznacza,
  że drift w tym pliku nie zostanie wykryty — świadomy kompromis wobec
  skanowania całego repozytorium;
- skills nie zastępują ADR-ów ani `docs/architecture/`; są instrukcją „jak
  pracować z tym kontraktem", nie kopią kontraktu;
- agenci bez obsługi skills nadal dostają `AGENTS.md` z mapą ścieżek, więc nic
  nie zależy od jednego klienta.

## Alternatywy odrzucone

- jeden duży `AGENTS.md` ze wszystkimi procedurami — ładowany do każdej sesji,
  kosztowny i nieczytelny;
- pełne kopie skills per klient (Claude, Codex) — rozjeżdżają się po pierwszej
  zmianie;
- walidacja skills przez model (LLM-as-judge) jako bramka merge'u —
  niedeterministyczna i droga; dopuszczalna tylko jako raport pomocniczy;
- skills produktowe i repozytoryjne w jednym katalogu — zaciera granicę między
  narzędziem developera a funkcją produktu podlegającą ADR-033;
- ręczna synchronizacja przez właściciela — plan poaudytowy jawnie ją wyklucza.

## Relacje

- ADR-021 (moduły, deploymenty) i ADR-025 (runtime) — źródła pierwszych skills;
- ADR-033 — granica z produktowym asystentem;
- plan poaudytowy §6 (P2) — harmonogram i bramka;
- wzorzec „living docs" i „jedno miejsce dla workflow" zapisany w vaulcie Memex.
