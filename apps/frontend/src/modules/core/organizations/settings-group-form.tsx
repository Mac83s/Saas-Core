"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  confirmStepUp,
  getSettingsGroup,
  previewSettingsGroup,
  updateSettingsGroup,
  type SettingEffect,
  type SettingOption,
  type SettingsGroupChange,
  type SettingsGroupKey,
  type SettingsGroupSchema,
  type SettingsGroupState,
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
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Switch } from "@saas-core/ui/components/switch";
import { Textarea } from "@saas-core/ui/components/textarea";

import { Link } from "#i18n/navigation";

type Values = Record<string, unknown>;

/** The field of a key in its group's API: the key's last segment (ADR-078). */
function fieldOf(option: SettingOption): string {
  return option.key.slice(option.key.lastIndexOf(".") + 1);
}

function text(labels: { pl: string; en: string }, locale: string): string {
  return locale === "en" ? labels.en : labels.pl;
}

/**
 * Whether a field matters now: `depends_on` names a switch of the group that
 * must be on, or `<key> == '<value>'` another field's value (ADR-078).
 */
function applies(option: SettingOption, values: Values): boolean {
  if (!option.depends_on) return true;
  const [key, expected] = option.depends_on.split(" == ");
  const value = values[key.slice(key.lastIndexOf(".") + 1)];
  return expected === undefined
    ? value !== false
    : value === expected.replace(/^'|'$/g, "");
}

/** A text longer than a line is written in a box, not a single field. */
const LONG_TEXT = 80;

function zodFor(option: SettingOption): z.ZodType {
  if (option.type === "bool") return z.boolean();
  if (option.type === "int") {
    let number = z.number().int();
    if (option.minimum !== null) number = number.min(option.minimum);
    if (option.maximum !== null) number = number.max(option.maximum);
    return number;
  }
  // A date or a text left empty goes back to the default through `reset`.
  return z.string().nullable();
}

/**
 * One settings group, drawn from its declaration: the values that apply,
 * where each comes from, "Restore the default", and a change that first shows
 * what it would do (re-planned reminders) when it does more than set a value.
 */
export function SettingsGroupForm({ group }: { group: SettingsGroupSchema }) {
  const t = useTranslations("CompanySettings");
  const locale = useLocale();
  const key = group.key as SettingsGroupKey;
  const [state, setState] = useState<SettingsGroupState>();
  const [reset, setReset] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{
    change: SettingsGroupChange;
    effects: SettingEffect[];
  }>();
  const [saved, setSaved] = useState(false);
  // A change that waits for a code from the authenticator app (billing, 31b).
  const [stepUp, setStepUp] = useState<SettingsGroupChange>();
  const [code, setCode] = useState("");
  const [stepUpProblem, setStepUpProblem] = useState<string>();
  const [mfaSetup, setMfaSetup] = useState(false);
  const schema = useMemo(
    () =>
      z.object(
        Object.fromEntries(
          group.keys.map((option) => [fieldOf(option), zodFor(option)]),
        ),
      ),
    [group.keys],
  );
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const watched = useWatch({ control: form.control });
  const readOnly = !state?.can_change;

  const load = useCallback(async () => {
    const value = await getSettingsGroup(key);
    setState(value);
    setReset([]);
    form.reset(value.values as Values);
  }, [form, key]);

  useEffect(() => {
    let mounted = true;
    void getSettingsGroup(key)
      .then((value) => {
        if (!mounted) return;
        setState(value);
        form.reset(value.values as Values);
      })
      .catch(() => {
        if (mounted)
          form.setError("root", { type: "server", message: t("loadError") });
      });
    return () => {
      mounted = false;
    };
  }, [form, key, t]);

  function failed(error: unknown) {
    if (!(error instanceof ApiProblemError)) {
      form.setError("root", { type: "server", message: t("saveError") });
      return;
    }
    if (error.problem.code === "settings_version_conflict") {
      form.setError("root", { type: "server", message: t("conflict") });
      void load();
      return;
    }
    const fields = new Set(group.keys.map(fieldOf));
    for (const item of error.problem.errors ?? []) {
      if (item.field && fields.has(item.field)) {
        form.setError(item.field, { type: "server", message: item.message });
      } else {
        form.setError("root", { type: "server", message: item.message });
      }
    }
  }

  async function save(change: SettingsGroupChange) {
    setConfirm(undefined);
    try {
      const value = await updateSettingsGroup(key, change, crypto.randomUUID());
      setState(value);
      setReset([]);
      form.reset(value.values as Values);
      setSaved(true);
    } catch (error) {
      if (error instanceof ApiProblemError) {
        if (error.problem.code === "step_up_required") {
          setCode("");
          setStepUpProblem(undefined);
          setStepUp(change);
          return;
        }
        if (error.problem.code === "step_up_mfa_setup_required") {
          setMfaSetup(true);
          return;
        }
      }
      failed(error);
    }
  }

  async function confirmCode() {
    if (!stepUp) return;
    try {
      await confirmStepUp(code);
    } catch (error) {
      const problem =
        error instanceof ApiProblemError ? error.problem.code : undefined;
      setStepUpProblem(
        problem === "step_up_locked"
          ? t("stepUpLocked")
          : problem === "mfa_locked"
            ? t("stepUpMfaLocked")
            : t("stepUpInvalid"),
      );
      return;
    }
    const change = stepUp;
    setStepUp(undefined);
    await save(change);
  }

  async function submit(values: Values) {
    if (!state) return;
    setSaved(false);
    const dirty = form.formState.dirtyFields as Record<string, boolean>;
    const cleared = group.keys
      .filter(
        (option) =>
          (option.type === "date" || option.type === "text") &&
          dirty[fieldOf(option)],
      )
      .filter((option) => !values[fieldOf(option)])
      .map(fieldOf);
    const change: SettingsGroupChange = {
      expected_version: state.version,
      reset: [...new Set([...reset, ...cleared])],
      ...Object.fromEntries(
        Object.entries(values).filter(
          ([field, value]) =>
            dirty[field] &&
            !reset.includes(field) &&
            value !== "" &&
            value !== null,
        ),
      ),
    };
    try {
      const preview = await previewSettingsGroup(key, change);
      if (Object.keys(preview.changes).length === 0) {
        setSaved(true);
        return;
      }
      if (preview.effects.length > 0) {
        setConfirm({ change, effects: preview.effects });
        return;
      }
      await save(change);
    } catch (error) {
      failed(error);
    }
  }

  function restore(option: SettingOption) {
    const field = fieldOf(option);
    setReset((current) => [...new Set([...current, field])]);
    form.setValue(field, option.default ?? null, { shouldDirty: true });
  }

  const { errors, isSubmitting } = form.formState;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{text(group.title, locale)}</CardTitle>
        <CardDescription>{text(group.description, locale)}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-6"
          noValidate
          onSubmit={form.handleSubmit(submit)}
        >
          {state?.locked ? (
            <p className="text-sm text-muted-foreground" role="status">
              {t("locked")}
            </p>
          ) : null}
          <FieldGroup>
            {group.keys.map((option) => {
              const field = fieldOf(option);
              if (!applies(option, watched)) return null;
              const source = reset.includes(field)
                ? "default"
                : (state?.sources as Record<string, string> | undefined)?.[
                    field
                  ];
              const id = `setting-${group.key}-${field}`;
              const error = errors[field];
              return (
                <Field data-invalid={Boolean(error)} key={option.key}>
                  {option.type === "bool" ? (
                    <Controller
                      control={form.control}
                      name={field}
                      render={({ field: control }) => (
                        <label className="flex min-h-11 items-center gap-3 font-medium">
                          <Switch
                            checked={control.value === true}
                            disabled={readOnly}
                            id={id}
                            onCheckedChange={(checked) =>
                              control.onChange(checked)
                            }
                          />
                          {text(option.label, locale)}
                        </label>
                      )}
                    />
                  ) : (
                    <>
                      <FieldLabel htmlFor={id}>
                        {text(option.label, locale)}
                      </FieldLabel>
                      {option.type === "enum" ? (
                        <NativeSelect
                          disabled={readOnly}
                          id={id}
                          {...form.register(field)}
                        >
                          {(option.values ?? []).map((value) => (
                            <option key={value.value} value={value.value}>
                              {text(value.label, locale)}
                            </option>
                          ))}
                        </NativeSelect>
                      ) : option.type === "text" &&
                        (option.max_length ?? 0) > LONG_TEXT ? (
                        <Textarea
                          aria-invalid={Boolean(error)}
                          disabled={readOnly}
                          id={id}
                          maxLength={option.max_length ?? undefined}
                          rows={3}
                          {...form.register(field)}
                        />
                      ) : (
                        <Input
                          aria-invalid={Boolean(error)}
                          className="max-w-xs"
                          disabled={readOnly}
                          id={id}
                          inputMode={
                            option.type === "int" ? "numeric" : undefined
                          }
                          max={option.maximum ?? undefined}
                          min={option.minimum ?? undefined}
                          type={
                            option.type === "int"
                              ? "number"
                              : option.type === "date"
                                ? "date"
                                : "text"
                          }
                          {...form.register(field, {
                            setValueAs: (value: unknown) =>
                              option.type === "int"
                                ? value === "" || value === null
                                  ? null
                                  : Number(value)
                                : value || null,
                          })}
                        />
                      )}
                    </>
                  )}
                  {option.help ? (
                    <FieldDescription>
                      {text(option.help, locale)}
                    </FieldDescription>
                  ) : null}
                  <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>{t(`source.${source ?? "code"}`)}</span>
                    {source === "organization" && !readOnly ? (
                      <Button
                        className="h-auto p-0 text-xs"
                        onClick={() => restore(option)}
                        type="button"
                        variant="link"
                      >
                        {t("restore")}
                      </Button>
                    ) : null}
                  </p>
                  <FieldError
                    errors={[error as { message?: string } | undefined]}
                  />
                </Field>
              );
            })}
          </FieldGroup>
          {mfaSetup ? (
            <p className="text-sm text-destructive" role="alert">
              {t("stepUpSetup")}{" "}
              <Link className="underline" href="/panel/settings/account">
                {t("stepUpSetupLink")}
              </Link>
            </p>
          ) : null}
          {errors.root ? (
            <p className="text-sm text-destructive" role="alert">
              {errors.root.message}
            </p>
          ) : null}
          <p aria-live="polite" className="text-sm text-muted-foreground">
            {saved ? t("saved") : null}
          </p>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {readOnly ? null : (
              <Button disabled={isSubmitting || !state} type="submit">
                {isSubmitting ? t("saving") : t("save")}
              </Button>
            )}
            {/* Who changed what, and when: this group's history (R4). */}
            <Link
              className="text-sm text-muted-foreground underline-offset-4 hover:underline"
              href={`/panel/settings/history?group=${encodeURIComponent(group.key)}`}
            >
              {t("groupHistory")}
            </Link>
          </div>
        </form>
      </CardContent>
      <Dialog
        onOpenChange={(open) => (open ? null : setConfirm(undefined))}
        open={Boolean(confirm)}
      >
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("confirmTitle")}</DialogTitle>
            <DialogDescription>{t("confirmDescription")}</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {confirm?.effects.map((effect, index) => (
              <li key={index}>{text(effect.summary, locale)}</li>
            ))}
          </ul>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {t("cancel")}
            </DialogClose>
            <Button
              onClick={() => (confirm ? void save(confirm.change) : undefined)}
              type="button"
            >
              {t("confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        onOpenChange={(open) => (open ? null : setStepUp(undefined))}
        open={Boolean(stepUp)}
      >
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("stepUpTitle")}</DialogTitle>
            <DialogDescription>{t("stepUpDescription")}</DialogDescription>
          </DialogHeader>
          <Field data-invalid={Boolean(stepUpProblem)}>
            <FieldLabel htmlFor={`step-up-${group.key}`}>
              {t("stepUpCode")}
            </FieldLabel>
            <Input
              aria-invalid={Boolean(stepUpProblem)}
              autoComplete="one-time-code"
              className="max-w-xs"
              id={`step-up-${group.key}`}
              inputMode="numeric"
              onChange={(event) => setCode(event.target.value)}
              value={code}
            />
            {stepUpProblem ? (
              <p className="text-sm text-destructive" role="alert">
                {stepUpProblem}
              </p>
            ) : null}
          </Field>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {t("cancel")}
            </DialogClose>
            <Button
              disabled={code.trim().length < 6}
              onClick={() => void confirmCode()}
              type="button"
            >
              {t("stepUpConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
