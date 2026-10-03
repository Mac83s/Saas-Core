"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { PencilIcon, PlusIcon } from "lucide-react";

import {
  createBookingExtra,
  updateBookingExtra,
  type BookingExtra,
  type ServiceSetup,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { amountText, formatMoney, parseAmount } from "./money";
import { refusal, VAT_CODES } from "./price-dialog";

type Basis = BookingExtra["basis"];
type VatCode = (typeof VAT_CODES)[number];

/**
 * „Dopłaty i kaucja” (ADR-072 §6, phase 3c): what an offer adds to its price —
 * on every booking or picked by the customer — and the security deposit it
 * holds, which is no charge and stays outside the total.
 */
export function ExtrasList({
  amounts,
  extras,
  onChanged,
  services,
}: {
  amounts: "gross" | "net";
  /** The extras of `services`, switched-off ones included. */
  extras: BookingExtra[];
  onChanged: () => Promise<void> | void;
  /** The offers an extra may belong to; one, and the offer is not asked. */
  services: ServiceSetup[];
}) {
  const t = useTranslations("PriceList");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [editing, setEditing] = useState<{ item?: BookingExtra }>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const offers = new Map(services.map((service) => [service.id, service]));
  const shown = extras.filter((extra) => offers.has(extra.service_id));
  const unitOf = (extra: BookingExtra) =>
    offers.get(extra.service_id)?.range_unit === "day" ? "day" : "night";

  async function toggle(item: BookingExtra) {
    setProblem(undefined);
    try {
      await updateBookingExtra(
        item.id,
        { active: !item.active, expected_version: item.version },
        crypto.randomUUID(),
      );
      setNotice(t(item.active ? "extraOff" : "extraOn", { name: item.name }));
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    }
    await onChanged();
  }

  const columns: ColumnDef<BookingExtra, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colExtra"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <p className="font-medium wrap-anywhere">
          {item.name}
          {item.kind === "security_deposit" ? (
            <Badge className="ml-2" variant="outline">
              {t("deposit")}
            </Badge>
          ) : null}
          {item.active ? null : (
            <Badge className="ml-2" variant="outline">
              {t("off")}
            </Badge>
          )}
        </p>
      ),
    },
    ...(services.length > 1
      ? [
          {
            id: "offer",
            header: t("colOffer"),
            enableSorting: false,
            cell: ({ row: { original: item } }) =>
              offers.get(item.service_id)?.name ?? "—",
          } satisfies ColumnDef<BookingExtra, unknown>,
        ]
      : []),
    {
      id: "amount",
      header: t("colAmount"),
      enableSorting: false,
      cell: ({ row: { original: item } }) =>
        item.kind === "security_deposit"
          ? t("depositTerms", {
              amount: formatMoney(item.amount_minor, item.currency, locale),
            })
          : [
              t(`extraAmount_${item.basis}` as "extraAmount_per_booking", {
                amount: formatMoney(item.amount_minor, item.currency, locale),
                unit: unitOf(item),
              }),
              item.mandatory
                ? t("extraMandatory")
                : t("extraPicked", { count: item.max_quantity }),
              t("termVat", { code: item.vat_code }),
            ].join(" · "),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
        <RowActions
          items={[
            {
              label: t("editFor", { name: item.name }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              main: true,
              onSelect: (trigger) => {
                setReturnTo(trigger ?? null);
                setEditing({ item });
              },
            },
            {
              label: t(item.active ? "switchOff" : "switchOn"),
              onSelect: () => void toggle(item),
            },
          ]}
          label={t("actionsFor", { name: item.name })}
        />
      ),
    },
  ];

  return (
    <PanelSection
      actions={
        <Button
          onClick={(event) => {
            setReturnTo(event.currentTarget);
            setEditing({});
          }}
          variant="outline"
        >
          <PlusIcon aria-hidden="true" />
          {t("addExtra")}
        </Button>
      }
      description={t("extrasHint")}
      title={t("extrasTitle")}
    >
      <p className="text-sm text-success-foreground empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DataTable
        caption={t("extrasTitle")}
        columns={columns}
        data={shown}
        getRowId={(item) => item.id}
        labels={{ ...labels, empty: t("noExtras") }}
      />
      {editing ? (
        <ExtraDialog
          amounts={amounts}
          finalFocus={returnTo}
          item={editing.item}
          onOpenChange={(open) => {
            if (!open) {
              setEditing(undefined);
              void onChanged();
            }
          }}
          onSaved={async (saved, created) => {
            setEditing(undefined);
            setNotice(
              t(created ? "extraAdded" : "extraSaved", { name: saved.name }),
            );
            await onChanged();
          }}
          services={services}
        />
      ) : null}
    </PanelSection>
  );
}

function ExtraDialog({
  amounts,
  finalFocus,
  item,
  onOpenChange,
  onSaved,
  services,
}: {
  amounts: "gross" | "net";
  finalFocus: HTMLElement | null;
  item?: BookingExtra;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: BookingExtra, created: boolean) => void;
  services: ServiceSetup[];
}) {
  const t = useTranslations("PriceList");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [serviceId, setServiceId] = useState(
    item?.service_id ?? services[0]?.id ?? "",
  );
  const [name, setName] = useState(item?.name ?? "");
  const [kind, setKind] = useState<BookingExtra["kind"]>(
    item?.kind ?? "charge",
  );
  const [basis, setBasis] = useState<Basis>(item?.basis ?? "per_booking");
  const [amount, setAmount] = useState(amountText(item?.amount_minor, locale));
  const [vat, setVat] = useState<VatCode>(item?.vat_code ?? "23");
  const [mandatory, setMandatory] = useState(item?.mandatory ?? false);
  const [quantity, setQuantity] = useState(String(item?.max_quantity ?? 1));
  const [active, setActive] = useState(item?.active ?? true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const offer = services.find((service) => service.id === serviceId);
  const stay = offer?.time_model === "range";
  const unit = offer?.range_unit === "day" ? "day" : "night";
  const bases: Basis[] = stay
    ? ["per_booking", "per_person", "per_time_unit", "per_person_per_time_unit"]
    : ["per_booking", "per_person"];
  const chosen = bases.includes(basis) ? basis : "per_booking";
  const charge = kind === "charge";
  const entered = t(amounts === "net" ? "enteredNet" : "enteredGross");

  async function save() {
    if (!serviceId) return setProblem(t("extraOfferRequired"));
    if (!name.trim()) return setProblem(t("extraNameRequired"));
    const value = parseAmount(amount);
    if (value === null) return setProblem(t("amountInvalid"));
    const most = Number(quantity);
    if (
      charge &&
      !mandatory &&
      (!Number.isInteger(most) || most < 1 || most > 100)
    )
      return setProblem(t("quantityInvalid"));
    // A deposit is one amount held for the booking: the server sets the rest.
    const body = {
      name: name.trim(),
      kind,
      amount_minor: value,
      ...(charge
        ? {
            basis: chosen,
            vat_code: vat,
            mandatory,
            max_quantity: mandatory ? 1 : most,
          }
        : {}),
      active,
    };
    setBusy(true);
    setProblem(undefined);
    try {
      onSaved(
        item
          ? await updateBookingExtra(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : await createBookingExtra(
              { ...body, service_id: serviceId },
              idempotencyKey,
            ),
        !item,
      );
    } catch (error) {
      setProblem(refusal(error, t("failed"), t("versionConflict")));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {t(item ? "editExtraTitle" : "newExtraTitle")}
            </DialogTitle>
            <DialogDescription>{t("extraDialogHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            {services.length > 1 ? (
              <Field className="sm:col-span-2">
                <FieldLabel htmlFor="extra-offer">{t("extraOffer")}</FieldLabel>
                <NativeSelect
                  // An extra stays with its offer: bookings name it.
                  disabled={Boolean(item)}
                  id="extra-offer"
                  onChange={(event) => setServiceId(event.target.value)}
                  value={serviceId}
                >
                  {services.map((service) => (
                    <option key={service.id} value={service.id}>
                      {service.name}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            ) : null}
            <Field>
              <FieldLabel htmlFor="extra-kind">{t("extraKind")}</FieldLabel>
              <NativeSelect
                id="extra-kind"
                onChange={(event) =>
                  setKind(event.target.value as BookingExtra["kind"])
                }
                value={kind}
              >
                <option value="charge">{t("extraKind_charge")}</option>
                <option value="security_deposit">
                  {t("extraKind_security_deposit")}
                </option>
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="extra-name">{t("extraName")}</FieldLabel>
              <Input
                autoComplete="off"
                id="extra-name"
                maxLength={160}
                onChange={(event) => setName(event.target.value)}
                value={name}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="extra-amount">
                {charge ? t("amount", { entered }) : t("depositAmount")}
              </FieldLabel>
              <Input
                autoComplete="off"
                id="extra-amount"
                inputMode="decimal"
                onChange={(event) => setAmount(event.target.value)}
                value={amount}
              />
            </Field>
            {charge ? (
              <>
                <Field>
                  <FieldLabel htmlFor="extra-basis">{t("basis")}</FieldLabel>
                  <NativeSelect
                    id="extra-basis"
                    onChange={(event) => setBasis(event.target.value as Basis)}
                    value={chosen}
                  >
                    {bases.map((option) => (
                      <option key={option} value={option}>
                        {t(`extraBasis_${option}` as "extraBasis_per_booking", {
                          unit,
                        })}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="extra-vat">{t("vat")}</FieldLabel>
                  <NativeSelect
                    id="extra-vat"
                    onChange={(event) => setVat(event.target.value as VatCode)}
                    value={vat}
                  >
                    {VAT_CODES.map((code) => (
                      <option key={code} value={code}>
                        {t("vatCode", { code })}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="extra-mandatory">
                    {t("extraWho")}
                  </FieldLabel>
                  <NativeSelect
                    id="extra-mandatory"
                    onChange={(event) =>
                      setMandatory(event.target.value === "mandatory")
                    }
                    value={mandatory ? "mandatory" : "picked"}
                  >
                    <option value="picked">{t("extraWho_picked")}</option>
                    <option value="mandatory">{t("extraWho_mandatory")}</option>
                  </NativeSelect>
                </Field>
                {mandatory ? null : (
                  <Field>
                    <FieldLabel htmlFor="extra-quantity">
                      {t("extraMax")}
                    </FieldLabel>
                    <Input
                      id="extra-quantity"
                      inputMode="numeric"
                      max={100}
                      min={1}
                      onChange={(event) => setQuantity(event.target.value)}
                      type="number"
                      value={quantity}
                    />
                  </Field>
                )}
              </>
            ) : null}
          </div>
          {charge ? null : (
            <FieldDescription>{t("depositHint")}</FieldDescription>
          )}
          {item ? (
            <label
              className="flex min-h-11 items-center gap-2 text-sm"
              htmlFor="extra-active"
            >
              <input
                checked={active}
                className="size-4"
                id="extra-active"
                onChange={(event) => setActive(event.target.checked)}
                type="checkbox"
              />
              {t("extraActive")}
            </label>
          ) : null}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button type="button" variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy} type="submit">
              {t("save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
