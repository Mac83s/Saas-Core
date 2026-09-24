"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { PencilIcon, PlusIcon } from "lucide-react";

import {
  createInventoryItem,
  updateInventoryItem,
  type InventoryItem,
  type InventoryItemInput,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  FormDialog,
  UNITS,
  VAT_RATES,
  useFormat,
  type InventoryData,
  type PageFrame,
} from "./shared";

type Draft = {
  name: string;
  sku: string;
  ean: string;
  category: string;
  unit: string;
  minimum_quantity: string;
  sale_price: string;
  vat_rate: string;
  notes: string;
};

const EMPTY: Draft = {
  name: "",
  sku: "",
  ean: "",
  category: "",
  unit: "piece",
  minimum_quantity: "0",
  sale_price: "",
  vat_rate: "23",
  notes: "",
};

function draftOf(item: InventoryItem): Draft {
  return {
    name: item.name,
    sku: item.sku ?? "",
    ean: item.ean ?? "",
    category: item.category_id ?? "",
    unit: item.unit,
    minimum_quantity: item.minimum_quantity,
    sale_price:
      item.sale_price_net_minor === null ||
      item.sale_price_net_minor === undefined
        ? ""
        : String(item.sale_price_net_minor / 100),
    vat_rate: item.vat_rate,
    notes: item.notes,
  };
}

/**
 * Katalog: jedna pozycja to jeden SKU. Pozycji standardowej produktu nie da
 * się usunąć — tylko zmienić albo ukryć; historia ruchów musi mieć do czego
 * wracać, więc żadnej pozycji nie usuwamy.
 */
export function ItemsTab({
  data,
  canManage,
  onChanged,
  page,
}: {
  data: InventoryData;
  canManage: boolean;
  onChanged: (notice: string) => void;
  page: PageFrame;
}) {
  const t = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const { amount, money } = useFormat();
  const [category, setCategory] = useState("");
  const [editing, setEditing] = useState<InventoryItem | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);

  const open = (item: InventoryItem | "new") => {
    setDraft(item === "new" ? EMPTY : draftOf(item));
    setEditing(item);
  };

  async function save() {
    const input: InventoryItemInput = {
      name: draft.name,
      sku: draft.sku,
      ean: draft.ean,
      category: draft.category || null,
      unit: draft.unit as InventoryItemInput["unit"],
      minimum_quantity: draft.minimum_quantity || "0",
      sale_price_net_minor: draft.sale_price
        ? Math.round(Number(draft.sale_price) * 100)
        : null,
      vat_rate: draft.vat_rate as InventoryItemInput["vat_rate"],
      notes: draft.notes,
    };
    if (editing === "new") {
      await createInventoryItem(input);
      onChanged(t("itemAdded", { name: draft.name }));
    } else if (editing) {
      await updateInventoryItem(editing.id, input);
      onChanged(t("itemSaved", { name: draft.name }));
    }
  }

  async function toggle(item: InventoryItem) {
    await updateInventoryItem(item.id, { active: !item.active });
    onChanged(t(item.active ? "itemHidden" : "itemShown", { name: item.name }));
  }

  const columns: ColumnDef<InventoryItem, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("itemName"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {item.name}{" "}
            {item.system_key ? (
              <Badge variant="secondary">{t("standard")}</Badge>
            ) : null}{" "}
            {item.active ? null : (
              <Badge variant="outline">{t("hidden")}</Badge>
            )}
          </p>
          {item.sku || item.ean ? (
            <p className="text-xs text-muted-foreground">
              {[item.sku, item.ean].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "category",
      accessorFn: (item) => item.category_name ?? "",
      header: t("category"),
    },
    {
      id: "unit",
      accessorFn: (item) => t(`unit_${item.unit}`),
      header: t("unit"),
    },
    {
      id: "minimum",
      accessorFn: (item) => Number(item.minimum_quantity),
      header: t("minimum"),
      cell: ({ row: { original: item } }) => amount(item.minimum_quantity),
    },
    {
      id: "cost",
      accessorKey: "average_cost_minor",
      header: t("averageCost"),
      cell: ({ row: { original: item } }) =>
        money(item.average_cost_minor, item.currency),
    },
    {
      id: "price",
      accessorFn: (item) => item.sale_price_net_minor ?? -1,
      header: t("salePrice"),
      cell: ({ row: { original: item } }) =>
        money(item.sale_price_net_minor, item.currency),
    },
    ...(canManage
      ? [
          {
            id: "actions",
            header: t("actions"),
            meta: { actions: true },
            cell: ({ row: { original: item } }) => (
              <RowActions
                items={[
                  {
                    label: t("edit"),
                    icon: <PencilIcon aria-hidden="true" />,
                    inline: true,
                    onSelect: () => open(item),
                  },
                  {
                    label: item.active ? t("hide") : t("show"),
                    onSelect: () => void toggle(item),
                  },
                ]}
                label={t("actionsFor", { name: item.name })}
              />
            ),
          } satisfies ColumnDef<InventoryItem, unknown>,
        ]
      : []),
  ];

  const field = (key: keyof Draft) => ({
    id: `item-${key}`,
    onChange: (event: { target: { value: string } }) =>
      setDraft({ ...draft, [key]: event.target.value }),
    value: draft[key],
  });

  return (
    <PanelPage
      {...page}
      actions={
        canManage ? (
          <Button onClick={() => open("new")}>
            <PlusIcon aria-hidden="true" />
            {t("addItem")}
          </Button>
        ) : null
      }
      description={t("itemsDescription")}
    >
      <DataTable
        caption={t("itemsCaption")}
        columns={columns}
        data={
          category
            ? data.items.filter((item) => item.category_id === category)
            : data.items
        }
        getRowId={(item) => item.id}
        labels={{ ...labels, empty: t("itemsEmpty") }}
        searchable
        searchText={(item) =>
          [item.name, item.sku, item.ean, item.category_name].join(" ")
        }
        toolbar={
          data.categories.length ? (
            <DataTableFilter
              id="items-category"
              label={t("category")}
              onChange={(event) => setCategory(event.target.value)}
              value={category}
            >
              <option value="">{t("allCategories")}</option>
              {data.categories.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </DataTableFilter>
          ) : null
        }
      />
      <FormDialog
        description={editing === "new" ? t("addItemDescription") : undefined}
        onOpenChange={(next) => setEditing(next ? editing : null)}
        onSubmit={save}
        open={editing !== null}
        submitLabel={t("save")}
        title={editing === "new" ? t("addItem") : t("editItem")}
      >
        <Field>
          <FieldLabel htmlFor="item-name">{t("itemName")}</FieldLabel>
          <Input {...field("name")} maxLength={120} required />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="item-sku">{t("sku")}</FieldLabel>
            <Input {...field("sku")} maxLength={64} />
          </Field>
          <Field>
            <FieldLabel htmlFor="item-ean">{t("ean")}</FieldLabel>
            <Input {...field("ean")} inputMode="numeric" maxLength={14} />
          </Field>
          <Field>
            <FieldLabel htmlFor="item-category">{t("category")}</FieldLabel>
            <NativeSelect {...field("category")}>
              <option value="">{t("noCategory")}</option>
              {data.categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor="item-unit">{t("unit")}</FieldLabel>
            <NativeSelect {...field("unit")}>
              {UNITS.map((unit) => (
                <option key={unit} value={unit}>
                  {t(`unit_${unit}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor="item-minimum_quantity">
              {t("minimum")}
            </FieldLabel>
            <Input
              {...field("minimum_quantity")}
              min="0"
              step="0.001"
              type="number"
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="item-sale_price">{t("salePrice")}</FieldLabel>
            <Input {...field("sale_price")} min="0" step="0.01" type="number" />
          </Field>
          <Field>
            <FieldLabel htmlFor="item-vat_rate">{t("vatRate")}</FieldLabel>
            <NativeSelect {...field("vat_rate")}>
              {VAT_RATES.map((rate) => (
                <option key={rate} value={rate}>
                  {rate === "zw" ? t("vatExempt") : `${rate}%`}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </div>
        <Field>
          <FieldLabel htmlFor="item-notes">{t("notes")}</FieldLabel>
          <Textarea {...field("notes")} rows={2} />
        </Field>
      </FormDialog>
    </PanelPage>
  );
}
