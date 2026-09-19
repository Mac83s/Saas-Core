"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronRightIcon, PlusIcon, SearchIcon } from "lucide-react";

import { createFarm, listFarms, type Farm } from "@saas-core/api-client";
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
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Input } from "@saas-core/ui/components/input";

import { Link } from "#i18n/navigation";
import { FarmForm } from "./farm-form";
import { farmProblem } from "./problem";

/** The organization's farms (ADR-051): a company's cards or a farmer's own. */
export function FarmsPanel() {
  const t = useTranslations("Farms");
  const common = useTranslations("Common");
  const [farms, setFarms] = useState<Farm[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [adding, setAdding] = useState(false);

  const load = useCallback(
    async (query: string) => {
      setLoading(true);
      try {
        setFarms(await listFarms(query || undefined));
        setProblem(undefined);
      } catch (error) {
        setProblem(farmProblem(error, t("loadFailed")));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    const timer = setTimeout(() => void load(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [load, search]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        <Button onClick={() => setAdding(true)} type="button">
          <PlusIcon aria-hidden="true" />
          {t("add")}
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("listTitle", { count: farms.length })}</CardTitle>
          <CardDescription>{t("listDescription")}</CardDescription>
          <div className="relative pt-2">
            <SearchIcon
              aria-hidden="true"
              className="pointer-events-none absolute left-3 top-1/2 mt-1 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label={t("search")}
              className="pl-9"
              onChange={(event) => setSearch(event.target.value)}
              placeholder={t("search")}
              value={search}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          {!loading && !problem && farms.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {search ? t("noResults") : t("empty")}
            </p>
          ) : null}
          {farms.map((farm) => (
            <Link
              className="flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/50"
              href={`/panel/farms/${farm.id}`}
              key={farm.id}
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{farm.name}</p>
                <p className="truncate text-sm text-muted-foreground">
                  {[farm.village, farm.keeper_name, farm.phone]
                    .filter(Boolean)
                    .join(" · ") || t("noDetails")}
                </p>
              </div>
              {farm.herd_number ? (
                <Badge variant="outline">{farm.herd_number}</Badge>
              ) : null}
              <ChevronRightIcon
                aria-hidden="true"
                className="size-4 text-muted-foreground"
              />
            </Link>
          ))}
        </CardContent>
      </Card>
      <Dialog onOpenChange={setAdding} open={adding}>
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("add")}</DialogTitle>
            <DialogDescription>{t("addDescription")}</DialogDescription>
          </DialogHeader>
          <FarmForm
            onSubmit={async (values) => {
              try {
                await createFarm(values);
                setAdding(false);
                await load(search.trim());
                return undefined;
              } catch (error) {
                return farmProblem(error, t("saveFailed"));
              }
            }}
            submitLabel={t("add")}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}
