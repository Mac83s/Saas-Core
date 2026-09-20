"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ArrowRightIcon, CheckIcon } from "lucide-react";

import {
  getCustomerBillingOverview,
  listBookingAppointments,
  listFarms,
  listInvitations,
  listMemberships,
  listSites,
} from "@saas-core/api-client";
import { Link } from "#i18n/navigation";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { cn } from "@saas-core/ui/lib/utils";

/**
 * The "Na start" list on the Today screen: what is left before the first real
 * day of work. Every item is derived from data that already exists — a
 * subscription, a farm, an appointment, a second member, a website — so it
 * cannot go stale or claim progress nobody made. Which items appear follows
 * the organization's type (ADR-050) and the membership's permissions, the
 * same gates as the menu: a type without a farm register is never told to add
 * a farm, and someone who may not invite is not asked to.
 *
 * Creating the organization is not an item: the panel does not open without
 * one — the layout sends an account without any to the first-run screen.
 */
type StepKey = "plan" | "farm" | "appointment" | "team" | "website";

type Step = {
  key: StepKey;
  href: string;
  /** Who is offered this step at all. */
  visible: (access: PanelAccess) => boolean;
  /** What proves it done, read from data the panel already owns. */
  load: () => Promise<boolean>;
};

/** The same rule the team screen applies: full management, or limited roles. */
function canInvite(access: PanelAccess): boolean {
  return (
    allows(access, { permission: "organization.members.manage" }) ||
    allows(access, { permission: "organization.members.manage_limited" })
  );
}

const STEPS: readonly Step[] = [
  {
    // Picking a plan starts the trial; paying comes later (ADR-026).
    key: "plan",
    href: "/panel/settings/billing",
    visible: (access) =>
      allows(access, { module: "shared.billing", ownerOnly: true }),
    load: async () =>
      Boolean((await getCustomerBillingOverview()).subscription),
  },
  {
    key: "farm",
    href: "/panel/farms",
    visible: (access) =>
      allows(access, { module: "shared.farms", permission: "farms.manage" }),
    load: async () => (await listFarms()).length > 0,
  },
  {
    key: "appointment",
    href: "/panel/calendar",
    visible: (access) =>
      allows(access, {
        module: "shared.booking",
        permission: "booking.appointment.manage",
      }),
    load: async () => (await listBookingAppointments()).length > 0,
  },
  {
    key: "team",
    href: "/panel/team",
    visible: canInvite,
    load: async () => {
      // An invitation nobody has accepted yet still closes the step.
      const [members, invitations] = await Promise.all([
        listMemberships(),
        listInvitations(),
      ]);
      return (
        members.length > 1 ||
        invitations.some((invitation) => invitation.status === "pending")
      );
    },
  },
  {
    key: "website",
    href: "/panel/sites",
    visible: (access) =>
      allows(access, {
        module: "shared.sites",
        permission: "site.content.edit",
      }),
    load: async () => (await listSites()).items.length > 0,
  },
];

// ponytail: one key per person, not per organization — a second organization
// of the same person starts hidden. Key it by id if that ever bites.
const HIDDEN_KEY = "saas-core.getting-started.hidden";

function readHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function GettingStarted({ access }: { access: PanelAccess }) {
  const t = useTranslations("GettingStarted");
  const [hidden, setHidden] = useState(false);
  const [done, setDone] = useState<Partial<Record<StepKey, boolean>>>();
  const [failed, setFailed] = useState(false);

  const steps = useMemo(
    () => STEPS.filter((step) => step.visible(access)),
    [access],
  );

  const load = useCallback(async () => {
    if (steps.length === 0) return;
    setFailed(false);
    try {
      const answers = await Promise.all(
        steps.map(async (step) => [step.key, await step.load()] as const),
      );
      setDone(Object.fromEntries(answers));
    } catch {
      setFailed(true);
    }
  }, [steps]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- browser only
    setHidden(readHidden());
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  function hide() {
    try {
      localStorage.setItem(HIDDEN_KEY, "1");
    } catch {
      // A browser that refuses storage still hides it for this visit.
    }
    setHidden(true);
  }

  // Nothing this membership may act on, so nothing to show.
  if (hidden || steps.length === 0) return null;

  if (failed)
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("title")}</h2>
          </CardTitle>
          <CardDescription role="alert">{t("failed")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );

  if (!done)
    return (
      <div className="h-56 animate-pulse rounded-xl bg-muted">
        <span className="sr-only">{t("loading")}</span>
      </div>
    );

  const total = steps.length;
  const completed = steps.filter((step) => done[step.key]).length;
  const next = steps.find((step) => !done[step.key]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
        <CardAction>
          <Button onClick={hide} size="sm" variant="ghost">
            {t("hide")}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-5">
        <div aria-live="polite" className="space-y-2">
          <p className="text-sm font-medium">
            {t("progress", { done: completed, total })}
          </p>
          {/* Decoration: the line above carries the number, not the colour. */}
          <div
            aria-hidden="true"
            className="h-2 w-full overflow-hidden rounded-full bg-muted"
          >
            <div
              className="h-full rounded-full bg-primary"
              style={{ width: `${Math.round((completed / total) * 100)}%` }}
            />
          </div>
          {next ? null : (
            <p className="text-sm text-success-foreground">{t("allDone")}</p>
          )}
        </div>
        <ol className="space-y-3">
          {steps.map((step, index) => (
            <StepRow
              action={t(`${step.key}Action`)}
              body={t(`${step.key}Body`)}
              done={Boolean(done[step.key])}
              href={step.href}
              key={step.key}
              number={index + 1}
              primary={step === next}
              status={t(done[step.key] ? "statusDone" : "statusTodo")}
              title={t(`${step.key}Title`)}
            />
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function StepRow({
  action,
  body,
  done,
  href,
  number,
  primary,
  status,
  title,
}: {
  action: string;
  body: string;
  done: boolean;
  href: string;
  number: number;
  primary: boolean;
  status: string;
  title: string;
}) {
  return (
    <li
      className={cn(
        "flex flex-col gap-3 rounded-xl border p-3 sm:flex-row sm:items-center",
        done && "border-success-foreground/20 bg-success",
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
          done && "border-transparent bg-success-foreground text-success",
        )}
      >
        {done ? <CheckIcon className="size-4" /> : number}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-medium">{title}</span>
          {/* Never colour alone: the state is a word a screen reader reads. */}
          <span className="text-xs text-muted-foreground">{status}</span>
        </span>
        <span className="mt-1 block text-sm leading-6 text-muted-foreground">
          {body}
        </span>
      </span>
      {done ? null : (
        <Link
          className={buttonVariants({
            className: "shrink-0 sm:w-fit",
            size: "sm",
            variant: primary ? "default" : "outline",
          })}
          href={href}
        >
          {action}
          <ArrowRightIcon aria-hidden="true" />
        </Link>
      )}
    </li>
  );
}
