# Profile zaparkowane

Profil produktu, którego moduły jeszcze nie istnieją, leży tutaj — poza wzorcem
`deployments/<nazwa>/`, który akceptuje walidator. Dzięki temu nie udaje
poprawnego: `deployment.json` wymieniający nienapisany moduł przechodzi schemat,
a wywala się dopiero przy starcie procesu.

Profil wychodzi stąd w tym samym przyroście, w którym powstaje jego wertykał, i
wtedy przechodzi `pnpm deployment:check --profile <nazwa>` oraz
`pnpm deployment:artifact`.

Dziś nic tu nie stoi. MedPlano czekał w tym miejscu od sierpnia 2026 i wyszedł
17.09.2026 razem z modułem `vertical.medical` — przy okazji okazało się, że jego
zaparkowana lista wymieniała `core.audit` i `config.medplano`, których w
katalogu modułów nie ma. To jest właśnie ten rodzaj dryfu, dla którego profile
bez kodu trzymamy poza walidacją, a nie obok gotowych.
