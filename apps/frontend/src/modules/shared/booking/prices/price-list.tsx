"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  CopyIcon,
  HistoryIcon,
  PencilIcon,
  PlusIcon,
  UsersIcon,
} from "lucide-react";

import {
  copyBookingPricesToNextYear,
  deleteBookingPrice,
  updateBookingPrice,
  type BookingPrice,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelSection } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { CategoriesDialog } from "./categories-dialog";
import {
  pricesOf,
  usePriceWords,
  type PriceBook,
  type PriceSetup,
} from "./price-book";
import { PriceDialog, refusal } from "./price-dialog";
import { PriceHistoryDialog } from "./price-history";
import { PricePreview } from "./price-preview";

/**
 * The price list (ADR-072 §6, phase 3e): the prices of one offer, or of
 * everything booked by dates — the base price, a season's, a weekend's or a
 * peak's — with the question beside it: which of them applies on a day.
 */
export function PriceList({
  book,
  description,
  onChanged,
  service,
  setup,
  title,
  zone,
}: {
  book: PriceBook;
  description: string;
  /** After each write: the price book is read again. */
  onChanged: () => Promise<void> | void;
  /** One offer's price list; without it, everything booked by dates. */
  service?: ServiceSetup;
  setup: PriceSetup;
  title: string;
  zone: string;
}) {
  const t = useTranslations("PriceList");
  const labels = useDataTableLabels();
  const words = usePriceWords(setup);
  const [editing, setEditing] = useState<{ item?: BookingPrice }>();
  const [categorizing, setCategorizing] = useState(false);
  const [history, setHistory] = useState(false);
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();

  // What a price may be of: the offer and what it books, or every stay.
  const offers = service
    ? [service]
    : setup.services.filter((offer) => offer.time_model === "range");
  const stays = offers.some((offer) => offer.time_model === "range");
  const groups = stays
    ? setup.groups.filter(
        (group) => !service || service.group_ids.includes(group.id),
      )
    : [];
  const units = stays
    ? setup.resources.filter(
        (unit) =>
          !service ||
          service.resource_ids.includes(unit.id) ||
          (unit.group_id && service.group_ids.includes(unit.group_id)),
      )
    : [];
  const shown = service
    ? pricesOf(service, book.prices, setup.resources)
    : book.prices.filter(
        (rule) =>
          !rule.service_id ||
          offers.some((offer) => offer.id === rule.service_id),
      );
  const latestYear = Math.max(
    0,
    ...shown
      .filter((rule) => rule.starts_on)
      .map((rule) => Number(rule.starts_on?.slice(0, 4))),
  );

  async function act<T>(action: () => Promise<T>, said: (done: T) => string) {
    setProblem(undefined);
    try {
      setNotice(said(await action()));
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    }
    await onChanged();
  }

  const columns: ColumnDef<BookingPrice, unknown>[] = [
    {
      id: "price",
      accessorFn: (rule) => words.title(rule),
      header: t("colPrice"),
      meta: { primary: true },
      cell: ({ row: { original: rule } }) => (
        <>
          <p className="font-medium wrap-anywhere">
            {words.title(rule)}
            {rule.active ? null : (
              <Badge className="ml-2" variant="outline">
                {t("off")}
              </Badge>
            )}
          </p>
          <p className="text-sm text-muted-foreground">
            {[rule.name ? words.when(rule) : null, ...words.narrowed(rule)]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </>
      ),
    },
    {
      id: "scope",
      header: t("colAppliesTo"),
      enableSorting: false,
      cell: ({ row: { original: rule } }) => words.scope(rule),
    },
    {
      id: "amount",
      header: t("colAmount"),
      enableSorting: false,
      cell: ({ row: { original: rule } }) => (
        <>
          <p className="tabular-nums">{words.amount(rule)}</p>
          <p className="text-sm text-muted-foreground">
            {words.terms(rule, book.categories).join(" · ")}
          </p>
        </>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: rule } }) => (
        <RowActions
          items={[
            {
              label: t("editFor", { name: words.title(rule) }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              onSelect: (trigger) => {
                setReturnTo(trigger ?? null);
                setEditing({ item: rule });
              },
            },
            {
              label: t(rule.active ? "switchOff" : "switchOn"),
              onSelect: () =>
                void act(
                  () =>
                    updateBookingPrice(
                      rule.id,
                      { active: !rule.active, expected_version: rule.version },
                      crypto.randomUUID(),
                    ),
                  () =>
                    t(rule.active ? "priceOff" : "priceOn", {
                      name: words.title(rule),
                    }),
                ),
            },
            {
              label: t("removePrice"),
              destructive: true,
              onSelect: () =>
                void act(
                  () =>
                    deleteBookingPrice(
                      rule.id,
                      rule.version,
                      crypto.randomUUID(),
                    ),
                  () => t("priceRemoved", { name: words.title(rule) }),
                ),
            },
          ]}
          label={t("actionsFor", { name: words.title(rule) })}
        />
      ),
    },
  ];

  return (
    <PanelSection
      actions={
        <>
          <Button
            onClick={(event) => {
              setReturnTo(event.currentTarget);
              setCategorizing(true);
            }}
            variant="outline"
          >
            <UsersIcon aria-hidden="true" />
            {t("categoriesTitle")}
          </Button>
          <Button
            onClick={(event) => {
              setReturnTo(event.currentTarget);
              setHistory(true);
            }}
            variant="outline"
          >
            <HistoryIcon aria-hidden="true" />
            {t("history")}
          </Button>
          {latestYear ? (
            <Button
              onClick={() =>
                void act(
                  () =>
                    copyBookingPricesToNextYear(
                      latestYear,
                      crypto.randomUUID(),
                    ),
                  (count) => t("pricesCopied", { count, year: latestYear + 1 }),
                )
              }
              variant="outline"
            >
              <CopyIcon aria-hidden="true" />
              {t("copyPrices", { from: latestYear, to: latestYear + 1 })}
            </Button>
          ) : null}
          <Button
            onClick={(event) => {
              setReturnTo(event.currentTarget);
              setEditing({});
            }}
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("addPrice")}
          </Button>
        </>
      }
      description={description}
      title={title}
    >
      <p className="text-sm text-muted-foreground">
        {t(book.amounts === "net" ? "amountsNet" : "amountsGross")}{" "}
        <Link
          className="font-medium text-primary hover:underline"
          href="/panel/settings/bookings"
        >
          {t("amountsChange")}
        </Link>
      </p>
      <p className="text-sm text-success-foreground empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <div
        className={
          service
            ? "space-y-4"
            : "grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]"
        }
      >
        <div className="min-w-0">
          <DataTable
            caption={title}
            columns={columns}
            data={shown}
            getRowId={(rule) => rule.id}
            labels={{ ...labels, empty: t("none") }}
          />
        </div>
        {offers.length ? (
          <PricePreview
            book={book}
            // Another offer's dialog starts with its own question.
            key={service?.id ?? "stays"}
            services={offers}
            setup={setup}
            zone={zone}
          />
        ) : null}
      </div>
      {editing ? (
        <PriceDialog
          amounts={book.amounts}
          categories={book.categories.filter(
            (category) =>
              category.active ||
              editing.item?.category_prices.some(
                (line) => line.category_id === category.id,
              ),
          )}
          finalFocus={returnTo}
          groups={groups.filter(
            (group) => group.active || group.id === editing.item?.group_id,
          )}
          item={editing.item}
          onOpenChange={(open) => {
            if (!open) {
              setEditing(undefined);
              void onChanged();
            }
          }}
          onSaved={(saved, created) => {
            setEditing(undefined);
            setNotice(
              t(created ? "priceAdded" : "priceSaved", {
                name: words.title(saved),
              }),
            );
            void onChanged();
          }}
          resources={units.filter(
            (unit) => unit.active || unit.id === editing.item?.resource_id,
          )}
          services={offers.filter(
            (offer) =>
              offer.active ||
              offer.draft ||
              offer.id === (editing.item?.service_id ?? service?.id),
          )}
        />
      ) : null}
      {history ? (
        <PriceHistoryDialog
          finalFocus={returnTo}
          onOpenChange={(open) => (open ? undefined : setHistory(false))}
          setup={setup}
        />
      ) : null}
      {categorizing ? (
        <CategoriesDialog
          categories={book.categories}
          finalFocus={returnTo}
          onChanged={onChanged}
          onOpenChange={(open) => (open ? undefined : setCategorizing(false))}
        />
      ) : null}
    </PanelSection>
  );
}
