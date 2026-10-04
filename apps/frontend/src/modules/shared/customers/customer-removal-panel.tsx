"use client";

import { useId, useState, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { SearchIcon, UserXIcon } from "lucide-react";

import { searchCustomers, type CustomerFound } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";

import { RemoveCustomerDialog } from "./remove-customer-dialog";

type Found = { q: string; total: number; items: CustomerFound[] };

/**
 * Ustawienia › Usuwanie danych klienta (ADR-073, slice 4i): the place for a
 * customer's request to be forgotten, whether or not they ever ordered
 * anything. The panel has no list of customers, so the person is found by
 * what they gave — a name, an e-mail, a phone — among the customers the
 * reader sees elsewhere in the panel; the removal asks the same question as
 * on an order's page.
 */
export function CustomerRemovalPanel() {
  const t = useTranslations("CustomerRemoval");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const ids = useId();
  const [text, setText] = useState("");
  const [found, setFound] = useState<Found>();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [removing, setRemoving] = useState<CustomerFound>();
  const [notice, setNotice] = useState<string>();

  async function search(q: string) {
    setBusy(true);
    setFailed(false);
    try {
      setFound({ q, ...(await searchCustomers(q)) });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const q = text.trim();
    if (q.length < 2) return;
    setNotice(undefined);
    void search(q);
  }

  const columns: ColumnDef<CustomerFound, unknown>[] = [
    {
      id: "customer",
      header: t("colCustomer"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-col gap-0.5">
          <span className="font-medium wrap-anywhere">{row.name}</span>
          {row.email ? (
            <span className="text-sm wrap-anywhere">{row.email}</span>
          ) : null}
          {row.phone ? (
            <span className="text-sm text-muted-foreground">{row.phone}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "known",
      header: t("colKnownFrom"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-col gap-0.5">
          {row.links.map((link) => (
            <Link
              className="text-sm text-primary hover:underline"
              href={link.href}
              key={link.href}
            >
              {(locale === "en" ? link.title.en : link.title.pl) ?? link.href}
            </Link>
          ))}
        </span>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      enableSorting: false,
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={[
            {
              label: t("remove"),
              destructive: true,
              inline: true,
              icon: <UserXIcon aria-hidden="true" />,
              onSelect: () => setRemoving(row),
            },
          ]}
          label={t("actionsFor", { name: row.name })}
        />
      ),
    },
  ];

  return (
    <PanelPage description={t("pageDescription")} title={t("pageTitle")}>
      <form className="space-y-2" onSubmit={submit} role="search">
        {/* The button stands beside the field, the hint under both. */}
        <div className="flex flex-wrap items-end gap-3">
          <Field className="max-w-md min-w-0 flex-1">
            <FieldLabel htmlFor={`${ids}-q`}>{t("searchLabel")}</FieldLabel>
            <Input
              aria-describedby={`${ids}-hint`}
              autoComplete="off"
              id={`${ids}-q`}
              maxLength={120}
              onChange={(event) => setText(event.target.value)}
              type="search"
              value={text}
            />
          </Field>
          <Button disabled={busy || text.trim().length < 2} type="submit">
            <SearchIcon aria-hidden="true" />
            {t("search")}
          </Button>
        </div>
        <p
          className="max-w-2xl text-sm text-muted-foreground"
          id={`${ids}-hint`}
        >
          {t("hint")}
        </p>
      </form>
      <p className="text-sm text-success-foreground empty:hidden" role="status">
        {notice}
      </p>
      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("searchFailed")}
        </p>
      ) : null}
      {found ? (
        <>
          <DataTable
            caption={t("caption")}
            columns={columns}
            data={found.items}
            getRowId={(row) => row.customer_id}
            labels={{ ...labels, empty: t("none", { q: found.q }) }}
            loading={busy}
          />
          {found.total > found.items.length ? (
            <p className="text-sm text-muted-foreground">
              {t("more", { total: found.total, shown: found.items.length })}
            </p>
          ) : null}
        </>
      ) : null}
      <p className="text-sm text-muted-foreground">
        {t("automatic")}{" "}
        <Link
          className="font-medium text-primary hover:underline"
          href="/panel/settings/privacy"
        >
          {t("automaticLink")}
        </Link>
      </p>
      {removing ? (
        <RemoveCustomerDialog
          customerId={removing.customer_id}
          name={removing.name}
          onDone={() => {
            setNotice(t("removed", { name: removing.name }));
            setRemoving(undefined);
            // The person is gone from the search as well: read it again.
            if (found) void search(found.q);
          }}
          onOpenChange={(open) => {
            if (!open) setRemoving(undefined);
          }}
        />
      ) : null}
    </PanelPage>
  );
}
