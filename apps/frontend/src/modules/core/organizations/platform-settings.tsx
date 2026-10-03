"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  changePlatformSetting,
  getPlatformSettingHistory,
  getPlatformSettings,
  previewPlatformSetting,
  type PlatformHistoryItem,
  type PlatformKey,
  type PlatformPreview,
  type PlatformSchema,
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

import { useStepUp } from "./step-up";

type Labels = { pl: string; en: string };

function text(labels: Labels, locale: string): string {
  return locale === "en" ? labels.en : labels.pl;
}

/** A text longer than a line is written in a box, not a single field. */
const LONG_TEXT = 80;

/** What the operator is about to do: a new value, or back to the default. */
type Intent = { key: PlatformKey; value?: unknown; restore?: boolean };

/**
 * The „Platforma” page (platform settings, phase 2; S-T5, S-T7): every key the
 * platform sets, by area and group — the value in force and where it comes
 * from; a change with a reason that first shows how many companies it
 * reaches; a key's history, from which an earlier value can be set again. A
 * level-2 key asks for a fresh code from the authenticator app.
 */
export function PlatformSettings() {
  const t = useTranslations("PlatformSettings");
  const locale = useLocale();
  const [schema, setSchema] = useState<PlatformSchema>();
  const [failed, setFailed] = useState(false);
  const [intent, setIntent] = useState<Intent>();
  const [history, setHistory] = useState<PlatformKey>();

  const load = useCallback(async () => {
    try {
      setSchema(await getPlatformSettings());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    getPlatformSettings()
      .then((value) => (mounted ? setSchema(value) : undefined))
      .catch(() => (mounted ? setFailed(true) : undefined));
    return () => {
      mounted = false;
    };
  }, []);

  if (failed)
    return (
      <p className="text-sm text-destructive" role="alert">
        {t("loadError")}
      </p>
    );
  if (!schema)
    return (
      <p aria-live="polite" className="text-sm text-muted-foreground">
        {t("loading")}
      </p>
    );
  return (
    <div className="space-y-8">
      <p className="text-sm text-muted-foreground">
        {t(schema.operator_level >= 2 ? "levelAdmin" : "levelOperator")}
      </p>
      {schema.areas.map((area) => (
        <section
          aria-labelledby={`platform-area-${area.key}`}
          className="space-y-4"
          key={area.key}
        >
          <h2
            className="text-lg font-semibold"
            id={`platform-area-${area.key}`}
          >
            {text(area.title, locale)}
          </h2>
          {schema.groups
            .filter((group) => group.area === area.key)
            .map((group) => (
              <Card key={group.key}>
                <CardHeader>
                  <CardTitle>{text(group.title, locale)}</CardTitle>
                  <CardDescription>
                    {text(group.description, locale)}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="divide-y">
                    {group.keys.map((key) => (
                      <KeyRow
                        key={key.key}
                        onChange={() => setIntent({ key })}
                        onHistory={() => setHistory(key)}
                        onRestore={() => setIntent({ key, restore: true })}
                        option={key}
                      />
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
        </section>
      ))}
      {intent ? (
        <ChangeDialog
          intent={intent}
          onClose={() => setIntent(undefined)}
          onSaved={() => {
            setIntent(undefined);
            void load();
          }}
        />
      ) : null}
      {history ? (
        <HistoryDialog
          onClose={() => setHistory(undefined)}
          onSetAgain={(value) => {
            setHistory(undefined);
            setIntent({ key: history, value });
          }}
          option={history}
        />
      ) : null}
    </div>
  );
}

function useShow() {
  const t = useTranslations("PlatformSettings");
  const locale = useLocale();
  return (option: PlatformKey, value: unknown): string => {
    if (value === null || value === undefined || value === "")
      return t("empty");
    if (option.type === "bool") return t(value ? "on" : "off");
    if (option.type === "enum") {
      const variant = (option.values ?? []).find(
        (item) => item.value === value,
      );
      return variant ? text(variant.label, locale) : String(value);
    }
    return String(value);
  };
}

function KeyRow({
  option,
  onChange,
  onRestore,
  onHistory,
}: {
  option: PlatformKey;
  onChange: () => void;
  onRestore: () => void;
  onHistory: () => void;
}) {
  const t = useTranslations("PlatformSettings");
  const locale = useLocale();
  const show = useShow();
  const label = text(option.label, locale);
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 space-y-1">
        <p className="font-medium">{label}</p>
        {option.help ? (
          <p className="text-sm text-muted-foreground">
            {text(option.help, locale)}
          </p>
        ) : null}
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono">{show(option, option.value)}</span>
          <span className="text-muted-foreground">
            {t(`source.${option.source}`)}
          </span>
          {option.operator_level >= 2 ? (
            <Badge variant="outline">{t("levelTwo")}</Badge>
          ) : null}
          {option.scopes.includes("organization") ? (
            <Badge variant="secondary">{t("companiesChoose")}</Badge>
          ) : null}
        </p>
        {/* The product's own default stands above the platform's (ADR-078
            pkt 3): what the operator sets here reaches no company then. */}
        {option.product_value !== null ? (
          <p className="text-sm text-muted-foreground" role="note">
            {t("productShadow", {
              value: show(option, option.product_value),
            })}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        {option.can_change ? (
          <Button
            aria-label={t("changeLabel", { label })}
            onClick={onChange}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("change")}
          </Button>
        ) : null}
        {option.can_change && option.source === "platform" ? (
          <Button
            aria-label={t("restoreLabel", { label })}
            onClick={onRestore}
            size="sm"
            type="button"
            variant="ghost"
          >
            {t("restore")}
          </Button>
        ) : null}
        <Button
          aria-label={t("historyLabel", { label })}
          onClick={onHistory}
          size="sm"
          type="button"
          variant="ghost"
        >
          {t("history")}
        </Button>
      </div>
    </li>
  );
}

function valueSchema(option: PlatformKey): z.ZodType {
  if (option.type === "bool") return z.boolean();
  if (option.type === "int") {
    let number = z.number().int();
    if (option.minimum !== null) number = number.min(option.minimum);
    if (option.maximum !== null) number = number.max(option.maximum);
    return number;
  }
  return z.string();
}

type Values = { value: unknown; reason: string };

function ChangeDialog({
  intent,
  onClose,
  onSaved,
}: {
  intent: Intent;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("PlatformSettings");
  const locale = useLocale();
  const show = useShow();
  const option = intent.key;
  const stepUp = useStepUp(t("stepUpDescription"));
  const [preview, setPreview] = useState<PlatformPreview>();
  const form = useForm<Values>({
    resolver: zodResolver(
      z.object({
        value: intent.restore ? z.null() : valueSchema(option),
        reason: z.string().trim().min(1, t("reasonRequired")).max(500),
      }),
    ),
    defaultValues: {
      value: intent.restore
        ? null
        : intent.value !== undefined
          ? intent.value
          : option.value,
      reason: "",
    },
  });
  const id = `platform-${option.key}`;

  function problem(error: unknown) {
    if (!(error instanceof ApiProblemError)) {
      form.setError("root", { type: "server", message: t("saveError") });
      return;
    }
    const items = error.problem.errors ?? [];
    if (items.length === 0)
      form.setError("root", {
        type: "server",
        message:
          error.problem.code === "operator_level_required"
            ? t("levelRequired")
            : t("saveError"),
      });
    for (const item of items) {
      const field =
        item.field === "value" || item.field === "reason" ? item.field : "root";
      form.setError(field, { type: "server", message: item.message });
    }
  }

  async function check(values: Values) {
    try {
      setPreview(
        await previewPlatformSetting(option.key, {
          value: values.value,
          reason: values.reason,
        }),
      );
    } catch (error) {
      problem(error);
    }
  }

  async function save() {
    const values = form.getValues();
    const change = { value: values.value, reason: values.reason.trim() };
    try {
      await changePlatformSetting(option.key, change);
      onSaved();
    } catch (error) {
      if (!stepUp.handled(error, save)) problem(error);
    }
  }

  const { errors, isSubmitting } = form.formState;
  const label = text(option.label, locale);
  return (
    <Dialog onOpenChange={(open) => (open ? null : onClose())} open>
      <DialogContent closeLabel={t("cancel")}>
        <DialogHeader>
          <DialogTitle>
            {intent.restore ? t("restoreTitle", { label }) : label}
          </DialogTitle>
          <DialogDescription>
            {intent.restore ? t("restoreDescription") : t("changeDescription")}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          id={`${id}-form`}
          noValidate
          onSubmit={form.handleSubmit(check)}
        >
          <FieldGroup>
            {intent.restore ? null : (
              <Field data-invalid={Boolean(errors.value)}>
                {option.type === "bool" ? (
                  <Controller
                    control={form.control}
                    name="value"
                    render={({ field }) => (
                      <label className="flex min-h-11 items-center gap-3 font-medium">
                        <Switch
                          checked={field.value === true}
                          disabled={Boolean(preview)}
                          id={id}
                          onCheckedChange={(checked) => field.onChange(checked)}
                        />
                        {label}
                      </label>
                    )}
                  />
                ) : (
                  <>
                    <FieldLabel htmlFor={id}>{t("newValue")}</FieldLabel>
                    {option.type === "enum" ? (
                      <NativeSelect
                        disabled={Boolean(preview)}
                        id={id}
                        {...form.register("value")}
                      >
                        {(option.values ?? []).map((variant) => (
                          <option key={variant.value} value={variant.value}>
                            {text(variant.label, locale)}
                          </option>
                        ))}
                      </NativeSelect>
                    ) : option.type === "text" &&
                      (option.max_length ?? 0) > LONG_TEXT ? (
                      <Textarea
                        aria-invalid={Boolean(errors.value)}
                        disabled={Boolean(preview)}
                        id={id}
                        maxLength={option.max_length ?? undefined}
                        rows={3}
                        {...form.register("value")}
                      />
                    ) : (
                      <Input
                        aria-invalid={Boolean(errors.value)}
                        className="max-w-xs"
                        disabled={Boolean(preview)}
                        id={id}
                        inputMode={
                          option.type === "int" ? "numeric" : undefined
                        }
                        max={option.maximum ?? undefined}
                        maxLength={option.max_length ?? undefined}
                        min={option.minimum ?? undefined}
                        type={
                          option.type === "int"
                            ? "number"
                            : option.type === "date"
                              ? "date"
                              : "text"
                        }
                        {...form.register("value", {
                          valueAsNumber: option.type === "int",
                        })}
                      />
                    )}
                  </>
                )}
                <FieldDescription>
                  {t("now", { value: show(option, option.value) })}
                </FieldDescription>
                <FieldError
                  errors={[errors.value as { message?: string } | undefined]}
                />
              </Field>
            )}
            <Field data-invalid={Boolean(errors.reason)}>
              <FieldLabel htmlFor={`${id}-reason`}>{t("reason")}</FieldLabel>
              <Textarea
                aria-invalid={Boolean(errors.reason)}
                disabled={Boolean(preview)}
                id={`${id}-reason`}
                maxLength={500}
                rows={2}
                {...form.register("reason")}
              />
              <FieldDescription>{t("reasonHelp")}</FieldDescription>
              <FieldError errors={[errors.reason]} />
            </Field>
          </FieldGroup>
          {preview ? (
            <div
              className="space-y-1 rounded-md border p-3 text-sm"
              role="status"
            >
              <p>
                {t("previewChange", {
                  from: show(option, preview.current),
                  to: intent.restore
                    ? t("previewDefault")
                    : show(option, preview.proposed),
                })}
              </p>
              <p className="text-muted-foreground">
                {preview.product_value !== null
                  ? t("previewProduct", {
                      value: show(option, preview.product_value),
                    })
                  : preview.companies_following === null
                    ? t("previewPlatformOnly")
                    : t("previewCompanies", {
                        count: preview.companies_following,
                      })}
              </p>
            </div>
          ) : null}
          {errors.root ? (
            <p className="text-sm text-destructive" role="alert">
              {errors.root.message}
            </p>
          ) : null}
          {stepUp.ui}
        </form>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            {t("cancel")}
          </DialogClose>
          {preview ? (
            <Button onClick={() => void save()} type="button">
              {t("confirm")}
            </Button>
          ) : (
            <Button disabled={isSubmitting} form={`${id}-form`} type="submit">
              {t("check")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function HistoryDialog({
  option,
  onClose,
  onSetAgain,
}: {
  option: PlatformKey;
  onClose: () => void;
  onSetAgain: (value: unknown) => void;
}) {
  const t = useTranslations("PlatformSettings");
  const locale = useLocale();
  const format = useFormatter();
  const show = useShow();
  const [items, setItems] = useState<PlatformHistoryItem[]>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    getPlatformSettingHistory(option.key)
      .then((value) => (mounted ? setItems(value) : undefined))
      .catch(() => (mounted ? setFailed(true) : undefined));
    return () => {
      mounted = false;
    };
  }, [option.key]);

  return (
    <Dialog onOpenChange={(open) => (open ? null : onClose())} open>
      <DialogContent closeLabel={t("close")}>
        <DialogHeader>
          <DialogTitle>
            {t("historyTitle", { label: text(option.label, locale) })}
          </DialogTitle>
          <DialogDescription>{t("historyDescription")}</DialogDescription>
        </DialogHeader>
        {failed ? (
          <p className="text-sm text-destructive" role="alert">
            {t("loadError")}
          </p>
        ) : !items ? (
          <p aria-live="polite" className="text-sm text-muted-foreground">
            {t("loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>
        ) : (
          <ol className="max-h-96 space-y-3 overflow-y-auto">
            {items.map((item, index) => (
              <li className="space-y-1 text-sm" key={index}>
                <p className="font-medium">
                  {item.value === null
                    ? t("historyRestored")
                    : show(option, item.value)}
                </p>
                <p className="text-muted-foreground">
                  {format.dateTime(new Date(item.created_at), {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}{" "}
                  · {item.operator}
                </p>
                <p>{item.reason}</p>
                {option.can_change && item.value !== null && index > 0 ? (
                  <Button
                    className="h-auto p-0"
                    onClick={() => onSetAgain(item.value)}
                    type="button"
                    variant="link"
                  >
                    {t("setAgain")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ol>
        )}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            {t("close")}
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
