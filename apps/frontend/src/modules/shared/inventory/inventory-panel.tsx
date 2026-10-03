"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  listInventoryCategories,
  listInventoryItems,
  listMemberships,
  listStockLocations,
  listSuppliers,
} from "@saas-core/api-client";
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { ListSkeleton } from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { DocumentsTab } from "./documents-tab";
import { ItemsTab } from "./items-tab";
import { LotsTab } from "./lots-tab";
import { ReportsTab } from "./reports-tab";
import { SetupTab } from "./setup-tab";
import {
  LoadProblemNotice,
  loadProblem,
  type InventoryData,
  type LoadProblem,
} from "./shared";
import { StockTab } from "./stock-tab";

/** The warehouse's pages, each at its own address under Magazyn (ADR-057). */
export type InventorySection =
  "stock" | "items" | "lots" | "documents" | "reports" | "setup";

/** What only the one who runs the warehouse sees. */
const MANAGED: InventorySection[] = ["lots", "documents", "reports", "setup"];

/**
 * Magazyn firmy (ADR-055). Właściciel pyta „co mam, czego brakuje, co przyszło
 * i wyszło”, pracownik — „z czym wyjeżdżam”. Stan zmienia tylko dokument.
 */
export function InventoryPanel({
  canManage = false,
  canRead = false,
  section = "stock",
  zone = "UTC",
  canManageBilling = false,
}: {
  canManage?: boolean;
  canRead?: boolean;
  /** Whoever may change the plan: a missing plan feature offers the plans. */
  canManageBilling?: boolean;
  section?: InventorySection;
  /** The company's time zone: a report's period is the company's days. */
  zone?: string;
} = {}) {
  const t = useTranslations("Inventory");
  const [data, setData] = useState<InventoryData | undefined>();
  const [problem, setProblem] = useState<LoadProblem>();
  const [notice, setNotice] = useState("");
  const [reloads, setReloads] = useState(0);
  const allowed = canRead && (canManage || !MANAGED.includes(section));

  useEffect(() => {
    if (!allowed) return;
    let current = true;
    Promise.all([
      listInventoryItems(),
      listInventoryCategories(),
      listStockLocations(),
      canManage ? listSuppliers() : Promise.resolve([]),
      // Skład ekipy tylko dla tego, kto wydaje: lista ludzi to nie widok magazynu.
      canManage
        ? listMemberships().then((people) =>
            people.filter((one) => one.status === "active"),
          )
        : Promise.resolve([]),
    ])
      .then(([items, categories, locations, suppliers, crew]) => {
        if (!current) return;
        setData({ items, categories, locations, suppliers, crew });
        setProblem(undefined);
      })
      .catch((error: unknown) => {
        if (current) setProblem(loadProblem(error));
      });
    return () => {
      current = false;
    };
  }, [allowed, canManage, reloads]);

  const changed = (message: string) => {
    setNotice(message);
    setReloads((value) => value + 1);
  };

  const title = {
    stock: canManage ? t("tabStock") : t("myStock"),
    items: t("tabItems"),
    lots: t("lotsTitle"),
    documents: t("tabDocuments"),
    reports: t("reportsTitle"),
    setup: t("setupTitle"),
  }[section];

  if (!allowed || problem || !data)
    return (
      <PanelPage eyebrow={t("title")} title={title}>
        {!allowed ? (
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>{t("noAccessTitle")}</h2>
              </CardTitle>
              <CardDescription>{t("noAccess")}</CardDescription>
            </CardHeader>
          </Card>
        ) : problem ? (
          <LoadProblemNotice
            canManageBilling={canManageBilling}
            problem={problem}
          />
        ) : (
          <ListSkeleton label={t("loading")} />
        )}
      </PanelPage>
    );

  const page = { eyebrow: t("title"), notice, title };
  if (section === "items")
    return (
      <ItemsTab
        canManage={canManage}
        data={data}
        onChanged={changed}
        page={page}
      />
    );
  if (section === "documents")
    return (
      <DocumentsTab
        data={data}
        onChanged={changed}
        page={page}
        reloads={reloads}
      />
    );
  if (section === "setup")
    return <SetupTab data={data} onChanged={changed} page={page} />;
  if (section === "reports")
    return <ReportsTab data={data} page={page} zone={zone} />;
  if (section === "lots")
    return <LotsTab data={data} page={page} reloads={reloads} />;
  return (
    <StockTab
      canManage={canManage}
      data={data}
      onChanged={changed}
      page={page}
      reloads={reloads}
    />
  );
}
