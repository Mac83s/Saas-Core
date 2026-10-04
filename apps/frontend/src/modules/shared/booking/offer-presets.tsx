"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { BellIcon, PlusIcon } from "lucide-react";

import {
  ApiProblemError,
  applyBookingPreset,
  listBookingPresets,
  readCatalogDictionary,
  saveBookingPresetInterest,
  withdrawBookingPresetInterest,
  type BookingPreset,
  type ServiceSetup,
} from "@saas-core/api-client";
import {
  availablePageTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
} from "@saas-core/site-blocks";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";
import { cn } from "@saas-core/ui/lib/utils";

import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { problemText } from "./people/person-dialogs";

/** As the API bounds what a company writes under „Czego Ci brakuje?”. */
const NOTE_MAX_LENGTH = 1000;
/** A visit's length offered first; the company changes it in the dialog. */
const DEFAULT_MINUTES = 60;

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

/** The preset's words in the panel's language, else in English. */
function words(preset: BookingPreset, locale: string) {
  const labels = preset.labels as Record<
    string,
    { name: string; description: string } | undefined
  >;
  return labels[locale] ?? labels.en ?? labels.pl!;
}

/**
 * „Wzorce ofert” (ADR-072 §10, slice 5g): what a company starts an offer
 * from, by hand. A ready preset makes the offer — the company's own copy,
 * switched off — and says what it suggests besides: where the company stands
 * in the catalogue and the page template of its site. A preset that is only
 * announced takes a sign-up and what the company says it lacks („Czego Ci
 * brakuje?”). The assistant offers the same list in a conversation.
 */
export function OfferPresets({
  catalog,
  website,
}: {
  /** The company has a business card it may change: a category is suggested. */
  catalog: boolean;
  /** The company edits its site: a page template is suggested. */
  website: boolean;
}) {
  const t = useTranslations("ServicesSetup.presets");
  const common = useTranslations("Common");
  const settings = useTranslations("Settings");
  const locale = useLocale();
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [presets, setPresets] = useState<BookingPreset[]>();
  const [problem, setProblem] = useState<string>();
  const [categories, setCategories] = useState<Record<string, string>>({});
  const [applying, setApplying] = useState<BookingPreset>();
  const [waiting, setWaiting] = useState<BookingPreset>();
  const [made, setMade] = useState<{
    offer: ServiceSetup;
    preset: BookingPreset;
  }>();
  const opener = useRef<HTMLElement | null>(null);

  const load = useCallback(async () => {
    try {
      setPresets(await listBookingPresets());
      setProblem(undefined);
    } catch (error) {
      setProblem(problemText(error, t("loadFailed"), settings("noAccess")));
    }
  }, [settings, t]);

  useEffect(() => {
    let mounted = true;
    listBookingPresets().then(
      (list) => {
        if (mounted) setPresets(list);
      },
      (error: unknown) => {
        if (mounted)
          setProblem(problemText(error, t("loadFailed"), settings("noAccess")));
      },
    );
    // The category's name, for the suggestion; without it the key is said.
    if (catalog)
      readCatalogDictionary().then(
        (dictionary) => {
          if (!mounted) return;
          setCategories(
            Object.fromEntries(
              dictionary.categories.map((category) => [
                category.key,
                (category.labels as Record<string, string | undefined>)[
                  locale
                ] ??
                  category.labels.pl ??
                  category.key,
              ]),
            ),
          );
        },
        () => undefined,
      );
    return () => {
      mounted = false;
    };
  }, [catalog, locale, settings, t]);

  // The template's name as the gallery of the page editor shows it.
  const templates = useMemo(
    () =>
      Object.fromEntries(
        availablePageTemplates(registry, [
          "sites.enabled",
          "booking.enabled",
        ]).map((template) => [
          template.id,
          (template.labels as Record<string, { name: string } | undefined>)[
            locale
          ]?.name ?? template.labels.pl.name,
        ]),
      ),
    [locale],
  );

  const columns: ColumnDef<BookingPreset>[] = [
    {
      id: "name",
      header: t("colPreset"),
      meta: { primary: true },
      accessorFn: (preset) => words(preset, locale).name,
      cell: ({ row: { original: preset } }) => (
        <div className="space-y-1">
          <p className="font-medium">{words(preset, locale).name}</p>
          <p className="max-w-2xl text-sm text-muted-foreground">
            {words(preset, locale).description}
          </p>
        </div>
      ),
    },
    {
      id: "booked",
      header: t("colBooked"),
      enableSorting: false,
      cell: ({ row: { original: preset } }) => t(`booked.${preset.time_model}`),
    },
    {
      id: "state",
      header: t("colState"),
      enableSorting: false,
      cell: ({ row: { original: preset } }) =>
        preset.readiness === "ready" ? (
          <div className="space-y-1">
            <Badge variant="success">{t("ready")}</Badge>
            {preset.online_booking === "soon" ? (
              <p className="text-sm text-muted-foreground">{t("onlineSoon")}</p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-1">
            <Badge variant="secondary">{t("soon")}</Badge>
            {preset.interest ? (
              <p className="text-sm text-muted-foreground">
                {t("signedUp", {
                  date: format.dateTime(new Date(preset.interest.updated_at), {
                    dateStyle: "medium",
                  }),
                })}
              </p>
            ) : null}
          </div>
        ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: preset } }) => (
        <RowActions
          items={[
            preset.readiness === "ready"
              ? {
                  label: t("use"),
                  icon: <PlusIcon aria-hidden="true" />,
                  inline: true,
                  labelled: true,
                  main: true,
                  onSelect: (trigger) => {
                    opener.current = trigger;
                    setApplying(preset);
                  },
                }
              : {
                  label: preset.interest ? t("changeSignUp") : t("signUp"),
                  icon: <BellIcon aria-hidden="true" />,
                  inline: true,
                  labelled: true,
                  main: true,
                  onSelect: (trigger) => {
                    opener.current = trigger;
                    setWaiting(preset);
                  },
                },
          ]}
          label={t("actionsFor", { name: words(preset, locale).name })}
        />
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      {made ? (
        <section
          aria-labelledby="preset-made-title"
          className="space-y-3 rounded-lg border bg-card p-4"
          role="status"
        >
          <h2 className="font-medium" id="preset-made-title">
            {t("madeTitle", { name: made.offer.name })}
          </h2>
          <p className="text-sm text-muted-foreground">{t("madeText")}</p>
          <ol className="list-decimal space-y-2 pl-5 text-sm">
            <li>
              {t(
                made.preset.time_model === "range" ? "nextUnits" : "nextPeople",
              )}{" "}
              <Link
                className="font-medium text-primary underline"
                href="/panel/settings/services"
              >
                {t("nextServicesLink")}
              </Link>
            </li>
            {catalog && made.preset.catalog_category ? (
              <li>
                {t("nextCategory", {
                  category:
                    categories[made.preset.catalog_category] ??
                    made.preset.catalog_category,
                })}{" "}
                <Link
                  className="font-medium text-primary underline"
                  href="/panel/profile"
                >
                  {t("nextCategoryLink")}
                </Link>
              </li>
            ) : null}
            {website && made.preset.page_template ? (
              <li>
                {t("nextTemplate", {
                  template:
                    templates[made.preset.page_template] ??
                    made.preset.page_template,
                })}{" "}
                <Link
                  className="font-medium text-primary underline"
                  href="/panel/sites"
                >
                  {t("nextTemplateLink")}
                </Link>
              </li>
            ) : null}
          </ol>
        </section>
      ) : null}
      <DataTable
        caption={t("caption")}
        columns={columns}
        data={presets ?? []}
        getRowId={(preset) => preset.id}
        labels={{ ...labels, empty: t("empty") }}
        loading={!presets && !problem}
      />
      <p className="text-sm text-muted-foreground">
        {t("ownService")}{" "}
        <Link
          className={cn(
            buttonVariants({ variant: "link" }),
            "h-auto p-0 align-baseline",
          )}
          href="/panel/settings/services"
        >
          {t("ownServiceLink")}
        </Link>
      </p>
      {applying ? (
        <ApplyDialog
          closeLabel={common("close")}
          key={applying.id}
          name={words(applying, locale).name}
          onClose={() => setApplying(undefined)}
          onMade={(offer) => {
            setMade({ offer, preset: applying });
            setApplying(undefined);
          }}
          preset={applying}
          returnFocus={opener}
        />
      ) : null}
      {waiting ? (
        <InterestDialog
          closeLabel={common("close")}
          key={waiting.id}
          name={words(waiting, locale).name}
          onClose={() => setWaiting(undefined)}
          onSaved={() => {
            setWaiting(undefined);
            void load();
          }}
          preset={waiting}
          returnFocus={opener}
        />
      ) : null}
    </div>
  );
}

function ApplyDialog({
  closeLabel,
  name,
  onClose,
  onMade,
  preset,
  returnFocus,
}: {
  closeLabel: string;
  name: string;
  onClose: () => void;
  onMade: (offer: ServiceSetup) => void;
  preset: BookingPreset;
  returnFocus: { current: HTMLElement | null };
}) {
  const t = useTranslations("ServicesSetup.presets");
  const settings = useTranslations("Settings");
  const [offerName, setOfferName] = useState(name);
  const [minutes, setMinutes] = useState(String(DEFAULT_MINUTES));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  // One key per answer: a double click makes one offer; other words are
  // another request.
  const sent = useRef<{ key: string; body: string }>(undefined);
  const visit = preset.time_model === "slot";

  async function apply() {
    const length = Number(minutes);
    if (!offerName.trim()) return setProblem(t("nameRequired"));
    if (visit && !(Number.isInteger(length) && length > 0))
      return setProblem(t("minutesRequired"));
    setBusy(true);
    setProblem(undefined);
    const input = {
      preset_id: preset.id,
      version: preset.version,
      name: offerName.trim(),
      ...(visit ? { duration_minutes: length } : {}),
    };
    const body = JSON.stringify(input);
    if (sent.current?.body !== body)
      sent.current = { key: crypto.randomUUID(), body };
    try {
      onMade(await applyBookingPreset(input, sent.current.key));
    } catch (error) {
      setProblem(
        problemText(error, t("applyFailed"), settings("noAccess"), {
          preset_not_ready: t("notReady"),
          preset_unknown: t("notReady"),
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={(open) => (open ? undefined : onClose())} open>
      <DialogContent
        closeLabel={closeLabel}
        finalFocus={() => returnFocus.current ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("applyTitle", { name })}</DialogTitle>
          <DialogDescription>{t("applyText")}</DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="preset-offer-name">{t("offerName")}</FieldLabel>
          <Input
            aria-describedby="preset-offer-name-hint"
            id="preset-offer-name"
            maxLength={160}
            onChange={(event) => setOfferName(event.target.value)}
            value={offerName}
          />
          <FieldDescription id="preset-offer-name-hint">
            {t("offerNameHint")}
          </FieldDescription>
        </Field>
        {visit ? (
          <Field>
            <FieldLabel htmlFor="preset-offer-minutes">
              {t("minutes")}
            </FieldLabel>
            <Input
              id="preset-offer-minutes"
              inputMode="numeric"
              onChange={(event) => setMinutes(event.target.value)}
              value={minutes}
            />
          </Field>
        ) : null}
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {t("cancel")}
          </DialogClose>
          <Button disabled={busy} onClick={() => void apply()} type="button">
            {t("applyConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function InterestDialog({
  closeLabel,
  name,
  onClose,
  onSaved,
  preset,
  returnFocus,
}: {
  closeLabel: string;
  name: string;
  onClose: () => void;
  onSaved: () => void;
  preset: BookingPreset;
  returnFocus: { current: HTMLElement | null };
}) {
  const t = useTranslations("ServicesSetup.presets");
  const settings = useTranslations("Settings");
  const [note, setNote] = useState(preset.interest?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const sent = useRef<{ key: string; note: string }>(undefined);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setProblem(undefined);
    try {
      await work();
      onSaved();
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          error.problem.errors?.[0]?.code === "preset_ready"
          ? t("nowReady")
          : problemText(error, t("signUpFailed"), settings("noAccess")),
      );
    } finally {
      setBusy(false);
    }
  }

  function save() {
    const text = note.trim();
    if (sent.current?.note !== text)
      sent.current = { key: crypto.randomUUID(), note: text };
    const { key } = sent.current;
    void run(() => saveBookingPresetInterest(preset.id, text, key));
  }

  return (
    <Dialog onOpenChange={(open) => (open ? undefined : onClose())} open>
      <DialogContent
        closeLabel={closeLabel}
        finalFocus={() => returnFocus.current ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("signUpTitle", { name })}</DialogTitle>
          <DialogDescription>{t("signUpText")}</DialogDescription>
        </DialogHeader>
        <Field>
          <FieldLabel htmlFor="preset-interest-note">{t("lacking")}</FieldLabel>
          <Textarea
            aria-describedby="preset-interest-note-hint"
            id="preset-interest-note"
            maxLength={NOTE_MAX_LENGTH}
            onChange={(event) => setNote(event.target.value)}
            rows={4}
            value={note}
          />
          <FieldDescription id="preset-interest-note-hint">
            {t("lackingHint")}
          </FieldDescription>
        </Field>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          {preset.interest ? (
            <Button
              disabled={busy}
              onClick={() =>
                void run(() => withdrawBookingPresetInterest(preset.id))
              }
              type="button"
              variant="outline"
            >
              {t("withdraw")}
            </Button>
          ) : (
            <DialogClose render={<Button type="button" variant="outline" />}>
              {t("cancel")}
            </DialogClose>
          )}
          <Button disabled={busy} onClick={save} type="button">
            {preset.interest ? t("saveSignUp") : t("signUpConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
