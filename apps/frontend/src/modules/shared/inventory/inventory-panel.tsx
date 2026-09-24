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
import { SetupTab } from "./setup-tab";
import type { InventoryData } from "./shared";
import { StockTab } from "./stock-tab";

/** The warehouse's pages, each at its own address under Magazyn (ADR-057). */
export type InventorySection = "stock" | "items" | "documents" | "setup";

/** What only the one who runs the warehouse sees. */
const MANAGED: InventorySection[] = ["documents", "setup"];

/**
 * Magazyn firmy (ADR-055). Właściciel pyta „co mam, czego brakuje, co przyszło
 * i wyszło”, pracownik — „z czym wyjeżdżam”. Stan zmienia tylko dokument.
 */
export function InventoryPanel({
  canManage = false,
  canRead = false,
  section = "stock",
}: {
  canManage?: boolean;
  canRead?: boolean;
  section?: InventorySection;
} = {}) {
  const t = useTranslations("Inventory");
  const [data, setData] = useState<InventoryData | undefined>();
  const [failed, setFailed] = useState(false);
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
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
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
    documents: t("tabDocuments"),
    setup: t("setupTitle"),
  }[section];

  if (!allowed || failed || !data)
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
        ) : failed ? (
          <p className="text-sm text-destructive" role="alert">
            {t("loadError")}
          </p>
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
