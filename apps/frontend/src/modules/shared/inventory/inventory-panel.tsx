"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { PackageCheckIcon, PackagePlusIcon, PlusIcon } from "lucide-react";

import {
  createInventoryItem,
  issueInventory,
  listInventoryBalances,
  listInventoryItems,
  listMemberships,
  receiveInventory,
  type InventoryBalance,
  type InventoryItem,
  type MembershipSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

/** `ItemCategory` magazynu (models.py); leki są kategorią, nie osobnym bytem. */
const CATEGORIES = ["block", "dressing", "medicine", "tool", "other"] as const;

/**
 * Magazyn firmy i mój zapas na dziś.
 *
 * Dwie listy, bo to dwa różne pytania: właściciel pyta „co mam i czego brakuje",
 * korektor — „z czym wyjeżdżam". Stan nie jest tu polem do wpisania: zmienia go
 * przyjęcie, wydanie albo korekta, każde ze śladem.
 */
export function InventoryPanel({
  canManage = false,
  canRead = false,
}: {
  canManage?: boolean;
  canRead?: boolean;
} = {}) {
  const t = useTranslations("Inventory");
  const common = useTranslations("Common");
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [stock, setStock] = useState<InventoryBalance[]>([]);
  const [mine, setMine] = useState<InventoryBalance[]>([]);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState(false);
  const [receiving, setReceiving] = useState(false);
  const [issuing, setIssuing] = useState(false);
  const [crew, setCrew] = useState<MembershipSummary[]>([]);
  const [issue, setIssue] = useState({
    item_id: "",
    holder_id: "",
    quantity: "",
  });
  const [held, setHeld] = useState<InventoryBalance[]>([]);
  const [draft, setDraft] = useState({ name: "", category: "block" });
  const [receipt, setReceipt] = useState({
    item_id: "",
    quantity: "",
    price: "",
  });
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (!canRead) return;
    let current = true;
    Promise.all([
      listInventoryItems(),
      canManage ? listInventoryBalances() : Promise.resolve([]),
      listInventoryBalances({ mine: true }),
    ])
      .then(([catalogue, company, personal]) => {
        if (!current) return;
        setItems(catalogue);
        setStock(company);
        setMine(personal);
        setFailed(false);
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [canManage, canRead, reloads]);

  // Skład ekipy tylko dla tego, kto wydaje: lista ludzi to nie jest widok magazynu.
  useEffect(() => {
    if (!canManage) return;
    let current = true;
    listMemberships()
      .then((people) => {
        if (current) setCrew(people.filter((one) => one.status === "active"));
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [canManage]);

  // Co ten człowiek ma już przy sobie — pytanie zadawane dokładnie w chwili
  // wydawania, więc i odpowiedź przychodzi dopiero tutaj.
  useEffect(() => {
    if (!issue.holder_id) return;
    let current = true;
    listInventoryBalances({ holderId: issue.holder_id })
      .then((rows) => {
        if (current) setHeld(rows);
      })
      .catch(() => {
        if (current) setHeld([]);
      });
    return () => {
      current = false;
    };
  }, [issue.holder_id, reloads]);

  const refresh = () => setReloads((value) => value + 1);
  const name = (balance: InventoryBalance) => balance.item_name;
  const low = (balance: InventoryBalance) =>
    Number(balance.minimum_quantity) > 0 &&
    Number(balance.quantity) <= Number(balance.minimum_quantity);

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
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="max-w-2xl text-muted-foreground">{t("description")}</p>
        </div>
        {canManage ? (
          <div className="flex flex-wrap gap-2">
            <Dialog onOpenChange={setReceiving} open={receiving}>
              <DialogTrigger render={<Button variant="outline" />}>
                <PackagePlusIcon aria-hidden="true" />
                {t("receive")}
              </DialogTrigger>
              <DialogContent closeLabel={common("close")}>
                <DialogHeader>
                  <DialogTitle>{t("receive")}</DialogTitle>
                  <DialogDescription>
                    {t("receiveDescription")}
                  </DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-4"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    try {
                      await receiveInventory({
                        item_id: receipt.item_id,
                        quantity: receipt.quantity,
                        // Cena z faktury, w groszach: po niej wycenia się rozchód.
                        unit_cost_minor: Math.round(
                          Number(receipt.price) * 100,
                        ),
                      });
                      setReceiving(false);
                      setReceipt({ item_id: "", quantity: "", price: "" });
                      setNotice(t("received"));
                      refresh();
                    } catch {
                      setFailed(true);
                    }
                  }}
                >
                  <Field>
                    <FieldLabel htmlFor="receipt-item">{t("item")}</FieldLabel>
                    <NativeSelect
                      id="receipt-item"
                      onChange={(event) =>
                        setReceipt({ ...receipt, item_id: event.target.value })
                      }
                      required
                      value={receipt.item_id}
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
                    <FieldLabel htmlFor="receipt-quantity">
                      {t("quantity")}
                    </FieldLabel>
                    <Input
                      id="receipt-quantity"
                      min="0"
                      onChange={(event) =>
                        setReceipt({ ...receipt, quantity: event.target.value })
                      }
                      required
                      step="0.01"
                      type="number"
                      value={receipt.quantity}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="receipt-price">
                      {t("unitPrice")}
                    </FieldLabel>
                    <Input
                      id="receipt-price"
                      min="0"
                      onChange={(event) =>
                        setReceipt({ ...receipt, price: event.target.value })
                      }
                      step="0.01"
                      type="number"
                      value={receipt.price}
                    />
                  </Field>
                  <Button
                    disabled={!receipt.item_id || !receipt.quantity}
                    type="submit"
                  >
                    {t("save")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>

            <Dialog onOpenChange={setIssuing} open={issuing}>
              <DialogTrigger render={<Button variant="outline" />}>
                <PackageCheckIcon aria-hidden="true" />
                {t("issue")}
              </DialogTrigger>
              <DialogContent closeLabel={common("close")}>
                <DialogHeader>
                  <DialogTitle>{t("issue")}</DialogTitle>
                  <DialogDescription>{t("issueDescription")}</DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-4"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    try {
                      await issueInventory(issue);
                      setIssuing(false);
                      setIssue({ item_id: "", holder_id: "", quantity: "" });
                      setHeld([]);
                      setNotice(t("issued"));
                      refresh();
                    } catch {
                      setFailed(true);
                    }
                  }}
                >
                  <Field>
                    <FieldLabel htmlFor="issue-holder">
                      {t("holder")}
                    </FieldLabel>
                    <NativeSelect
                      id="issue-holder"
                      onChange={(event) => {
                        // Czyścimy tu, a nie w efekcie: przy zmianie osoby
                        // stary stan nie ma prawa mignąć pod nowym nazwiskiem.
                        setHeld([]);
                        setIssue({ ...issue, holder_id: event.target.value });
                      }}
                      required
                      value={issue.holder_id}
                    >
                      <option value="">{t("pickHolder")}</option>
                      {crew.map((one) => (
                        <option key={one.user_id} value={one.user_id}>
                          {`${one.first_name} ${one.last_name}`.trim() ||
                            one.email}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                  {issue.holder_id ? (
                    <p className="text-sm text-muted-foreground">
                      {held.length
                        ? t("holderHas", {
                            stock: held
                              .map(
                                (balance) =>
                                  `${name(balance)} ${balance.quantity}`,
                              )
                              .join(", "),
                          })
                        : t("holderHasNothing")}
                    </p>
                  ) : null}
                  <Field>
                    <FieldLabel htmlFor="issue-item">{t("item")}</FieldLabel>
                    <NativeSelect
                      id="issue-item"
                      onChange={(event) =>
                        setIssue({ ...issue, item_id: event.target.value })
                      }
                      required
                      value={issue.item_id}
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
                    <FieldLabel htmlFor="issue-quantity">
                      {t("quantity")}
                    </FieldLabel>
                    <Input
                      id="issue-quantity"
                      min="0"
                      onChange={(event) =>
                        setIssue({ ...issue, quantity: event.target.value })
                      }
                      required
                      step="0.01"
                      type="number"
                      value={issue.quantity}
                    />
                  </Field>
                  <Button
                    disabled={
                      !issue.item_id || !issue.holder_id || !issue.quantity
                    }
                    type="submit"
                  >
                    {t("save")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>

            <Dialog onOpenChange={setAdding} open={adding}>
              <DialogTrigger render={<Button />}>
                <PlusIcon aria-hidden="true" />
                {t("addItem")}
              </DialogTrigger>
              <DialogContent closeLabel={common("close")}>
                <DialogHeader>
                  <DialogTitle>{t("addItem")}</DialogTitle>
                  <DialogDescription>
                    {t("addItemDescription")}
                  </DialogDescription>
                </DialogHeader>
                <form
                  className="space-y-4"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    try {
                      await createInventoryItem({
                        name: draft.name,
                        category: draft.category as (typeof CATEGORIES)[number],
                      });
                      setAdding(false);
                      setDraft({ name: "", category: "block" });
                      setNotice(t("itemAdded", { name: draft.name }));
                      refresh();
                    } catch {
                      setFailed(true);
                    }
                  }}
                >
                  <Field>
                    <FieldLabel htmlFor="item-name">{t("itemName")}</FieldLabel>
                    <Input
                      id="item-name"
                      onChange={(event) =>
                        setDraft({ ...draft, name: event.target.value })
                      }
                      required
                      value={draft.name}
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="item-category">
                      {t("category")}
                    </FieldLabel>
                    <NativeSelect
                      id="item-category"
                      onChange={(event) =>
                        setDraft({ ...draft, category: event.target.value })
                      }
                      value={draft.category}
                    >
                      {CATEGORIES.map((value) => (
                        <option key={value} value={value}>
                          {t(`category_${value}`)}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                  <Button disabled={!draft.name.trim()} type="submit">
                    {t("save")}
                  </Button>
                </form>
              </DialogContent>
            </Dialog>
          </div>
        ) : null}
      </header>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("myStock")}</h2>
          </CardTitle>
          <CardDescription>{t("myStockDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {mine.length === 0 ? (
            <p className="text-muted-foreground">{t("myStockEmpty")}</p>
          ) : (
            <ul className="divide-y">
              {mine.map((balance) => (
                <li
                  className="flex items-center justify-between gap-3 py-2"
                  key={balance.item_id}
                >
                  <span>{name(balance)}</span>
                  <span className="tabular-nums">
                    {balance.quantity} {t(`unit_${balance.unit}`)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {canManage ? (
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>{t("companyStock")}</h2>
            </CardTitle>
            <CardDescription>{t("companyStockDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            {stock.length === 0 ? (
              <p className="text-muted-foreground">{t("companyStockEmpty")}</p>
            ) : (
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{t("tableCaption")}</caption>
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-3 font-medium" scope="col">
                      {t("item")}
                    </th>
                    <th className="py-2 pr-3 font-medium" scope="col">
                      {t("category")}
                    </th>
                    <th className="py-2 text-right font-medium" scope="col">
                      {t("quantity")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {stock.map((balance) => (
                    <tr key={balance.item_id}>
                      <th
                        className="py-3 pr-3 text-left font-normal"
                        scope="row"
                      >
                        {name(balance)}
                      </th>
                      <td className="py-3 pr-3">
                        {t(`category_${balance.category}`)}
                      </td>
                      <td className="py-3 text-right tabular-nums">
                        {balance.quantity} {t(`unit_${balance.unit}`)}
                        {low(balance) ? (
                          <Badge className="ml-2" variant="outline">
                            {t("low")}
                          </Badge>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      ) : null}

      {failed ? (
        <p className="text-sm text-destructive" role="alert">
          {t("failed")}
        </p>
      ) : null}
      <p aria-live="polite" className="text-sm text-success-foreground">
        {notice}
      </p>
    </div>
  );
}
