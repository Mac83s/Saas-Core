"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
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
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";

const schema = z.object({
  locale: z.enum(["pl", "en"]),
  marketing_enabled: z.boolean(),
});
type Values = z.infer<typeof schema>;

export function NotificationsPanel() {
  const t = useTranslations("Notifications");
  const [templates, setTemplates] = useState<NotificationTemplateCatalog>();
  const [preview, setPreview] = useState<NotificationTemplatePreview>();
  const [problem, setProblem] = useState<string>();
  const [saved, setSaved] = useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { locale: "pl", marketing_enabled: false },
  });

  useEffect(() => {
    let mounted = true;
    void Promise.all([getNotificationPreferences(), getNotificationTemplates()])
      .then(([preferences, catalog]) => {
        if (!mounted) return;
        form.reset(preferences);
        setTemplates(catalog);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(problemText(error, t("loadError")));
      });
    return () => {
      mounted = false;
    };
  }, [form, t]);

  const save = form.handleSubmit(async (values) => {
    setProblem(undefined);
    setSaved(false);
    try {
      form.reset(await updateNotificationPreferences(values));
      setSaved(true);
    } catch (error) {
      setProblem(problemText(error, t("saveError")));
    }
  });

  const showPreview = async (key: string, version: number) => {
    setProblem(undefined);
    try {
      setPreview(
        await previewNotificationTemplate({
          key,
          version,
          locale: form.getValues("locale"),
          context: { display_name: "Alex", message: t("previewMessage") },
        }),
      );
    } catch (error) {
      setProblem(problemText(error, t("previewError")));
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t("preferencesTitle")}</CardTitle>
          <CardDescription>{t("preferencesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={save}>
            <div className="space-y-2">
              <Label htmlFor="notification-locale">{t("locale")}</Label>
              <NativeSelect
                id="notification-locale"
                {...form.register("locale")}
              >
                <option value="pl">Polski</option>
                <option value="en">English</option>
              </NativeSelect>
            </div>
            <label className="flex items-start gap-3 rounded-lg border p-4 text-sm">
              <input
                className="mt-0.5 size-4 accent-primary"
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
            <p className="text-sm text-muted-foreground">{t("requiredHelp")}</p>
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            {saved ? (
              <p className="text-sm text-emerald-700" role="status">
                {t("saved")}
              </p>
            ) : null}
            <Button disabled={form.formState.isSubmitting} type="submit">
              {t("save")}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("templatesTitle")}</CardTitle>
          <CardDescription>{t("templatesDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {templates?.items.map((item) => (
            <div
              className="flex items-center justify-between gap-3 rounded-lg border p-3"
              key={`${item.key}:${item.version}`}
            >
              <div>
                <p className="font-mono text-sm">
                  {item.key} v{item.version}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t(
                    item.category === "marketing"
                      ? "marketingCategory"
                      : "requiredCategory",
                  )}
                </p>
              </div>
              <Button
                onClick={() => void showPreview(item.key, item.version)}
                size="sm"
                variant="outline"
              >
                {t("preview")}
              </Button>
            </div>
          ))}
          {preview ? (
            <section
              className="rounded-lg border bg-muted/30 p-4"
              aria-live="polite"
            >
              <h3 className="font-medium">{preview.subject}</h3>
              <div
                className="mt-2 text-sm text-muted-foreground"
                dangerouslySetInnerHTML={{ __html: preview.html_body }}
              />
            </section>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError &&
    typeof error.problem.detail === "string"
    ? error.problem.detail
    : fallback;
}
