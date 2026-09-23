"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { PlusIcon, Trash2Icon } from "lucide-react";

import {
  listInventoryBalances,
  listInventoryItems,
  type BookingMaterialLine,
  type InventoryItem,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

export type MaterialDraft = {
  item_id: string;
  quantity: string;
  mode: "consume" | "sale";
};

export type Warehouse = {
  items: InventoryItem[];
  /** What the main warehouse can still give, after reservations. */
  available: Record<string, number>;
};

/** The catalogue and the main warehouse's free stock, read once per form. */
export function useWarehouse(enabled: boolean): Warehouse | undefined {
  const [warehouse, setWarehouse] = useState<Warehouse>();
  useEffect(() => {
    if (!enabled) return;
    let current = true;
    Promise.all([listInventoryItems(), listInventoryBalances()])
      .then(([items, balances]) => {
        if (!current) return;
        setWarehouse({
          items: items.filter((item) => item.active),
          available: Object.fromEntries(
            balances.map((row) => [row.item_id, Number(row.available)]),
          ),
        });
      })
      // Without the warehouse the form still books; it just offers no products.
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [enabled]);
  return warehouse;
}

export function draftsOf(
  lines: Pick<BookingMaterialLine, "item_id" | "quantity" | "mode">[] = [],
): MaterialDraft[] {
  return lines.map((line) => ({
    item_id: line.item_id,
    quantity: String(Number(line.quantity)),
    mode: line.mode === "sale" ? "sale" : "consume",
  }));
}

/** Rows ready for the API: empty rows dropped. */
export function materialsInput(drafts: MaterialDraft[]) {
  return drafts.filter((row) => row.item_id && Number(row.quantity) > 0);
}

/**
 * Products a visit takes: item, quantity, and whether it is used up at the
 * company's cost or sold to the customer. Short stock warns, never blocks —
 * the owner's rule for visits (ADR-055).
 */
export function MaterialsEditor({
  drafts,
  idPrefix,
  onChange,
  warehouse,
  held = {},
}: {
  drafts: MaterialDraft[];
  idPrefix: string;
  onChange: (drafts: MaterialDraft[]) => void;
  warehouse?: Warehouse;
  /** What this visit already holds: its own reservation is not a shortage. */
  held?: Record<string, number>;
}) {
  const t = useTranslations("BookingMaterials");
  const locale = useLocale();
  const amount = (value: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value);
  const set = (index: number, patch: Partial<MaterialDraft>) =>
    onChange(
      drafts.map((row, at) => (at === index ? { ...row, ...patch } : row)),
    );
  if (!warehouse)
    return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  if (!warehouse.items.length)
    return <p className="text-sm text-muted-foreground">{t("noItems")}</p>;

  return (
    <div className="space-y-3">
      {drafts.map((row, index) => {
        const free =
          (warehouse.available[row.item_id] ?? 0) + (held[row.item_id] ?? 0);
        const short = row.item_id && Number(row.quantity) > free;
        return (
          <div className="space-y-1" key={index}>
            <div className="flex flex-wrap items-end gap-2">
              <Field className="min-w-44 flex-1">
                <FieldLabel htmlFor={`${idPrefix}-item-${index}`}>
                  {t("item")}
                </FieldLabel>
                <NativeSelect
                  id={`${idPrefix}-item-${index}`}
                  onChange={(event) =>
                    set(index, { item_id: event.target.value })
                  }
                  value={row.item_id}
                >
                  <option value="">{t("pickItem")}</option>
                  {warehouse.items.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field className="w-24">
                <FieldLabel htmlFor={`${idPrefix}-quantity-${index}`}>
                  {t("quantity")}
                </FieldLabel>
                <Input
                  id={`${idPrefix}-quantity-${index}`}
                  min="0.001"
                  onChange={(event) =>
                    set(index, { quantity: event.target.value })
                  }
                  step="0.001"
                  type="number"
                  value={row.quantity}
                />
              </Field>
              <Field className="w-44">
                <FieldLabel htmlFor={`${idPrefix}-mode-${index}`}>
                  {t("mode")}
                </FieldLabel>
                <NativeSelect
                  id={`${idPrefix}-mode-${index}`}
                  onChange={(event) =>
                    set(index, {
                      mode: event.target.value === "sale" ? "sale" : "consume",
                    })
                  }
                  value={row.mode}
                >
                  <option value="consume">{t("consume")}</option>
                  <option value="sale">{t("sale")}</option>
                </NativeSelect>
              </Field>
              <Button
                aria-label={t("remove")}
                onClick={() => onChange(drafts.filter((_, at) => at !== index))}
                size="icon"
                type="button"
                variant="ghost"
              >
                <Trash2Icon aria-hidden="true" />
              </Button>
            </div>
            {short ? (
              <p className="text-sm text-destructive">
                {t("short", { available: amount(free) })}
              </p>
            ) : null}
          </div>
        );
      })}
      <Button
        onClick={() =>
          onChange([...drafts, { item_id: "", quantity: "1", mode: "consume" }])
        }
        type="button"
        variant="outline"
      >
        <PlusIcon aria-hidden="true" />
        {t("add")}
      </Button>
    </div>
  );
}

/** A visit's products as the calendar shows them; sales add up to a total. */
export function MaterialsList({ lines }: { lines: BookingMaterialLine[] }) {
  const t = useTranslations("BookingMaterials");
  const inventory = useTranslations("Inventory");
  const locale = useLocale();
  const money = (minor: number, currency: string) =>
    new Intl.NumberFormat(locale, { style: "currency", currency }).format(
      minor / 100,
    );
  const sales = lines.filter(
    (line) => line.mode === "sale" && line.unit_price_minor !== null,
  );
  const total = sales.reduce(
    (sum, line) => sum + Number(line.quantity) * (line.unit_price_minor ?? 0),
    0,
  );
  if (!lines.length)
    return <p className="text-sm text-muted-foreground">{t("none")}</p>;
  return (
    <div className="space-y-2 text-sm">
      <ul className="divide-y divide-border">
        {lines.map((line, index) => (
          <li
            className="flex flex-wrap justify-between gap-x-4 py-1.5"
            key={index}
          >
            <span>
              {line.name} ·{" "}
              {new Intl.NumberFormat(locale, {
                maximumFractionDigits: 3,
              }).format(Number(line.quantity))}{" "}
              {inventory(`unit_${line.unit}`)}
            </span>
            <span className="text-muted-foreground">
              {line.mode === "sale"
                ? line.unit_price_minor !== null
                  ? `${t("sale")} · ${money(line.unit_price_minor, line.currency)}`
                  : t("sale")
                : t("consume")}
            </span>
          </li>
        ))}
      </ul>
      {sales.length ? (
        <p className="font-medium">
          {t("salesTotal", { total: money(total, sales[0].currency) })}
        </p>
      ) : null}
    </div>
  );
}
