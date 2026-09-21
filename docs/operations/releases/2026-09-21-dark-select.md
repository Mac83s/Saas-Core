# Native select contrast — 2026-09-21

The image picker in the dark Site Studio inspector opened a white native menu
with almost white unselected labels. This was reproduced in Chromium against
the running application. The document already used `color-scheme: dark`; the
select's dark background was translucent and its options had transparent
backgrounds, leaving the popup surface to the browser.

Commit `ddfb091` gives `NativeSelect` options and option groups an opaque
`--background` / `--foreground` pair. Disabled options use `--muted-foreground`.
The existing theme tokens provide both light and dark colors. The scope is the
shared component's `data-slot`, so the fix applies to all products and preserves
the light document preview inside a dark editor. Native form registration,
keyboard behavior and mobile controls remain in place; no component replacement
or new dependency was needed.

## Checks

- [x] Screenshot and computed styles reproduce the original light popup in dark mode.
- [x] The proposed CSS fixes the actual image picker in the running editor:
  dark options `#09090b` / `#fafafa`, light options `#ffffff` / `#09090b`.
- [x] Arrow/Home selection, Escape, disabled options and groups checked in Chromium.
- [x] 1440 px desktop and 390 px mobile viewport, no horizontal overflow or JS errors.
- [x] Light document preview stays light inside the dark editor.
- [x] UI tests **53/53**, UI TypeScript and ESLint, changed-file Prettier and diff checks.
- [x] Products synchronized through `core:update`; OpenAPI/client/profile regeneration
  produces no changes, and both `core:check` and deployment artifact checks pass.
- [x] Three production frontend images built, deployed and verified through HTTPS.
- [x] Real browser verification of served CSS in all three products.
- [x] Own synthetic accounts and imported template images removed after acceptance.

All three deployed frontends passed the real browser checks above using their
served CSS, without injected styles. Eighteen public HTTPS checks and CSS
fingerprints passed. Three own synthetic accounts and three stored template
images were removed, with zero pending objects on their erasure receipts.

Only shared CSS changes. Backend code, schemas and module profiles are unchanged;
there is no database migration. UI checks used host Node 22.22.2, which reports
the repository's Node 24 engine warning. Production images build on Node 24.17.0.
Browser checks use Chromium from Playwright 1.62.1; a mobile viewport is not a
separate iOS/Android browser verification.

## Deployment and recovery

| Product | Frontend image source |
| --- | --- |
| Saas-Core / vps-dev | `ddfb091` |
| HoofCare | `98d990e` |
| MedPlano | `fa8bcce` |

Each image is built from the exact Git archive of its source commit, with a
product-specific tag. Only the frontend service is recreated, using
`--no-deps --no-build`; the backend/frontend profile hash remains unchanged.
The previous frontend image is retained as
`<project>-frontend:rollback-dark-select-20260921`. These are local image IDs,
not registry digests. Rollback uses the retained frontend with the unchanged
backend and profile.

Private source manifests, image IDs, logs, screenshots and verification results:
`/root/Saas-Core/.runtime/releases/20260921-dark-select/`.

The first Saas-Core attempt hit a transient public 503 after the container was
healthy and automatically restored the previous image. Caddy logs confirmed its
10-second active health cycle still marked the recreated upstream unavailable.
The deployment check now allows up to 45 seconds for public health recovery,
while failing immediately on a profile mismatch. Caddy itself was not restarted
or reconfigured. The original and recovered container identities are retained.
HoofCare browser verification initially encountered ERR_NETWORK_CHANGED during
container recreation; the fresh run after deployment passed. A host-wide identity
check also observed a change to goldenstar-engine-1 outside this frontend-only
operation. The scoped check confirms all **25** product backends, workers,
schedulers, databases and infrastructure containers retain their original IDs,
images and start times.

The four earlier infrastructure follow-ups remain outside this CSS increment.
Native popup rendering remains browser-dependent; explicit option colors are
supported in the Chromium configuration used for this acceptance. See
[MDN option styling](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/option#styling_with_css).
