"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { CircleAlertIcon, RefreshCwIcon } from "lucide-react";
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
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@saas-core/ui/components/sheet";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { PlanGate } from "#components/panel/plan-gate";
import { useMedia } from "#lib/use-media";
import { useDataTableLabels } from "#lib/data-table-labels";
import { SiteInquiries } from "../sites/site-inquiries";

const schema = z.object({
  locale: z.enum(["pl", "en"]),
  marketing_enabled: z.boolean(),
});
type Values = z.infer<typeof schema>;
type Language = Values["locale"];
type Template = NotificationTemplateCatalog["items"][number];

const LANGUAGES: Record<Language, string> = { pl: "Polski", en: "English" };

// A template's name, use and variables come from the messages, which a product
// extends with its own (UX-048): never the raw key on screen.

/** Example dates, written in the preview's own language. */
const SAMPLE_DATES: Record<string, [Date, Intl.DateTimeFormatOptions]> = {
  starts_at: [
    new Date(2026, 9, 9, 10, 0),
    {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    },
  ],
  previous_starts_at: [
    new Date(2026, 9, 8, 14, 0),
    {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    },
  ],
  ends_at: [
    new Date(2026, 9, 31),
    { day: "numeric", month: "long", year: "numeric" },
  ],
};

type Preview = NotificationTemplatePreview & { samples: string[] };

/** Example values in the preview's own language, marked where they land. */
function sampleContext(
  template: Template,
  sample: (field: string) => string,
): Record<string, string> {
  return Object.fromEntries(
    template.context_fields.map((field) => [field, sample(field)]),
  );
}

function escapeHtml(text: string) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

/** The API's HTML with every example value marked, outside tags only: a
 *  link's address stays an address. */
export function markSamples(html: string, values: readonly string[]) {
  const escaped = values
    .filter((value) => value.length > 2)
    .map(escapeHtml)
    .sort((a, b) => b.length - a.length);
  if (!escaped.length) return html;
  const pattern = new RegExp(
    escaped
      .map((value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|"),
    "g",
  );
  return html
    .split(/(<[^>]*>)/)
    .map((part) =>
      part.startsWith("<")
        ? part
        : part.replace(
            pattern,
            (value) =>
              `<mark class="rounded-sm bg-primary/15 px-0.5 text-foreground">${value}</mark>`,
          ),
    )
    .join("");
}

/**
 * Messages: website inquiries, and what goes out automatically (templates with
 * their variables and a preview) and what the person receives. Each is a page
 * of its own (ADR-057); a person with the right to one only gets that one.
 * Sent-message history and reminder timing have no API yet, so they are not
 * shown.
 */
export function NotificationsPanel({
  canManageBilling = false,
  canReadSiteInquiries = false,
  canManageNotifications = true,
  section,
  titleId,
}: {
  /** The owner is offered the plans when messages are not in the plan. */
  canManageBilling?: boolean;
  canReadSiteInquiries?: boolean;
  canManageNotifications?: boolean;
  /** Which page; without it, the inquiries when allowed. */
  section?: "inquiries" | "automation";
  /** The page's title, which names the inquiries instead of their own. */
  titleId?: string;
}) {
  const notifications = canManageNotifications ? (
    <div className="space-y-8">
      <TemplatesSection canManageBilling={canManageBilling} />
      <PreferencesSection />
    </div>
  ) : null;
  if (section === "automation" || !canReadSiteInquiries) return notifications;
  return <SiteInquiries labelledBy={titleId} />;
}

function TemplatesSection({ canManageBilling }: { canManageBilling: boolean }) {
  const t = useTranslations("Notifications");
  const labels = useDataTableLabels();
  const uiLocale = useLocale();
  const [items, setItems] = useState<Template[]>();
  const [failure, setFailure] = useState<"plan" | "permission" | "error">();
  const [selected, setSelected] = useState<{
    template: Template;
    language: Language;
  }>();
  const [preview, setPreview] = useState<Preview | "loading" | "error">();
  const narrow = useMedia("(max-width: 1023px)");
  const [sheetOpen, setSheetOpen] = useState(false);
  const samples = useTranslations("Notifications.samples");
  // Only the answer to the latest click is shown, whatever order they arrive in.
  const latest = useRef(0);

  const show = useCallback(
    async (template: Template, language: Language) => {
      const request = ++latest.current;
      setSelected({ template, language });
      setPreview("loading");
      const context = sampleContext(template, (field) => {
        const date = SAMPLE_DATES[field];
        if (date)
          return new Intl.DateTimeFormat(language, date[1]).format(date[0]);
        return samples.has(field) ? samples(field) : `{${field}}`;
      });
      try {
        const result = await previewNotificationTemplate({
          key: template.key,
          version: template.version,
          locale: language,
          // Example values in the preview's language, marked in the result,
          // instead of bare {organization_name} (UX-048).
          context,
        });
        if (request === latest.current)
          setPreview({ ...result, samples: Object.values(context) });
      } catch {
        if (request === latest.current) setPreview("error");
      }
    },
    [samples],
  );

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

  // The name selects the template for the detail beside the list; the row
  // it is in says so in words, not only in colour.
  const columns: ColumnDef<Template, unknown>[] = [
    {
      id: "template",
      accessorFn: (item) => templateName(item.key, t),
      header: t("colTemplate"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-2">
            <button
              aria-pressed={selected?.template === item}
              className="rounded-sm text-left font-medium wrap-anywhere outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 aria-pressed:text-primary"
              onClick={() => {
                void show(
                  item,
                  languageFor(item, selected?.language ?? uiLocale),
                );
                if (narrow) setSheetOpen(true);
              }}
              type="button"
            >
              {templateName(item.key, t)}
            </button>
            {selected?.template === item ? (
              <Badge>{t("previewing")}</Badge>
            ) : null}
          </p>
          <p className="text-xs text-muted-foreground">
            {item.locales.map((code) => code.toUpperCase()).join(" · ")}
          </p>
        </div>
      ),
    },
    {
      id: "category",
      accessorFn: (item) =>
        t(
          item.category === "marketing"
            ? "marketingCategory"
            : "requiredCategory",
        ),
      header: t("colCategory"),
      cell: ({ row: { original: item } }) => (
        <Badge
          variant={item.category === "marketing" ? "outline" : "secondary"}
        >
          {t(
            item.category === "marketing"
              ? "marketingCategory"
              : "requiredCategory",
          )}
        </Badge>
      ),
    },
  ];

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
        <PlanGate
          action={
            canManageBilling
              ? {
                  href: "/panel/settings/billing?feature=notifications.enabled",
                  label: t("planGateAction"),
                }
              : undefined
          }
          title={t("planGateTitle")}
        >
          {t(canManageBilling ? "planGateOwner" : "planGateMember")}
        </PlanGate>
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
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <DataTable
            caption={t("templatesTitle")}
            columns={columns}
            data={items}
            getRowId={(item) => `${item.key}:${item.version}`}
            labels={labels}
          />
          {selected && !narrow ? (
            <TemplateDetail
              language={selected.language}
              onLanguage={(language) => void show(selected.template, language)}
              preview={preview}
              template={selected.template}
            />
          ) : null}
        </div>
      )}
      {/* Below two columns the preview opens over the list, not 1700 px
          under it (UX-049). */}
      {narrow ? (
        <Sheet
          onOpenChange={setSheetOpen}
          open={sheetOpen && Boolean(selected)}
        >
          <SheetContent closeLabel={t("close")}>
            <SheetHeader className="sr-only">
              <SheetTitle>
                {selected ? templateName(selected.template.key, t) : ""}
              </SheetTitle>
            </SheetHeader>
            <SheetBody>
              {selected ? (
                <TemplateDetail
                  language={selected.language}
                  onLanguage={(language) =>
                    void show(selected.template, language)
                  }
                  preview={preview}
                  template={selected.template}
                />
              ) : null}
            </SheetBody>
          </SheetContent>
        </Sheet>
      ) : null}
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
  preview: Preview | "loading" | "error" | undefined;
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
        {t.has(`templateUse.${slug(template.key)}`) ? (
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
                    {t.has(`variables.${field}`)
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
                <p
                  className="font-medium"
                  dangerouslySetInnerHTML={{
                    __html: markSamples(
                      escapeHtml(preview.subject),
                      preview.samples,
                    ),
                  }}
                  lang={language}
                />
                {/* Rendered by the API from a fixed template, with every value
                    escaped; only <mark> around our own examples is added, and
                    a link looks like one (UX-048). */}
                <div
                  className="mt-3 space-y-2 border-t pt-3 text-sm [&_a]:font-medium [&_a]:text-primary [&_a]:underline"
                  dangerouslySetInnerHTML={{
                    __html: markSamples(preview.html_body, preview.samples),
                  }}
                  lang={language}
                />
                <p className="mt-3 text-xs text-muted-foreground">
                  {t("samplesNote")}
                </p>
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

const unnamed = new Set<string>();

/** Core's names and a product's own; a template nobody named says so in
 *  words, and once in the console, instead of showing its key. */
function templateName(key: string, t: Translator) {
  if (t.has(`templateNames.${slug(key)}`))
    return t(`templateNames.${slug(key)}`);
  if (!unnamed.has(key)) {
    unnamed.add(key);
    console.warn(`Notification template without a name: ${key}`);
  }
  return t("unnamedTemplate");
}

/** The language asked for when the template has it, else Polish, else English. */
function languageFor(template: Template, wanted: string): Language {
  if (wanted === "pl" || wanted === "en")
    if (template.locales.includes(wanted)) return wanted;
  return template.locales.includes("pl") ? "pl" : "en";
}
