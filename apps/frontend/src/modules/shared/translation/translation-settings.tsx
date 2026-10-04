"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  getTranslationSettings,
  updateTranslationSettings,
  type TranslationOffer,
  type TranslationSettings,
  type TranslationSettingsChange,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Checkbox } from "@saas-core/ui/components/checkbox";
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
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Progress } from "@saas-core/ui/components/progress";
import {
  RadioGroup,
  RadioGroupItem,
} from "@saas-core/ui/components/radio-group";
import { Switch } from "@saas-core/ui/components/switch";

import { PanelSection } from "#components/panel/panel-page";
import { GlossarySection } from "./glossary-section";
import { AutomationHeld } from "./held-demand";
import { useTranslationOffer } from "./use-translation";

const MODE = "translation.settings.mode";
const AUTO = "translation.settings.auto_changes";
const LIMIT = "translation.settings.auto_monthly_limit";

type Option = TranslationOffer["settings"][number];
type ResetKey = NonNullable<TranslationSettingsChange["reset"]>[number];
type Values = { mode: string; limit: number };

/** What the form starts from: the company's own value, else the one in
 *  force — unless somebody above the company forces it, and then the
 *  default the company would otherwise get. */
function formValues(
  state: TranslationSettings,
  options: Map<string, Option>,
): Values {
  const mode = state.values[MODE];
  const limit = state.values[LIMIT];
  return {
    mode: String(
      mode?.value ??
        (mode?.locked ? options.get(MODE)?.default : mode?.effective) ??
        "",
    ),
    limit: Number(limit?.value ?? limit?.effective ?? 0),
  };
}

function SourceBadge({ text }: { text: string }) {
  return text ? <Badge variant="outline">{text}</Badge> : null;
}

/**
 * „Tłumaczenia AI” on Ustawienia › Języki i tłumaczenia (TL16e): whether
 * translations go out at once or wait for a person, the automation of
 * changes with the consent it runs on, its monthly limit with what this month
 * has used, the one-off confirmation that content goes to the AI providers,
 * and the glossary. The variants, bounds, labels and help come from the API
 * (ADR-078); a product without the translation engine gets no section.
 */
export function TranslationSettingsSection({
  canManage,
}: {
  /** `translation.manage`: everyone else reads. */
  canManage: boolean;
}) {
  const offer = useTranslationOffer();
  if (offer.state === "loading" || offer.state === "absent") return null;
  return <Section canManage={canManage} offer={offer.offer} />;
}

function Section({
  canManage,
  offer,
}: {
  canManage: boolean;
  offer: TranslationOffer;
}) {
  const t = useTranslations("Translations.settings");
  const common = useTranslations("Common");
  const locale = useLocale();
  const format = useFormatter();
  const ids = useId();
  const [state, setState] = useState<TranslationSettings>();
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState("");
  const [reset, setReset] = useState<ResetKey[]>([]);
  // The consent dialog and the key its confirmation is sent under.
  const [consent, setConsent] = useState<{ key: string }>();
  const [dialogProblem, setDialogProblem] = useState("");
  // The processing statement, ticked in the section or in the dialog.
  const [ackTicked, setAckTicked] = useState(false);
  const [dialogAck, setDialogAck] = useState(false);

  const options = useMemo(
    () => new Map(offer.settings.map((option) => [option.key, option])),
    [offer.settings],
  );
  const text = (labels: { pl: string; en: string } | null | undefined) =>
    labels ? (locale === "en" ? labels.en : labels.pl) : "";
  const modeOption = options.get(MODE);
  const limitOption = options.get(LIMIT);
  const schema = useMemo(
    () =>
      z.object({
        mode: z.string(),
        limit: z
          .number({ error: t("limit.invalid") })
          .int(t("limit.invalid"))
          .min(limitOption?.minimum ?? 0, t("limit.invalid"))
          .max(limitOption?.maximum ?? 100_000, t("limit.invalid")),
      }),
    [limitOption, t],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { mode: "", limit: 0 },
  });

  const apply = useCallback(
    (value: TranslationSettings) => {
      setState(value);
      setReset([]);
      form.reset(formValues(value, options));
    },
    [form, options],
  );
  const load = useCallback(async () => {
    setLoadFailed(false);
    try {
      apply(await getTranslationSettings());
    } catch {
      setLoadFailed(true);
    }
  }, [apply]);
  useEffect(() => {
    let alive = true;
    getTranslationSettings()
      .then((value) => {
        if (alive) apply(value);
      })
      .catch(() => {
        if (alive) setLoadFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [apply]);

  const day = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "long" });

  /** Sends one change at the version on screen; false when it did not go. */
  async function send(
    change: TranslationSettingsChange,
    done: string,
    key: string = crypto.randomUUID(),
    say: (message: string) => void = setProblem,
  ): Promise<boolean> {
    if (!state) return false;
    setBusy(true);
    setProblem("");
    setDialogProblem("");
    setNotice("");
    try {
      apply(await updateTranslationSettings(change, state.version, key));
      setNotice(done);
      return true;
    } catch (error) {
      const found =
        error instanceof ApiProblemError ? error.problem : undefined;
      if (found?.code === "translation_version_conflict") {
        say(t("conflict"));
        await load();
      } else if (found?.status === 403) say(t("forbidden"));
      else if (
        found?.errors?.some((item) => item.field === "auto_monthly_limit")
      )
        form.setError("limit", { type: "server", message: t("limit.invalid") });
      else say(t("saveError"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submit(values: Values) {
    const dirty = form.formState.dirtyFields;
    const change: TranslationSettingsChange = {
      ...(dirty.mode && !reset.includes(MODE)
        ? { mode: values.mode as TranslationSettingsChange["mode"] }
        : {}),
      ...(dirty.limit && !reset.includes(LIMIT)
        ? { auto_monthly_limit: values.limit }
        : {}),
      ...(reset.length ? { reset } : {}),
    };
    if (Object.keys(change).length === 0) {
      setNotice(t("saved"));
      return;
    }
    await send(change, t("saved"));
  }

  function askConsent() {
    setDialogAck(false);
    setDialogProblem("");
    setConsent({ key: crypto.randomUUID() });
  }

  function restore(key: ResetKey, field: keyof Values) {
    setReset((current) => [...new Set([...current, key])]);
    const fallback = options.get(key)?.default;
    form.setValue(
      field,
      (field === "limit"
        ? Number(fallback ?? 0)
        : String(fallback ?? "")) as never,
      { shouldDirty: true },
    );
  }

  if (loadFailed)
    return (
      <PanelSection description={t("description")} title={t("title")}>
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} type="button" variant="outline">
            {t("retry")}
          </Button>
        </div>
      </PanelSection>
    );
  if (!state)
    return (
      <PanelSection description={t("description")} title={t("title")}>
        <p className="text-sm text-muted-foreground" role="status">
          {t("loading")}
        </p>
      </PanelSection>
    );

  const mode = state.values[MODE];
  const auto = state.values[AUTO];
  const limit = state.values[LIMIT];
  const automation = state.automation;
  const on = auto?.value === true;
  const limitNow = Number(limit?.effective ?? 0);
  const used = automation.month_credits;
  const credits = offer.billing.mode === "credits";
  const needsAck = credits && !state.processing_acknowledged;
  const sourceOf = (key: ResetKey, source: string | undefined) =>
    reset.includes(key)
      ? t("source.default")
      : t.has(`source.${source}`)
        ? t(`source.${source}`)
        : "";
  const lockText = (reason: string | null | undefined) =>
    t.has(`lock.${reason}`) ? t(`lock.${reason}`) : t("lock.other");
  const { errors, isDirty } = form.formState;

  return (
    <PanelSection description={t("description")} title={t("title")}>
      <p className="text-sm empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      {canManage ? null : (
        <p className="text-sm text-muted-foreground">{t("readOnly")}</p>
      )}

      <form
        className="space-y-6"
        noValidate
        onSubmit={form.handleSubmit(submit)}
      >
        <div className="space-y-2 rounded-lg border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-medium" id={`${ids}-mode`}>
              {text(modeOption?.label)}
            </h3>
            <SourceBadge text={sourceOf(MODE, mode?.source)} />
          </div>
          <Controller
            control={form.control}
            name="mode"
            render={({ field }) => (
              <RadioGroup
                aria-labelledby={`${ids}-mode`}
                disabled={!canManage || Boolean(mode?.locked) || busy}
                onValueChange={(value) => {
                  setReset((current) => current.filter((key) => key !== MODE));
                  field.onChange(String(value));
                }}
                value={field.value}
              >
                {(modeOption?.values ?? []).map((choice) => (
                  <label
                    className="flex min-h-11 items-center gap-3 text-sm"
                    key={choice.value}
                  >
                    <RadioGroupItem value={choice.value} />
                    <span>
                      <span className="font-medium">{text(choice.label)}</span>
                      <span className="block text-muted-foreground">
                        {t.has(`modeHelp.${choice.value}`)
                          ? t(`modeHelp.${choice.value}`)
                          : null}
                      </span>
                    </span>
                  </label>
                ))}
              </RadioGroup>
            )}
          />
          <p className="text-sm text-muted-foreground">{t("legalNote")}</p>
          {mode?.locked ? (
            <p className="text-sm" role="note">
              {lockText(mode.lock_reason)}
              {mode.operator_reason
                ? ` ${t("operatorReason", { reason: mode.operator_reason })}`
                : null}
            </p>
          ) : null}
          {canManage &&
          !mode?.locked &&
          mode?.value != null &&
          !reset.includes(MODE) ? (
            <Button
              onClick={() => restore(MODE, "mode")}
              size="sm"
              type="button"
              variant="link"
            >
              {t("restore")}
            </Button>
          ) : null}
        </div>

        <div className="space-y-4 rounded-lg border p-4">
          <div className="space-y-1">
            <label className="flex min-h-11 items-center justify-between gap-3">
              <span className="font-medium">
                {text(options.get(AUTO)?.label)}
              </span>
              <Switch
                checked={on}
                disabled={!canManage || busy}
                onCheckedChange={(next) => {
                  if (next) askConsent();
                  else void send({ auto_changes: false }, t("automation.off"));
                }}
              />
            </label>
            <p className="max-w-3xl text-sm text-muted-foreground">
              {text(options.get(AUTO)?.help)}
            </p>
            {/* Switched off by the company: its own „off” can go back to
                what the product sets. */}
            {canManage && auto?.value === false ? (
              <Button
                className="self-start"
                disabled={busy}
                onClick={() =>
                  void send({ reset: [AUTO] }, t("automation.restored"))
                }
                size="sm"
                type="button"
                variant="link"
              >
                {t("restore")}
              </Button>
            ) : null}
          </div>
          {/* Held for a reason the consent line below does not say. */}
          {on && automation.consent_holds ? (
            <AutomationHeld reloadKey={state.version} />
          ) : null}
          {on ? (
            automation.consent_holds ? (
              <p className="text-sm">
                {t("automation.consent", {
                  name: automation.consent_name ?? t("automation.somebody"),
                  date: automation.consent_at ? day(automation.consent_at) : "",
                })}
              </p>
            ) : (
              <div
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm"
                role="alert"
              >
                <span>
                  {t("automation.consentLost", {
                    name: automation.consent_name ?? t("automation.somebody"),
                  })}
                </span>
                {canManage ? (
                  <Button
                    disabled={busy}
                    onClick={askConsent}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    {t("automation.confirmAgain")}
                  </Button>
                ) : null}
              </div>
            )
          ) : null}

          <Field data-invalid={Boolean(errors.limit)}>
            <div className="flex flex-wrap items-center gap-2">
              <FieldLabel htmlFor={`${ids}-limit`}>
                {text(limitOption?.label)}
              </FieldLabel>
              <SourceBadge text={sourceOf(LIMIT, limit?.source)} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Input
                aria-describedby={`${ids}-limit-help`}
                aria-invalid={Boolean(errors.limit)}
                className="w-32"
                disabled={!canManage || busy}
                id={`${ids}-limit`}
                inputMode="numeric"
                max={limitOption?.maximum ?? undefined}
                min={limitOption?.minimum ?? undefined}
                type="number"
                {...form.register("limit", {
                  valueAsNumber: true,
                  onChange: () =>
                    setReset((current) =>
                      current.filter((key) => key !== LIMIT),
                    ),
                })}
              />
              <span className="text-sm text-muted-foreground">
                {t("limit.unit")}
              </span>
            </div>
            <FieldDescription id={`${ids}-limit-help`}>
              {text(limitOption?.help)}
            </FieldDescription>
            <FieldError errors={[errors.limit]} />
            {limit?.locked ? (
              <p className="text-sm" role="note">
                {t("limit.capped", { limit: limitNow })}
                {limit.operator_reason
                  ? ` ${t("operatorReason", { reason: limit.operator_reason })}`
                  : null}
              </p>
            ) : null}
            {canManage && limit?.value != null && !reset.includes(LIMIT) ? (
              <Button
                className="self-start"
                onClick={() => restore(LIMIT, "limit")}
                size="sm"
                type="button"
                variant="link"
              >
                {t("restore")}
              </Button>
            ) : null}
          </Field>

          {on || used > 0 ? (
            <div className="space-y-1.5">
              <p className="text-sm" id={`${ids}-usage`}>
                {t("usage.line", { used, limit: limitNow })}
              </p>
              {limitNow > 0 ? (
                <Progress
                  aria-labelledby={`${ids}-usage`}
                  className="max-w-md"
                  max={limitNow}
                  value={Math.min(used, limitNow)}
                />
              ) : null}
              <p className="text-sm text-muted-foreground">
                {limitNow > 0 && used >= limitNow
                  ? t("usage.exhausted", {
                      date: day(automation.month_resets_at),
                    })
                  : t("usage.resets", {
                      date: day(automation.month_resets_at),
                    })}
              </p>
            </div>
          ) : null}
        </div>

        {canManage ? (
          <Button disabled={busy || !isDirty} type="submit">
            {busy ? t("saving") : t("save")}
          </Button>
        ) : null}
      </form>

      {credits ? (
        <div className="space-y-2 rounded-lg border p-4">
          <h3 className="font-medium">{t("processing.title")}</h3>
          {state.processing_acknowledged ? (
            <p className="text-sm text-muted-foreground">
              {t("processing.done", {
                date: state.processing_ack_at
                  ? day(state.processing_ack_at)
                  : "",
              })}
            </p>
          ) : (
            <>
              <p className="max-w-3xl text-sm text-muted-foreground">
                {t("processing.why")}
              </p>
              {canManage ? (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="flex min-h-11 items-center gap-3 text-sm">
                    <Checkbox
                      checked={ackTicked}
                      disabled={busy}
                      onCheckedChange={(value) => setAckTicked(value)}
                    />
                    {t("processing.statement")}
                  </label>
                  <Button
                    disabled={busy || !ackTicked}
                    onClick={() =>
                      void send(
                        { processing_acknowledged: true },
                        t("processing.saved"),
                      )
                    }
                    type="button"
                    variant="outline"
                  >
                    {t("processing.confirm")}
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      ) : null}

      <GlossarySection canManage={canManage} limit={offer.glossary_limit} />

      <Dialog
        onOpenChange={(next) => (next ? undefined : setConsent(undefined))}
        open={consent !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {t(on ? "consentDialog.titleAgain" : "consentDialog.title")}
            </DialogTitle>
            <DialogDescription>{t("consentDialog.what")}</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            <li>
              {credits
                ? offer.billing.credits_per_unit === null
                  ? t("consentDialog.priceUnknown")
                  : t("consentDialog.price", {
                      credits: offer.billing.credits_per_unit,
                      characters: offer.billing.unit_characters,
                    })
                : t("consentDialog.platformPays")}
            </li>
            {credits ? (
              <li>
                {limitNow > 0
                  ? t("consentDialog.limit", { limit: limitNow })
                  : t("consentDialog.limitZero")}
              </li>
            ) : null}
            <li>{t("consentDialog.asYou")}</li>
          </ul>
          {needsAck ? (
            <label className="flex min-h-11 items-center gap-3 text-sm">
              <Checkbox
                checked={dialogAck}
                disabled={busy}
                onCheckedChange={(value) => setDialogAck(value)}
              />
              {t("processing.statement")}
            </label>
          ) : null}
          {dialogProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {dialogProblem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy || (needsAck && !dialogAck)}
              onClick={async () => {
                if (!consent) return;
                const sent = await send(
                  {
                    auto_changes: true,
                    ...(needsAck ? { processing_acknowledged: true } : {}),
                  },
                  t(on ? "automation.confirmed" : "automation.on"),
                  consent.key,
                  setDialogProblem,
                );
                // A refused confirmation is asked again as a new one.
                setConsent(sent ? undefined : { key: crypto.randomUUID() });
              }}
              type="button"
            >
              {t(on ? "consentDialog.confirmAgain" : "consentDialog.confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PanelSection>
  );
}
