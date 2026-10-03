"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  BanknoteIcon,
  CreditCardIcon,
  PencilIcon,
  PlusIcon,
} from "lucide-react";

import {
  ApiProblemError,
  getBookingSetup,
  updateSetupGroup,
  updateSetupLocation,
  updateSetupResource,
  updateSetupService,
  type BookingSetup,
  type GroupSetup,
  type PlaceSetup,
  type ResourceSetup,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { cn } from "@saas-core/ui/lib/utils";
import {
  DataTable,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";

import { PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  organizationType as organizationTypeInfo,
  typeText,
} from "#lib/organization-types";
import { CatalogTranslations } from "./catalog-translations";
import { ClosuresSection } from "./closures-section";
import {
  ItemTranslationsSheet,
  type TranslatedItem,
} from "./item-translations-sheet";
import { SeasonsSection } from "./seasons-section";
import { problemText } from "./people/person-dialogs";
import { OfferPricesDialog } from "./prices/offer-prices-dialog";
import { usePriceBook, usePriceWords } from "./prices/price-book";
import {
  ItemDialog,
  ServiceDialog,
  type ServiceTemplate,
} from "./setup-dialogs";

type Editing =
  | { kind: "service"; service?: ServiceSetup; template?: ServiceTemplate }
  | { kind: "location"; item?: PlaceSetup }
  | { kind: "resource"; item?: ResourceSetup }
  | { kind: "group"; item?: GroupSetup };

/**
 * Settings › Services & schedule (team phase 3c, board 12): what customers can
 * book, how long it takes, how many people it needs and who does it, where,
 * and with what. People and their hours are Zespół's; this page links there.
 */
export function BookingSettings({
  organizationType,
  canManageBilling,
  canUseInventory = false,
  organizationId,
  timezone = "UTC",
}: {
  /** The company's zone: a price is asked about for its local day and hour. */
  timezone?: string;
  /** Chooses the service templates offered (ADR-050). */
  organizationType?: string;
  /** The owner is sent to the plan when booking is not in it. */
  canManageBilling: boolean;
  /** Services can carry products from the warehouse (ADR-055). */
  canUseInventory?: boolean;
  /** The catalogue's translation object (TL12e); absent, no catalogue line. */
  organizationId?: string;
}) {
  const t = useTranslations("ServicesSetup");
  const common = useTranslations("Common");
  const settings = useTranslations("Settings");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [setup, setSetup] = useState<BookingSetup>();
  const [failure, setFailure] = useState<"plan" | "error">();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [editing, setEditing] = useState<Editing>();
  /** A service still booked ahead, asked about before it is switched off (W1). */
  const [switchingOff, setSwitchingOff] = useState<ServiceSetup>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  /** The item whose „Tłumaczenia” are open (TL12d). */
  const [translating, setTranslating] = useState<TranslatedItem>();
  const translations = useTranslations("Translations");
  // The price list (ADR-072 §6): read once, shared by the offers' column,
  // each offer's „Cennik” and the stays' prices under „Sezony”.
  const prices = usePriceBook();
  const priceList = useTranslations("PriceList");
  const priceWords = usePriceWords({
    services: setup?.services ?? [],
    groups: setup?.groups ?? [],
    resources: setup?.resources ?? [],
  });
  /** The offer whose „Cennik” is open. */
  const [pricing, setPricing] = useState<string>();

  const load = useCallback(async () => {
    try {
      setSetup(await getBookingSetup());
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
            <h2 className="font-medium">{settings("planTitle")}</h2>
            <p className="text-sm text-muted-foreground">
              {canManageBilling
                ? settings("planOwner")
                : settings("planAskOwner")}
            </p>
          </div>
          {canManageBilling ? (
            <Link className={buttonVariants()} href="/panel/settings/billing">
              {settings("planAction")}
            </Link>
          ) : null}
        </div>
      </section>
    );

  if (failure === "error")
    return (
      <div className="flex flex-wrap items-center gap-3" role="alert">
        <p className="text-sm text-destructive">{settings("loadError")}</p>
        <Button
          onClick={() => {
            setFailure(undefined);
            void load();
          }}
          variant="outline"
        >
          {settings("retry")}
        </Button>
      </div>
    );

  const open = (next: Editing, trigger: HTMLElement | null) => {
    setReturnTo(trigger);
    setProblem(undefined);
    setEditing(next);
  };

  const saved = (text: string) => {
    setEditing(undefined);
    setNotice(text);
    void load();
  };

  async function toggle(
    action: (idempotencyKey: string) => Promise<unknown>,
    text: string,
  ): Promise<void> {
    setProblem(undefined);
    try {
      await action(crypto.randomUUID());
      saved(text);
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
        }),
      );
      // Somebody else changed it: the list shows their version now.
      void load();
    }
  }

  const switchService = (service: ServiceSetup) =>
    toggle(
      (key) =>
        updateSetupService(
          service.id,
          { active: !service.active, expected_version: service.version },
          key,
        ),
      t(service.active ? "switchedOff" : "switchedOn", { name: service.name }),
    );

  const close = () => {
    setEditing(undefined);
    // A dialog closed after a conflict leaves a stale row behind otherwise.
    void load();
  };

  const duration = (minutes: number) =>
    minutes < 60
      ? t("minutes", { count: minutes })
      : minutes % 60
        ? t("hoursMinutes", {
            hours: Math.floor(minutes / 60),
            minutes: minutes % 60,
          })
        : t("hours", { count: minutes / 60 });

  const inactive = (
    key: "inactiveService" | "inactivePlace" | "inactiveResource",
  ) => (
    <Badge className="ml-2" variant="neutral">
      {t(key)}
    </Badge>
  );

  const services = setup?.services ?? [];
  const priced = services.find((service) => service.id === pricing);
  const usedBy = (field: "location_ids" | "resource_ids", id: string) =>
    services.filter((service) => service.active && service[field].includes(id))
      .length;
  // A switched-off service reads as one, not only by its badge (UX-059).
  const dim = (service: ServiceSetup) =>
    service.active ? undefined : "text-muted-foreground";
  // The kinds of visit the company's modules provide (ADR-050); none, no column.
  const kinds = new Map(
    (setup?.appointment_kinds ?? []).map((kind) => [kind.key, kind.label]),
  );

  const serviceColumns: ColumnDef<ServiceSetup, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colService"),
      meta: { primary: true },
      cell: ({ row: { original: service } }) => (
        <p className={cn("font-medium wrap-anywhere", dim(service))}>
          {service.name}
          {service.active ? null : inactive("inactiveService")}
        </p>
      ),
    },
    ...(kinds.size
      ? [
          {
            id: "kind",
            accessorFn: (service: ServiceSetup) =>
              kinds.get(service.appointment_kind) ?? t("kindOther"),
            header: t("colKind"),
            cell: ({ row: { original: service } }) => (
              <span className={dim(service)}>
                {kinds.get(service.appointment_kind) ?? t("kindOther")}
              </span>
            ),
          } satisfies ColumnDef<ServiceSetup, unknown>,
        ]
      : []),
    {
      id: "duration",
      accessorKey: "duration_minutes",
      header: t("colDuration"),
      cell: ({ row: { original: service } }) => (
        <span className={dim(service)}>
          {service.duration_minutes === null
            ? t(`rangeLength_${service.range_unit === "day" ? "day" : "night"}`)
            : duration(service.duration_minutes)}
        </span>
      ),
    },
    {
      id: "count",
      accessorKey: "staff_count",
      header: t("colPeople"),
      cell: ({ row: { original: service } }) => (
        <span className={dim(service)}>{service.staff_count}</span>
      ),
    },
    {
      id: "performers",
      header: t("colPerformers"),
      enableSorting: false,
      cell: ({ row: { original: service } }) =>
        service.time_model === "range" ? (
          // A stay takes a unit, nobody (ADR-072 §2).
          "—"
        ) : service.staff_ids.length ? (
          service.staff_ids.length < service.staff_count ? (
            <span className="text-warning-foreground">
              {t("performersShort", {
                count: service.staff_ids.length,
                need: service.staff_count,
              })}
            </span>
          ) : (
            <span className={dim(service)}>
              {t("performersOf", {
                count: service.staff_ids.length,
                total: setup?.staff.length ?? service.staff_ids.length,
              })}
            </span>
          )
        ) : (
          <span className="text-warning-foreground">{t("nobody")}</span>
        ),
    },
    {
      id: "price",
      header: t("colPrice"),
      enableSorting: false,
      cell: ({ row: { original: service } }) => {
        // The offer's own prices as they were entered; what a booking costs
        // is the quote's to say, not this column's.
        const own = (prices.book?.prices ?? []).filter(
          (rule) => rule.service_id === service.id && rule.active,
        );
        const base = own.find(
          (rule) =>
            !rule.starts_on && !rule.weekdays.length && !rule.local_from,
        );
        return (
          <span className={dim(service)}>
            {base
              ? priceWords.amount(base)
              : own.length
                ? priceList("offerPrices", { count: own.length })
                : priceList("noPrice")}
          </span>
        );
      },
    },
    {
      id: "public",
      header: t("colPublic"),
      enableSorting: false,
      cell: ({ row: { original: service } }) => (
        <span className={dim(service)}>
          {t(`public_${service.public_staff_choice}` as "public_none")}
        </span>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: service } }) => (
        <RowActions
          items={[
            {
              label: t("editFor", { name: service.name }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              onSelect: (trigger) =>
                open({ kind: "service", service }, trigger ?? null),
            },
            {
              label: t("priceListAction"),
              icon: <BanknoteIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => {
                setReturnTo(trigger ?? null);
                setPricing(service.id);
              },
            },
            {
              label: translations("action"),
              onSelect: () =>
                setTranslating({
                  kind: "service",
                  id: service.id,
                  name: service.name,
                }),
            },
            {
              label: t(service.active ? "switchOffService" : "switchOnService"),
              onSelect: () =>
                // Bookings still ahead stay; the owner hears how many first (W1).
                service.active && service.future_bookings
                  ? setSwitchingOff(service)
                  : void switchService(service),
            },
          ]}
          label={t("actionsFor", { name: service.name })}
        />
      ),
    },
  ];

  const itemActions = (
    kind: "location" | "resource" | "group",
    item: PlaceSetup | ResourceSetup | GroupSetup,
  ): RowAction[] => [
    {
      label: t("editFor", { name: item.name }),
      icon: <PencilIcon aria-hidden="true" />,
      inline: true,
      main: true,
      onSelect: (trigger) =>
        open(
          kind === "location"
            ? { kind, item: item as PlaceSetup }
            : kind === "group"
              ? { kind, item: item as GroupSetup }
              : { kind, item: item as ResourceSetup },
          trigger ?? null,
        ),
    },
    {
      label: translations("action"),
      onSelect: () => setTranslating({ kind, id: item.id, name: item.name }),
    },
    {
      label: t(item.active ? "switchOff" : "switchOn"),
      onSelect: () =>
        void toggle(
          (key) => {
            const change = {
              active: !item.active,
              expected_version: item.version,
            };
            return kind === "location"
              ? updateSetupLocation(item.id, change, key)
              : kind === "group"
                ? updateSetupGroup(item.id, change, key)
                : updateSetupResource(item.id, change, key);
          },
          t(item.active ? "switchedOff" : "switchedOn", { name: item.name }),
        ),
    },
  ];

  const placeColumns: ColumnDef<PlaceSetup, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colPlace"),
      meta: { primary: true },
      cell: ({ row: { original: place } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {place.name}
            {place.active ? null : inactive("inactivePlace")}
          </p>
          {place.address ? (
            <p className="text-sm text-muted-foreground">{place.address}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "services",
      header: t("colServices"),
      enableSorting: false,
      cell: ({ row: { original: place } }) =>
        t("servicesCount", { count: usedBy("location_ids", place.id) }),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: place } }) => (
        <RowActions
          items={itemActions("location", place)}
          label={t("actionsFor", { name: place.name })}
        />
      ),
    },
  ];

  const groupNames = new Map(
    (setup?.groups ?? []).map((group) => [group.id, group.name]),
  );
  const unitsOf = (groupId: string) =>
    (setup?.resources ?? []).filter((thing) => thing.group_id === groupId)
      .length;

  const groupColumns: ColumnDef<GroupSetup, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colGroup"),
      meta: { primary: true },
      cell: ({ row: { original: group } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {group.name}
            {group.active ? null : inactive("inactiveResource")}
          </p>
          {group.description ? (
            <p className="text-sm text-muted-foreground wrap-anywhere">
              {group.description}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "units",
      header: t("colUnits"),
      enableSorting: false,
      cell: ({ row: { original: group } }) =>
        t("unitsCount", { count: unitsOf(group.id) }),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: group } }) => (
        <RowActions
          items={itemActions("group", group)}
          label={t("actionsFor", { name: group.name })}
        />
      ),
    },
  ];

  const resourceColumns: ColumnDef<ResourceSetup, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colResource"),
      meta: { primary: true },
      cell: ({ row: { original: thing } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {thing.name}
            {thing.active ? null : inactive("inactiveResource")}
          </p>
          {thing.capacity ? (
            <p className="text-sm text-muted-foreground">
              {t("capacityShort", { count: thing.capacity })}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "group",
      header: t("colGroup"),
      enableSorting: false,
      cell: ({ row: { original: thing } }) =>
        groupNames.get(thing.group_id ?? "") ?? "—",
    },
    {
      id: "services",
      header: t("colServices"),
      enableSorting: false,
      cell: ({ row: { original: thing } }) =>
        t("servicesCount", { count: usedBy("resource_ids", thing.id) }),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: thing } }) => (
        <RowActions
          items={itemActions("resource", thing)}
          label={t("actionsFor", { name: thing.name })}
        />
      ),
    },
  ];

  // The organization type's ready-made services not added yet (ADR-050).
  const names = new Set(services.map((service) => service.name));
  const templates = organizationTypeInfo(organizationType)
    .serviceTemplates.map((template) => ({
      key: template.key,
      name: typeText(template.label, locale),
      durationMinutes: template.durationMinutes,
      appointmentKind: template.appointmentKind,
    }))
    .filter((template) => !names.has(template.name));

  return (
    <div className="space-y-10">
      <ItemTranslationsSheet
        item={translating}
        onClose={() => setTranslating(undefined)}
      />
      {/* The people's hours live with the people: said first, not last (UX-059). */}
      <p className="max-w-3xl text-sm text-muted-foreground">
        {t("peopleElsewhere")}{" "}
        <Link
          className="font-medium text-primary hover:underline"
          href="/panel/team"
        >
          {t("peopleLink")}
        </Link>
      </p>
      {organizationId && setup ? (
        <CatalogTranslations organizationId={organizationId} />
      ) : null}
      <p className="text-sm text-success-foreground empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <PanelSection
        actions={
          setup ? (
            <Button
              onClick={(event) =>
                open({ kind: "service" }, event.currentTarget)
              }
            >
              <PlusIcon aria-hidden="true" />
              {t("addService")}
            </Button>
          ) : null
        }
        description={t("servicesHint")}
        title={t("services")}
      >
        {templates.length && setup ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">
              {t("fromTemplate")}
            </span>
            {templates.map((template) => (
              <Button
                key={template.key}
                onClick={(event) =>
                  open({ kind: "service", template }, event.currentTarget)
                }
                size="sm"
                variant="outline"
              >
                <PlusIcon aria-hidden="true" />
                {template.name}
              </Button>
            ))}
          </div>
        ) : null}
        <DataTable
          caption={t("servicesCaption")}
          columns={serviceColumns}
          data={services}
          getRowId={(service) => service.id}
          labels={{ ...labels, empty: t("noServices") }}
          loading={!setup}
        />
      </PanelSection>
      <PanelSection
        actions={
          setup ? (
            <Button
              onClick={(event) =>
                open({ kind: "location" }, event.currentTarget)
              }
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addPlace")}
            </Button>
          ) : null
        }
        description={t("placesHint")}
        title={t("placesTitle")}
      >
        <DataTable
          caption={t("placesCaption")}
          columns={placeColumns}
          data={setup?.locations ?? []}
          getRowId={(place) => place.id}
          labels={{ ...labels, empty: t("noPlacesYet") }}
          loading={!setup}
        />
      </PanelSection>
      <PanelSection
        actions={
          setup ? (
            <Button
              onClick={(event) =>
                open({ kind: "resource" }, event.currentTarget)
              }
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addResource")}
            </Button>
          ) : null
        }
        description={t("resourcesSectionHint")}
        title={t("resourcesTitle")}
      >
        <DataTable
          caption={t("resourcesCaption")}
          columns={resourceColumns}
          data={setup?.resources ?? []}
          getRowId={(thing) => thing.id}
          labels={{ ...labels, empty: t("noResourcesYet") }}
          loading={!setup}
        />
      </PanelSection>
      <PanelSection
        actions={
          setup ? (
            <Button
              onClick={(event) => open({ kind: "group" }, event.currentTarget)}
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addGroup")}
            </Button>
          ) : null
        }
        description={t("groupsHint")}
        title={t("groupsTitle")}
      >
        <DataTable
          caption={t("groupsCaption")}
          columns={groupColumns}
          data={setup?.groups ?? []}
          getRowId={(group) => group.id}
          labels={{ ...labels, empty: t("noGroupsYet") }}
          loading={!setup}
        />
      </PanelSection>
      {setup ? <ClosuresSection places={setup.locations} /> : null}
      {/* Seasons act on stays: only a company with an offer booked by dates. */}
      {setup?.services.some((service) => service.time_model === "range") ? (
        <SeasonsSection
          book={prices.book}
          groups={setup.groups}
          onPricesChanged={prices.reload}
          resources={setup.resources}
          zone={timezone}
          services={setup.services.filter(
            (service) => service.time_model === "range",
          )}
        />
      ) : null}

      <Dialog
        onOpenChange={(next) => (next ? undefined : setSwitchingOff(undefined))}
        open={Boolean(switchingOff)}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {t("switchOffTitle", { name: switchingOff?.name ?? "" })}
            </DialogTitle>
            <DialogDescription>
              {t("switchOffFuture", {
                count: switchingOff?.future_bookings ?? 0,
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Link
              className={buttonVariants({ variant: "outline" })}
              href={`/panel/calendar?view=list&service=${encodeURIComponent(
                switchingOff?.name ?? "",
              )}`}
            >
              {t("showInCalendar")}
            </Link>
            <Button
              onClick={() => {
                const service = switchingOff;
                setSwitchingOff(undefined);
                if (service) void switchService(service);
              }}
              type="button"
            >
              {t("switchOffAnyway")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {setup && prices.book && priced ? (
        <OfferPricesDialog
          book={prices.book}
          finalFocus={returnTo}
          onChanged={prices.reload}
          onOpenChange={(value) => (value ? undefined : setPricing(undefined))}
          onSetupChanged={load}
          service={priced}
          setup={setup}
          zone={timezone}
        />
      ) : null}
      {setup && editing?.kind === "service" ? (
        <ServiceDialog
          canUseInventory={canUseInventory}
          finalFocus={returnTo}
          onOpenChange={(value) => (value ? undefined : close())}
          onSaved={(service, created) =>
            saved(t(created ? "created" : "saved", { name: service.name }))
          }
          service={editing.service}
          setup={setup}
          template={editing.template}
        />
      ) : null}
      {editing && editing.kind !== "service" ? (
        <ItemDialog
          finalFocus={returnTo}
          item={editing.item}
          kind={editing.kind}
          onOpenChange={(value) => (value ? undefined : close())}
          setup={setup}
          onSaved={(name, created) =>
            saved(t(created ? "created" : "saved", { name }))
          }
        />
      ) : null}
    </div>
  );
}
