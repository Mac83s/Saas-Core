# ADR-063 — szablony firmy jako dane organizacji obok recept w plikach

**Status:** Accepted — odpowiedzi właściciela 2026-09-28 (1a, 2a, 3a, 4a),
plan memex `saas-core-site-studio-templates` (F4-B).
**Data:** 2026-09-28

Częściowo doprecyzowuje decyzję memex
`page-templates-remain-file-backed-immutable-reci` („szablony stron zostają
niezmiennymi recepturami w plikach, bez tabeli ORM”): obowiązuje ona nadal dla
recept **systemowych**; nie obejmuje szablonów, które zapisuje organizacja.

## Kontekst

Recepty stron i sekcje biblioteki są kontraktami rdzenia: pliki w
`packages/contracts/page-templates` i katalog sekcji, wersjonowane razem z kodem,
jednakowe dla wszystkich. Właściciel 28.09 chce, żeby firma mogła zapisać własną
sekcję albo całą stronę **z treścią i zdjęciami** (2a), widoczną dla całej
organizacji (3a), dostępną we wszystkich planach z limitem w niższych (4a).
Takie szablony powstają w runtime, należą do jednego tenanta i zawierają jego
treść — nie mogą być plikami w repozytorium.

## Decyzja

1. **Dwa źródła szablonów.** Recepty systemowe zostają plikami (bez zmian). Szablony
   firmy to dane tenanta: `SiteTemplate` (rodzaj `section`/`page`, nazwa, opis,
   bieżąca wersja, archiwizacja) i niezmienne `SiteTemplateVersion` (sekcje,
   wygląd strony tylko dla szablonu strony, zdjęcia). Obie tabele mają wymuszone
   RLS; wersje są append-only (wyzwalacz, wyjątek tylko dla usuwania organizacji,
   ADR-042), strażnik nie pozwala wersji wskazać szablonu innego tenanta.
2. **Kopia, nie odwołanie.** Użycie szablonu kopiuje jego sekcje do strony (sekcja
   do formularza, strona przez ten sam `save_draft` z pochodzeniem
   `own_template`). Nowa wersja szablonu ani archiwizacja nie zmieniają stron już
   zbudowanych. Publiczny renderer nigdy nie czyta szablonów.
3. **Zdjęcia żyją z wersją.** Wersja trzyma referencje mediów z typem właściciela
   `sites.template_version`, jak wersja strony — ten sam mechanizm, te same
   reguły gotowości i izolacji.
4. **Uprawnienia i limit.** Zapis, zmiana nazwy i archiwizacja wymagają
   `site.content.edit` (właściciel, administrator, kierownik) i `sites.enabled`;
   API jest granicą. Limit to kwota `sites.templates.max` na aktywne szablony obu
   rodzajów razem; plan bez kwoty nie ma limitu.

## Konsekwencje

- Biblioteka sekcji i galeria stron mają dwie grupy: „Szablony firmy” (z API) i
  gotowe recepty (z plików). Typy API są generowane z OpenAPI.
- Usunięcie zdjęcia z biblioteki mediów po zapisaniu szablonu sprawia, że import
  szablonu strony odmawia (`site_media_reference_unavailable`); dopasowanie przy
  podmianie to F4-C.
- Liczby limitu per plan wymagają migracji planów (wzór `billing/0024_pages_quota`)
  po decyzji właściciela; do tego czasu limitu nie ma nigdzie.
