# Profile zaparkowane

Profil produktu, którego moduły jeszcze nie istnieją, leży tutaj — poza wzorcem
`deployments/<nazwa>/`, który akceptuje walidator. Dzięki temu nie udaje
poprawnego: `deployment.json` wymieniający nienapisany moduł przechodzi schemat,
a wywala się dopiero przy starcie procesu.

Profil wychodzi stąd w tym samym przyroście, w którym powstaje jego wertykał, i
wtedy przechodzi `pnpm deployment:check --profile <nazwa>` oraz
`pnpm deployment:artifact`.

Dziś nic tu nie stoi. Profil produktu z własnym wertykałem żyje w repozytorium
tego produktu (ADR-049), nie tutaj.
