"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ArrowDownToLineIcon,
  ArrowUpFromLineIcon,
  CalendarClockIcon,
  GaugeIcon,
  Undo2Icon,
} from "lucide-react";

import {
  getSettingsGroup,
  issueInventory,
  listInventoryBalances,
  receiveInventory,
  returnInventory,
  setInventoryPlaceMinimum,
  type InventoryBalance,
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

import { PanelActions } from "#components/panel/panel-actions";
import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  FormDialog,
  LotStatusBadge,
  locationLabel,
  personName,
  useFormat,
  type InventoryData,
  type PageFrame,
} from "./shared";

type Movement = "receive" | "issue" | "return";
// By the direction of the goods (UX-061): into the warehouse, out of it, and
// coming back.
const MOVEMENT_ICONS = {
  receive: ArrowDownToLineIcon,
  issue: ArrowUpFromLineIcon,
  return: Undo2Icon,
};

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
  page,
}: {
  data: InventoryData;
  canManage: boolean;
  reloads: number;
  onChanged: (notice: string) => void;
  page: PageFrame;
}) {
  const t = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const { amount, day } = useFormat();
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
    lot_number: "",
    expires_on: "",
  });
  const [held, setHeld] = useState<InventoryBalance[]>([]);
  // A low-stock notice links here with the list already narrowed.
  const params = useSearchParams();
  const [onlyLow, setOnlyLow] = useState(params?.get("low") === "1");
  const [minimumOf, setMinimumOf] = useState<InventoryBalance | null>(null);
  const [minimum, setMinimum] = useState("");
  // Whether the daily notice is off — then the list offers to switch it on.
  const [alertsOff, setAlertsOff] = useState(false);

  useEffect(() => {
    if (!canManage) return;
    let current = true;
    getSettingsGroup("inventory.alerts")
      .then((state) => {
        const values = state.values as { low_stock?: string };
        if (current) setAlertsOff(values.low_stock === "off");
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [canManage]);

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

  // The API decides what is short (the place's minimum, else the item's).
  const low = (row: InventoryBalance) => row.below_minimum;

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
      meta: { numeric: true },
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
      meta: { numeric: true },
      cell: ({ row: { original: row } }) => amount(row.reserved),
    },
    {
      id: "available",
      accessorFn: (row) => Number(row.available),
      header: t("available"),
      meta: { numeric: true },
      cell: ({ row: { original: row } }) => (
        <span className="inline-flex flex-wrap items-center gap-2">
          {amount(row.available)}
          {low(row) ? <Badge variant="warning">{t("low")}</Badge> : null}
        </span>
      ),
    },
    {
      id: "minimum",
      accessorFn: (row) => Number(row.minimum_quantity ?? -1),
      header: t("minimum"),
      meta: { numeric: true },
      cell: ({ row: { original: row } }) => (
        <span className="inline-flex flex-wrap items-center justify-end gap-2">
          {row.minimum_quantity === null ? "—" : amount(row.minimum_quantity)}
          {row.place_minimum === null ? null : (
            <Badge title={t("minimumOwnHint")} variant="neutral">
              {t("minimumOwn")}
            </Badge>
          )}
        </span>
      ),
    },
    {
      // The lot that expires first here: red past it, amber within 30 days.
      id: "expiry",
      accessorFn: (row) => row.nearest_expiry ?? "",
      header: t("nearestExpiry"),
      cell: ({ row: { original: row } }) =>
        row.nearest_expiry ? (
          <span className="inline-flex flex-wrap items-center gap-2">
            {day(row.nearest_expiry)}
            <LotStatusBadge status={row.lot_status} />
          </span>
        ) : null,
    },
    ...(canManage
      ? [
          {
            id: "actions",
            header: t("actions"),
            meta: { actions: true },
            // The main warehouse takes deliveries and gives out; a person's
            // stock gets more or gives back.
            cell: ({ row: { original: row } }) => (
              <RowActions
                items={[
                  ...(row.holder_id
                    ? [
                        movement("issue", row, true),
                        movement("return", row, true),
                      ]
                    : [
                        movement("receive", row, true),
                        movement("issue", row, true),
                        movement("return", row, false),
                      ]),
                  {
                    label: t("placeMinimum"),
                    icon: <GaugeIcon aria-hidden="true" />,
                    onSelect: () => {
                      setMinimum(
                        row.place_minimum === null
                          ? ""
                          : String(Number(row.place_minimum)),
                      );
                      setMinimumOf(row);
                    },
                  },
                  ...(row.tracks_lots
                    ? [
                        {
                          label: t("showLots"),
                          icon: <CalendarClockIcon aria-hidden="true" />,
                          link: (
                            <Link
                              href={`/panel/inventory/lots?item=${row.item_id}`}
                            />
                          ),
                        },
                      ]
                    : []),
                ]}
                label={t("actionsFor", { name: row.item_name })}
              />
            ),
          } satisfies ColumnDef<InventoryBalance, unknown>,
        ]
      : []),
  ];

  const people = data.crew;
  const items = data.items.filter((item) => item.active);
  // A receipt of an item with lots names the lot and its expiry date.
  const lots =
    dialog === "receive" &&
    items.some((item) => item.id === form.item_id && item.tracks_lots);
  const open = (kind: Movement, row?: InventoryBalance) => {
    // One id per opened form: a retry after a lost answer is the same document.
    setForm({
      id: crypto.randomUUID(),
      item_id: row?.item_id ?? "",
      holder_id: kind === "receive" ? "" : (row?.holder_id ?? ""),
      quantity: "",
      price: "",
      lot_number: "",
      expires_on: "",
    });
    setHeld([]);
    setDialog(kind);
  };
  function movement(kind: Movement, row: InventoryBalance, inline: boolean) {
    const Icon = MOVEMENT_ICONS[kind];
    return {
      label: t(kind),
      icon: <Icon aria-hidden="true" />,
      inline,
      onSelect: () => open(kind, row),
    };
  }

  const placeName = (row: InventoryBalance) => {
    const location = data.locations.find((one) => one.id === row.location_id);
    return location ? locationLabel(location) : row.location_name;
  };
  // The Catalogue's minimum of the item: what an empty field falls back to.
  const itemMinimum = (row: InventoryBalance | null) =>
    data.items.find((item) => item.id === row?.item_id)?.minimum_quantity ?? 0;

  async function saveMinimum() {
    if (!minimumOf) return;
    await setInventoryPlaceMinimum({
      item_id: minimumOf.item_id,
      location_id: minimumOf.location_id,
      minimum_quantity: minimum.trim() === "" ? null : minimum,
    });
    onChanged(t("placeMinimumSaved", { name: minimumOf.item_name }));
  }

  async function submit() {
    if (dialog === "receive") {
      await receiveInventory({
        id: form.id,
        item_id: form.item_id,
        quantity: form.quantity,
        // Cena z faktury, w groszach: po niej wycenia się rozchód.
        unit_cost_minor: Math.round(Number(form.price || 0) * 100),
        ...(lots
          ? { lot_number: form.lot_number, expires_on: form.expires_on || null }
          : {}),
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
    <DataTableFilter
      id="stock-location"
      label={t("location")}
      onChange={(event) => setLocationId(event.target.value)}
      value={shown}
    >
      {data.locations.map((location) => (
        <option key={location.id} value={location.id}>
          {locationLabel(location)}
        </option>
      ))}
    </DataTableFilter>
  ) : null;

  // „Przyjmij dostawę” first; issuing and a return beside it, or under „…”
  // on a phone (UX-004).
  const actions = canManage ? (
    <PanelActions
      more={[
        {
          label: t("issue"),
          icon: <ArrowUpFromLineIcon aria-hidden="true" />,
          onSelect: () => open("issue"),
        },
        {
          label: t("return"),
          icon: <Undo2Icon aria-hidden="true" />,
          onSelect: () => open("return"),
        },
      ]}
    >
      <Button onClick={() => open("receive")}>
        <ArrowDownToLineIcon aria-hidden="true" />
        {t("receive")}
      </Button>
    </PanelActions>
  ) : null;

  return (
    <PanelPage
      {...page}
      actions={actions}
      description={canManage ? t("stockDescription") : t("myStockDescription")}
    >
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("stockCaption")}
          columns={columns}
          data={onlyLow ? (rows ?? []).filter(low) : (rows ?? [])}
          getRowId={(row) => `${row.location_id}:${row.item_id}`}
          labels={{
            ...labels,
            empty: onlyLow
              ? t("lowEmpty")
              : canManage
                ? t("stockEmpty")
                : t("myStockEmpty"),
          }}
          activeFilters={onlyLow ? 1 : 0}
          filters={
            <DataTableFilter
              id="stock-low"
              label={t("lowFilter")}
              onChange={(event) => setOnlyLow(event.target.value === "low")}
              value={onlyLow ? "low" : ""}
            >
              <option value="">{t("lowFilterAll")}</option>
              <option value="low">{t("lowFilterLow")}</option>
            </DataTableFilter>
          }
          loading={!rows}
          searchable
          searchText={(row) =>
            [row.item_name, row.sku, row.category_name].join(" ")
          }
          toolbar={toolbar}
        />
      )}

      {canManage && alertsOff && (rows ?? []).some(low) ? (
        // Off by default: the list is where a company learns the notice exists.
        <p className="mt-3 text-sm text-muted-foreground">
          {t("alertsHint")}{" "}
          <Link
            className="font-medium text-foreground underline underline-offset-4"
            href="/panel/settings/inventory"
          >
            {t("alertsHintLink")}
          </Link>
        </p>
      ) : null}

      <FormDialog
        description={
          minimumOf
            ? t("placeMinimumDescription", {
                place: placeName(minimumOf),
              })
            : undefined
        }
        onOpenChange={(next) => setMinimumOf(next ? minimumOf : null)}
        onSubmit={saveMinimum}
        open={minimumOf !== null}
        submitLabel={t("save")}
        title={
          minimumOf ? t("placeMinimumTitle", { name: minimumOf.item_name }) : ""
        }
      >
        <Field>
          <FieldLabel htmlFor="place-minimum">
            {t("placeMinimumField")}
            {minimumOf ? ` (${t(`unit_${minimumOf.unit}`)})` : ""}
          </FieldLabel>
          <Input
            id="place-minimum"
            min="0"
            onChange={(event) => setMinimum(event.target.value)}
            step="0.001"
            type="number"
            value={minimum}
          />
          <p className="text-sm text-muted-foreground">
            {minimumOf?.holder_id
              ? t("placeMinimumHelpPerson")
              : t("placeMinimumHelpWarehouse", {
                  amount: amount(itemMinimum(minimumOf)),
                })}
          </p>
        </Field>
      </FormDialog>

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
        {lots ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="movement-lot">{t("lot")}</FieldLabel>
              <Input
                id="movement-lot"
                maxLength={64}
                onChange={(event) =>
                  setForm({ ...form, lot_number: event.target.value })
                }
                required
                value={form.lot_number}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="movement-expires">
                {t("expiresOn")}
              </FieldLabel>
              <Input
                id="movement-expires"
                onChange={(event) =>
                  setForm({ ...form, expires_on: event.target.value })
                }
                type="date"
                value={form.expires_on}
              />
            </Field>
          </div>
        ) : null}
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
    </PanelPage>
  );
}
