"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { PlusIcon } from "lucide-react";

import {
  createInventoryCategory,
  createWarehouse,
  deleteInventoryCategory,
  renameInventoryCategory,
  saveSupplier,
  updateStockLocation,
  type InventoryCategory,
  type StockLocation,
  type Supplier,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { PanelPage, PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  FormDialog,
  locationLabel,
  problemText,
  type InventoryData,
  type PageFrame,
} from "./shared";

type Naming =
  | { kind: "warehouse"; target?: StockLocation }
  | { kind: "category"; target?: InventoryCategory };

const SUPPLIER_FIELDS = ["name", "tax_id", "email", "phone", "notes"] as const;
type SupplierDraft = Record<(typeof SUPPLIER_FIELDS)[number], string>;

/** Magazyny, dostawcy i kategorie: to, co ustawia się raz i rzadko zmienia. */
export function SetupTab({
  data,
  onChanged,
  page,
}: {
  data: InventoryData;
  onChanged: (notice: string) => void;
  page: PageFrame;
}) {
  const t = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const [naming, setNaming] = useState<Naming | null>(null);
  const [name, setName] = useState("");
  const [supplier, setSupplier] = useState<Supplier | "new" | null>(null);
  const [supplierDraft, setSupplierDraft] = useState<SupplierDraft>({
    name: "",
    tax_id: "",
    email: "",
    phone: "",
    notes: "",
  });
  const [problem, setProblem] = useState("");

  const rename = (next: Naming) => {
    setName(next.target?.name ?? "");
    setNaming(next);
  };

  async function run(action: () => Promise<unknown>, done: string) {
    setProblem("");
    try {
      await action();
      onChanged(done);
    } catch (error) {
      setProblem(problemText(error, t("failed")));
    }
  }

  async function saveName() {
    if (!naming) return;
    if (naming.kind === "warehouse") {
      await (naming.target
        ? updateStockLocation(naming.target.id, { name })
        : createWarehouse(name));
    } else {
      await (naming.target
        ? renameInventoryCategory(naming.target.id, name)
        : createInventoryCategory(name));
    }
    onChanged(t("saved"));
  }

  async function saveSupplierDraft() {
    await saveSupplier(
      supplierDraft,
      supplier && supplier !== "new" ? supplier.id : undefined,
    );
    onChanged(t("saved"));
  }

  const locationColumns: ColumnDef<StockLocation, unknown>[] = [
    {
      id: "name",
      accessorFn: locationLabel,
      header: t("location"),
      meta: { primary: true },
      cell: ({ row: { original: location } }) => (
        <p className="font-medium wrap-anywhere">
          {locationLabel(location)}{" "}
          {location.is_default ? (
            <Badge variant="secondary">{t("mainWarehouse")}</Badge>
          ) : null}{" "}
          {location.active === false ? (
            <Badge variant="outline">{t("inactive")}</Badge>
          ) : null}
        </p>
      ),
    },
    {
      id: "kind",
      accessorFn: (location) => t(`locationKind_${location.kind}`),
      header: t("locationKind"),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: location } }) =>
        location.kind === "warehouse" ? (
          <RowActions
            items={[
              {
                label: t("rename"),
                onSelect: () => rename({ kind: "warehouse", target: location }),
              },
              ...(location.is_default
                ? []
                : [
                    {
                      label:
                        location.active === false
                          ? t("activate")
                          : t("deactivate"),
                      onSelect: () =>
                        void run(
                          () =>
                            updateStockLocation(location.id, {
                              active: location.active === false,
                            }),
                          t("saved"),
                        ),
                    },
                  ]),
            ]}
            label={t("actionsFor", { name: location.name })}
          />
        ) : null,
    },
  ];

  const supplierColumns: ColumnDef<Supplier, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("supplier"),
      meta: { primary: true },
      cell: ({ row: { original: one } }) => (
        <>
          <p className="font-medium wrap-anywhere">{one.name}</p>
          {one.tax_id ? (
            <p className="text-xs text-muted-foreground">
              {t("taxId")}: {one.tax_id}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "contact",
      header: t("contact"),
      enableSorting: false,
      accessorFn: (one) => [one.email, one.phone].filter(Boolean).join(" · "),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: one } }) => (
        <RowActions
          items={[
            {
              label: t("edit"),
              onSelect: () => {
                setSupplierDraft({
                  name: one.name,
                  tax_id: one.tax_id ?? "",
                  email: one.email ?? "",
                  phone: one.phone ?? "",
                  notes: one.notes ?? "",
                });
                setSupplier(one);
              },
            },
          ]}
          label={t("actionsFor", { name: one.name })}
        />
      ),
    },
  ];

  const categoryColumns: ColumnDef<InventoryCategory, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("category"),
      meta: { primary: true },
      cell: ({ row: { original: category } }) => (
        <p className="font-medium wrap-anywhere">
          {category.name}{" "}
          {category.system ? (
            <Badge variant="secondary">{t("standard")}</Badge>
          ) : null}
        </p>
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: category } }) => (
        <RowActions
          items={[
            {
              label: t("rename"),
              onSelect: () => rename({ kind: "category", target: category }),
            },
            ...(category.system
              ? []
              : [
                  {
                    label: t("delete"),
                    destructive: true,
                    separated: true,
                    onSelect: () =>
                      void run(
                        () => deleteInventoryCategory(category.id),
                        t("categoryDeleted", { name: category.name }),
                      ),
                  },
                ]),
          ]}
          label={t("actionsFor", { name: category.name })}
        />
      ),
    },
  ];

  return (
    <PanelPage {...page} description={t("setupDescription")}>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="space-y-10">
        <PanelSection
          actions={
            <Button
              onClick={() => rename({ kind: "warehouse" })}
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addWarehouse")}
            </Button>
          }
          title={t("locations")}
        >
          <DataTable
            caption={t("locations")}
            columns={locationColumns}
            data={data.locations}
            getRowId={(location) => location.id}
            labels={labels}
          />
        </PanelSection>
        <PanelSection
          actions={
            <Button
              onClick={() => {
                setSupplierDraft({
                  name: "",
                  tax_id: "",
                  email: "",
                  phone: "",
                  notes: "",
                });
                setSupplier("new");
              }}
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addSupplier")}
            </Button>
          }
          title={t("suppliers")}
        >
          <DataTable
            caption={t("suppliers")}
            columns={supplierColumns}
            data={data.suppliers}
            getRowId={(one) => one.id}
            labels={{ ...labels, empty: t("suppliersEmpty") }}
            searchable={data.suppliers.length > 10}
          />
        </PanelSection>
        <PanelSection
          actions={
            <Button
              onClick={() => rename({ kind: "category" })}
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("addCategory")}
            </Button>
          }
          title={t("categories")}
        >
          <DataTable
            caption={t("categories")}
            columns={categoryColumns}
            data={data.categories}
            getRowId={(category) => category.id}
            labels={labels}
          />
        </PanelSection>
      </div>

      <FormDialog
        onOpenChange={(next) => setNaming(next ? naming : null)}
        onSubmit={saveName}
        open={naming !== null}
        submitLabel={t("save")}
        title={
          naming?.kind === "warehouse"
            ? t(naming.target ? "renameWarehouse" : "addWarehouse")
            : t(naming?.target ? "renameCategory" : "addCategory")
        }
      >
        <Field>
          <FieldLabel htmlFor="setup-name">{t("name")}</FieldLabel>
          <Input
            id="setup-name"
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
            required
            value={name}
          />
        </Field>
      </FormDialog>

      <FormDialog
        onOpenChange={(next) => setSupplier(next ? supplier : null)}
        onSubmit={saveSupplierDraft}
        open={supplier !== null}
        submitLabel={t("save")}
        title={supplier === "new" ? t("addSupplier") : t("editSupplier")}
      >
        {SUPPLIER_FIELDS.map((key) => (
          <Field key={key}>
            <FieldLabel htmlFor={`supplier-${key}`}>
              {t(`supplier_${key}`)}
            </FieldLabel>
            <Input
              id={`supplier-${key}`}
              onChange={(event) =>
                setSupplierDraft({
                  ...supplierDraft,
                  [key]: event.target.value,
                })
              }
              required={key === "name"}
              type={key === "email" ? "email" : "text"}
              value={supplierDraft[key]}
            />
          </Field>
        ))}
      </FormDialog>
    </PanelPage>
  );
}
