"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  PackageCheckIcon,
  PackageMinusIcon,
  PackagePlusIcon,
} from "lucide-react";

import {
  issueInventory,
  listInventoryBalances,
  receiveInventory,
  returnInventory,
  type InventoryBalance,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useDataTableLabels } from "#lib/data-table-labels";
import {
  FormDialog,
  locationLabel,
  personName,
  useFormat,
  type InventoryData,
} from "./shared";

type Movement = "receive" | "issue" | "return";

/**
 * Stany jednego miejsca. Właściciel wybiera magazyn albo czyjś zapas; pracownik
 * widzi tylko swój — z tym wyjeżdża. Stan nie jest polem do wpisania: zmienia
 * go dokument, każdy ze śladem.
 */
export function StockTab({
  data,
  canManage,
  reloads,
  onChanged,
}: {
  data: InventoryData;
  canManage: boolean;
  reloads: number;
  onChanged: (notice: string) => void;
}) {
  const t = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const { amount } = useFormat();
  const warehouse = data.locations.find((location) => location.is_default);
  const [locationId, setLocationId] = useState("");
  const shown = locationId || warehouse?.id || "";
  const [rows, setRows] = useState<InventoryBalance[] | undefined>();
  const [failed, setFailed] = useState(false);
  const [dialog, setDialog] = useState<Movement | null>(null);
  const [form, setForm] = useState({
    id: "",
    item_id: "",
    holder_id: "",
    quantity: "",
    price: "",
  });
  const [held, setHeld] = useState<InventoryBalance[]>([]);

  useEffect(() => {
    if (canManage && !shown) return;
    let current = true;
    (canManage
      ? listInventoryBalances({ locationId: shown })
      : listInventoryBalances({ mine: true })
    )
      .then((balances) => {
        if (!current) return;
        setRows(balances);
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [canManage, shown, reloads]);

  // Co ten człowiek ma już przy sobie — pytanie zadawane w chwili wydawania.
  useEffect(() => {
    if (!form.holder_id) return;
    let current = true;
    listInventoryBalances({ holderId: form.holder_id })
      .then((balances) => {
        if (current) setHeld(balances);
      })
      .catch(() => {
        if (current) setHeld([]);
      });
    return () => {
      current = false;
    };
  }, [form.holder_id]);

  const low = (row: InventoryBalance) =>
    Number(row.minimum_quantity) > 0 &&
    Number(row.available) <= Number(row.minimum_quantity);

  const columns: ColumnDef<InventoryBalance, unknown>[] = [
    {
      id: "item",
      accessorKey: "item_name",
      header: t("item"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{row.item_name}</p>
          {row.sku ? (
            <p className="text-xs text-muted-foreground">{row.sku}</p>
          ) : null}
        </>
      ),
    },
    {
      id: "category",
      accessorFn: (row) => row.category_name ?? "",
      header: t("category"),
    },
    {
      id: "quantity",
      accessorFn: (row) => Number(row.quantity),
      header: t("quantity"),
      cell: ({ row: { original: row } }) => (
        <span className={Number(row.quantity) < 0 ? "text-destructive" : ""}>
          {amount(row.quantity)} {t(`unit_${row.unit}`)}
        </span>
      ),
    },
    {
      id: "reserved",
      accessorFn: (row) => Number(row.reserved),
      header: t("reserved"),
      cell: ({ row: { original: row } }) => amount(row.reserved),
    },
    {
      id: "available",
      accessorFn: (row) => Number(row.available),
      header: t("available"),
      cell: ({ row: { original: row } }) => (
        <span className="inline-flex flex-wrap items-center gap-2">
          {amount(row.available)}
          {low(row) ? <Badge variant="destructive">{t("low")}</Badge> : null}
        </span>
      ),
    },
    {
      id: "minimum",
      accessorFn: (row) => Number(row.minimum_quantity),
      header: t("minimum"),
      cell: ({ row: { original: row } }) => amount(row.minimum_quantity),
    },
  ];

  const people = data.crew;
  const items = data.items.filter((item) => item.active);
  const open = (kind: Movement) => {
    // One id per opened form: a retry after a lost answer is the same document.
    setForm({
      id: crypto.randomUUID(),
      item_id: "",
      holder_id: "",
      quantity: "",
      price: "",
    });
    setHeld([]);
    setDialog(kind);
  };

  async function submit() {
    if (dialog === "receive") {
      await receiveInventory({
        id: form.id,
        item_id: form.item_id,
        quantity: form.quantity,
        // Cena z faktury, w groszach: po niej wycenia się rozchód.
        unit_cost_minor: Math.round(Number(form.price || 0) * 100),
      });
      onChanged(t("received"));
      return;
    }
    const input = {
      id: form.id,
      item_id: form.item_id,
      holder_id: form.holder_id,
      quantity: form.quantity,
    };
    if (dialog === "issue") await issueInventory(input);
    else await returnInventory(input);
    onChanged(t(dialog === "issue" ? "issued" : "returned"));
  }

  const toolbar = canManage ? (
    <div className="flex flex-wrap items-end gap-2">
      <Field className="min-w-48">
        <FieldLabel htmlFor="stock-location">{t("location")}</FieldLabel>
        <NativeSelect
          id="stock-location"
          onChange={(event) => setLocationId(event.target.value)}
          value={shown}
        >
          {data.locations.map((location) => (
            <option key={location.id} value={location.id}>
              {locationLabel(location)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Button onClick={() => open("receive")} variant="outline">
        <PackagePlusIcon aria-hidden="true" />
        {t("receive")}
      </Button>
      <Button onClick={() => open("issue")} variant="outline">
        <PackageCheckIcon aria-hidden="true" />
        {t("issue")}
      </Button>
      <Button onClick={() => open("return")} variant="outline">
        <PackageMinusIcon aria-hidden="true" />
        {t("return")}
      </Button>
    </div>
  ) : null;

  return (
    <div className="space-y-4">
      <p className="text-muted-foreground">
        {canManage ? t("stockDescription") : t("myStockDescription")}
      </p>
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("stockCaption")}
          columns={columns}
          data={rows ?? []}
          getRowId={(row) => `${row.location_id}:${row.item_id}`}
          labels={{
            ...labels,
            empty: canManage ? t("stockEmpty") : t("myStockEmpty"),
          }}
          loading={!rows}
          searchable
          searchText={(row) =>
            [row.item_name, row.sku, row.category_name].join(" ")
          }
          toolbar={toolbar}
        />
      )}

      <FormDialog
        description={dialog ? t(`${dialog}Description`) : undefined}
        onOpenChange={(next) => setDialog(next ? dialog : null)}
        onSubmit={submit}
        open={dialog !== null}
        submitLabel={t("save")}
        title={dialog ? t(dialog) : ""}
      >
        {dialog === "issue" || dialog === "return" ? (
          <Field>
            <FieldLabel htmlFor="movement-holder">{t("holder")}</FieldLabel>
            <NativeSelect
              id="movement-holder"
              onChange={(event) => {
                // Czyścimy tu, a nie w efekcie: stan poprzedniej osoby nie
                // ma prawa mignąć pod nowym nazwiskiem.
                setHeld([]);
                setForm({ ...form, holder_id: event.target.value });
              }}
              required
              value={form.holder_id}
            >
              <option value="">{t("pickHolder")}</option>
              {people.map((person) => (
                <option key={person.user_id} value={person.user_id}>
                  {personName(person)}
                </option>
              ))}
            </NativeSelect>
            {form.holder_id ? (
              <p className="text-sm text-muted-foreground">
                {held.length
                  ? t("holderHas", {
                      stock: held
                        .map(
                          (row) =>
                            `${row.item_name} ${amount(row.quantity)} ${t(`unit_${row.unit}`)}`,
                        )
                        .join(", "),
                    })
                  : t("holderHasNothing")}
              </p>
            ) : null}
          </Field>
        ) : null}
        <Field>
          <FieldLabel htmlFor="movement-item">{t("item")}</FieldLabel>
          <NativeSelect
            id="movement-item"
            onChange={(event) =>
              setForm({ ...form, item_id: event.target.value })
            }
            required
            value={form.item_id}
          >
            <option value="">{t("pickItem")}</option>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field>
          <FieldLabel htmlFor="movement-quantity">{t("quantity")}</FieldLabel>
          <Input
            id="movement-quantity"
            min="0.001"
            onChange={(event) =>
              setForm({ ...form, quantity: event.target.value })
            }
            required
            step="0.001"
            type="number"
            value={form.quantity}
          />
        </Field>
        {dialog === "receive" ? (
          <Field>
            <FieldLabel htmlFor="movement-price">{t("unitPrice")}</FieldLabel>
            <Input
              id="movement-price"
              min="0"
              onChange={(event) =>
                setForm({ ...form, price: event.target.value })
              }
              step="0.01"
              type="number"
              value={form.price}
            />
          </Field>
        ) : null}
      </FormDialog>
    </div>
  );
}
