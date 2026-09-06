# Instrukcje dla agentów

Repozytorium rozwijają agenci, więc instrukcje są tu artefaktem inżynierskim, a
nie notatką. Ten dokument mówi, gdzie co żyje, jak agent trafia do właściwej
instrukcji, czego instrukcja nie może zrobić i co się dzieje, gdy się
zdezaktualizuje.

## 1. Podział

| Warstwa                       | Gdzie                          | Co zawiera                                                                 |
| ----------------------------- | ------------------------------ | -------------------------------------------------------------------------- |
| reguły dla każdego zadania    | `AGENTS.md`                    | niezmienne zasady, granice pracy, mapa ścieżek do skills                     |
| instrukcje obszarowe (skills) | `.agents/skills/<nazwa>/SKILL.md` | kolejność pracy, komendy i pułapki jednego obszaru                        |
| adaptery klienckie            | `.claude/skills/<nazwa>/SKILL.md` | ten sam `name` i `description`, wskazanie pliku kanonicznego              |
| decyzje                       | `docs/adr/`                    | co zostało postanowione i dlaczego; skill nie zastępuje ADR-u                |
| kontrakty wykonywalne         | `docs/architecture/`           | to, co można sprawdzić testem                                               |
| pamięć projektu               | vault memex                    | czego nauczyły się poprzednie sesje                                         |

`AGENTS.md` czyta się zawsze. Skill czyta się wtedy, gdy praca dotyka jego
obszaru — i to nie jest sugestia, tylko wiersz w mapie ścieżek.

## 2. Routing

Klient wybiera skill po polu `description` we frontmatterze, nie po treści
pliku. Stąd dwie konsekwencje, które wyglądają na drobiazgi, a nie są:

- **`description` mówi, kiedy użyć**, nie co plik zawiera. Dwa opisy, które się
  pokrywają, robią z wyboru loterię;
- **adapter musi powtarzać `name` i `description` co do znaku.** Klient
  skanujący wyłącznie `.claude/skills/` routuje po adapterze; sam link do
  `.agents/` bez frontmatteru wyłączyłby routing po cichu — skill nadal by
  istniał i nigdy nie zostałby wybrany.

Adapter jest cienki (limit 1200 bajtów) i wskazuje plik kanoniczny. Wyjątkiem
są skills memexa, które jego własne narzędzie publikuje jako dokładne kopie;
walidator zna tę listę i sprawdza równość bajt po bajcie.

Implicit invocation zostaje domyślne: agent sam wybiera zestaw. Mapa ścieżek w
`AGENTS.md` jest siatką bezpieczeństwa na wypadek, gdy rozpoznanie intencji
zawiedzie — a zawodzi najczęściej tam, gdzie zadanie brzmi niewinnie („dodaj
pole"), a dotyka izolacji tenantów.

## 3. Granice uprawnień

Skill **nie może**:

- rozszerzać uprawnień ani autoryzować operacji produkcyjnej lub nieodwracalnej;
- zastępować ADR-u. Skill opisuje, jak pracować wewnątrz decyzji; zmiana samej
  decyzji wymaga nowego ADR-u;
- zawierać sekretu, tokenu ani danych klienta;
- powielać treści innego skill. Skill aplikacyjny niesie różnice branżowe i
  kieruje do skills Core/Shared.

Meta-skill `maintain-saas-core-skills` też im podlega: nie uznaje własnej zmiany
za poprawną dlatego, że plik się parsuje.

## 4. Walidacja

```
pnpm ai:validate
pnpm ai:eval
```

Obie bramki są deterministyczne i wpięte w `pnpm lint`, czyli i w CI.

`ai:validate` pyta, czy skill jest dobrze zbudowany: frontmatter i jego
domknięcie, `name` równy nazwie katalogu, unikalność nazw i opisów, długość
opisu, rozmiar pliku, istnienie **każdej ścieżki repozytorium** i **każdej
komendy `pnpm`** wymienionej w treści, zgodność frontmatteru adaptera z
kanonicznym, cienkość adapterów, równość mirrorów, adaptery osierocone, ślady
sekretów oraz **polecenia nieodwracalne w blokach kodu** (`git push`, `--force`,
`--apply`, `rm -rf`, `DROP`/`TRUNCATE`). Rozróżnienie jest celowe: pisać o tych
poleceniach wolno i często trzeba, podawać je do wykonania — nie.

`ai:eval` pyta o to, co jest ważne później: czy katalog **routuje** i czy
**pokrywa** produkt. Dla scenariuszy z `.agents/evals/routing.json` sprawdza, czy
oczekiwany skill wygrywa terminami z każdym innym, i czy każdy moduł katalogu ma
przypisaną procedurę albo świadomie wybrany skill ogólny — z zapisanym powodem.

Czego żadna z bramek **nie** sprawdza: czy model faktycznie wybierze właściwy
skill (to zależy od modelu; sprawdzalne jest tylko to, czy opisy rozróżniają) i
czy rada jest dobra. Od tego jest człowiek w przeglądzie — dlatego zmiana skill
idzie osobnym commitem, a diff jest recenzją.

## 5. Gdy instrukcja się zdezaktualizuje

Nieaktualny skill jest gorszy niż brak skill, bo jest wykonywany z przekonaniem.
Procedura naprawy jest w `.agents/skills/maintain-saas-core-skills/SKILL.md`:
wykryj zmianę źródła, wskaż zależne skills, zmień tylko to, co się zmieniło,
uruchom walidator, wykonaj to, co skill obiecuje, i zrób osobny commit z
dowodami.

Drift wykrywa się przy zmianie źródła: ADR-u, dokumentu w `docs/architecture/`,
deskryptora modułu lub deploymentu, kontraktu OpenAPI albo komendy jakościowej.
Walidator złapie przeniesioną ścieżkę i zniknięte polecenie od razu — reszta
wymaga przeczytania diffu źródła i zadania pytania, które skills na nim stoją.

## 6. Stan katalogu

Skills powstają dopiero, gdy mają realne źródła. Skill dla modułu, którego nie
ma, opisywałby zamiar, a walidator uznałby ten zamiar za aktualny.

Pierwszy katalog P2 jest kompletny — osiem skills: `change-tenant-data`,
`develop-saas-core-module`, `prepare-product-deployment`,
`change-api-and-events`, `develop-sites`, `develop-booking`,
`verify-saas-core-release` i `maintain-saas-core-skills`.

Później, razem z etapem, który tworzy ich źródło: `develop-commerce-payments`
(P5), `develop-assistant-runtime` (P6), `develop-medplano` (P7).
