"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CreditCardIcon } from "lucide-react";

import {
  ApiProblemError,
  getBookingCatalog,
  type BookingCatalog,
} from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

import { Link } from "#i18n/navigation";
import { organizationType as organizationTypeInfo } from "#lib/organization-types";
import { BookingConfiguration } from "./booking-configuration";

type Row = { id: string; name: string; detail?: string };

/**
 * Settings › Services & schedule: what the calendar builds free slots from.
 * What is set up comes first, then the forms that add to it.
 */
export function BookingSettings({
  organizationType,
  canManageBilling,
}: {
  /** Chooses the service templates offered (ADR-050). */
  organizationType?: string;
  /** The owner is sent to the plan when booking is not in it. */
  canManageBilling: boolean;
}) {
  const t = useTranslations("Settings");
  const [catalog, setCatalog] = useState<BookingCatalog>();
  const [failure, setFailure] = useState<"plan" | "error">();

  const load = useCallback(async () => {
    try {
      setCatalog(await getBookingCatalog());
      setFailure(undefined);
    } catch (error) {
      setFailure(
        error instanceof ApiProblemError &&
          error.problem.code === "entitlement_required"
          ? "plan"
          : "error",
      );
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  if (failure === "plan")
    return (
      <section className="flex max-w-3xl items-start gap-3 rounded-xl border bg-muted/40 p-5">
        <CreditCardIcon
          aria-hidden="true"
          className="mt-0.5 size-5 shrink-0 text-muted-foreground"
        />
        <div className="space-y-3">
          <div className="space-y-1">
            <h2 className="font-medium">{t("planTitle")}</h2>
            <p className="text-sm text-muted-foreground">
              {canManageBilling ? t("planOwner") : t("planAskOwner")}
            </p>
          </div>
          {canManageBilling ? (
            <Link className={buttonVariants()} href="/panel/settings/billing">
              {t("planAction")}
            </Link>
          ) : null}
        </div>
      </section>
    );

  if (failure === "error")
    return (
      <div className="flex flex-wrap items-center gap-3" role="alert">
        <p className="text-sm text-destructive">{t("loadError")}</p>
        <Button
          onClick={() => {
            setFailure(undefined);
            void load();
          }}
          variant="outline"
        >
          {t("retry")}
        </Button>
      </div>
    );

  if (!catalog)
    return (
      <div aria-busy="true" className="space-y-6" role="status">
        <span className="sr-only">{t("loading")}</span>
        <div className="h-40 animate-pulse rounded-xl bg-muted" />
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="h-80 animate-pulse rounded-xl bg-muted" />
          <div className="h-80 animate-pulse rounded-xl bg-muted" />
        </div>
      </div>
    );

  const groups: {
    key: "services" | "staff" | "locations" | "resources";
    rows: Row[];
  }[] = [
    {
      key: "services",
      rows: catalog.services.map((service) => ({
        id: service.id,
        name: service.name,
        detail: t("minutes", { count: service.duration_minutes }),
      })),
    },
    { key: "staff", rows: catalog.staff },
    { key: "locations", rows: catalog.locations },
    { key: "resources", rows: catalog.resources },
  ];
  const empty = groups.every((group) => group.rows.length === 0);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("setupTitle")}</CardTitle>
          <CardDescription>
            {empty ? t("setupEmpty") : t("setupDescription")}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {groups.map(({ key, rows }) => (
              <div key={key}>
                <dt className="font-medium">{t(key)}</dt>
                <dd className="mt-1.5 text-muted-foreground">
                  {rows.length === 0 ? (
                    t("none")
                  ) : (
                    <ul className="space-y-1">
                      {rows.map((row) => (
                        <li key={row.id}>
                          <span className="text-foreground">{row.name}</span>
                          {row.detail ? ` · ${row.detail}` : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>
      <BookingConfiguration
        catalog={catalog}
        onChanged={load}
        serviceTemplates={
          organizationTypeInfo(organizationType).serviceTemplates
        }
      />
    </div>
  );
}
