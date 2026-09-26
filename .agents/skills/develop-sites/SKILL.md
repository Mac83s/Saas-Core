---
name: develop-sites
description: Working on customer websites in SaaS Core — pages and blocks, drafts and publication, collections and entries, domains, DNS and TLS, public media, and the content-operations contract an external optimizer writes through. Use when touching modules/shared/sites, the public renderer, page templates or automation grants.
---

# Sites: content, publication and domains

Read `docs/adr/ADR-027-Sites-Tresc-Media-i-Publikacja.md` (content and
publication), `docs/adr/ADR-028-Domeny-DNS-TLS-i-Publiczny-Routing.md`
(addresses), `docs/adr/ADR-031-Panel-Klienta-i-Wizualny-Site-Studio.md` (the
editor) and `docs/adr/ADR-035-Publikacja-Systemowa-i-SeoContentRank.md`
(automation). `memex_pack` first — this module has more recorded traps than any
other.

## The shapes that decide everything else

- **Versions are append-only.** A new `PageVersion` writes a fresh set of block
  rows with fresh UUIDs. No block identity survives between versions, which is
  why the change-set contract addresses blocks by **position against
  `base.version`**, never by id, and why the whole set applies as one unit
  rather than command by command.
- **Publication is a snapshot.** The renderer reads
  `Publication.snapshot`, not live tables, so an edit becomes visible on the
  next publication — the same way a navigation change does. Anything a page
  must show at render time has to be *in* the snapshot.
- **Entries publish on their own.** A blog entry is reachable even when the site
  has no publication yet, so the entry's own publication stands in for the
  site's. Do not make the collection depend on the site snapshot.
- **A hostname is the tenant declaration.** `sites_domain` has no policy, so the
  renderer resolves the host, then reads everything else *inside* that tenant
  via `tenant_is_servable(organization_id)` in
  `apps/backend/src/saas_core/modules/shared/sites/publication_routing.py`.
  The public paths must never use the pre-tenant door — see `change-tenant-data`.

## Six operations belong to a person

`assert_person_required(context, what)` in
`apps/backend/src/saas_core/modules/shared/sites/services.py` refuses every
automation context with `403 person_required`: domains (create, change,
mutate), site navigation, the pricing block, legal pages, withdrawals, and
publishing a whole site. `PERSON_ONLY_PAGE_TYPES` and
`PERSON_ONLY_BLOCK_TYPES` hold the type lists.

The check runs **before** the surface policy on purpose: `person_required`
tells a connector "this will never be yours", while `page_automation_forbidden`
says "this surface is not yours today". Connectors treat those differently.

If you add an endpoint in this area, ask which of the two it is, and add it to
the helper rather than writing a second check.

## Automation grants

Four modes: `suggest_only`, `draft_write`, `publish_with_approval`,
`autonomous`. The historical `auto_publish_limited` is **not** an alias and must
fail closed. `autonomous` means no per-change approval — it is still bounded by
resource scope, limits, windows, command and link allowlists, the kill switch
and the content policy, which can only narrow a grant.

Every service behind an `IsSessionOrApiKey` route asks the grant, reads
included — `assert_within_grant`, or `_assert_entry_writable` for anything that
writes into a collection. Creating a collection or an entry once asked nothing,
so a key hired for one blog could open sections and write articles beside it.
A listing narrows to what the key's grants cover rather than refusing. When a
site grant and a collection grant both reach an entry, the collection grant
decides — mode and link hosts alike — whichever was issued first.

The link allowlist is `assert_links_within_grant` in `services.py`: an
automation may link only to the site's own hostnames (its verified `Domain`
rows — a pending one is only a claim) and the grant's `allowed_link_hosts`,
exact match after IDNA normalization, no implied subdomains; an empty list
means internal links only. `normalize_hostname` lowercases rather than
casefolds: casefolding makes `straße.de` equal `strasse.de`, two domains a
browser keeps apart.
Paths, in-page anchors, `mailto:` and `tel:` have no host and pass. It runs in
the change-set plan (so preview refuses too, before anything is written) and in
`save_draft`/`save_entry_draft`, because a key also writes entry drafts
directly. Hosts are read the way a browser reads them (`link_host` in
`domains.py`: `//host`, `/\host`, userinfo, extra slashes). Links already in
the draft being changed are exempt — they are the person's, not the
automation's. Every block link field must be named `href`/`…Href`/`…_href`,
the one exception being `core.entry_list` `items[].path` (`is_link_field` names
it); a test holds every schema field whose pattern accepts a path or an
`https://` URL to that rule. A person's session is never limited.

A link says how it vouches for its target with `rel` (ADR-061: rich text v4,
link list v2, footer v2). `default_automation_rel` gives an automation's new
outbound link `nofollow` and puts back a `rel` a person set; it runs in the
change-set plan and in both draft saves, next to the host check.

The contract has **no command that changes a published address**, and it will
not get one. `translation.update` carries `title`, `description`,
`social_title`, `social_description` — no `slug`. Moving a URL costs the
position that URL earned; it goes through
`PUT /api/v1/sites/pages/<id>/url/`, a human session with a mandatory reason.

Capabilities answer with the **narrowest** active grant mode, each grant's
scope with its `allowed_link_hosts`, the command list read from
`packages/contracts/content-operations/`, and the contract versions.
A capabilities response that disagrees with the contract it describes is worse
than none, because the client believes it.

## Section and page templates are built to convert

Owner decision, 2026-09-23: every new section template and page recipe is
designed for conversion — a visitor should know within one screen what they
get and what to do next. The templates that existed before are **not** a
quality reference; do not extend or imitate them. Their versions stay loadable
for pages already built on them, and new recipes replace them in the library.
The acceptance checklist is in `docs/architecture/site-section-catalog.md`
("Szablony nastawione na konwersję"); in short:

- **One goal per page.** A recipe names its primary action (inquiry form,
  call, booking, e-mail) and every button says the outcome ("Umów bezpłatną
  wycenę"), not the mechanism ("Wyślij").
- **First screen sells**, at 390 px as much as at 1440 px: who it is for and
  what they get, one supporting sentence, the primary action, a trust cue or
  photo. Never "Witamy na naszej stronie".
- **Decision path:** need → offer and benefits → proof → how it works / what
  happens next → objections (FAQ, limits, price range) → final call to action.
  The primary action returns at each decision point; one quieter secondary
  action at most, never two competing buttons in one section.
- **Proof is never invented.** Seeds carry no made-up reviews, ratings,
  client logos, statistics, prices or certificates. They carry clearly marked
  slots (`[Uzupełnij: …]`) the owner fills with real material. The same holds
  for automation (blueprints never write quotes or proof).
- **Low friction:** short forms (name, contact, message), say what happens
  after sending and how soon, no account required.
- **No dark patterns:** no countdowns, fake scarcity, pre-ticked consent.
- **Mobile and speed** are part of conversion: the action is reachable on the
  first phone screen, tap targets 44 px, the hero image fits the LCP budget.

Review each new template against the checklist with screenshots at 390 and
1440 px before it enters the catalogue.

## Traps

- **Reading media before setting the tenant.** `media_mediaasset` forces RLS, so
  `serve_public_media` sets the tenant the host named before the read. That bug
  once made every image on every published page answer 404.
- **Scheduled publication cannot carry a signed contract.** It expires long
  before the date. `publish_scheduled_entry` rebuilds the context from the
  stored `scheduled_membership_id`, or for an integration from
  `scheduled_credential_id` (a key's membership id is synthetic and would never
  be found), which also means a person suspended or a key revoked in the
  meantime does not get one more publication out of the queue. A schedule whose
  author can no longer be acted for is closed as `failed` with a reason, not
  left pending for the scan to hand out every minute.
- **A page view is the renderer's verdict** (ADR-060). `countsAsPageView`
  decides in the renderer and only `x-saas-core-count-view: 1` reaches the
  backend — never the user agent. Layout, metadata and page build the same
  path (`publicSitePath`) and pass the same verdict; if one of them asks
  differently, `cache()` splits the call and a visit counts twice. The metrics
  route takes only the `content:metrics` scope and a whole-site grant.
- **Template media goes through the ordinary media lifecycle** — upload
  completion, malware scan, normalization, variants, quota, audit. There is no
  trusted-file shortcut. Object storage does not roll back with PostgreSQL, so
  a failed import compensates by deleting only what that attempt created.
- **The rich text editor's schema is the contract** (ADR-056). A new node,
  mark or limit in `core.rich_text` also goes into `rich-text-schema.ts` and
  `rich-text-doc.ts`; the round-trip test pushes every shipped seed and recipe
  through the editor and must get it back unchanged. The editor writes to the
  page form and Ctrl+Z is the page's undo (`PageEditorContext`) — do not add a
  second history. jsdom cannot type into `contentEditable`: typing, shortcuts,
  paste and undo are checked in a browser, jsdom checks loading and the UI.
- **A contract directory read at runtime must be in the image**, with an env var
  and a Django system check. `PAGE_TEMPLATE_CONTRACTS_PATH` once resolved to a
  path that existed in a checkout and not in the container: 361 green tests, and
  a 500 on the first import click.

## Done means

```
pnpm backend:test
pnpm api:check
pnpm --filter @saas-core/frontend test
```

plus, for anything the public renderer touches, a page, a feed and an image
fetched from the running stack by hostname — the suite cannot tell you the
renderer works, because it does not go through Caddy.
