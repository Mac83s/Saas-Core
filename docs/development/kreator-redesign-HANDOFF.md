# Kreator stron redesign: handoff

Branch `claude/kreator-redesign`, based on `main` at `e37cd193` (still the tip
of `origin/main` at the last push). Worked on by a cloud session (Claude Code
on the web) with Maciej. Pushed after every phase; never pushed to `main`.

## Scope

The Claude Design mockup "Kreator stron" redesigns the **page editor** (Site
Studio: `PageStudio` → `PageEditor` → `SectionCanvas`), not the site onboarding
wizard. Maciej chose (2026-10-03) to implement it in the page editor files.
`site-onboarding.tsx`, the onboarding backend and the onboarding route are not
touched.

Owner answers (also recorded in memex as
`kreator-stron-redesign-one-row-top-bar-icon-rail`):

1. The section library gets category chips with counts; the industry filter
   stays as a small select under them (product's trade first, decision 4a of
   24.09).
2. Each library row has an eye icon (opens the existing preview dialog) beside
   the "+" that adds the section.
3. List view only; no list/grid switch for the user.
4. Push to this branch after each phase, never to `main`.

Thumbnails stay real renders of the canonical recipes (decision "render
page-template previews from canonical recipes"), not the mockup's wireframe
rectangles.

## Design source

Claude Design project "Redesign kreatora stron", file `Kreator stron.dc.html`
(handoff bundle). It was not published as an artifact from this session: the
session's sharing policy blocked it. Maciej can share the Claude Design link.

## Phases

| #   | What                                                                                                                                   | State |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | ----- |
| 1   | One 52 px top bar: back, page name + "Szkic, wersja N", mode, undo/redo, device switch in the middle, language, „…”, preview, save     | done  |
| 2   | Vertical 72 px icon rail + one 300 px panel; compact outline with header/footer rows and a working drag handle                         | done  |
| 3   | Section library: category chips with counts, compact rows (thumbnail, name, two lines, eye + "+"), insert hint, canvas "+" opens it    | done  |
| 4   | Page templates: two-column gallery of rendered thumbnails, in-panel detail (description, goal/style, section list, preview, use)        | done  |
| 5   | Inspector: "Sekcja N z M" header with icon actions (up, down, duplicate, save as company template, remove); tabs Treść / Układ / Styl | done  |
| 6   | Tests, axe, PL/EN, 390 px, dark scheme                                                                                                 | done  |

## Files touched (expect conflicts with local work)

- `apps/frontend/src/modules/shared/sites/page-editor.tsx` and its test
- `apps/frontend/src/modules/shared/sites/page-studio.tsx` and its test
- `apps/frontend/src/modules/shared/sites/section-canvas.tsx`
- `apps/frontend/src/modules/shared/sites/section-library.tsx` and its test
- `apps/frontend/src/modules/shared/sites/own-templates.tsx` (compact rows
  for company section and page templates in the studio's panel, an icon-only
  "save as company template"; the cards elsewhere are unchanged)
- `apps/frontend/src/modules/shared/sites/block-form.tsx` (`BlockFields`
  `part`, `SectionMoveButtons` `compact` + children)
- `apps/frontend/src/modules/shared/sites/page-editor-rich-content.test.tsx`
  (picks the category by its chip, opens a template's details, the "Styl" tab)
- `apps/frontend/src/modules/shared/sites/placeholder-banner.test.tsx` (asks
  for the "Treść" textbox, not the "Treść" tab)
- `packages/ui/src/styles/site-studio.css`
- `apps/frontend/messages/pl.json`, `en.json` (`Sites.studio.*` and
  `Sites.sectionLibrary.*` only)

No backend, API, OpenAPI, `api-client` or migration changes.

## Notes for the integrator

Top bar (phase 1)

- `PageEditor` has a new `leading` prop (the studio's back button and the
  dialog's title). `PageStudio` renders its own header row only for a language
  version (`PageLanguageEditor` is unchanged).
- `SectionCanvas` takes a `viewport` prop; the device switch moved from the
  canvas toolbar into the editor's top bar (hidden on a phone and in the forms
  mode). `.studio-stage-toolbar` is gone.
- Error, conflict and restored-version notices moved under the top bar
  (`.studio-notices`), so the bar is always the first row.
- Top bar controls are 32 px on a mouse (`pointer-fine:`) and keep 36/44 px on
  touch. `LanguageSwitch` is untouched, so it keeps its own height in the bar.

Left side (phase 2)

- A rail (72 px, wider than the mockup's 64 px so „Biblioteka” and
  „Podstrony” do not break mid-word) beside one 300 px panel that names what it
  holds; the workspace grid is `372px | 1fr | 320px`. The rail keeps the
  product's words (Sekcje, Biblioteka, Całe strony, Wygląd, Podstrony) rather
  than the mockup's „Dodaj”/„Szablony”, so tests and the label-in-name rule
  hold. On a phone the rail lies in one row over the panel.
- The outline is a `ReorderList` of its own: each row selects its section, its
  grip moves it (drag or arrow keys; handle named „Przenieś sekcję N na
  liście” so it never collides with the canvas handle). The site's header and
  footer show as muted rows around the sections when the site has them.

Section library (phase 3)

- `SectionLibraryContent`: the category select became a group of chips
  (`aria-pressed`, short word visible, full name in `title`); a chip's count
  follows the search and the trade, an empty category hides unless chosen. The
  industry select stays. In the panel (`compact`) each layout is one row: a
  84×56 render of the recipe at 10 %, its name and two lines, an eye (the
  existing preview dialog) over a "+"; a click anywhere on the row adds it too
  (an `aria-hidden` button under the row, the pattern the canvas already uses).
  The dialog in the forms mode keeps its cards, with the chips.
- The canvas's "+" no longer opens a library dialog: it opens the library in
  the left panel, aimed at that gap („na początku strony”, „po sekcji 2” in
  the panel's header) and focuses its search. Adding, or choosing another
  section, goes back to "under the selected section". The bare block picker
  moved under the library („Potrzebujesz czegoś innego?”).

Page templates (phase 4)

- `TemplateOption` (one tall card per recipe) is replaced by `TemplateTile` (a
  3:4 render at 12.5 % with name and goal; the whole tile is one button) and
  `TemplateDetail` (goal and style, the sections by type and heading, the full
  preview dialog and "Użyj szablonu", which keeps its accessible name „Użyj
  szablonu {name}”). `PageTemplatePicker` in `page-editor.tsx` holds which one
  is open; the way back focuses its tile. Company page templates sit above as
  compact rows, or a dashed box with "save this page" when there are none. The
  swap flow is unchanged.

Inspector (phase 5)

- The header says „Sekcja N z M” and the type, with one row of icons
  (`SectionMoveButtons compact` with duplicate and `SaveAsTemplate iconOnly`
  between "down" and "remove"). Below, `@saas-core/ui` `Tabs`: Treść (the
  fields; a separator's size, width and tone), Układ (type change, layout
  select, layout comparison) and Styl (width, surface, anchor, then
  decorations).
- `BlockFields` takes `part`; the other parts stay mounted and `hidden`, so a
  registered select (the layout, a separator's size) keeps giving the form the
  value it shows, exactly as before. Without that, a legacy hero saved without
  its `layout`. Forms mode passes no `part` and is unchanged.
- A save the schema refuses switches to the tab with the first error; "Zmień
  zdjęcie" on the canvas switches to Treść. „Dodaj sekcję poniżej” is gone from
  the inspector: the canvas's "+" and the panel's library do that.
- Inputs and selects in the inspector are 36 px on a mouse (`pointer: fine`),
  44 px on touch.

Messages (pl and en, both)

- Added: `Sites.studio.draftVersion`, `siteHeader`, `siteFooter`,
  `reorderInOutline`, `insertAtStart`, `insertAfterNumber`, `blankHint`,
  `allTemplates`, `templateSections`, `useTemplate`, `sectionOf`,
  `inspectorTabs`, `tabContent`, `tabLayout`, `tabStyle`, `oneLayout`;
  `Sites.sectionLibrary.allShort`, `Sites.sectionLibrary.chip.*`.
- Removed (no longer used): `Sites.studio.liveCanvasLabel`, `outlineHint`,
  `insertAfter`.

## How to verify

What this session ran on the branch (Node 24.21, pnpm 11):

```
pnpm --filter @saas-core/frontend typecheck   # clean
pnpm --filter @saas-core/frontend test        # 111 files, 919 tests passed
pnpm --filter @saas-core/ui test              # 13 files, 80 tests passed
pnpm exec eslint <changed files>              # clean
pnpm exec prettier --check <changed files>    # clean
```

New tests: the top bar's device switch, the outline's own handle, category
chips and their counts, the canvas "+" opening the panel library at its gap,
a template's details and the way back, the inspector's header, icons and tabs
(axe included), a refused save returning to the right tab.

Visual check: on a local page that rendered `PageStudio` with stubbed API
answers (not committed), at 1440, 1024 and 390 px and in the dark scheme; no
sideways scroll at 390 px. It was not run on the live stack: please open a page
in the studio there, add a section with "+" between two sections, open a ready
page's details and use it on a page with content (the swap dialog), and switch
the inspector's tabs on a separator and on a hero.

## Follow-ups after the owner's answers (03.10, `feat/editor-followups`)

Maciej's answers to the three decisions below: 1a (the rail keeps „Biblioteka”
and „Całe strony”), 2b and 3b. What followed:

- `PlaceholderBanner` is one line under the top bar at every width: what is
  left in short (slots, „kontakt z szablonu”, links to nowhere) as the polite
  status, „Pokaż”/„Zwiń” and the close button. The sentences and the section
  chips are a region that is `hidden` until asked for, so a test opens it
  before it reads them.
- Styl tab: the content width is a row of segments (`SegmentedOptions`, the
  top bar's `.studio-segmented`), the surface is four swatch buttons painted by
  the site's own look (`PageEditorContext.look` + the real
  `site-presentation--surface-*` class, `.studio-swatch`), the decoration's
  visibility is two segments. Each is a `fieldset` named by its legend with
  `aria-pressed` buttons. The other decoration fields stay selects: their
  options are too long for segments, and a background pattern is not readable
  in a 20 px dot. Neither set draws a box of its own any more, so no legend
  sits on a border. „Standardowa (jak witryna)” became „Standardowa”; the hint
  under the segments says the rest.
- The language mode has the source editor's top bar (`PageLanguageEditor`
  takes `leading`; `PageStudio` no longer draws a header row): back, the page's
  name over „{language} · Wersja N”, from 1280 px the sentence about the
  structure with the way to the source (narrower: under „Więcej”), then the
  language switch, „Więcej”, preview and save. `LanguageSwitch` is unchanged.

## What is left

- The Wygląd and Podstrony panels keep their content (the mockup only sketched
  them).
- The mockup is not on the local machine: the swatches and segments are plain
  `@saas-core/ui` buttons, not a copy of its drawing.
