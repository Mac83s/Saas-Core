"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  EyeIcon,
  KeyRoundIcon,
  PawPrintIcon,
  PencilIcon,
  PhoneIcon,
  PlusIcon,
  WarehouseIcon,
} from "lucide-react";

import {
  createFarm,
  listFarms,
  redeemFarmActivationCode,
  updateFarm,
  type Farm,
} from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  DataTable,
  DataTableSearch,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
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

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { FarmForm } from "./farm-form";
import { farmProblem, farmProblemKind, type FarmProblem } from "./problem";

// Shared by both farm screens; they are each other's only neighbours, so they
// live here rather than in a file of their own.
export const focusRing =
  "rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/** Without `farms.read` nothing is fetched; the screen says so instead. */
export function FarmNoAccess() {
  const t = useTranslations("Farms");
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("noAccessTitle")}</h2>
        </CardTitle>
        <CardDescription>{t("problem_access")}</CardDescription>
      </CardHeader>
    </Card>
  );
}

/**
 * A failed read, with the one way out that fits it: retry when the call may
 * work next time, the plan when the organization has not bought the register,
 * nothing when neither would help.
 */
export function FarmNotice({
  kind,
  onRetry,
}: {
  kind: FarmProblem;
  onRetry: () => void;
}) {
  const t = useTranslations("Farms");
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-xl border border-destructive/30 p-4"
      role="alert"
    >
      <p className="text-sm text-destructive">{t(`problem_${kind}`)}</p>
      {kind === "load" ? (
        <Button onClick={onRetry} variant="outline">
          {t("retry")}
        </Button>
      ) : null}
      {kind === "plan" ? (
        <Link
          className={buttonVariants({ variant: "outline" })}
          href="/panel/settings/billing"
        >
          {t("openBilling")}
        </Link>
      ) : null}
    </div>
  );
}

/**
 * The organization's farms (ADR-051): a service company's client cards or a
 * farmer's own register. The columns are what the register knows — a farm's
 * visits live in another module and are not shown here.
 */
export function FarmsPanel({
  canManage = false,
  canRead = false,
}: {
  /** farms.manage: add and edit farms. */
  canManage?: boolean;
  /** farms.read: see the register at all. The API enforces both. */
  canRead?: boolean;
} = {}) {
  const t = useTranslations("Farms");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const [farms, setFarms] = useState<Farm[]>();
  const [search, setSearch] = useState("");
  const [problem, setProblem] = useState<FarmProblem>();
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Farm>();
  // The row's button gets focus back when the edit dialog closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [claiming, setClaiming] = useState(false);
  const [code, setCode] = useState("");
  const [claimProblem, setClaimProblem] = useState<string>();
  const [reloads, setReloads] = useState(0);
  const refresh = () => setReloads((value) => value + 1);

  // The server searches, so a big register stays on one screen. Only the
  // answer to the newest query may land: an older, slower search would
  // otherwise replace the list under a newer one.
  useEffect(() => {
    if (!canRead) return;
    let current = true;
    const timer = setTimeout(() => {
      listFarms(search.trim() || undefined)
        .then((found) => {
          if (!current) return;
          setFarms(found);
          setProblem(undefined);
        })
        .catch((error: unknown) => {
          if (current) setProblem(farmProblemKind(error));
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [canRead, reloads, search]);

  const columns: ColumnDef<Farm, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colFarm"),
      meta: { primary: true },
      cell: ({ row: { original: farm } }) => (
        <>
          <Link
            className={`font-medium wrap-anywhere hover:underline ${focusRing}`}
            href={`/panel/farms/${farm.id}`}
          >
            {farm.name}
          </Link>
          {farm.herd_number ? (
            <p className="text-xs text-muted-foreground tabular-nums">
              {farm.herd_number}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "village",
      accessorKey: "village",
      header: t("village"),
      cell: ({ row: { original: farm } }) => farm.village || "—",
    },
    {
      id: "keeper",
      accessorFn: (farm) => farm.keeper_name,
      header: t("colKeeper"),
      cell: ({ row: { original: farm } }) => (
        <>
          <p className="wrap-anywhere">{farm.keeper_name || "—"}</p>
          {farm.phone ? (
            <a
              className={`text-muted-foreground hover:text-foreground hover:underline ${focusRing}`}
              href={`tel:${farm.phone.replaceAll(" ", "")}`}
            >
              {farm.phone}
            </a>
          ) : null}
        </>
      ),
    },
    {
      id: "animals",
      accessorKey: "animal_count",
      header: t("animals"),
      meta: { className: "tabular-nums" },
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: farm } }) => (
        <RowActions
          items={[
            {
              label: t("open"),
              icon: <EyeIcon aria-hidden="true" />,
              inline: true,
              link: <Link href={`/panel/farms/${farm.id}`} />,
            },
            ...(farm.phone
              ? [
                  {
                    label: t("call", { phone: farm.phone }),
                    icon: <PhoneIcon aria-hidden="true" />,
                    inline: true,
                    link: <a href={`tel:${farm.phone.replaceAll(" ", "")}`} />,
                  },
                ]
              : []),
            {
              label: t("animalsOfFarm"),
              icon: <PawPrintIcon aria-hidden="true" />,
              link: <Link href={`/panel/animals?farm=${farm.id}`} />,
            },
            ...(canManage
              ? [
                  {
                    label: t("edit"),
                    icon: <PencilIcon aria-hidden="true" />,
                    onSelect: (trigger: HTMLElement | null) => {
                      setReturnTo(trigger);
                      setEditing(farm);
                    },
                  },
                ]
              : []),
          ]}
          label={t("actionsFor", { name: farm.name })}
        />
      ),
    },
  ];

  const list = !canRead ? (
    <FarmNoAccess />
  ) : problem && !farms ? (
    <FarmNotice kind={problem} onRetry={refresh} />
  ) : farms?.length === 0 && !search.trim() ? (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-muted/30 p-6">
      <WarehouseIcon aria-hidden="true" className="size-8 text-primary" />
      <h2 className="font-semibold">{t("emptyTitle")}</h2>
      <p className="max-w-xl text-muted-foreground">
        {t(canManage ? "empty" : "emptyReadOnly")}
      </p>
      {canManage ? (
        <Button onClick={() => setAdding(true)}>
          <PlusIcon aria-hidden="true" />
          {t("add")}
        </Button>
      ) : null}
    </div>
  ) : (
    <>
      {problem ? <FarmNotice kind={problem} onRetry={refresh} /> : null}
      <DataTable
        caption={t("tableCaption")}
        columns={columns}
        data={farms ?? []}
        getRowId={(farm) => farm.id}
        labels={{ ...labels, empty: t("noResults"), loading: t("loading") }}
        emptyAction={
          <Button onClick={() => setSearch("")} variant="outline">
            {t("clearSearch")}
          </Button>
        }
        loading={!farms}
        // The server searches, so a big register stays on one screen.
        toolbar={
          <DataTableSearch
            id="farms-search"
            label={t("search")}
            onChange={setSearch}
            value={search}
          />
        }
      />
    </>
  );

  return (
    <PanelPage
      actions={
        canRead && canManage ? (
          <>
            <Dialog onOpenChange={setClaiming} open={claiming}>
              <DialogTrigger render={<Button variant="outline" />}>
                <KeyRoundIcon aria-hidden="true" />
                {t("claim")}
              </DialogTrigger>
              <DialogContent closeLabel={common("close")}>
                <DialogHeader>
                  <DialogTitle>{t("claim")}</DialogTitle>
                  <DialogDescription>{t("claimDescription")}</DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-4"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    setClaimProblem(undefined);
                    try {
                      const taken = await redeemFarmActivationCode(code.trim());
                      setClaiming(false);
                      setCode("");
                      setNotice(
                        t("claimed", {
                          name: taken.farm.name,
                          count: taken.animals_added,
                        }),
                      );
                      refresh();
                    } catch (error) {
                      setClaimProblem(farmProblem(error, t("claimFailed")));
                    }
                  }}
                >
                  <div className="space-y-2">
                    <Label htmlFor="farm-claim-code">{t("claimCode")}</Label>
                    <Input
                      autoComplete="off"
                      id="farm-claim-code"
                      onChange={(event) => setCode(event.target.value)}
                      placeholder="ABCD-EFGH-JKLM-NPQR"
                      required
                      value={code}
                    />
                  </div>
                  {claimProblem ? (
                    <p className="text-sm text-destructive" role="alert">
                      {claimProblem}
                    </p>
                  ) : null}
                  <Button disabled={code.trim().length < 8} type="submit">
                    {t("claimSubmit")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
            <Dialog onOpenChange={setAdding} open={adding}>
              <DialogTrigger render={<Button />}>
                <PlusIcon aria-hidden="true" />
                {t("add")}
              </DialogTrigger>
              <DialogContent closeLabel={common("close")}>
                <DialogHeader>
                  <DialogTitle>{t("add")}</DialogTitle>
                  <DialogDescription>{t("addDescription")}</DialogDescription>
                </DialogHeader>
                <FarmForm
                  onSubmit={async (values) => {
                    try {
                      const farm = await createFarm(values);
                      setAdding(false);
                      setNotice(t("added", { name: farm.name }));
                      refresh();
                      return undefined;
                    } catch (error) {
                      return farmProblem(error, t("saveFailed"));
                    }
                  }}
                  submitLabel={t("add")}
                />
              </DialogContent>
            </Dialog>
          </>
        ) : null
      }
      description={t("description")}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {list}
      {editing ? (
        <Dialog
          onOpenChange={(open) => {
            if (!open) setEditing(undefined);
          }}
          open
        >
          <DialogContent
            closeLabel={common("close")}
            finalFocus={() => returnTo ?? true}
          >
            <DialogHeader>
              <DialogTitle>{t("edit")}</DialogTitle>
              <DialogDescription>{editing.name}</DialogDescription>
            </DialogHeader>
            <FarmForm
              farm={editing}
              onSubmit={async (_values, changed) => {
                try {
                  await updateFarm(editing.id, changed);
                  setEditing(undefined);
                  setNotice(t("saved"));
                  refresh();
                  return undefined;
                } catch (error) {
                  return farmProblem(error, t("saveFailed"));
                }
              }}
              submitLabel={t("save")}
            />
          </DialogContent>
        </Dialog>
      ) : null}
    </PanelPage>
  );
}
