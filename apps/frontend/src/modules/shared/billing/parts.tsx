import type { ComponentProps, ReactNode } from "react";
import { FlaskConicalIcon, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@saas-core/ui/lib/utils";

/**
 * What the subscription screens (plan and credits) share, so both tabs of
 * "Subscription" read as one screen: the state messages, the figures and the
 * formatting of money and dates.
 */
const TONES = {
  info: ["border-info-foreground/25 bg-info", "text-info-foreground"],
  success: [
    "border-success-foreground/25 bg-success",
    "text-success-foreground",
  ],
  warning: [
    "border-warning-foreground/25 bg-warning",
    "text-warning-foreground",
  ],
  destructive: ["border-destructive/30 bg-destructive/5", "text-destructive"],
} as const;

export function Notice({
  tone,
  icon: Icon,
  title,
  action,
  children,
  className,
  ...props
}: Omit<ComponentProps<"div">, "title"> & {
  tone: keyof typeof TONES;
  icon: LucideIcon;
  title: ReactNode;
  action?: ReactNode;
}) {
  const [surface, ink] = TONES[tone];
  return (
    <div
      className={cn(
        "flex flex-wrap items-start gap-3 rounded-lg border p-4 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
        surface,
        className,
      )}
      {...props}
    >
      <Icon aria-hidden="true" className={cn("mt-0.5 size-5 shrink-0", ink)} />
      <div className="min-w-0 flex-1 basis-56 space-y-1">
        <p className="font-medium">{title}</p>
        {children ? (
          <div className="text-muted-foreground">{children}</div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function DemoPaymentBanner() {
  const t = useTranslations("CustomerBilling");
  return (
    <aside aria-label={t("simulationBannerTitle")}>
      <Notice
        icon={FlaskConicalIcon}
        title={t("simulationBannerTitle")}
        tone="info"
      >
        {t("simulationBannerDescription")}
      </Notice>
    </aside>
  );
}

export function SectionHeader({
  id,
  title,
  description,
}: {
  id: string;
  title: string;
  description?: string;
}) {
  return (
    <div className="max-w-3xl space-y-1">
      <h2 className="text-xl font-semibold tracking-tight" id={id}>
        {title}
      </h2>
      {description ? (
        <p className="text-sm text-muted-foreground">{description}</p>
      ) : null}
    </div>
  );
}

/** One figure of a `<dl>`; `share` (0–1) draws how much of it is left. */
export function Fact({
  label,
  value,
  note,
  share,
}: {
  label: string;
  value: string;
  note?: string;
  share?: number;
}) {
  return (
    <div className="rounded-lg bg-background p-4 ring-1 ring-border">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-base font-semibold tabular-nums">{value}</dd>
      {share !== undefined ? (
        // The value above says the same in words; the bar is for the eye.
        <dd aria-hidden="true" className="mt-2 h-1.5 rounded-full bg-muted">
          <span
            className="block h-full rounded-full bg-primary"
            style={{ width: `${Math.round(Math.min(1, share) * 100)}%` }}
          />
        </dd>
      ) : null}
      {note ? (
        <dd className="mt-1 text-xs text-muted-foreground">{note}</dd>
      ) : null}
    </div>
  );
}

export function formatMoney(minor: number, currency: string, locale: string) {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    // Whole amounts without ",00", but never rounded away: 149,99 stays.
    ...(minor % 100 === 0 ? { maximumFractionDigits: 0 } : {}),
  }).format(minor / 100);
}

/** A day; a bare date ("2026-09-30") is read in UTC so it cannot shift by one. */
export function formatDay(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    ...(value.length === 10 ? { timeZone: "UTC" } : {}),
  }).format(new Date(value));
}
