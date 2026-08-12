"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  cancelBookingAppointment,
  createBookingAppointment,
  getBookingCatalog,
  getBookingSlots,
  listBookingAppointments,
  rescheduleBookingAppointment,
  type BookingAppointment,
  type BookingCatalog,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
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

import { BookingConfiguration } from "./booking-configuration";

export function BookingPanel() {
  const t = useTranslations("Booking");
  const [catalog, setCatalog] = useState<BookingCatalog>();
  const [appointments, setAppointments] = useState<BookingAppointment[]>([]);
  const [problem, setProblem] = useState<string>();
  const [slot, setSlot] = useState("");
  const [slots, setSlots] = useState<
    Array<{
      starts_at: string;
      staff_id: string;
      resource_id: string | null;
    }>
  >([]);
  const [appointmentId, setAppointmentId] = useState("");
  const [customerName, setCustomerName] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [locationId, setLocationId] = useState("");
  const [newStartsAt, setNewStartsAt] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextCatalog, nextAppointments] = await Promise.all([
        getBookingCatalog(),
        listBookingAppointments(),
      ]);
      setCatalog(nextCatalog);
      setAppointments(nextAppointments);
      setProblem(undefined);
    } catch (error) {
      setProblem(problemText(error, t("loadError")));
    }
  }, [t]);

  useEffect(() => {
    // The loader only updates state after its awaited requests settle.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const cancel = async (id: string) => {
    try {
      await cancelBookingAppointment(id, crypto.randomUUID());
      await load();
    } catch (error) {
      setProblem(problemText(error, t("cancelError")));
    }
  };

  const searchSlots = async () => {
    if (!serviceId || !locationId) return;
    const from = new Date();
    const to = new Date(from);
    to.setDate(to.getDate() + 14);
    try {
      const value = await getBookingSlots({
        service_id: serviceId,
        location_id: locationId,
        from: from.toISOString().slice(0, 10),
        to: to.toISOString().slice(0, 10),
      });
      setSlots(value.items);
    } catch {
      setProblem(t("loadError"));
    }
  };

  const create = async () => {
    const selected = slots.find((item) => item.starts_at === slot);
    if (!selected) return;
    try {
      await createBookingAppointment(
        {
          service_id: serviceId,
          location_id: locationId,
          staff_id: selected.staff_id,
          resource_id: selected.resource_id,
          starts_at: selected.starts_at,
          customer: {
            display_name: customerName,
            email: customerEmail,
            phone: "",
            locale: "pl",
          },
        },
        crypto.randomUUID(),
      );
      await load();
    } catch (error) {
      setProblem(problemText(error, t("createError")));
    }
  };

  const reschedule = async () => {
    if (!appointmentId || !newStartsAt) return;
    try {
      await rescheduleBookingAppointment(
        appointmentId,
        new Date(newStartsAt).toISOString(),
        crypto.randomUUID(),
      );
      await load();
    } catch (error) {
      setProblem(problemText(error, t("rescheduleError")));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">
          {t("title")}
        </h1>
        <p className="mt-2 text-muted-foreground">{t("description")}</p>
      </div>
      {problem ? (
        <p
          className="rounded-lg border border-destructive/30 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-4">
        {(["locations", "staff", "services", "resources"] as const).map(
          (key) => (
            <Card key={key}>
              <CardHeader className="pb-2">
                <CardDescription>{t(key)}</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-semibold">
                  {catalog?.[key].length ?? 0}
                </p>
              </CardContent>
            </Card>
          ),
        )}
      </div>
      <BookingConfiguration catalog={catalog} onChanged={load} />
      <Card>
        <CardHeader>
          <CardTitle>{t("createTitle")}</CardTitle>
          <CardDescription>{t("createDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <div>
            <Label htmlFor="panel-service">{t("services")}</Label>
            <NativeSelect
              id="panel-service"
              onChange={(event) => setServiceId(event.target.value)}
              value={serviceId}
            >
              <option value="">{t("choose")}</option>
              {catalog?.services.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <Label htmlFor="panel-location">{t("locations")}</Label>
            <NativeSelect
              id="panel-location"
              onChange={(event) => setLocationId(event.target.value)}
              value={locationId}
            >
              <option value="">{t("choose")}</option>
              {catalog?.locations.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <Button
            onClick={() => void searchSlots()}
            type="button"
            variant="outline"
          >
            {t("search")}
          </Button>
          <NativeSelect
            aria-label={t("slot")}
            onChange={(event) => setSlot(event.target.value)}
            value={slot}
          >
            <option value="">{t("choose")}</option>
            {slots.map((item) => (
              <option key={item.starts_at} value={item.starts_at}>
                {new Date(item.starts_at).toLocaleString()}
              </option>
            ))}
          </NativeSelect>
          <Input
            aria-label={t("customerName")}
            onChange={(event) => setCustomerName(event.target.value)}
            placeholder={t("customerName")}
            value={customerName}
          />
          <Input
            aria-label="E-mail"
            onChange={(event) => setCustomerEmail(event.target.value)}
            placeholder="E-mail"
            type="email"
            value={customerEmail}
          />
          <Button onClick={() => void create()}>{t("create")}</Button>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("calendar")}</CardTitle>
          <CardDescription>{t("calendarDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {appointments.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("empty")}</p>
          ) : null}
          {appointments.map((item) => (
            <article
              className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center"
              key={item.id}
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{item.service_name}</p>
                  <Badge variant="outline">{t(`status_${item.status}`)}</Badge>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  {new Intl.DateTimeFormat(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                    timeZone: item.timezone,
                  }).format(new Date(item.starts_at))}{" "}
                  · {item.staff_name} · {item.location_name}
                </p>
                <p className="text-sm">{item.customer_name}</p>
              </div>
              {item.status === "confirmed" ? (
                <div className="flex gap-2">
                  <Button
                    onClick={() => setAppointmentId(item.id)}
                    variant="outline"
                  >
                    {t("change")}
                  </Button>
                  <Button
                    onClick={() => void cancel(item.id)}
                    variant="outline"
                  >
                    {t("cancel")}
                  </Button>
                </div>
              ) : null}
            </article>
          ))}
        </CardContent>
      </Card>
      {appointmentId ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("changeTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row">
            <Input
              aria-label={t("newTime")}
              onChange={(event) => setNewStartsAt(event.target.value)}
              type="datetime-local"
              value={newStartsAt}
            />
            <Button onClick={() => void reschedule()}>{t("save")}</Button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError &&
    typeof error.problem.detail === "string"
    ? error.problem.detail
    : fallback;
}
