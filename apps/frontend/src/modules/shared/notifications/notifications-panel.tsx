"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { CircleAlertIcon, LockKeyholeIcon, RefreshCwIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  getNotificationPreferences,
  getNotificationTemplates,
  previewNotificationTemplate,
  updateNotificationPreferences,
  type NotificationTemplateCatalog,
  type NotificationTemplatePreview,
} from "@saas-core/api-client";
import { Link } from "#i18n/navigation";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";
import { SiteInquiries } from "../sites/site-inquiries";

const schema = z.object({
  locale: z.enum(["pl", "en"]),
  marketing_enabled: z.boolean(),
});
type Values = z.infer<typeof schema>;
type Language = Values["locale"];
type Template = NotificationTemplateCatalog["items"][number];

const LANGUAGES: Record<Language, string> = { pl: "Polski", en: "English" };

// Core's templates and their variables have names for people; a product's own
// template shows its key until it brings a name.
const NAMED_TEMPLATES = new Set([
  "booking.confirmation",
  "booking.reminder",
  "system.activity",
  "billing.trial_ending",
  "billing.grace_ending",
  "product.update",
]);
const NAMED_VARIABLES = new Set([
  "organization_name",
  "starts_at",
  "display_name",
  "message",
  "plan_name",
  "ends_at",
]);

/**
 * Messages: what goes out automatically (templates with their variables and a
 * preview) and what the person receives. Sent-message history and reminder
 * timing have no API yet, so they are not shown.
 */
export function NotificationsPanel({
  canManageBilling = false,
  canReadSiteInquiries = false,
  canManageNotifications = true,
}: {
  /** The owner is offered the plans when messages are not in the plan. */
  canManageBilling?: boolean;
  canReadSiteInquiries?: boolean;
  canManageNotifications?: boolean;
}) {
  const t = useTranslations("Notifications");
  const notifications = canManageNotifications ? (
    <div className="space-y-8">
      <TemplatesSection canManageBilling={canManageBilling} />
      <PreferencesSection />
    </div>
  ) : null;
  if (!canReadSiteInquiries) return notifications;
  if (!canManageNotifications) return <SiteInquiries />;
  return (
    <Tabs defaultValue="inquiries">
      <TabsList aria-label={t("sectionsLabel")}>
        <TabsTab value="inquiries">{t("inquiriesTab")}</TabsTab>
        <TabsTab value="notifications">{t("automationTab")}</TabsTab>
        <TabsIndicator />
      </TabsList>
      <TabsPanel value="inquiries">
        <SiteInquiries />
      </TabsPanel>
      <TabsPanel value="notifications">{notifications}</TabsPanel>
    </Tabs>
  );
}

function TemplatesSection({ canManageBilling }: { canManageBilling: boolean }) {
  const t = useTranslations("Notifications");
  const uiLocale = useLocale();
  const [items, setItems] = useState<Template[]>();
  const [failure, setFailure] = useState<"plan" | "permission" | "error">();
  const [selected, setSelected] = useState<{
    template: Template;
    language: Language;
  }>();
  const [preview, setPreview] = useState<
    NotificationTemplatePreview | "loading" | "error"
  >();
  // Only the answer to the latest click is shown, whatever order they arrive in.
  const latest = useRef(0);

  const show = useCallback(async (template: Template, language: Language) => {
    const request = ++latest.current;
    setSelected({ template, language });
    setPreview("loading");
    try {
      const result = await previewNotificationTemplate({
        key: template.key,
        version: template.version,
        locale: language,
        // Each variable stands in for itself, so the preview shows where the
        // real value lands rather than made-up data.
        context: Object.fromEntries(
          template.context_fields.map((field) => [field, `{${field}}`]),
        ),
      });
      if (request === latest.current) setPreview(result);
    } catch {
      if (request === latest.current) setPreview("error");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const catalog = await getNotificationTemplates();
      setItems(catalog.items);
      const first = catalog.items[0];
      if (first) void show(first, languageFor(first, uiLocale));
    } catch (error) {
      const code =
        error instanceof ApiProblemError ? error.problem.code : undefined;
      setFailure(
        code === "entitlement_required"
          ? "plan"
          : code === "organization_permission_denied"
            ? "permission"
            : "error",
      );
    }
  }, [show, uiLocale]);

  useEffect(() => {
    // The loader only updates state after its awaited request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  return (
    <section aria-labelledby="templates-heading" className="space-y-4">
      <div className="max-w-3xl space-y-1">
        <h2
          className="text-xl font-semibold tracking-tight"
          id="templates-heading"
        >
          {t("templatesTitle")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t("templatesDescription")}
        </p>
      </div>

      {failure === "plan" ? (
        <div className="flex flex-wrap items-start gap-3 rounded-lg border border-warning-foreground/25 bg-warning p-4 text-sm">
          <LockKeyholeIcon
            aria-hidden="true"
            className="mt-0.5 size-5 shrink-0 text-warning-foreground"
          />
          <div className="min-w-0 flex-1 basis-56 space-y-1">
            <p className="font-medium">{t("planGateTitle")}</p>
            <p className="text-muted-foreground">
              {t(canManageBilling ? "planGateOwner" : "planGateMember")}
            </p>
          </div>
          {canManageBilling ? (
            <Link
              className={buttonVariants()}
              href="/panel/settings/billing?feature=notifications.enabled"
            >
              {t("planGateAction")}
            </Link>
          ) : null}
        </div>
      ) : failure === "permission" ? (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          {t("noPermission")}
        </p>
      ) : failure === "error" ? (
        <LoadError
          message={t("templatesLoadError")}
          onRetry={() => {
            setFailure(undefined);
            void load();
          }}
          retry={t("retry")}
        />
      ) : !items ? (
        <div
          aria-busy="true"
          aria-label={t("loading")}
          className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]"
        >
          <div className="h-64 animate-pulse rounded-xl bg-muted" />
          <div className="h-64 animate-pulse rounded-xl bg-muted" />
        </div>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t("templatesEmpty")}
        </p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
          <ul className="space-y-2">
            {items.map((item) => (
              <li key={`${item.key}:${item.version}`}>
                <button
                  aria-pressed={selected?.template === item}
                  className="flex min-h-11 w-full flex-col items-start gap-1.5 rounded-lg border bg-background px-4 py-3 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-pressed:border-primary aria-pressed:ring-1 aria-pressed:ring-primary"
                  onClick={() =>
                    void show(
                      item,
                      languageFor(item, selected?.language ?? uiLocale),
                    )
                  }
                  type="button"
                >
                  <span className="font-medium">
                    {templateName(item.key, t)}
                  </span>
                  <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge
                      variant={
                        item.category === "marketing" ? "outline" : "secondary"
                      }
                    >
                      {t(
                        item.category === "marketing"
                          ? "marketingCategory"
                          : "requiredCategory",
                      )}
                    </Badge>
                    {item.locales.map((code) => code.toUpperCase()).join(" · ")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {selected ? (
            <TemplateDetail
              language={selected.language}
              onLanguage={(language) => void show(selected.template, language)}
              preview={preview}
              template={selected.template}
            />
          ) : null}
        </div>
      )}
    </section>
  );
}

function TemplateDetail({
  template,
  language,
  preview,
  onLanguage,
}: {
  template: Template;
  language: Language;
  preview: NotificationTemplatePreview | "loading" | "error" | undefined;
  onLanguage: (language: Language) => void;
}) {
  const t = useTranslations("Notifications");
  const languages = (["pl", "en"] as const).filter((code) =>
    template.locales.includes(code),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg font-semibold">
          <h3>{templateName(template.key, t)}</h3>
        </CardTitle>
        {NAMED_TEMPLATES.has(template.key) ? (
          <CardDescription>
            {t(`templateUse.${slug(template.key)}`)}
          </CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-6">
        {template.context_fields.length > 0 ? (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">{t("variablesTitle")}</h4>
            <dl className="grid gap-2 sm:grid-cols-2">
              {template.context_fields.map((field) => (
                <div
                  className="rounded-lg bg-background px-3 py-2 ring-1 ring-border"
                  key={field}
                >
                  <dt>
                    <code className="font-mono text-xs">{`{${field}}`}</code>
                  </dt>
                  <dd>
                    {NAMED_VARIABLES.has(field)
                      ? t(`variables.${field}`)
                      : field}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="text-xs text-muted-foreground">
              {t("variablesHelp")}
            </p>
          </div>
        ) : null}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-medium">{t("previewTitle")}</h4>
            {languages.length > 1 ? (
              <div
                aria-label={t("previewLanguage")}
                className="flex gap-1"
                role="group"
              >
                {languages.map((code) => (
                  <Button
                    aria-pressed={code === language}
                    key={code}
                    onClick={() => onLanguage(code)}
                    type="button"
                    variant={code === language ? "secondary" : "ghost"}
                  >
                    {LANGUAGES[code]}
                  </Button>
                ))}
              </div>
            ) : null}
          </div>
          <div
            aria-busy={preview === "loading"}
            aria-live="polite"
            className="rounded-lg bg-background p-4 ring-1 ring-border"
          >
            {preview === "error" ? (
              <p className="text-sm text-destructive" role="alert">
                {t("previewError")}
              </p>
            ) : preview && preview !== "loading" ? (
              <>
                <p className="text-xs text-muted-foreground">{t("subject")}</p>
                <p className="font-medium" lang={language}>
                  {preview.subject}
                </p>
                {/* Rendered by the API from a fixed template, with every value
                    escaped; no text typed here reaches it unescaped. */}
                <div
                  className="mt-3 space-y-2 border-t pt-3 text-sm"
                  dangerouslySetInnerHTML={{ __html: preview.html_body }}
                  lang={language}
                />
              </>
            ) : (
              <div className="space-y-2">
                <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
                <div className="h-16 animate-pulse rounded bg-muted" />
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function PreferencesSection() {
  const t = useTranslations("Notifications");
  const [state, setState] = useState<"loading" | "ready" | "error" | "hidden">(
    "loading",
  );
  const [problem, setProblem] = useState<string>();
  const [saved, setSaved] = useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { locale: "pl", marketing_enabled: false },
  });

  const load = useCallback(async () => {
    try {
      form.reset(await getNotificationPreferences());
      setState("ready");
    } catch (error) {
      // Without messages in the plan the templates above already say so.
      setState(
        error instanceof ApiProblemError &&
          error.problem.code === "entitlement_required"
          ? "hidden"
          : "error",
      );
    }
  }, [form]);

  useEffect(() => {
    // The loader only updates state after its awaited request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const save = form.handleSubmit(async (values) => {
    setProblem(undefined);
    setSaved(false);
    try {
      form.reset(await updateNotificationPreferences(values));
      setSaved(true);
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          typeof error.problem.detail === "string"
          ? error.problem.detail
          : t("saveError"),
      );
    }
  });

  if (state === "hidden") return null;
  return (
    <section aria-labelledby="preferences-heading">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 id="preferences-heading">{t("preferencesTitle")}</h2>
          </CardTitle>
          <CardDescription>{t("preferencesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {state === "loading" ? (
            <div
              aria-busy="true"
              aria-label={t("loading")}
              className="h-40 max-w-xl animate-pulse rounded-lg bg-muted"
            />
          ) : state === "error" ? (
            <LoadError
              message={t("loadError")}
              onRetry={() => {
                setState("loading");
                void load();
              }}
              retry={t("retry")}
            />
          ) : (
            <form className="max-w-xl space-y-5" onSubmit={save}>
              <div className="space-y-2">
                <Label htmlFor="notification-locale">{t("locale")}</Label>
                <NativeSelect
                  id="notification-locale"
                  {...form.register("locale")}
                >
                  <option value="pl">{LANGUAGES.pl}</option>
                  <option value="en">{LANGUAGES.en}</option>
                </NativeSelect>
              </div>
              <label className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border bg-background p-4 text-sm">
                <input
                  className="mt-0.5 size-5 shrink-0 accent-primary"
                  type="checkbox"
                  {...form.register("marketing_enabled")}
                />
                <span>
                  <span className="block font-medium">{t("marketing")}</span>
                  <span className="text-muted-foreground">
                    {t("marketingHelp")}
                  </span>
                </span>
              </label>
              <p className="text-sm text-muted-foreground">
                {t("requiredHelp")}
              </p>
              {problem ? (
                <p className="text-sm text-destructive" role="alert">
                  {problem}
                </p>
              ) : null}
              {saved ? (
                <p className="text-sm text-success-foreground" role="status">
                  {t("saved")}
                </p>
              ) : null}
              <Button disabled={form.formState.isSubmitting} type="submit">
                {t("save")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function LoadError({
  message,
  retry,
  onRetry,
}: {
  message: string;
  retry: string;
  onRetry: () => void;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm"
      role="alert"
    >
      <CircleAlertIcon
        aria-hidden="true"
        className="size-5 shrink-0 text-destructive"
      />
      <p className="min-w-0 flex-1 basis-56">{message}</p>
      <Button onClick={onRetry} type="button" variant="outline">
        <RefreshCwIcon aria-hidden="true" />
        {retry}
      </Button>
    </div>
  );
}

type Translator = ReturnType<typeof useTranslations<"Notifications">>;

function slug(key: string) {
  return key.replaceAll(".", "_");
}

function templateName(key: string, t: Translator) {
  return NAMED_TEMPLATES.has(key) ? t(`templateNames.${slug(key)}`) : key;
}

/** The language asked for when the template has it, else Polish, else English. */
function languageFor(template: Template, wanted: string): Language {
  if (wanted === "pl" || wanted === "en")
    if (template.locales.includes(wanted)) return wanted;
  return template.locales.includes("pl") ? "pl" : "en";
}
