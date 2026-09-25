"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  listInventoryLots,
  type InventoryLotStock,
} from "@saas-core/api-client";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  LotStatusBadge,
  locationLabel,
  useFormat,
  type InventoryData,
  type PageFrame,
} from "./shared";

type Soon = "" | "soon" | "expired";

/**
 * Partie i ważność (decyzja 25.09): co gdzie leży, od partii, która najwcześniej
 * traci ważność. Po terminie — na czerwono, w ciągu 30 dni — na bursztynowo;
 * w pracy nic tu nie blokuje, sprzedaży partii po terminie odmawia WZ.
 */
export function LotsTab({
  data,
  reloads,
  page,
}: {
  data: InventoryData;
  reloads: number;
  page: PageFrame;
}) {
  const t = useTranslations("Inventory");
  const labels = useDataTableLabels();
  const { amount, day } = useFormat();
  // The stock page leads here with the item already chosen.
  const params = useSearchParams();
  const [itemId, setItemId] = useState(params?.get("item") ?? "");
  const [locationId, setLocationId] = useState("");
  const [soon, setSoon] = useState<Soon>("");
  const [rows, setRows] = useState<InventoryLotStock[] | undefined>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    listInventoryLots()
      .then((lots) => {
        if (!current) return;
        setRows(lots);
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [reloads]);

  const place = (row: InventoryLotStock) => {
    const location = data.locations.find((one) => one.id === row.location_id);
    return location ? locationLabel(location) : row.location_name;
  };
  const shown = (rows ?? []).filter(
    (row) =>
      (!itemId || row.item_id === itemId) &&
      (!locationId || row.location_id === locationId) &&
      (soon === "" ||
        row.status === "expired" ||
        (soon === "soon" && row.status === "expiring")),
  );

  const columns: ColumnDef<InventoryLotStock, unknown>[] = [
    {
      id: "item",
      accessorKey: "item_name",
      header: t("item"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <>
          <p className="font-medium wrap-anywhere">{row.item_name}</p>
          <p className="text-xs text-muted-foreground">
            {t("lot")}: {row.number}
          </p>
        </>
      ),
    },
    {
      id: "expiry",
      accessorFn: (row) => row.expires_on ?? "9999-12-31",
      header: t("expiresOn"),
      cell: ({ row: { original: row } }) => (
        <span className="inline-flex flex-wrap items-center gap-2">
          {row.expires_on ? day(row.expires_on) : t("lotStatus_no_date")}
          <LotStatusBadge status={row.status} />
        </span>
      ),
    },
    {
      id: "location",
      accessorFn: place,
      header: t("location"),
    },
    {
      id: "quantity",
      accessorFn: (row) => Number(row.quantity),
      header: t("quantity"),
      cell: ({ row: { original: row } }) =>
        `${amount(row.quantity)} ${t(`unit_${row.unit}`)}`,
    },
  ];

  return (
    <PanelPage {...page} description={t("lotsDescription")}>
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("loadError")}
        </p>
      ) : (
        <DataTable
          caption={t("lotsCaption")}
          columns={columns}
          data={shown}
          getRowId={(row) => `${row.lot_id}:${row.location_id}`}
          labels={{ ...labels, empty: t("lotsEmpty") }}
          loading={!rows}
          searchable
          searchText={(row) => [row.item_name, row.number].join(" ")}
          toolbar={
            <>
              <DataTableFilter
                id="lots-soon"
                label={t("lotFilter")}
                onChange={(event) => setSoon(event.target.value as Soon)}
                value={soon}
              >
                <option value="">{t("lotFilterAll")}</option>
                <option value="soon">{t("lotFilterSoon")}</option>
                <option value="expired">{t("lotFilterExpired")}</option>
              </DataTableFilter>
              <DataTableFilter
                id="lots-item"
                label={t("item")}
                onChange={(event) => setItemId(event.target.value)}
                value={itemId}
              >
                <option value="">{t("allItems")}</option>
                {data.items
                  .filter((item) => item.tracks_lots)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
              </DataTableFilter>
              <DataTableFilter
                id="lots-location"
                label={t("location")}
                onChange={(event) => setLocationId(event.target.value)}
                value={locationId}
              >
                <option value="">{t("allLocations")}</option>
                {data.locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {locationLabel(location)}
                  </option>
                ))}
              </DataTableFilter>
            </>
          }
        />
      )}
    </PanelPage>
  );
}
