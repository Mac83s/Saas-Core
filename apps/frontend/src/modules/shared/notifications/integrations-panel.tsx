"use client";

import {
  useCallback,
  useEffect,
  useState,
  type FormEventHandler,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { PlusIcon } from "lucide-react";
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
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";

const keySchema = z.object({ name: z.string().trim().min(2).max(100) });
const webhookSchema = z.object({
  name: z.string().trim().min(2).max(100),
  url: z.string().url().startsWith("https://"),
});

/**
 * API keys and outbound webhooks (ADR-054 lists), each added from its
 * section's header. A new secret is shown once, above both lists.
 */
export function IntegrationsPanel() {
  const t = useTranslations("Integrations");
  const labels = useDataTableLabels();
  const [keys, setKeys] = useState<IntegrationApiKey[]>();
  const [webhooks, setWebhooks] = useState<IntegrationWebhook[]>();
  const [revealedSecret, setRevealedSecret] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [adding, setAdding] = useState<"key" | "webhook" | null>(null);
  const [createProblem, setCreateProblem] = useState<string>();
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
    setCreateProblem(undefined);
    try {
      const created = await createIntegrationApiKey({
        name,
        scopes: ["notifications:read"],
      });
      setRevealedSecret(created.secret);
      keyForm.reset();
      setAdding(null);
      await load();
    } catch (error) {
      setCreateProblem(problemText(error, t("createError")));
    }
  });
  const createWebhook = webhookForm.handleSubmit(async ({ name, url }) => {
    setCreateProblem(undefined);
    try {
      const created = await createIntegrationWebhook({
        name,
        url,
        events: ["sites.site.published"],
      });
      setRevealedSecret(created.secret);
      webhookForm.reset();
      setAdding(null);
      await load();
    } catch (error) {
      setCreateProblem(problemText(error, t("createError")));
    }
  });

  const keyColumns: ColumnDef<IntegrationApiKey, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("name"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <p className="font-medium wrap-anywhere">{item.name}</p>
      ),
    },
    {
      id: "prefix",
      accessorKey: "prefix",
      header: t("colPrefix"),
      cell: ({ row: { original: item } }) => (
        <code className="text-xs text-muted-foreground">{item.prefix}…</code>
      ),
    },
    {
      id: "status",
      accessorFn: (item) => (item.revoked_at ? t("revoked") : t("active")),
      header: t("colStatus"),
      cell: ({ row: { original: item } }) => (
        <Badge variant={item.revoked_at ? "destructive" : "outline"}>
          {item.revoked_at ? t("revoked") : t("active")}
        </Badge>
      ),
    },
  ];
  const webhookColumns: ColumnDef<IntegrationWebhook, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("name"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <p className="font-medium wrap-anywhere">{item.name}</p>
      ),
    },
    {
      id: "url",
      accessorKey: "url",
      header: t("colUrl"),
      cell: ({ row: { original: item } }) => (
        <span className="text-xs text-muted-foreground wrap-anywhere">
          {item.url}
        </span>
      ),
    },
    {
      id: "secret",
      accessorKey: "secret_hint",
      header: t("secretHint"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => (
        <code className="text-xs">…{item.secret_hint}</code>
      ),
    },
  ];

  const opener = (kind: "key" | "webhook") => (open: boolean) => {
    setCreateProblem(undefined);
    setAdding(open ? kind : null);
  };

  return (
    <div className="space-y-10">
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
          className="rounded-lg border border-warning-foreground/30 bg-warning p-4 text-sm text-warning-foreground"
          role="status"
        >
          <p className="font-medium">{t("copyNow")}</p>
          <code className="mt-2 block overflow-x-auto rounded bg-background p-2">
            {revealedSecret}
          </code>
        </div>
      ) : null}
      <PanelSection
        actions={
          <CreateDialog
            description={t("apiKeysDescription")}
            label={t("newApiKey")}
            onOpenChange={opener("key")}
            onSubmit={createKey}
            open={adding === "key"}
            pending={keyForm.formState.isSubmitting}
            problem={createProblem}
          >
            <div className="space-y-2">
              <Label htmlFor="api-key-name">{t("name")}</Label>
              <Input id="api-key-name" {...keyForm.register("name")} />
            </div>
          </CreateDialog>
        }
        description={t("apiKeysDescription")}
        title={t("apiKeys")}
      >
        {keys || !problem ? (
          <DataTable
            caption={t("apiKeys")}
            columns={keyColumns}
            data={keys ?? []}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("apiKeysEmpty") }}
            loading={!keys}
          />
        ) : null}
      </PanelSection>
      <PanelSection
        actions={
          <CreateDialog
            description={t("webhooksDescription")}
            label={t("newWebhook")}
            onOpenChange={opener("webhook")}
            onSubmit={createWebhook}
            open={adding === "webhook"}
            pending={webhookForm.formState.isSubmitting}
            problem={createProblem}
          >
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
          </CreateDialog>
        }
        description={t("webhooksDescription")}
        title={t("webhooks")}
      >
        {webhooks || !problem ? (
          <DataTable
            caption={t("webhooks")}
            columns={webhookColumns}
            data={webhooks ?? []}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("webhooksEmpty") }}
            loading={!webhooks}
          />
        ) : null}
      </PanelSection>
    </div>
  );
}

/** "New …" in a section's header: its form in a dialog, the failure inside. */
function CreateDialog({
  label,
  description,
  open,
  onOpenChange,
  onSubmit,
  pending,
  problem,
  children,
}: {
  label: string;
  description: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: FormEventHandler<HTMLFormElement>;
  pending: boolean;
  problem?: string;
  children: ReactNode;
}) {
  const t = useTranslations("Integrations");
  const common = useTranslations("Common");
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogTrigger render={<Button variant="outline" />}>
        <PlusIcon aria-hidden="true" />
        {label}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={onSubmit}>
          {children}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <Button disabled={pending} type="submit">
            {t("create")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function problemText(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError &&
    typeof error.problem.detail === "string"
    ? error.problem.detail
    : fallback;
}
