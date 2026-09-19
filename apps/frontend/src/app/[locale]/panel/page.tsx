import {
  ArrowRightIcon,
  CalendarDaysIcon,
  CheckCircle2Icon,
  CreditCardIcon,
  Globe2Icon,
  SparklesIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import {
  getServerCurrentOrganization,
  getServerBookingCatalog,
  getServerCustomerBillingOverview,
  getServerSites,
  getServerUser,
} from "#lib/server-auth";
import { modulesFor } from "#lib/organization-types";
import { Badge } from "@saas-core/ui/components/badge";
import { buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { cn } from "@saas-core/ui/lib/utils";

export default async function PanelPage() {
  const [user, organization, t] = await Promise.all([
    getServerUser(),
    getServerCurrentOrganization(),
    getTranslations("Dashboard"),
  ]);
  const modules = modulesFor(organization?.organization_type);
  const canManageBilling = organization?.role === "owner";
  const billing =
    canManageBilling && modules.has("shared.billing")
      ? await getServerCustomerBillingOverview()
      : null;
  const needsPlan =
    canManageBilling && modules.has("shared.billing") && !billing?.subscription;
  const hasPlanAccess = billing?.subscription?.access_mode === "full";
  const sites =
    canManageBilling && hasPlanAccess && modules.has("shared.sites")
      ? await getServerSites()
      : null;
  const hasWebsite = Boolean(sites?.items.length);
  const booking =
    canManageBilling && hasWebsite && modules.has("shared.booking")
      ? await getServerBookingCatalog()
      : null;
  const hasBooking = Boolean(booking?.services.length);
  const showLaunchRoadmap =
    canManageBilling &&
    modules.has("shared.billing") &&
    modules.has("shared.sites") &&
    modules.has("shared.booking");
  const actions = [
    modules.has("shared.sites")
      ? {
          href: "/panel/sites",
          icon: Globe2Icon,
          title: t("websiteTitle"),
          description: t("websiteDescription"),
        }
      : null,
    modules.has("shared.booking")
      ? {
          href: "/panel/calendar",
          icon: CalendarDaysIcon,
          title: t("calendarTitle"),
          description: t("calendarDescription"),
        }
      : null,
    {
      href: "/panel/team",
      icon: UsersIcon,
      title: t("teamTitle"),
      description: t("teamDescription"),
    },
    modules.has("shared.billing") && canManageBilling
      ? {
          href: "/panel/settings/billing",
          icon: CreditCardIcon,
          title: t("billingTitle"),
          description: t("billingDescription"),
        }
      : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null);
  const primaryAction = needsPlan
    ? { href: "/panel/settings/billing", label: t("primaryPlanAction") }
    : modules.has("shared.sites") && !hasWebsite
      ? { href: "/panel/sites", label: t("primaryAction") }
      : modules.has("shared.booking") && !hasBooking
        ? { href: "/panel/calendar", label: t("calendarTitle") }
        : modules.has("shared.sites")
          ? { href: "/panel/sites", label: t("primaryAction") }
          : null;

  return (
    <main className="mx-auto w-full max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:py-10">
      <section className="relative overflow-hidden rounded-3xl border bg-gradient-to-br from-primary/12 via-background to-background p-6 shadow-sm sm:p-10">
        <div className="relative z-10 max-w-3xl space-y-5">
          <Badge className="w-fit" variant="secondary">
            <SparklesIcon aria-hidden="true" />
            {t("eyebrow")}
          </Badge>
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              {t("greeting", {
                name: organization?.name ?? user?.email.split("@")[0] ?? "",
              })}
            </h1>
            <p className="max-w-2xl text-base leading-7 text-muted-foreground sm:text-lg">
              {t("description")}
            </p>
          </div>
          {primaryAction ? (
            <Link
              className={buttonVariants({
                className: "w-fit rounded-xl",
                size: "lg",
              })}
              href={primaryAction.href}
            >
              {primaryAction.label}
              <ArrowRightIcon aria-hidden="true" />
            </Link>
          ) : null}
        </div>
        <div
          aria-hidden="true"
          className="absolute -right-20 -top-24 size-72 rounded-full bg-primary/10 blur-3xl"
        />
      </section>

      <section aria-labelledby="quick-actions-heading" className="space-y-4">
        <div>
          <h2 className="text-xl font-semibold" id="quick-actions-heading">
            {t("quickActions")}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("quickActionsDescription")}
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {actions.map((action) => (
            <ActionCard key={action.href} {...action} />
          ))}
        </div>
      </section>

      {showLaunchRoadmap ? (
        <Card className="border-primary/20 bg-primary/[0.025]">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2Icon aria-hidden="true" className="text-primary" />
              {t("roadmapTitle")}
            </CardTitle>
            <CardDescription>{t("roadmapDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <ol className="grid gap-3 text-sm sm:grid-cols-3">
              <RoadmapStep
                complete={hasPlanAccess}
                number="1"
                text={t("roadmapPlan")}
              />
              <RoadmapStep
                complete={hasWebsite}
                number="2"
                text={t("roadmapWebsite")}
              />
              <RoadmapStep
                complete={hasBooking}
                number="3"
                text={t("roadmapBooking")}
              />
            </ol>
          </CardContent>
        </Card>
      ) : null}
    </main>
  );
}

function ActionCard({
  href,
  icon: Icon,
  title,
  description,
}: {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <Link
      className="group rounded-2xl border bg-card p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      href={href}
    >
      <span className="mb-5 flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
        <Icon aria-hidden="true" className="size-5" />
      </span>
      <span className="block font-semibold">{title}</span>
      <span className="mt-1 block text-sm leading-6 text-muted-foreground">
        {description}
      </span>
      <ArrowRightIcon
        aria-hidden="true"
        className="mt-4 size-4 text-muted-foreground transition-transform group-hover:translate-x-1 group-hover:text-primary"
      />
    </Link>
  );
}

function RoadmapStep({
  complete,
  number,
  text,
}: {
  complete: boolean;
  number: string;
  text: string;
}) {
  return (
    <li
      className={cn(
        "flex items-center gap-3 rounded-xl border bg-background p-3",
        complete && "border-emerald-600/20 bg-emerald-600/[0.035]",
      )}
    >
      <span
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground",
          complete && "bg-emerald-600",
        )}
      >
        {complete ? (
          <CheckCircle2Icon aria-hidden="true" className="size-4" />
        ) : (
          number
        )}
      </span>
      <span>{text}</span>
    </li>
  );
}
