"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  createPublicBookingAppointment,
  getPublicBookingCatalog,
  getPublicBookingConsents,
  getPublicBookingDays,
  getPublicBookingQuote,
  getPublicBookingTimes,
  type BookingPublicAppointment,
  type BookingPublicCatalog,
  type BookingPublicChoice,
  type BookingPublicConsents,
  type BookingPublicQuote,
  type BookingSlotTimeList,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { addDays, dateFormat, formatDay, wallClock } from "./calendar-time";
import {
  BookedCard,
  ContactFields,
  type ContactValues,
  contactIssues,
  contactShape,
  DocumentBoxes,
  ExtrasPicker,
  LanguageUnavailable,
  otherLanguages,
  pickedExtras,
  ticked,
} from "./public-booking-parts";
import { PublicStayFlow, type StayPreset } from "./public-stay-flow";
import { QuoteSummary } from "./quote-summary";

type Values = ContactValues & {
  service_id: string;
  location_id: string;
  starts_at: string;
};

export function PublicBookingFlow({
  preset,
  publicSlug,
}: {
  /** What the link to the form chose ahead — a block of the company's site
   *  names the offer, what is booked of it, the days and the people
   *  (ADR-072, slice 5d). */
  preset?: StayPreset;
  publicSlug: string;
}) {
  const t = useTranslations("PublicBooking");
  const locale = useLocale();
  const [catalog, setCatalog] = useState<BookingPublicCatalog>();
  // An offer booked from–to chosen in „Usługa”: it has its own form
  // (ADR-072, phase 5b). A company that offers nothing else opens on it.
  // Unset — nothing chosen here yet; null — a visit was.
  const [stayId, setStayId] = useState<string | null>();
  // The company's documents in force in the page's language (ADR-073 §9),
  // the ones ticked, and whether a booking was tried without them. A list
  // that did not load is not a way round them: the server answers a booking
  // without them with the list.
  const [documents, setDocuments] = useState<
    BookingPublicConsents["documents"]
  >([]);
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [unaccepted, setUnaccepted] = useState(false);
  // The marketing consent the company asks for, and whether it is ticked —
  // never by us.
  const [statement, setStatement] = useState<string>();
  const [offers, setOffers] = useState(false);
  const marketing = statement
    ? { statement, checked: offers, onChange: setOffers }
    : undefined;
  // The booking terms have no text in the page's language: the languages to
  // offer instead of a form the server would refuse.
  const [elsewhere, setElsewhere] = useState<string[]>();
  // The search the days belong to, the days it found, the day chosen and its
  // times; an unset list is one still being asked for.
  const [query, setQuery] = useState<
    {
      service_id: string;
      location_id: string;
    } & BookingPublicChoice
  >();
  const [days, setDays] = useState<string[]>();
  const [day, setDay] = useState("");
  const [times, setTimes] = useState<BookingSlotTimeList["items"]>();
  const [booked, setBooked] = useState<BookingPublicAppointment>();
  const [problem, setProblem] = useState<string>();
  // „Do kogo?”: nobody in particular, or the team / person the service offers.
  const [choice, setChoice] = useState<BookingPublicChoice>({});
  // Which contact the company requires online (booking.online.contact, B9).
  const contact = catalog?.online.contact ?? "email";
  const schema = useMemo(
    () =>
      z
        .object({
          service_id: z.string().uuid(t("required")),
          location_id: z.string().uuid(t("required")),
          starts_at: z.string().min(1, t("pickTime")),
          ...contactShape(t),
        })
        .superRefine(contactIssues(contact, t)),
    [contact, t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      location_id: "",
      starts_at: "",
      display_name: "",
      email: "",
      phone: "",
      notes: "",
    },
  });
  const errors = form.formState.errors;
  const zone = catalog?.timezone;
  const serviceId = useWatch({ control: form.control, name: "service_id" });
  const service = catalog?.services.find((x) => String(x.id) === serviceId);
  const offered =
    service?.staff_choice === "team"
      ? (catalog?.teams ?? []).filter((x) => service.team_ids.includes(x.id))
      : service?.staff_choice === "person"
        ? (catalog?.people ?? []).filter((x) =>
            service.person_ids.includes(x.id),
          )
        : [];
  const choiceKey =
    service?.staff_choice === "person" ? "person_id" : "team_id";
  const loading = (!!query && !days) || (!!day && !times);
  // The extras the customer may add to this service, and how many of each.
  const options = (catalog?.extras ?? []).filter(
    (x) => String(x.service_id) === serviceId && !x.mandatory,
  );
  const [picked, setPicked] = useState<Record<string, number>>({});
  const extras = useMemo(() => pickedExtras(picked), [picked]);
  // The price of what is chosen now; an answer for an earlier choice is not
  // shown. No price shown never stops a booking: the server prices it anyway.
  const startsAt = useWatch({ control: form.control, name: "starts_at" });
  const quoteKey =
    serviceId && startsAt ? JSON.stringify([serviceId, startsAt, extras]) : "";
  const [priced, setPriced] = useState<{
    key: string;
    quote: BookingPublicQuote | null;
  }>();
  const quote = priced?.key === quoteKey ? priced.quote : undefined;

  useEffect(() => {
    void getPublicBookingCatalog(publicSlug, locale)
      .then(setCatalog)
      .catch(() => setProblem(t("loadError")));
  }, [locale, publicSlug, t]);
  useEffect(() => {
    void getPublicBookingConsents(publicSlug, locale)
      .then((value) => {
        setDocuments(value.documents);
        setStatement(value.marketing?.statement);
        if (!value.bookable) setElsewhere(value.bookable_locales);
      })
      .catch(() => undefined);
  }, [locale, publicSlug]);

  // Each answer is dropped once the customer has moved on to another search
  // or day, as in useFreeSlots: a late reply must not fill in the wrong list.
  useEffect(() => {
    if (!query || !zone) return;
    let current = true;
    // The business's today: the days offered are its calendar, not the browser's.
    const from = wallClock(new Date(), zone).day;
    getPublicBookingDays(publicSlug, {
      ...query,
      from,
      // As far ahead as the company takes bookings online (B3).
      to: catalog?.online.last_day ?? addDays(from, 14),
    })
      .then((value) => {
        if (!current) return;
        setDays(value);
        setProblem(undefined);
      })
      .catch(() => {
        if (!current) return;
        setQuery(undefined);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
  }, [catalog?.online.last_day, publicSlug, query, t, zone]);
  useEffect(() => {
    if (!quoteKey) return;
    let current = true;
    getPublicBookingQuote(publicSlug, {
      service_id: serviceId,
      starts_at: startsAt,
      extras,
      locale,
    })
      .then((value) => {
        if (current) setPriced({ key: quoteKey, quote: value });
      })
      .catch(() => {
        if (current) setPriced({ key: quoteKey, quote: null });
      });
    return () => {
      current = false;
    };
  }, [extras, locale, publicSlug, quoteKey, serviceId, startsAt]);
  useEffect(() => {
    if (!query || !day) return;
    let current = true;
    getPublicBookingTimes(publicSlug, { ...query, date: day })
      .then((value) => {
        if (!current) return;
        setTimes(value);
        setProblem(undefined);
      })
      .catch(() => {
        if (!current) return;
        setTimes([]);
        setProblem(t("loadError"));
      });
    return () => {
      current = false;
    };
  }, [day, publicSlug, query, t]);

  // Another service or place: the days and times listed are no longer its own.
  function reset() {
    form.clearErrors(["service_id", "location_id"]);
    setQuery(undefined);
    setDays(undefined);
    pickDay("");
  }
  function choose(next: BookingPublicChoice) {
    setChoice(next);
    reset();
  }
  // „Usługa” lists visits and stays together: a stay opens its own form, a
  // visit this one.
  const stays = catalog?.stays ?? [];
  function pickOffer(id: string) {
    const stay = stays.some((item) => String(item.id) === id);
    setStayId(stay ? id : null);
    form.setValue("service_id", stay ? "" : id);
    setPicked({});
    choose({});
  }
  function pickDay(value: string) {
    setDay(value);
    setTimes(undefined);
    form.setValue("starts_at", "");
  }
  const search = async () => {
    if (!(await form.trigger(["service_id", "location_id"]))) return;
    reset();
    setQuery({
      service_id: form.getValues("service_id"),
      location_id: form.getValues("location_id"),
      ...choice,
    });
  };
  const book = form.handleSubmit(
    async ({ display_name, email, phone, notes, ...booking }) => {
      if (documents.some((document) => !accepted[document.text_id])) return;
      try {
        // Who takes the visit, and the room it needs, is the server's pick
        // (ADR-058 §4) — within the team or the person the customer chose.
        const created = await createPublicBookingAppointment(
          publicSlug,
          {
            ...booking,
            ...(query?.team_id ? { team_id: query.team_id } : {}),
            ...(query?.person_id ? { person_id: query.person_id } : {}),
            ...(notes.trim() ? { customer_notes: notes.trim() } : {}),
            ...(extras.length ? { extras } : {}),
            // The price shown: another one by now is asked about, not charged.
            ...(quote ? { quote_digest: quote.digest } : {}),
            ...ticked(documents, marketing),
            customer: {
              display_name,
              email,
              phone: phone.trim(),
              // The page's language: the documents above are in it.
              locale,
            },
          },
          crypto.randomUUID(),
        );
        setBooked(created);
        setProblem(undefined);
      } catch (error) {
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "quote_changed"
        ) {
          const detail = error.problem.detail as {
            quote?: BookingPublicQuote | null;
          };
          setPriced({ key: quoteKey, quote: detail.quote ?? null });
          setProblem(t("priceChanged"));
          return;
        }
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "documents_changed"
        ) {
          const detail = error.problem.detail as Partial<BookingPublicConsents>;
          setDocuments(detail.documents ?? []);
          setAccepted({});
          setUnaccepted(false);
          setProblem(t("documentsChanged"));
          return;
        }
        const languages = otherLanguages(error);
        if (languages) {
          setElsewhere(languages);
          return;
        }
        setProblem(t("createError"));
      }
    },
  );
  // A box left empty is said together with the fields left empty.
  const submit = (event: FormEvent<HTMLFormElement>) => {
    setUnaccepted(true);
    return book(event);
  };
  // The business's wall clock, zone named: the customer may be elsewhere, and
  // the autumn hour that happens twice reads as two different times.
  const clock = zone
    ? dateFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
        timeZone: zone,
        timeZoneName: "short",
      })
    : undefined;

  if (booked)
    return (
      <BookedCard
        booked={booked}
        email={form.getValues("email")}
        name={form.getValues("display_name").trim()}
      />
    );
  // The company paused online booking (ADR-078, booking.online): say so
  // instead of a form the server would refuse.
  if (catalog?.online.paused)
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription role="status">
            {catalog.online.resume_on
              ? t("pausedUntil", {
                  date: new Intl.DateTimeFormat(locale, {
                    dateStyle: "long",
                  }).format(new Date(`${catalog.online.resume_on}T12:00:00`)),
                })
              : t("paused")}
          </CardDescription>
        </CardHeader>
      </Card>
    );
  if (elsewhere)
    return <LanguageUnavailable locales={elsewhere} publicSlug={publicSlug} />;
  // The stay the link named: the offer itself, or the one that lists the
  // group or the unit it named. A name the form does not have is no choice.
  const linked =
    stays.find((item) => String(item.id) === preset?.offer) ??
    (preset?.offer
      ? undefined
      : stays.find(
          (item) =>
            item.groups.some((group) => String(group.id) === preset?.group) ||
            item.units.some((unit) => String(unit.id) === preset?.unit),
        ));
  const stay =
    stayId === undefined
      ? (linked?.id ?? (catalog?.services.length ? undefined : stays[0]?.id))
      : stayId;
  if (catalog && stay && stays.some((item) => String(item.id) === stay))
    return (
      <PublicStayFlow
        catalog={catalog}
        documents={documents}
        key={String(stay)}
        marketing={marketing}
        offerId={String(stay)}
        onDocuments={setDocuments}
        onElsewhere={setElsewhere}
        onOffer={pickOffer}
        preset={
          linked && String(linked.id) === String(stay) ? preset : undefined
        }
        publicSlug={publicSlug}
      />
    );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" noValidate onSubmit={submit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field data-invalid={Boolean(errors.service_id)}>
              <FieldLabel htmlFor="booking-service">{t("service")}</FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.service_id)}
                id="booking-service"
                {...form.register("service_id", {
                  onChange: (event: { target: { value: string } }) =>
                    pickOffer(event.target.value),
                })}
              >
                <option value="">{t("choose")}</option>
                {catalog?.services.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
                {stays.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {x.name}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.service_id]} />
            </Field>
            <Field data-invalid={Boolean(errors.location_id)}>
              <FieldLabel htmlFor="booking-location">
                {t("location")}
              </FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.location_id)}
                id="booking-location"
                {...form.register("location_id", { onChange: reset })}
              >
                <option value="">{t("choose")}</option>
                {catalog?.locations.map((x) => (
                  <option key={String(x.id)} value={String(x.id)}>
                    {String(x.name)}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.location_id]} />
            </Field>
          </div>
          {offered.length ? (
            <FieldSet>
              <FieldLegend variant="label">{t("whoLegend")}</FieldLegend>
              <div className="grid gap-1">
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={!choice.team_id && !choice.person_id}
                    className="size-4"
                    name="booking-who"
                    onChange={() => choose({})}
                    type="radio"
                  />
                  {t(choiceKey === "team_id" ? "anyTeam" : "anyPerson")}
                </label>
                <label className="flex min-h-11 items-center gap-2 text-sm">
                  <input
                    checked={Boolean(choice.team_id || choice.person_id)}
                    className="size-4"
                    name="booking-who"
                    onChange={() =>
                      choose({ [choiceKey]: String(offered[0].id) })
                    }
                    type="radio"
                  />
                  {t(choiceKey === "team_id" ? "pickTeam" : "pickPerson")}
                </label>
              </div>
              {choice.team_id || choice.person_id ? (
                <NativeSelect
                  aria-label={t(choiceKey === "team_id" ? "team" : "person")}
                  onChange={(event) =>
                    choose({ [choiceKey]: event.target.value })
                  }
                  value={choice.team_id ?? choice.person_id}
                >
                  {offered.map((x) => (
                    <option key={String(x.id)} value={String(x.id)}>
                      {x.name}
                    </option>
                  ))}
                </NativeSelect>
              ) : null}
              <FieldDescription>
                {t(choiceKey === "team_id" ? "teamsHint" : "peopleHint")}
              </FieldDescription>
            </FieldSet>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={loading}
              onClick={() => void search()}
              type="button"
              variant="outline"
            >
              {t("search")}
            </Button>
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {loading
                ? t("loadingTimes")
                : days?.length === 0
                  ? t("noDays")
                  : null}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="booking-day">{t("day")}</FieldLabel>
              <NativeSelect
                disabled={!days?.length}
                id="booking-day"
                onChange={(event) => pickDay(event.target.value)}
                value={day}
              >
                <option value="">{t("choose")}</option>
                {days?.map((item) => (
                  <option key={item} value={item}>
                    {formatDay(item, locale, { dateStyle: "full" })}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field data-invalid={Boolean(errors.starts_at)}>
              <FieldLabel htmlFor="booking-slot">{t("slot")}</FieldLabel>
              <NativeSelect
                aria-invalid={Boolean(errors.starts_at)}
                id="booking-slot"
                {...form.register("starts_at")}
              >
                <option value="">{t("choose")}</option>
                {times?.map((x) => (
                  <option key={x.starts_at} value={x.starts_at}>
                    {clock?.format(new Date(x.starts_at))}
                  </option>
                ))}
              </NativeSelect>
              <FieldError errors={[errors.starts_at]} />
            </Field>
          </div>
          <ExtrasPicker
            currency={catalog?.currency ?? "PLN"}
            onPick={setPicked}
            options={options}
            picked={picked}
          />
          {quote ? <QuoteSummary quote={quote} /> : null}
          <ContactFields
            contact={contact}
            errors={errors}
            register={(name) => form.register(name)}
          />
          <DocumentBoxes
            accepted={accepted}
            documents={documents}
            marketing={marketing}
            onAccept={(textId, checked) =>
              setAccepted({ ...accepted, [textId]: checked })
            }
            unaccepted={unaccepted}
          />
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {/* The company answers each booking of this service itself. */}
          {service?.confirmation === "on_request" ? (
            <p className="text-sm text-muted-foreground" role="note">
              {t("onRequestHint", { hours: service.response_hours ?? 24 })}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {t(service?.confirmation === "on_request" ? "request" : "book")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
