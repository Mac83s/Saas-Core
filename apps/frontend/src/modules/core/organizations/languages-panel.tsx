"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { PlusIcon } from "lucide-react";

import {
  changePublicLocales,
  getPublicLocales,
  previewPublicLocales,
  type PublicLocales,
  type PublicLocalesPlan,
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
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelPage } from "#components/panel/panel-page";
import { companyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { organizationErrorMessage } from "./problem";

type Row = { code: string; name: string; first: boolean; protectedBy?: string };

/**
 * Ustawienia › Języki i tłumaczenia (ADR-071 pkt 4–7): the languages the
 * company speaks to its customers, in order — the first is its customers'
 * language. Adding counts against the plan; removing and reordering always
 * work, and a removal shows first which addresses start to redirect.
 */
export function LanguagesPanel() {
  const t = useTranslations("Languages");
  const settings = useTranslations("Settings");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const [state, setState] = useState<PublicLocales>();
  const [failed, setFailed] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState("");
  const [removal, setRemoval] = useState<{ code: string; plan: PublicLocalesPlan }>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string>();

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setState(await getPublicLocales());
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    void getPublicLocales()
      .then((value) => {
        if (mounted) setState(value);
      })
      .catch(() => {
        if (mounted) setFailed(true);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const nameOf = (code: string) =>
    state?.offered.find((item) => item.code === code)?.native_name ??
    companyLocales(undefined, [code])[0]?.name ??
    code;
  const rows: Row[] = (state?.public_locales ?? []).map((code, index) => ({
    code,
    name: nameOf(code),
    first: index === 0,
    protectedBy: state?.protected[code],
  }));
  const addable = (state?.offered ?? []).filter(
    (item) => !state?.public_locales.includes(item.code),
  );

  const save = useCallback(
    async (locales: string[], done: string) => {
      if (!state) return;
      setBusy(true);
      setProblem(undefined);
      try {
        await changePublicLocales(
          { public_locales: locales, expected_version: state.version },
          crypto.randomUUID(),
        );
        setNotice(done);
        setAdding(false);
        setRemoval(undefined);
        await load();
      } catch (error) {
        setProblem(organizationErrorMessage(error, t("saveError")));
      } finally {
        setBusy(false);
      }
    },
    [load, state, t],
  );

  const askRemoval = useCallback(
    async (code: string) => {
      if (!state) return;
      setProblem(undefined);
      try {
        const plan = await previewPublicLocales({
          public_locales: state.public_locales.filter((item) => item !== code),
          expected_version: state.version,
        });
        setRemoval({ code, plan });
      } catch (error) {
        setProblem(organizationErrorMessage(error, t("saveError")));
      }
    },
    [state, t],
  );

  const columns: ColumnDef<Row, unknown>[] = [
    {
      id: "language",
      accessorKey: "name",
      header: t("colLanguage"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{row.name}</span>
          <span className="text-muted-foreground uppercase">{row.code}</span>
        </span>
      ),
    },
    {
      id: "role",
      header: t("colRole"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-wrap gap-2">
          {row.first ? <Badge>{t("customersLanguage")}</Badge> : null}
          {row.protectedBy ? (
            <Badge variant="outline">{t(`protected.${row.protectedBy}`)}</Badge>
          ) : null}
        </span>
      ),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const items = [
          ...(row.first
            ? []
            : [
                {
                  label: t("makeFirst"),
                  onSelect: () =>
                    void save(
                      [row.code, ...(state?.public_locales ?? []).filter((c) => c !== row.code)],
                      t("madeFirst", { language: row.name }),
                    ),
                },
              ]),
          ...(row.protectedBy || rows.length < 2
            ? []
            : [
                {
                  label: t("remove"),
                  destructive: true,
                  onSelect: () => void askRemoval(row.code),
                },
              ]),
        ];
        return items.length ? (
          <RowActions items={items} label={t("actionsFor", { language: row.name })} />
        ) : null;
      },
    },
  ];

  const limit = state?.limit;
  return (
    <PanelPage
      actions={
        addable.length ? (
          <Button
            onClick={() => {
              setProblem(undefined);
              setAdded(addable[0]?.code ?? "");
              setAdding(true);
            }}
          >
            <PlusIcon aria-hidden="true" />
            {t("add")}
          </Button>
        ) : null
      }
      description={t("description")}
      eyebrow={settings("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <>
          {problem && !adding && !removal ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("caption")}
            columns={columns}
            data={rows}
            getRowId={(row) => row.code}
            labels={labels}
            loading={!state}
          />
          {limit && limit.additional_max !== null ? (
            <p className="text-sm text-muted-foreground">
              {t("limit", { count: limit.additional_max })}
            </p>
          ) : null}
        </>
      )}

      <Dialog onOpenChange={(next) => (next ? undefined : setAdding(false))} open={adding}>
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("add")}</DialogTitle>
            <DialogDescription>{t("addDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void save(
                [...(state?.public_locales ?? []), added],
                t("added", { language: nameOf(added) }),
              );
            }}
          >
            <Field>
              <FieldLabel htmlFor="language-add">{t("colLanguage")}</FieldLabel>
              <NativeSelect
                id="language-add"
                onChange={(event) => setAdded(event.target.value)}
                value={added}
              >
                {addable.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.native_name}
                  </option>
                ))}
              </NativeSelect>
              {limit && !limit.allowed ? (
                <FieldDescription>{t("addBlocked")}</FieldDescription>
              ) : null}
            </Field>
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>{common("cancel")}</DialogClose>
              <Button disabled={busy || !added} type="submit">
                {t("add")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(next) => (next ? undefined : setRemoval(undefined))}
        open={removal !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {t("removeTitle", { language: removal ? nameOf(removal.code) : "" })}
            </DialogTitle>
            <DialogDescription>{t("removeDescription")}</DialogDescription>
          </DialogHeader>
          {removal && removal.plan.redirects.length ? (
            <ul aria-label={t("redirectsLabel")} className="space-y-1 text-sm">
              {removal.plan.redirects.map((item) => (
                <li className="wrap-anywhere" key={item.path}>
                  {item.target
                    ? t("redirect", { path: item.path, target: item.target })
                    : t("redirectGone", { path: item.path })}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noRedirects")}</p>
          )}
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>{common("cancel")}</DialogClose>
            <Button
              disabled={busy}
              onClick={() =>
                removal &&
                void save(
                  removal.plan.public_locales,
                  t("removed", { language: nameOf(removal.code) }),
                )
              }
              variant="destructive"
            >
              {t("remove")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
