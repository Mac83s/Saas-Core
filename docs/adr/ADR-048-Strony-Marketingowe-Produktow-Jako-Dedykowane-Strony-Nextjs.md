# ADR-048: Strony marketingowe produktów to dedykowane strony Next.js, nie builder klientów

Status: zaakceptowana, 2026-09-18 (decyzja właściciela). Zmienia ADR-035 §1–2 w
zakresie stron marketingowych produktów; nie zmienia ADR-035 dla stron klientów.

## Kontekst

ADR-035 założył, że strony marketingowe i blog samej platformy powstają w
chronionym workspace platformy — tymi samymi blokami i tym samym rendererem co
strony klientów — a SeoContentRank optymalizuje je przez ten sam kontrakt
content-operations. Plan W9.6 opisuje to w scenariuszu demonstracyjnym.

Na tym jednym repozytorium stoją dziś trzy produkty (SaaS Core Business,
HoofCare, MedPlano). Każdy potrzebuje własnej strony głównej, cennika, kontaktu,
bloga i stron prawnych, w PL i EN, z pełnym SEO. Próba z 2026-09-18 pokazała,
że droga przez builder daje stronę złożoną z bloków pisanych z myślą o małej
firmie klienta, a nie o stronie produktu — i że workspace platformy nie był
nigdy uruchomiony w żadnym stosie (provisioning nadawał `sites.enabled`, ale nie
`sites.max`, więc `create_site` kończył się `QuotaUnavailable`).

## Decyzja

1. **Strony marketingowe produktów to dedykowane trasy Next.js** w
   `apps/frontend`, na wzór paneli SEOSiteAudit i SeoContentRank (szablon
   NextJs-Boilerplate): strona główna, cennik, kontakt, blog z wpisami, strony
   prawne. Odpowiadają na domenie produktu obok aplikacji (panel, logowanie,
   rejestracja).
2. **Treść jest per produkt i edytowalna**, wybierana po profilu deploymentu.
   Kod stron nie zawiera tekstów produktu. Cennik pochodzi z API billingu, nie z
   kodu.
3. **Wielojęzyczność i SEO jak w szablonie:** PL i EN przez `next-intl`, metadane
   z `hreflang` na każdej stronie, `sitemap`, `robots`, Open Graph, dane
   strukturalne.
4. **Builder (`shared.sites`) zostaje narzędziem dla stron klientów.** Workspace
   platformy z ADR-035 zostaje w kodzie, ale nie jest nośnikiem marketingu
   produktów.

## Konsekwencje

- **SeoContentRank potrzebuje osobnej integracji ze stronami produktów.**
  Kontrakt content-operations (ADR-035 §5) obejmuje wyłącznie treści w
  `shared.sites`, czyli strony klientów. Strony marketingowe produktów leżą poza
  nim, więc SCR nie zoptymalizuje ich przez istniejący connector. Integracja SCR
  ma odtąd dwie osobne drogi: builder klientów (istniejący kontrakt) i strony
  produktów (do zaprojektowania — patrz plan 14).
- **Kształt tej drugiej integracji zależy od formy edycji treści** — na teraz
  pliki w repozytorium (niżej). Treść w plikach repozytorium oznacza, że SCR proponuje
  zmiany jako zmianę w repo; treść w bazie edytowana z panelu oznacza wąskie API
  z tymi samymi zasadami co content-operations (grant, digest, zatwierdzenie).
- Scenariusz demonstracyjny W9.6 („operator publikuje stronę marketingową w
  workspace platformy") przestaje opisywać strony produktów; pozostaje ważny dla
  stron klientów.
- Znany defekt, gdyby workspace platformy miał kiedyś wrócić: provisioning nie
  nadaje quoty `sites.max`.

## Forma edycji (rozstrzygnięte 2026-09-18)

Najpierw **pliki w repozytorium**, jak w SEOSiteAudit: teksty w tłumaczeniach PL
i EN, blog i strony prawne jako MDX. Treść jest wydzielona z komponentów, więc
późniejsza edycja z panelu operatora to podmiana źródła, a nie przebudowa stron.
Dla SCR oznacza to na teraz propozycję zmiany w repozytorium.

## Alternatywy odrzucone

- **Strony produktów w builderze klientów (ADR-035).** Bloki projektowane pod
  stronę małej firmy, a nie pod stronę produktu; właściciel nie chce budować
  stron produktów narzędziem przeznaczonym dla klientów.

## Relacje

ADR-035 (treści systemowe — zmieniony w zakresie marketingu produktów), ADR-028
(routing hostów — bez zmian: host produktu należy do aplikacji Next.js).
