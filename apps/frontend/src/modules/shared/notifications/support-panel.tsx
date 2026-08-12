"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  getNotificationSupportHealth,
  retryNotificationMessage,
  type NotificationSupportHealth,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";
import { Textarea } from "@saas-core/ui/components/textarea";

const schema = z.object({
  messageId: z.string().uuid(),
  reason: z.string().trim().min(3).max(500),
});

export function NotificationSupportPanel() {
  const t = useTranslations("NotificationSupport");
  const [health, setHealth] = useState<NotificationSupportHealth>();
  const [problem, setProblem] = useState<string>();
  const [result, setResult] = useState<string>();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { messageId: "", reason: "" },
  });
  const load = useCallback(async () => {
    try {
      setHealth(await getNotificationSupportHealth());
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
  const retry = form.handleSubmit(async ({ messageId, reason }) => {
    try {
      const message = await retryNotificationMessage(messageId, reason);
      setResult(`${message.id}: ${message.status}`);
      form.reset();
      await load();
    } catch (error) {
      setProblem(problemText(error, t("retryError")));
    }
  });
  return (
    <div className="space-y-6">
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {health
          ? Object.entries(health).map(([key, value]) => (
              <Card key={key}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{t(key)}</CardTitle>
                </CardHeader>
                <CardContent className="text-2xl font-semibold">
                  {value}
                </CardContent>
              </Card>
            ))
          : null}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("retryTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={retry}>
            <div className="space-y-2">
              <Label htmlFor="retry-message-id">{t("messageId")}</Label>
              <Input id="retry-message-id" {...form.register("messageId")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="retry-reason">{t("reason")}</Label>
              <Textarea id="retry-reason" {...form.register("reason")} />
            </div>
            <p className="text-sm text-muted-foreground">{t("mfaHelp")}</p>
            <Button disabled={form.formState.isSubmitting} type="submit">
              {t("retry")}
            </Button>
            {result ? (
              <p className="text-sm text-emerald-700" role="status">
                {result}
              </p>
            ) : null}
          </form>
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
