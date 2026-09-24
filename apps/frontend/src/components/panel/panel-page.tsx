import type { ReactNode } from "react";
import { ChevronLeftIcon, InfoIcon } from "lucide-react";

import { Link } from "#i18n/navigation";

/**
 * The one page of the client panel (ADR-057): a header with the section above
 * the title, the page's own actions on its right, a line for "saved" and the
 * content — optionally with help or tools beside it. The width is the
 * layout's, never the page's, so no two pages differ.
 *
 * No hooks: a server page and a client module both render it.
 */
export function PanelPage({
  eyebrow,
  eyebrowHref,
  title,
  titleId,
  description,
  actions,
  notice,
  aside,
  asideLabel,
  children,
}: {
  /** The section the page belongs to, e.g. "Magazyn" over "Dokumenty". */
  eyebrow?: ReactNode;
  /** Makes the eyebrow the way back up, e.g. a farm's page to the farms. */
  eyebrowHref?: string;
  title: ReactNode;
  /** For a region the page's title names (`aria-labelledby`). */
  titleId?: string;
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
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 space-y-1.5">
          {eyebrow && eyebrowHref ? (
            <Link
              className="-ml-1 inline-flex min-h-8 items-center gap-1 rounded-md px-1 text-sm font-medium text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              href={eyebrowHref}
            >
              <ChevronLeftIcon aria-hidden="true" className="size-4" />
              {eyebrow}
            </Link>
          ) : eyebrow ? (
            <p className="text-sm font-medium text-primary">{eyebrow}</p>
          ) : null}
          <h1
            className="text-2xl font-semibold tracking-tight wrap-anywhere sm:text-3xl"
            id={titleId}
          >
            {title}
          </h1>
          {description ? (
            <p className="max-w-3xl text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
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
    <div aria-busy="true" className="space-y-6">
      <span className="sr-only">{label}</span>
      <div className="space-y-2.5">
        <div className={`${bar} h-4 w-24`} />
        <div className={`${bar} h-8 w-64 max-w-full`} />
        <div className={`${bar} h-4 w-96 max-w-full`} />
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
