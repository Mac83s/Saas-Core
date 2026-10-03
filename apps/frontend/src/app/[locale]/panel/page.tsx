import {
  ArrowRightIcon,
  CalendarDaysIcon,
  CreditCardIcon,
  Globe2Icon,
  PackageIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { GettingStarted } from "#components/panel/getting-started";
import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { allows, panelAccess } from "#lib/panel-navigation";
import { DayAgenda } from "../../../modules/shared/booking";
import type { ProductDashboard as ProductDashboardEntry } from "#lib/product-extension";
import ProductDashboard from "../../../product/dashboard";

export default async function PanelHomePage() {
  const [user, organization, t] = await Promise.all([
    getServerUser(),
    getServerCurrentOrganization(),
    getTranslations("Dashboard"),
  ]);
  const access = panelAccess(organization);
  // A product's "Today" only where it applies (e.g. HoofCare's for trimming
  // companies, the farmer's own for its farms, UX-078).
  const dashboards: readonly ProductDashboardEntry[] =
    ProductDashboard === null
      ? []
      : "component" in ProductDashboard
        ? [ProductDashboard]
        : ProductDashboard;
  const dashboard = dashboards.find((item) => allows(access, item));
  if (dashboard)
    return (
      <dashboard.component access={access} firstName={user?.first_name ?? ""} />
    );
  const modules = new Set(access.modules);
  // The same gates as the menu, so the start page offers no tile the menu hides.
  const can = (permission: string) => allows(access, { permission });
  // Who plans the team's day sets the company up too; everybody else gets
  // their own day and their own things (UX-023).
  const plans = can("booking.appointment.manage");
  const actions = [
    modules.has("shared.sites") && can("site.content.edit")
      ? {
          href: "/panel/sites",
          icon: Globe2Icon,
          title: t("websiteTitle"),
          description: t("websiteDescription"),
        }
      : null,
    modules.has("shared.booking") && can("booking.appointment.read")
      ? {
          href: "/panel/calendar",
          icon: CalendarDaysIcon,
          title: t("calendarTitle"),
          description: t("calendarDescription"),
        }
      : null,
    // „Zaproś zespół” for whoever may invite, not for whoever may look.
    can("organization.members.manage") ||
    can("organization.members.manage_limited")
      ? {
          href: "/panel/team",
          icon: UsersIcon,
          title: t("teamTitle"),
          description: t("teamDescription"),
        }
      : null,
    modules.has("shared.inventory") &&
    can("inventory.use") &&
    !can("inventory.manage")
      ? {
          href: "/panel/inventory",
          icon: PackageIcon,
          title: t("stockTitle"),
          description: t("stockDescription"),
        }
      : null,
    modules.has("shared.billing") && access.isOwner
      ? {
          href: "/panel/settings/billing",
          icon: CreditCardIcon,
          title: t("billingTitle"),
          description: t("billingDescription"),
        }
      : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null);

  return (
    <PanelPage
      description={t(plans ? "description" : "descriptionOwn")}
      eyebrow={t("eyebrow")}
      title={t("greeting", {
        name:
          user?.first_name ||
          organization?.name ||
          user?.email.split("@")[0] ||
          "",
      })}
    >
      {/* The day first (UX-022); what is left to set up after it, and a list
          already done folds itself to one line. */}
      {organization &&
      modules.has("shared.booking") &&
      can("booking.appointment.read") ? (
        <DayAgenda access={access} timeZone={organization.timezone} />
      ) : null}
      {organization ? <GettingStarted access={access} /> : null}

      <PanelSection
        description={t("quickActionsDescription")}
        title={t("quickActions")}
      >
        {/* Two by two on a phone: four shortcuts fit one screen. */}
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          {actions.map((action) => (
            <ActionCard key={action.href} {...action} />
          ))}
        </div>
      </PanelSection>
    </PanelPage>
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
