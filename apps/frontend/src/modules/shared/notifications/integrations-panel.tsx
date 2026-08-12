"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  createIntegrationApiKey,
  createIntegrationWebhook,
  listIntegrationApiKeys,
  listIntegrationWebhooks,
  type IntegrationApiKey,
  type IntegrationWebhook,
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

const keySchema = z.object({ name: z.string().trim().min(2).max(100) });
const webhookSchema = z.object({
  name: z.string().trim().min(2).max(100),
  url: z.string().url().startsWith("https://"),
});

export function IntegrationsPanel() {
  const t = useTranslations("Integrations");
  const [keys, setKeys] = useState<IntegrationApiKey[]>([]);
  const [webhooks, setWebhooks] = useState<IntegrationWebhook[]>([]);
  const [revealedSecret, setRevealedSecret] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const keyForm = useForm<z.infer<typeof keySchema>>({
    resolver: zodResolver(keySchema),
    defaultValues: { name: "" },
  });
  const webhookForm = useForm<z.infer<typeof webhookSchema>>({
    resolver: zodResolver(webhookSchema),
    defaultValues: { name: "", url: "" },
  });

  const load = useCallback(async () => {
    try {
      const [nextKeys, nextWebhooks] = await Promise.all([
        listIntegrationApiKeys(),
        listIntegrationWebhooks(),
      ]);
      setKeys(nextKeys);
      setWebhooks(nextWebhooks);
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

  const createKey = keyForm.handleSubmit(async ({ name }) => {
    try {
      const created = await createIntegrationApiKey({
        name,
        scopes: ["notifications:read"],
      });
      setRevealedSecret(created.secret);
      keyForm.reset();
      await load();
    } catch (error) {
      setProblem(problemText(error, t("createError")));
    }
  });
  const createWebhook = webhookForm.handleSubmit(async ({ name, url }) => {
    try {
      const created = await createIntegrationWebhook({
        name,
        url,
        events: ["sites.site.published"],
      });
      setRevealedSecret(created.secret);
      webhookForm.reset();
      await load();
    } catch (error) {
      setProblem(problemText(error, t("createError")));
    }
  });

  return (
    <div className="space-y-6">
      {problem ? (
        <p
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </p>
      ) : null}
      {revealedSecret ? (
        <div
          className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
          role="status"
        >
          <p className="font-medium">{t("copyNow")}</p>
          <code className="mt-2 block overflow-x-auto rounded bg-background p-2">
            {revealedSecret}
          </code>
        </div>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("apiKeys")}</CardTitle>
            <CardDescription>{t("apiKeysDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <form className="flex gap-2" onSubmit={createKey}>
              <div className="flex-1 space-y-2">
                <Label htmlFor="api-key-name">{t("name")}</Label>
                <Input id="api-key-name" {...keyForm.register("name")} />
              </div>
              <Button
                className="self-end"
                disabled={keyForm.formState.isSubmitting}
                type="submit"
              >
                {t("create")}
              </Button>
            </form>
            {keys.map((item) => (
              <div
                className="flex items-center justify-between rounded-lg border p-3"
                key={item.id}
              >
                <div>
                  <p className="font-medium">{item.name}</p>
                  <code className="text-xs text-muted-foreground">
                    {item.prefix}…
                  </code>
                </div>
                <Badge variant={item.revoked_at ? "destructive" : "outline"}>
                  {item.revoked_at ? t("revoked") : t("active")}
                </Badge>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("webhooks")}</CardTitle>
            <CardDescription>{t("webhooksDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <form className="space-y-3" onSubmit={createWebhook}>
              <div className="space-y-2">
                <Label htmlFor="webhook-name">{t("name")}</Label>
                <Input id="webhook-name" {...webhookForm.register("name")} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="webhook-url">URL HTTPS</Label>
                <Input
                  id="webhook-url"
                  placeholder="https://example.com/hooks"
                  {...webhookForm.register("url")}
                />
              </div>
              <Button
                disabled={webhookForm.formState.isSubmitting}
                type="submit"
              >
                {t("create")}
              </Button>
            </form>
            {webhooks.map((item) => (
              <div className="rounded-lg border p-3" key={item.id}>
                <p className="font-medium">{item.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {item.url}
                </p>
                <p className="mt-1 text-xs">
                  {t("secretHint")}: …{item.secret_hint}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError &&
    typeof error.problem.detail === "string"
    ? error.problem.detail
    : fallback;
}
