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
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";

import { DocumentsTab } from "./documents-tab";
import { ItemsTab } from "./items-tab";
import { SetupTab } from "./setup-tab";
import type { InventoryData } from "./shared";
import { StockTab } from "./stock-tab";

/**
 * Magazyn firmy (ADR-055). Właściciel pyta „co mam, czego brakuje, co przyszło
 * i wyszło”, pracownik — „z czym wyjeżdżam”. Stan zmienia tylko dokument.
 */
export function InventoryPanel({
  canManage = false,
  canRead = false,
}: {
  canManage?: boolean;
  canRead?: boolean;
} = {}) {
  const t = useTranslations("Inventory");
  const [data, setData] = useState<InventoryData | undefined>();
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!canRead) return;
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
  }, [canManage, canRead, reloads]);

  const changed = (message: string) => {
    setNotice(message);
    setReloads((value) => value + 1);
  };

  if (!canRead) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("noAccessTitle")}</h2>
          </CardTitle>
          <CardDescription>{t("noAccess")}</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1 className="text-3xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
      </header>
      <p aria-live="polite" className="text-sm text-success-foreground">
        {notice}
      </p>
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : !data ? (
        <p className="text-muted-foreground">{t("loading")}</p>
      ) : (
        <Tabs defaultValue="stock">
          <TabsList>
            <TabsTab value="stock">
              {canManage ? t("tabStock") : t("myStock")}
            </TabsTab>
            <TabsTab value="items">{t("tabItems")}</TabsTab>
            {canManage ? (
              <>
                <TabsTab value="documents">{t("tabDocuments")}</TabsTab>
                <TabsTab value="setup">{t("tabSetup")}</TabsTab>
              </>
            ) : null}
            <TabsIndicator />
          </TabsList>
          <TabsPanel value="stock">
            <StockTab
              canManage={canManage}
              data={data}
              onChanged={changed}
              reloads={reloads}
            />
          </TabsPanel>
          <TabsPanel value="items">
            <ItemsTab canManage={canManage} data={data} onChanged={changed} />
          </TabsPanel>
          {canManage ? (
            <>
              <TabsPanel value="documents">
                <DocumentsTab
                  data={data}
                  onChanged={changed}
                  reloads={reloads}
                />
              </TabsPanel>
              <TabsPanel value="setup">
                <SetupTab data={data} onChanged={changed} />
              </TabsPanel>
            </>
          ) : null}
        </Tabs>
      )}
    </div>
  );
}
