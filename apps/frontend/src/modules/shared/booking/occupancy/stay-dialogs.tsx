"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  addUnitBlock,
  createStay,
  getBookingSetup,
  listBookingExtras,
  listParticipantCategories,
  moveStay,
  previewStay,
  previewStayMove,
  type BookingAppointment,
  type BookingExtra,
  type BookingSetup,
  type OccupancyUnit,
  type ParticipantCategory,
  type StayPlan,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { formatDateRange } from "#lib/dates";
import { addDays, zonedInstant } from "../calendar-time";
import { changedQuote, isPriced, PanelQuote } from "../prices/panel-quote";
import {
  ExtrasPicker,
  extrasOf,
  ONE_PERSON,
  participantsOf,
  PartyFields,
  type Party,
} from "../prices/party";

/** The server's own words for a refused stay: a season's rule, a taken unit. */
function refusal(error: unknown, fallback: string): string {
  if (!(error instanceof ApiProblemError)) return fallback;
  const first = error.problem.errors?.[0]?.message;
  if (first) return first;
  return typeof error.problem.detail === "string" && error.problem.detail
    ? error.problem.detail
    : fallback;
}

/** „Sala A · 2 dni · 8–9 paź 2026”: what the dates would take. */
function usePlanText(zone: string) {
  const t = useTranslations("Occupancy");
  const locale = useLocale();
  return (plan: StayPlan) =>
    t("planSummary", {
      unit: plan.resource_name,
      length: t(plan.range_unit === "day" ? "lengthDays" : "lengthNights", {
        count: plan.length,
      }),
      when: formatDateRange(plan.starts_at, plan.ends_at, locale, zone),
    });
}

/**
 * „Nowy pobyt” (ADR-072 phase 2d): an offer booked by dates, a group's any
 * free unit or one unit, the dates — checked as they are chosen — and the
 * guest. The server picks the least busy unit of a group.
 */
export function NewStayDialog({
  onBooked,
  onOpenChange,
  open,
  preset,
  zone,
}: {
  onBooked: (stay: BookingAppointment) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  /** A free cell clicked: its unit and day. */
  preset?: { unitId?: string; day?: string };
  zone: string;
}) {
  const t = useTranslations("Occupancy");
  const prices = useTranslations("PriceList");
  const common = useTranslations("Common");
  const planText = usePlanText(zone);
  const [setup, setSetup] = useState<BookingSetup>();
  // Who comes and what they add: the price and a unit's capacity count them.
  const [categories, setCategories] = useState<ParticipantCategory[]>([]);
  const [extras, setExtras] = useState<BookingExtra[]>([]);
  const [party, setParty] = useState<Party>(ONE_PERSON);
  const [picked, setPicked] = useState<Record<string, number>>({});
  /** The price is another one than the form showed when it was sent. */
  const [changed, setChanged] = useState(false);
  const [serviceId, setServiceId] = useState("");
  const [target, setTarget] = useState("");
  const [startDate, setStartDate] = useState(preset?.day ?? "");
  const [endDate, setEndDate] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [plan, setPlan] = useState<StayPlan>();
  const [planProblem, setPlanProblem] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const offers = (setup?.services ?? []).filter(
    (service) => service.active && service.time_model === "range",
  );
  const offer = offers.find((service) => service.id === serviceId);
  const groups = (setup?.groups ?? []).filter(
    (group) => group.active && offer?.group_ids.includes(group.id),
  );
  const units = (setup?.resources ?? []).filter(
    (unit) =>
      unit.active &&
      ((unit.group_id && offer?.group_ids.includes(unit.group_id)) ||
        offer?.resource_ids.includes(unit.id)),
  );
  const byDays = offer?.range_unit === "day";
  const options = extras.filter(
    (extra) =>
      extra.service_id === serviceId &&
      extra.active &&
      extra.kind === "charge" &&
      !extra.mandatory,
  );
  const chosen = extrasOf(
    Object.fromEntries(
      options.map((extra) => [extra.id, picked[extra.id] ?? 0]),
    ),
  );
  const participants = participantsOf(party);
  const asked = JSON.stringify([participants, chosen]);

  useEffect(() => {
    if (!open || setup) return;
    // A price list that cannot be read asks about nobody and offers nothing.
    void listParticipantCategories()
      .then((found) => setCategories(found.filter((item) => item.active)))
      .catch(() => undefined);
    void listBookingExtras()
      .then(setExtras)
      .catch(() => undefined);
    void getBookingSetup().then((loaded) => {
      setSetup(loaded);
      const first = loaded.services.find(
        (service) =>
          service.active &&
          service.time_model === "range" &&
          (!preset?.unitId ||
            service.resource_ids.includes(preset.unitId) ||
            loaded.resources.some(
              (unit) =>
                unit.id === preset.unitId &&
                unit.group_id &&
                service.group_ids.includes(unit.group_id),
            )),
      );
      setServiceId(first?.id ?? "");
      setTarget(
        preset?.unitId
          ? `unit:${preset.unitId}`
          : first?.group_ids[0]
            ? `group:${first.group_ids[0]}`
            : "",
      );
    });
  }, [open, preset, setup]);

  const input = () => {
    const [kind, id] = target.split(":");
    return {
      service_id: serviceId,
      ...(kind === "group" ? { group_id: id } : {}),
      ...(kind === "unit" ? { resource_id: id } : {}),
      start_date: startDate,
      end_date: endDate,
      customer: {
        display_name: name.trim() || t("guestPlaceholder"),
        phone: phone.trim(),
        email: email.trim(),
      },
      customer_notes: notes.trim(),
      participants,
      ...(chosen.length ? { extras: chosen } : {}),
    };
  };

  // The dates are checked as soon as both are there: the season's rules, a
  // closed day and a taken unit say so before the guest's details — and the
  // price of the stay for the people who come.
  useEffect(() => {
    if (!serviceId || !target || !startDate || !endDate) return;
    let live = true;
    previewStay(input())
      .then((found) => {
        if (!live) return;
        setPlan(found);
        setChanged(false);
        setPlanProblem(undefined);
      })
      .catch((error: unknown) => {
        if (!live) return;
        setPlan(undefined);
        setPlanProblem(refusal(error, t("checkFailed")));
      });
    return () => {
      live = false;
    };
    // `input` reads the same state the dependencies list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceId, target, startDate, endDate, asked]);

  async function book() {
    if (!name.trim()) {
      setProblem(t("guestRequired"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      onBooked(
        await createStay(
          {
            ...input(),
            // The price shown: another one by now is asked about, not booked.
            ...(isPriced(plan?.quote)
              ? { quote_digest: plan?.quote?.digest }
              : {}),
          },
          idempotencyKey,
        ),
      );
    } catch (error) {
      const quote = changedQuote(error);
      if (quote && plan) {
        // „Cena się zmieniła”: the new amounts, and the next „Zarezerwuj”
        // books at them.
        setPlan({ ...plan, quote });
        setChanged(true);
      } else setProblem(refusal(error, t("bookFailed")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      {/* With who comes, the extras and the price the form is taller than a
          screen: it scrolls inside, the buttons stay within reach. */}
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-xl"
        closeLabel={common("close")}
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void book();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("newStay")}</DialogTitle>
            <DialogDescription>{t("newStayHint")}</DialogDescription>
          </DialogHeader>
          {setup && !offers.length ? (
            <p className="text-sm text-muted-foreground">{t("noOffers")}</p>
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="stay-offer">{t("offer")}</FieldLabel>
                  <NativeSelect
                    id="stay-offer"
                    onChange={(event) => {
                      const next = offers.find(
                        (service) => service.id === event.target.value,
                      );
                      setServiceId(event.target.value);
                      setTarget(
                        next?.group_ids[0] ? `group:${next.group_ids[0]}` : "",
                      );
                    }}
                    value={serviceId}
                  >
                    {offers.map((service) => (
                      <option key={service.id} value={service.id}>
                        {service.name}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="stay-unit">{t("where")}</FieldLabel>
                  <NativeSelect
                    id="stay-unit"
                    onChange={(event) => setTarget(event.target.value)}
                    value={target}
                  >
                    {groups.map((group) => (
                      <option key={group.id} value={`group:${group.id}`}>
                        {t("anyOfGroup", { group: group.name })}
                      </option>
                    ))}
                    {units.map((unit) => (
                      <option key={unit.id} value={`unit:${unit.id}`}>
                        {unit.name}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="stay-start">
                    {t(byDays ? "firstDay" : "arrival")}
                  </FieldLabel>
                  <Input
                    id="stay-start"
                    onChange={(event) => setStartDate(event.target.value)}
                    type="date"
                    value={startDate}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="stay-end">
                    {t(byDays ? "lastDay" : "departure")}
                  </FieldLabel>
                  <Input
                    id="stay-end"
                    min={startDate || undefined}
                    onChange={(event) => setEndDate(event.target.value)}
                    type="date"
                    value={endDate}
                  />
                </Field>
              </div>
              <p
                aria-live="polite"
                className={
                  planProblem
                    ? "text-sm text-destructive"
                    : "text-sm text-success-foreground"
                }
              >
                {planProblem ?? (plan ? planText(plan) : "")}
              </p>
              <FieldSet>
                <FieldLegend variant="label">
                  {prices("partyLegend")}
                </FieldLegend>
                <PartyFields
                  categories={categories}
                  idPrefix="stay-party"
                  onChange={setParty}
                  value={party}
                />
              </FieldSet>
              {options.length ? (
                <FieldSet>
                  <FieldLegend variant="label">
                    {prices("extrasLegend")}
                  </FieldLegend>
                  <ExtrasPicker
                    extras={options}
                    idPrefix="stay-extra"
                    onChange={setPicked}
                    value={picked}
                  />
                </FieldSet>
              ) : null}
              {plan?.quote && isPriced(plan.quote) ? (
                <PanelQuote changed={changed} quote={plan.quote} />
              ) : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <Field className="sm:col-span-2">
                  <FieldLabel htmlFor="stay-guest">{t("guest")}</FieldLabel>
                  <Input
                    autoComplete="off"
                    id="stay-guest"
                    onChange={(event) => setName(event.target.value)}
                    value={name}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="stay-phone">{t("phone")}</FieldLabel>
                  <Input
                    autoComplete="off"
                    id="stay-phone"
                    inputMode="tel"
                    onChange={(event) => setPhone(event.target.value)}
                    type="tel"
                    value={phone}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="stay-email">{t("email")}</FieldLabel>
                  <Input
                    autoComplete="off"
                    id="stay-email"
                    onChange={(event) => setEmail(event.target.value)}
                    type="email"
                    value={email}
                  />
                </Field>
                <Field className="sm:col-span-2">
                  <FieldLabel htmlFor="stay-notes">{t("notes")}</FieldLabel>
                  <Textarea
                    id="stay-notes"
                    maxLength={500}
                    onChange={(event) => setNotes(event.target.value)}
                    value={notes}
                  />
                </Field>
              </div>
            </>
          )}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy || !plan} type="submit">
              {t("book")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * „Zablokuj jednostkę”: the company keeps a unit for itself whole days — a
 * renovation, its own use. A unit taken then says so instead of blocking.
 */
export function BlockUnitDialog({
  onBlocked,
  onOpenChange,
  open,
  preset,
  units,
  zone,
}: {
  onBlocked: () => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  preset?: { unitId?: string; day?: string };
  units: OccupancyUnit[];
  zone: string;
}) {
  const t = useTranslations("Occupancy");
  const common = useTranslations("Common");
  const [unitId, setUnitId] = useState(preset?.unitId ?? units[0]?.id ?? "");
  const [from, setFrom] = useState(preset?.day ?? "");
  const [to, setTo] = useState(preset?.day ?? "");
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  async function block() {
    if (!from || !to) {
      setProblem(t("blockDatesRequired"));
      return;
    }
    if (to < from) {
      setProblem(t("blockEndBeforeStart"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      await addUnitBlock(
        unitId,
        {
          starts_at: zonedInstant(from, "00:00", zone).toISOString(),
          ends_at: zonedInstant(addDays(to, 1), "00:00", zone).toISOString(),
          reason: reason.trim(),
        },
        idempotencyKey,
      );
      onBlocked();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError && error.problem.code === "unit_busy"
          ? t("unitBusy")
          : refusal(error, t("blockFailed")),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent closeLabel={common("close")}>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void block();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("blockUnit")}</DialogTitle>
            <DialogDescription>{t("blockHint")}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="block-unit">{t("unit")}</FieldLabel>
            <NativeSelect
              id="block-unit"
              onChange={(event) => setUnitId(event.target.value)}
              value={unitId}
            >
              {units.map((unit) => (
                <option key={unit.id} value={unit.id}>
                  {unit.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="block-from">{t("blockFrom")}</FieldLabel>
              <Input
                id="block-from"
                onChange={(event) => setFrom(event.target.value)}
                type="date"
                value={from}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="block-to">{t("blockTo")}</FieldLabel>
              <Input
                id="block-to"
                min={from || undefined}
                onChange={(event) => setTo(event.target.value)}
                type="date"
                value={to}
              />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="block-reason">{t("blockReason")}</FieldLabel>
            <Input
              autoComplete="off"
              id="block-reason"
              maxLength={160}
              onChange={(event) => setReason(event.target.value)}
              value={reason}
            />
          </Field>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy} type="submit">
              {t("blockConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/**
 * „Zmień daty” on a stay: a stay moves by its dates, not by a slot; the
 * server keeps its unit when it is free, else the least busy one of the group.
 */
export function MoveStayDialog({
  appointment,
  onDone,
  zone,
}: {
  appointment: BookingAppointment;
  onDone: (appointment: BookingAppointment) => void;
  zone: string;
}) {
  const t = useTranslations("Occupancy");
  const common = useTranslations("Common");
  const planText = usePlanText(zone);
  const [open, setOpen] = useState(false);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [plan, setPlan] = useState<StayPlan>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState("");

  useEffect(() => {
    if (!open || !startDate || !endDate) return;
    let live = true;
    previewStayMove(appointment.id, {
      start_date: startDate,
      end_date: endDate,
    })
      .then((found) => {
        if (!live) return;
        setPlan(found);
        setChanged(false);
        setProblem(undefined);
      })
      .catch((error: unknown) => {
        if (!live) return;
        setPlan(undefined);
        setProblem(refusal(error, t("checkFailed")));
      });
    return () => {
      live = false;
    };
  }, [appointment.id, endDate, open, startDate, t]);

  async function move() {
    setBusy(true);
    try {
      const moved = await moveStay(
        appointment.id,
        {
          start_date: startDate,
          end_date: endDate,
          // The stay is priced again for the new dates: the price shown.
          ...(isPriced(plan?.quote)
            ? { quote_digest: plan?.quote?.digest }
            : {}),
        },
        idempotencyKey,
      );
      setOpen(false);
      onDone(moved);
    } catch (error) {
      const quote = changedQuote(error);
      if (quote && plan) {
        setPlan({ ...plan, quote });
        setChanged(true);
      } else setProblem(refusal(error, t("moveFailed")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (next) {
          setIdempotencyKey(crypto.randomUUID());
          setPlan(undefined);
          setProblem(undefined);
          setStartDate("");
          setEndDate("");
        }
        setOpen(next);
      }}
      open={open}
    >
      <DialogTrigger render={<Button type="button" variant="outline" />}>
        {t("moveStay")}
      </DialogTrigger>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto"
        closeLabel={common("close")}
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void move();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("moveStay")}</DialogTitle>
            <DialogDescription>{t("moveStayHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="move-start">{t("newStart")}</FieldLabel>
              <Input
                id="move-start"
                onChange={(event) => setStartDate(event.target.value)}
                type="date"
                value={startDate}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="move-end">{t("newEnd")}</FieldLabel>
              <Input
                id="move-end"
                min={startDate || undefined}
                onChange={(event) => setEndDate(event.target.value)}
                type="date"
                value={endDate}
              />
            </Field>
          </div>
          <p
            aria-live="polite"
            className={
              problem
                ? "text-sm text-destructive"
                : "text-sm text-success-foreground"
            }
          >
            {problem ?? (plan ? planText(plan) : "")}
          </p>
          {plan?.quote && isPriced(plan.quote) ? (
            <PanelQuote changed={changed} quote={plan.quote} />
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy || !plan} type="submit">
              {t("moveConfirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
