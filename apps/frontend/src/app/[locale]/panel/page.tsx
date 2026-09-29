import {
  ArrowRightIcon,
  CalendarDaysIcon,
  CreditCardIcon,
  Globe2Icon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { GettingStarted } from "#components/panel/getting-started";
import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { allows, panelAccess } from "#lib/panel-navigation";
import ProductDashboard from "../../../product/dashboard";

export default async function PanelHomePage() {
  const [user, organization, t] = await Promise.all([
    getServerUser(),
    getServerCurrentOrganization(),
    getTranslations("Dashboard"),
  ]);
  const access = panelAccess(organization);
  // A product's "Today" only where it applies (e.g. HoofCare's for trimming
  // companies, not for the farms of the same deployment).
  if (ProductDashboard && allows(access, ProductDashboard))
    return (
      <ProductDashboard.component
        access={access}
        firstName={user?.first_name ?? ""}
      />
    );
  const modules = new Set(access.modules);
  // The same gates as the menu, so the start page offers no tile the menu hides.
  const can = (permission: string) => allows(access, { permission });
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
    can("organization.members.read")
      ? {
          href: "/panel/team",
          icon: UsersIcon,
          title: t("teamTitle"),
          description: t("teamDescription"),
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
      description={t("description")}
      eyebrow={t("eyebrow")}
      title={t("greeting", {
        name:
          user?.first_name ||
          organization?.name ||
          user?.email.split("@")[0] ||
          "",
      })}
    >
      {/* The next step to take, ahead of the things one can always do. */}
      {organization ? <GettingStarted access={access} /> : null}

      <PanelSection
        description={t("quickActionsDescription")}
        title={t("quickActions")}
      >
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
