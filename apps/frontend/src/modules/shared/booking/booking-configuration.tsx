"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { z } from "zod";

import {
  configureBookingSchedule,
  createBookingCatalogItem,
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

const catalogSchema = z.object({
  kind: z.enum(["location", "staff", "service", "resource"]),
  name: z.string().trim().min(1).max(160),
  public_slug: z.string().trim().min(1).max(80),
});

const scheduleSchema = z.object({
  service_id: z.string().uuid(),
  staff_id: z.string().uuid(),
  location_id: z.string().uuid(),
  resource_id: z.string().uuid().optional(),
  weekday: z.number().int().min(0).max(6),
  local_start: z.string().min(1),
  local_end: z.string().min(1),
});

export function BookingConfiguration({
  catalog,
  onChanged,
}: {
  catalog?: BookingCatalog;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("BookingConfiguration");
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
  });

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
  });

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t("catalogTitle")}</CardTitle>
          <CardDescription>{t("catalogDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-3" onSubmit={addCatalogItem}>
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
          <form className="space-y-3" onSubmit={addSchedule}>
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
    </div>
  );
}
