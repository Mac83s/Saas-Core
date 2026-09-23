"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useLocale, useTranslations } from "next-intl";
import { z } from "zod";

import {
  ApiProblemError,
  configureBookingSchedule,
  createBookingCatalogItem,
  setBookingServiceMaterials,
  type BookingCatalog,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { typeText, type OrganizationTypeInfo } from "#lib/organization-types";

import {
  draftsOf,
  materialsInput,
  MaterialsEditor,
  useWarehouse,
  type MaterialDraft,
} from "./materials-editor";

const catalogSchema = z.object({
  kind: z.enum(["location", "staff", "service", "resource"]),
  name: z.string().trim().min(1).max(160),
  public_slug: z.string().trim().min(1).max(80),
});

const scheduleSchema = z.object({
  service_id: z.string().uuid(),
  staff_id: z.string().uuid(),
  location_id: z.string().uuid(),
  // Optional: the select's empty choice sends "".
  resource_id: z.union([z.literal(""), z.string().uuid()]),
  weekday: z.number().int().min(0).max(6),
  local_start: z.string().min(1),
  local_end: z.string().min(1),
});

export function BookingConfiguration({
  catalog,
  onChanged,
  serviceTemplates = [],
  canUseInventory = false,
}: {
  catalog?: BookingCatalog;
  onChanged: () => Promise<void>;
  /** Ready-made services of the organization's type (ADR-050). */
  serviceTemplates?: OrganizationTypeInfo["serviceTemplates"];
  /** Products from the warehouse can be attached to a service (ADR-055). */
  canUseInventory?: boolean;
}) {
  const t = useTranslations("BookingConfiguration");
  const locale = useLocale();
  const existing = new Set(catalog?.services.map((service) => service.name));
  const [problem, setProblem] = useState<string>();

  // An add that fails, or a form that is not complete, says so.
  async function attempt(action: () => Promise<void>) {
    setProblem(undefined);
    try {
      await action();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError ? error.message : t("saveError"),
      );
    }
  }
  const incomplete = () => setProblem(t("incomplete"));

  async function addFromTemplate(
    template: OrganizationTypeInfo["serviceTemplates"][number],
  ) {
    await createBookingCatalogItem({
      kind: "service",
      name: typeText(template.label, locale),
      duration_minutes: template.durationMinutes,
      minimum_notice_minutes: 60,
      ...(template.appointmentKind
        ? { appointment_kind: template.appointmentKind }
        : {}),
    });
    await onChanged();
  }
  const catalogForm = useForm<z.infer<typeof catalogSchema>>({
    resolver: zodResolver(catalogSchema),
    defaultValues: { kind: "service", name: "", public_slug: "" },
  });
  const scheduleForm = useForm<z.infer<typeof scheduleSchema>>({
    resolver: zodResolver(scheduleSchema),
    defaultValues: {
      service_id: "",
      staff_id: "",
      location_id: "",
      resource_id: "",
      weekday: 0,
      local_start: "09:00",
      local_end: "17:00",
    },
  });

  const addCatalogItem = catalogForm.handleSubmit(async (value) => {
    const common = {
      kind: value.kind,
      name: value.name,
      public_slug: value.public_slug,
    };
    await createBookingCatalogItem(
      value.kind === "service"
        ? { ...common, duration_minutes: 30, minimum_notice_minutes: 60 }
        : value.kind === "resource"
          ? { ...common, resource_kind: "room" }
          : common,
    );
    catalogForm.reset({ kind: value.kind, name: "", public_slug: "" });
    await onChanged();
  }, incomplete);

  const addSchedule = scheduleForm.handleSubmit(async (value) => {
    await configureBookingSchedule({
      kind: "service_staff",
      service_id: value.service_id,
      staff_id: value.staff_id,
    });
    await configureBookingSchedule({
      kind: "service_location",
      service_id: value.service_id,
      location_id: value.location_id,
    });
    if (value.resource_id) {
      await configureBookingSchedule({
        kind: "service_resource",
        service_id: value.service_id,
        resource_id: value.resource_id,
      });
    }
    await configureBookingSchedule({
      kind: "availability",
      staff_id: value.staff_id,
      location_id: value.location_id,
      weekday: value.weekday,
      local_start: value.local_start,
      local_end: value.local_end,
    });
    await onChanged();
  }, incomplete);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {problem ? (
        <p className="text-sm text-destructive lg:col-span-2" role="alert">
          {problem}
        </p>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>{t("catalogTitle")}</CardTitle>
          <CardDescription>{t("catalogDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {serviceTemplates.length > 0 ? (
            <div className="mb-4 space-y-2">
              <p className="text-sm font-medium">{t("fromTemplate")}</p>
              <div className="flex flex-wrap gap-2">
                {serviceTemplates.map((template) => {
                  const label = typeText(template.label, locale);
                  return (
                    <Button
                      disabled={existing.has(label)}
                      key={template.key}
                      onClick={() =>
                        void attempt(() => addFromTemplate(template))
                      }
                      type="button"
                      variant="outline"
                    >
                      + {label} ·{" "}
                      {t("minutes", { count: template.durationMinutes })}
                    </Button>
                  );
                })}
              </div>
            </div>
          ) : null}
          <form
            className="space-y-3"
            onSubmit={(event) => void attempt(() => addCatalogItem(event))}
          >
            <Label htmlFor="catalog-kind">{t("kind")}</Label>
            <NativeSelect id="catalog-kind" {...catalogForm.register("kind")}>
              <option value="location">{t("location")}</option>
              <option value="staff">{t("staff")}</option>
              <option value="service">{t("service")}</option>
              <option value="resource">{t("resource")}</option>
            </NativeSelect>
            <Label htmlFor="catalog-name">{t("name")}</Label>
            <Input id="catalog-name" {...catalogForm.register("name")} />
            <Label htmlFor="catalog-slug">{t("slug")}</Label>
            <Input id="catalog-slug" {...catalogForm.register("public_slug")} />
            <Button disabled={catalogForm.formState.isSubmitting} type="submit">
              {t("add")}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("scheduleTitle")}</CardTitle>
          <CardDescription>{t("scheduleDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(event) => void attempt(() => addSchedule(event))}
          >
            {(["service", "staff", "location", "resource"] as const).map(
              (kind) => {
                const values =
                  kind === "service"
                    ? catalog?.services
                    : kind === "staff"
                      ? catalog?.staff
                      : kind === "location"
                        ? catalog?.locations
                        : catalog?.resources;
                const field = `${kind}_id` as const;
                return (
                  <div key={kind}>
                    <Label htmlFor={`schedule-${kind}`}>{t(kind)}</Label>
                    <NativeSelect
                      id={`schedule-${kind}`}
                      {...scheduleForm.register(field)}
                    >
                      <option value="">{t("choose")}</option>
                      {values?.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </NativeSelect>
                  </div>
                );
              },
            )}
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label htmlFor="schedule-weekday">{t("weekday")}</Label>
                <NativeSelect
                  id="schedule-weekday"
                  {...scheduleForm.register("weekday", { valueAsNumber: true })}
                >
                  {Array.from({ length: 7 }, (_, day) => (
                    <option key={day} value={day}>
                      {t(`day_${day}`)}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              <div>
                <Label htmlFor="schedule-start">{t("from")}</Label>
                <Input
                  id="schedule-start"
                  type="time"
                  {...scheduleForm.register("local_start")}
                />
              </div>
              <div>
                <Label htmlFor="schedule-end">{t("to")}</Label>
                <Input
                  id="schedule-end"
                  type="time"
                  {...scheduleForm.register("local_end")}
                />
              </div>
            </div>
            <Button
              disabled={scheduleForm.formState.isSubmitting}
              type="submit"
            >
              {t("save")}
            </Button>
          </form>
        </CardContent>
      </Card>
      {canUseInventory && catalog?.services.length ? (
        <ServiceMaterials catalog={catalog} onChanged={onChanged} />
      ) : null}
    </div>
  );
}

/** What each visit of a service takes from the warehouse, by default. */
function ServiceMaterials({
  catalog,
  onChanged,
}: {
  catalog: BookingCatalog;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("BookingMaterials");
  const warehouse = useWarehouse(true);
  const [serviceId, setServiceId] = useState(catalog.services[0]?.id ?? "");
  const service = catalog.services.find((one) => one.id === serviceId);
  const [drafts, setDrafts] = useState<MaterialDraft[]>(() =>
    draftsOf(service?.materials),
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string }>();

  async function save() {
    setBusy(true);
    setMessage(undefined);
    try {
      await setBookingServiceMaterials(serviceId, materialsInput(drafts));
      await onChanged();
      setMessage({ ok: true, text: t("saved") });
    } catch (error) {
      setMessage({
        ok: false,
        text: error instanceof ApiProblemError ? error.message : t("failed"),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>{t("serviceTitle")}</CardTitle>
        <CardDescription>{t("serviceDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="max-w-sm">
          <Label htmlFor="service-materials-service">{t("service")}</Label>
          <NativeSelect
            id="service-materials-service"
            onChange={(event) => {
              const next = catalog.services.find(
                (one) => one.id === event.target.value,
              );
              setServiceId(event.target.value);
              setDrafts(draftsOf(next?.materials));
              setMessage(undefined);
            }}
            value={serviceId}
          >
            {catalog.services.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <MaterialsEditor
          drafts={drafts}
          idPrefix="service-materials"
          onChange={setDrafts}
          warehouse={warehouse}
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={busy || !serviceId} onClick={() => void save()}>
            {t("save")}
          </Button>
          {message ? (
            <p
              className={
                message.ok
                  ? "text-sm text-success-foreground"
                  : "text-sm text-destructive"
              }
              role={message.ok ? "status" : "alert"}
            >
              {message.text}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
