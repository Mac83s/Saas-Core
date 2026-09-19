"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { PlusIcon, WarehouseIcon } from "lucide-react";

import { createFarm, listFarms, type Farm } from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
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

import { Link } from "#i18n/navigation";
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
  const [farms, setFarms] = useState<Farm[]>();
  const [search, setSearch] = useState("");
  const [problem, setProblem] = useState<FarmProblem>();
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState(false);
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

  const list = !canRead ? (
    <FarmNoAccess />
  ) : (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("listTitle", { count: farms?.length ?? 0 })}</h2>
        </CardTitle>
        <CardDescription>{t("listDescription")}</CardDescription>
        <div className="grid gap-1.5 pt-2 sm:max-w-md">
          <Label htmlFor="farms-search">{t("search")}</Label>
          <Input
            id="farms-search"
            onChange={(event) => setSearch(event.target.value)}
            type="search"
            value={search}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && !farms ? (
          <FarmNotice kind={problem} onRetry={refresh} />
        ) : !farms ? (
          <div aria-busy="true" className="space-y-2">
            <span className="sr-only">{t("loading")}</span>
            {[0, 1, 2].map((row) => (
              <div
                className="h-14 animate-pulse rounded-lg bg-muted"
                key={row}
              />
            ))}
          </div>
        ) : (
          <>
            {problem ? <FarmNotice kind={problem} onRetry={refresh} /> : null}
            {farms.length === 0 && search.trim() ? (
              <div className="space-y-3">
                <p className="text-muted-foreground">{t("noResults")}</p>
                <Button onClick={() => setSearch("")} variant="outline">
                  {t("clearSearch")}
                </Button>
              </div>
            ) : farms.length === 0 ? (
              <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed bg-muted/30 p-6">
                <WarehouseIcon
                  aria-hidden="true"
                  className="size-8 text-primary"
                />
                <h3 className="font-semibold">{t("emptyTitle")}</h3>
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
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">{t("tableCaption")}</caption>
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3 font-medium" scope="col">
                        {t("colFarm")}
                      </th>
                      <th
                        className="hidden py-2 pr-3 font-medium md:table-cell"
                        scope="col"
                      >
                        {t("village")}
                      </th>
                      <th className="py-2 pr-3 font-medium" scope="col">
                        {t("colKeeper")}
                      </th>
                      <th className="py-2 text-right font-medium" scope="col">
                        {t("animals")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {farms.map((farm) => (
                      <tr key={farm.id}>
                        <th
                          className="py-3 pr-3 text-left align-top font-normal"
                          scope="row"
                        >
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
                          {farm.village ? (
                            <p className="text-muted-foreground md:hidden">
                              {farm.village}
                            </p>
                          ) : null}
                        </th>
                        <td className="hidden py-3 pr-3 align-top md:table-cell">
                          {farm.village || "—"}
                        </td>
                        <td className="py-3 pr-3 align-top">
                          <p className="wrap-anywhere">
                            {farm.keeper_name || "—"}
                          </p>
                          {farm.phone ? (
                            <a
                              className={`text-muted-foreground hover:text-foreground hover:underline ${focusRing}`}
                              href={`tel:${farm.phone.replaceAll(" ", "")}`}
                            >
                              {farm.phone}
                            </a>
                          ) : null}
                        </td>
                        <td className="py-3 text-right align-top tabular-nums">
                          {farm.animal_count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        <p aria-live="polite" className="text-sm text-success-foreground">
          {notice}
        </p>
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
        </div>
        {canRead && canManage ? (
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
        ) : null}
      </header>
      {list}
    </div>
  );
}
