# Kreator stron redesign: handoff

Branch `claude/kreator-redesign`, based on `main` at `e37cd193`. Worked on by
a cloud session (Claude Code on the web) with Maciej. Pushed after every phase;
never pushed to `main`.

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

| #   | What                                                                                                                  | State |
| --- | --------------------------------------------------------------------------------------------------------------------- | ----- |
| 1   | One 52 px top bar: back, page name + "Szkic, wersja N", mode, undo/redo, device switch in the middle, language, „…”, preview, save | done  |
| 2   | Vertical 64 px icon rail + one 300 px panel; compact outline with header/footer rows                                   | todo  |
| 3   | Section library: category chips, compact rows (thumbnail, name, two lines, eye + "+"), insert hint, canvas "+" opens it in the panel | todo  |
| 4   | Page templates: two-column grid of thumbnails, in-panel detail (description, goal/style, section list, preview, use)   | todo  |
| 5   | Inspector: "Sekcja N z M" header with icon actions; tabs Treść / Układ / Styl                                           | todo  |
| 6   | Tests, axe, PL/EN, 390 px check                                                                                       | todo  |

## Files touched (expect conflicts with local work)

- `apps/frontend/src/modules/shared/sites/page-editor.tsx` and its test
- `apps/frontend/src/modules/shared/sites/page-studio.tsx` and its test
- `apps/frontend/src/modules/shared/sites/section-canvas.tsx`
- `packages/ui/src/styles/site-studio.css`
- `apps/frontend/messages/pl.json`, `en.json` (`Sites.studio.*` only)

No backend, API, OpenAPI, `api-client` or migration changes so far.

## Notes for the integrator

- `PageEditor` has a new `leading` prop (the studio's back button and the
  dialog's title). `PageStudio` renders its own header row only for a language
  version (`PageLanguageEditor` is unchanged).
- `SectionCanvas` takes a `viewport` prop; the device switch moved from the
  canvas toolbar into the editor's top bar (hidden on a phone and in the forms
  mode). `.studio-stage-toolbar` is gone.
- Error, conflict and restored-version notices moved under the top bar
  (`.studio-notices`), so the bar is always the first row.
- Top bar controls are 32 px on a mouse (`pointer-fine:`) and keep 36/44 px on
  touch.
- Messages: `Sites.studio.draftVersion` added, `Sites.studio.liveCanvasLabel`
  removed.
- `LanguageSwitch` is untouched, so it keeps its own height in the bar.

## How to verify

```
pnpm --filter @saas-core/frontend typecheck
pnpm --filter @saas-core/frontend test -- src/modules/shared/sites
```

Then open a page in the studio at 1440 px and at 390 px: one top row on a wide
screen; on a phone the page name over save, preview and „…”, no sideways
scroll.

## Decisions that need Maciej

None open.
