import type { ReactNode } from "react";
import { ChevronLeftIcon, InfoIcon } from "lucide-react";

import { Link } from "#i18n/navigation";
import { PanelEyebrow } from "./panel-eyebrow";

/**
 * The one page of the client panel (ADR-057): a header with the section above
 * the title, the page's own actions on its right, a line for "saved" and the
 * content — optionally with help or tools beside it. The width is the
 * layout's, never the page's, so no two pages differ.
 *
 * The header is compact and ends with a light line, so the work starts high on
 * the screen; on a phone the description gives way to it (owner, 01.10).
 *
 * No hooks: a server page and a client module both render it.
 */
export function PanelPage({
  eyebrow,
  eyebrowHref,
  title,
  titleId,
  subtitle,
  description,
  actions,
  notice,
  aside,
  asideLabel,
  children,
}: {
  /**
   * Only for a page outside the menu: under a menu entry the eyebrow is that
   * entry's name (R1, UX-003). With `eyebrowHref` it is the way back up.
   */
  eyebrow?: ReactNode;
  /** Makes the eyebrow the way back up, e.g. a farm's page to the farms. */
  eyebrowHref?: string;
  title: ReactNode;
  /** For a region the page's title names (`aria-labelledby`). */
  titleId?: string;
  /**
   * A line of data or scope under the title — „Właściciel · w firmie od…”,
   * „Twoje ustawienia, każdy ma własne”. Unlike the description it stays on a
   * phone (UX-005).
   */
  subtitle?: ReactNode;
  /** An explanation; a phone leaves it out to start the work higher. */
  description?: ReactNode;
  /** What the page lets one do (add, receive), top right. */
  actions?: ReactNode;
  /** The outcome of the last action; read out when it changes. */
  notice?: string;
  /** Help or tools: beside the content from 1280 px, under it below. */
  aside?: ReactNode;
  /** Names the aside for screen readers, e.g. "Help". */
  asideLabel?: string;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-4 lg:space-y-5">
      {/* One wrapping row: actions that fit stay by the title (a lone
          icon), wider ones take the next line (UX-004). */}
      <header className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3 border-b pb-3 sm:pb-4">
        <div className="min-w-0 flex-1 basis-64 space-y-1">
          {eyebrow && eyebrowHref ? (
            <Link
              className="-ml-1 inline-flex min-h-8 items-center gap-1 rounded-md px-1 text-sm font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              href={eyebrowHref}
            >
              <ChevronLeftIcon aria-hidden="true" className="size-4" />
              {eyebrow}
            </Link>
          ) : (
            <PanelEyebrow fallback={eyebrow} title={title} />
          )}
          <h1
            className="text-xl font-semibold tracking-tight wrap-anywhere sm:text-2xl"
            id={titleId}
          >
            {title}
          </h1>
          {subtitle ? (
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          ) : null}
          {description ? (
            <p className="max-w-3xl text-sm text-pretty text-muted-foreground max-sm:hidden">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            {actions}
          </div>
        ) : null}
      </header>
      {notice !== undefined ? (
        <p
          aria-live="polite"
          className="text-sm text-success-foreground empty:hidden"
        >
          {notice}
        </p>
      ) : null}
      {aside ? (
        <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="min-w-0 space-y-6">{children}</div>
          <aside aria-label={asideLabel} className="space-y-4">
            {aside}
          </aside>
        </div>
      ) : (
        children
      )}
    </div>
  );
}

/**
 * What the page shows, above its filters: a date and its arrows, a choice of
 * view. A light line under it, like the header's, keeps the rows apart.
 */
export function PanelToolbar({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b pb-3">
      {children}
    </div>
  );
}

/**
 * A part of a page with several lists (settings, a farm): its title on the
 * left, what can be added to it on the right, like the page's own header.
 */
export function PanelSection({
  title,
  description,
  actions,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-lg font-semibold">{title}</h2>
          {description ? (
            <p className="max-w-3xl text-sm text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

/** A card of the aside: a short explanation next to the list it is about. */
export function PanelHelp({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2 rounded-xl border bg-muted/40 p-4 text-sm">
      <h2 className="flex items-center gap-2 font-semibold">
        <InfoIcon aria-hidden="true" className="size-4 text-primary" />
        {title}
      </h2>
      <div className="space-y-2 text-muted-foreground">{children}</div>
    </section>
  );
}

/** What a panel page looks like before its data arrives — the same everywhere. */
export function PanelSkeleton({ label }: { label: string }) {
  const bar = "animate-pulse rounded-md bg-muted";
  return (
    <div aria-busy="true" className="space-y-4 lg:space-y-5">
      <span className="sr-only">{label}</span>
      <div className="space-y-2 border-b pb-3 sm:pb-4">
        <div className={`${bar} h-4 w-24`} />
        <div className={`${bar} h-7 w-56 max-w-full`} />
        <div className={`${bar} h-4 w-96 max-w-full max-sm:hidden`} />
      </div>
      <div className={`${bar} h-11 w-72 max-w-full`} />
      <div className="space-y-2">
        {[0, 1, 2, 3, 4].map((row) => (
          <div className={`${bar} h-14`} key={row} />
        ))}
      </div>
    </div>
  );
}
