"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  EyeIcon,
  ExternalLinkIcon,
  HomeIcon,
  LinkIcon,
  PencilIcon,
  RotateCcwIcon,
  Trash2Icon,
} from "lucide-react";
import {
  ApiProblemError,
  deleteSitePage,
  listPageIncomingLinks,
  listSitePages,
  restoreSitePage,
  setPageType,
  type PageIncomingLink,
  type PageListItem,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  DataTableSearch,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { useDataTableLabels } from "#lib/data-table-labels";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { PageUrlDialog } from "./page-url";
import { sitesErrorMessage } from "./problem";

type Show = "live" | "deleted";

/** A page's address in the site's own language is `/<slug>/`. */
const slugOf = (path: string) => path.replace(/^\/|\/$/g, "");

/** Where visitors find the page: the home page's slug redirects to the root. */
const publicPath = (page: PageListItem) =>
  page.page_type === "homepage" && page.path ? "/" : page.path;

/**
 * The site's pages on the panel's list standard (ADR-054, ADR-057; decision 7,
 * 30.09): what each page is, where it answers, whether visitors see it and in
 * which version, and whether the menu has it. Editing is always in sight;
 * deleting asks first and says what happens to the address and the links.
 * Deleted pages wait under the „Usunięte” filter and can be restored.
 */
export function SitePagesTable({
  siteId,
  defaultLocale,
  pages,
  loading,
  publicBaseUrl,
  onEdit,
  onPreview,
  onChanged,
}: {
  siteId: string;
  defaultLocale: string;
  pages: readonly PageListItem[];
  loading: boolean;
  /** The published site's base address, when it has one. */
  publicBaseUrl: string | null;
  onEdit: (page: PageListItem) => void;
  onPreview: (page: PageListItem) => void;
  /** The list changed on the server: reload it (and anything derived). */
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites.pagesList");
  const types = useTranslations("Sites");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [show, setShow] = useState<Show>("live");
  const [search, setSearch] = useState("");
  const [deleted, setDeleted] = useState<PageListItem[]>();
  const [deleting, setDeleting] = useState<PageListItem>();
  const [moving, setMoving] = useState<PageListItem>();
  const [restoring, setRestoring] = useState<PageListItem>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [reloads, setReloads] = useState(0);
  const restoreReceipt = useRef<MutationReceipt | undefined>(undefined);

  useEffect(() => {
    if (show !== "deleted") return;
    let current = true;
    listSitePages(siteId, "deleted")
      .then((result) => {
        if (current) setDeleted(result.items);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, types));
      });
    return () => {
      current = false;
    };
  }, [show, siteId, reloads, types]);

  const rows = useMemo(() => {
    const source = show === "live" ? pages : (deleted ?? []);
    const query = search.trim().toLocaleLowerCase();
    return query
      ? source.filter((page) =>
          `${page.name} ${page.title ?? ""} ${page.path ?? ""}`
            .toLocaleLowerCase()
            .includes(query),
        )
      : [...source];
  }, [show, pages, deleted, search]);

  const livePages = pages.length;

  async function markHome(page: PageListItem) {
    setProblem(undefined);
    try {
      await setPageType(page.id, "homepage");
      await onChanged();
      setNotice(t("homeSet", { name: page.name }));
    } catch (error) {
      setProblem(sitesErrorMessage(error, types));
    }
  }

  /** Rejects with the server's problem; the caller says it where it was asked. */
  async function restore(page: PageListItem, slug?: string) {
    const slugs = slug ? { [defaultLocale]: slug } : undefined;
    await restoreSitePage(
      page.id,
      mutationKey(restoreReceipt, `page-restore-${page.id}`, {
        page: page.id,
        slugs,
      }),
      slugs,
    );
    restoreReceipt.current = undefined;
    setRestoring(undefined);
    setReloads((value) => value + 1);
    await onChanged();
    setNotice(t("restored", { name: page.name }));
  }

  async function restoreFromRow(page: PageListItem) {
    setProblem(undefined);
    try {
      await restore(page);
    } catch (error) {
      restoreReceipt.current = undefined;
      // Another page took its address meanwhile: ask for a new one.
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "page_restore_slug_taken"
      )
        setRestoring(page);
      else setProblem(sitesErrorMessage(error, types));
    }
  }

  const status = (page: PageListItem) => {
    if (page.published_version == null)
      return <Badge variant="secondary">{t("statusDraft")}</Badge>;
    if (page.version > page.published_version)
      return <Badge variant="outline">{t("statusChanged")}</Badge>;
    return <Badge>{t("statusPublished")}</Badge>;
  };

  const liveColumns: ColumnDef<PageListItem, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colName"),
      meta: { primary: true },
      cell: ({ row: { original: page } }) => (
        <>
          <p className="font-medium wrap-anywhere">{page.name}</p>
          {page.title && page.title !== page.name ? (
            <p className="text-xs text-muted-foreground wrap-anywhere">
              {page.title}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "path",
      accessorFn: (page) => publicPath(page) ?? "",
      header: t("colPath"),
      cell: ({ row: { original: page } }) =>
        publicPath(page) ? (
          <code className="text-sm wrap-anywhere">{publicPath(page)}</code>
        ) : (
          <span className="text-muted-foreground">{t("noPath")}</span>
        ),
    },
    {
      id: "type",
      accessorKey: "page_type",
      header: t("colType"),
      cell: ({ row: { original: page } }) =>
        types(`pageType_${page.page_type}`),
    },
    {
      id: "status",
      accessorFn: (page) => page.published_version ?? -1,
      header: t("colStatus"),
      cell: ({ row: { original: page } }) => status(page),
    },
    {
      id: "menu",
      accessorKey: "in_navigation",
      header: t("colMenu"),
      cell: ({ row: { original: page } }) =>
        page.in_navigation ? t("inMenu") : "—",
    },
    {
      id: "updated",
      accessorKey: "updated_at",
      header: t("colUpdated"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: page } }) =>
        format.dateTime(new Date(page.updated_at), {
          dateStyle: "medium",
          timeStyle: "short",
        }),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: page } }) => {
        const items: RowAction[] = [
          // Editing is always in sight (ADR-057).
          {
            label: t("edit"),
            icon: <PencilIcon aria-hidden="true" />,
            inline: true,
            main: true,
            onSelect: () => onEdit(page),
          },
          {
            label: t("preview"),
            icon: <EyeIcon aria-hidden="true" />,
            onSelect: () => onPreview(page),
          },
        ];
        if (publicBaseUrl && page.published_version != null && page.path)
          items.push({
            label: t("openPublic"),
            icon: <ExternalLinkIcon aria-hidden="true" />,
            link: (
              <a
                href={`${publicBaseUrl}${publicPath(page)}`}
                rel="noreferrer"
                target="_blank"
              />
            ),
          });
        if (page.page_type !== "homepage")
          items.push({
            label: t("makeHome"),
            icon: <HomeIcon aria-hidden="true" />,
            onSelect: () => void markHome(page),
          });
        // The home page answers at the root whatever its slug says.
        if (page.path && page.page_type !== "homepage")
          items.push({
            label: t("changeAddress"),
            icon: <LinkIcon aria-hidden="true" />,
            onSelect: () => setMoving(page),
          });
        // The home page and the last page stay (decision 7.4).
        if (page.page_type !== "homepage" && livePages > 1)
          items.push({
            label: t("delete"),
            icon: <Trash2Icon aria-hidden="true" />,
            destructive: true,
            separated: true,
            onSelect: () => setDeleting(page),
          });
        return (
          <RowActions
            items={items}
            label={t("actionsFor", { name: page.name })}
          />
        );
      },
    },
  ];

  const deletedColumns: ColumnDef<PageListItem, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colName"),
      meta: { primary: true },
      cell: ({ row: { original: page } }) => (
        <p className="font-medium wrap-anywhere">{page.name}</p>
      ),
    },
    {
      id: "path",
      accessorFn: (page) => page.path ?? "",
      header: t("colFormerPath"),
      cell: ({ row: { original: page } }) =>
        page.path ? (
          <code className="text-sm wrap-anywhere">{page.path}</code>
        ) : (
          "—"
        ),
    },
    {
      id: "deleted",
      accessorFn: (page) => page.deleted_at ?? "",
      header: t("colDeleted"),
      meta: { className: "tabular-nums" },
      cell: ({ row: { original: page } }) =>
        page.deleted_at
          ? format.dateTime(new Date(page.deleted_at), {
              dateStyle: "medium",
              timeStyle: "short",
            })
          : "—",
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: page } }) => (
        <RowActions
          items={[
            {
              label: t("restore"),
              icon: <RotateCcwIcon aria-hidden="true" />,
              inline: true,
              onSelect: () => void restoreFromRow(page),
            },
          ]}
          label={t("actionsFor", { name: page.name })}
        />
      ),
    },
  ];

  return (
    <div className="space-y-3">
      {notice ? (
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DataTable
        caption={t(show === "live" ? "caption" : "captionDeleted")}
        columns={show === "live" ? liveColumns : deletedColumns}
        data={rows}
        getRowId={(page) => page.id}
        labels={{
          ...labels,
          empty: t(
            search.trim()
              ? "noResults"
              : show === "live"
                ? "empty"
                : "emptyDeleted",
          ),
          loading: t("loading"),
        }}
        loading={show === "live" ? loading : deleted === undefined}
        toolbar={
          <DataTableSearch
            id="site-pages-search"
            label={t("search")}
            onChange={setSearch}
            value={search}
          />
        }
        activeFilters={show === "deleted" ? 1 : 0}
        filters={
          <DataTableFilter
            id="site-pages-show"
            label={t("show")}
            onChange={(event) => {
              setShow(event.target.value as Show);
              setNotice("");
            }}
            value={show}
          >
            <option value="live">{t("showLive")}</option>
            <option value="deleted">{t("showDeleted")}</option>
          </DataTableFilter>
        }
      />
      {deleting ? (
        <DeletePageDialog
          key={deleting.id}
          onClose={() => setDeleting(undefined)}
          onDeleted={async (redirects) => {
            const name = deleting.name;
            setDeleting(undefined);
            setReloads((value) => value + 1);
            await onChanged();
            setNotice(
              redirects.length
                ? t("deletedRedirected", {
                    name,
                    from: redirects[0]!.from_path,
                    to: redirects[0]!.to_path,
                  })
                : t("deleted", { name }),
            );
          }}
          page={deleting}
          pages={pages}
        />
      ) : null}
      {moving?.path ? (
        <PageUrlDialog
          locale={defaultLocale}
          onChanged={onChanged}
          onOpenChange={(next) => {
            if (!next) setMoving(undefined);
          }}
          open
          pageId={moving.id}
          slug={slugOf(moving.path)}
        />
      ) : null}
      {restoring ? (
        <RestoreAddressDialog
          onClose={() => setRestoring(undefined)}
          onRestore={async (slug) => {
            try {
              await restore(restoring, slug);
            } catch (error) {
              restoreReceipt.current = undefined;
              throw error;
            }
          }}
          page={restoring}
        />
      ) : null}
    </div>
  );
}

/** Deleting a page: whether visitors see it and where its address will lead,
 *  which pages link to it, and that the menu loses it (decision 7.1–7.3). */
function DeletePageDialog({
  page,
  pages,
  onClose,
  onDeleted,
}: {
  page: PageListItem;
  pages: readonly PageListItem[];
  onClose: () => void;
  onDeleted: (
    redirects: { from_path: string; to_path: string }[],
  ) => Promise<void>;
}) {
  const t = useTranslations("Sites.pagesList");
  const types = useTranslations("Sites");
  const common = useTranslations("Common");
  const published = page.published_version != null;
  const targets = pages.filter(
    (item) => item.id !== page.id && item.published_version != null,
  );
  const home = targets.find((item) => item.page_type === "homepage");
  const [target, setTarget] = useState(home?.id ?? targets[0]?.id ?? "");
  const [links, setLinks] = useState<PageIncomingLink[]>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const receipt = useRef<MutationReceipt | undefined>(undefined);

  useEffect(() => {
    let current = true;
    listPageIncomingLinks(page.id)
      .then((found) => {
        if (current) setLinks(found);
      })
      .catch(() => {
        if (current) setLinks([]);
      });
    return () => {
      current = false;
    };
  }, [page.id]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    const input = {
      expected_version: page.version,
      redirect_to_page_id: published && target ? target : null,
    };
    try {
      const result = await deleteSitePage(
        page.id,
        input,
        mutationKey(receipt, `page-delete-${page.id}`, input),
      );
      await onDeleted(result.redirects);
    } catch (error) {
      setProblem(sitesErrorMessage(error, types));
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
      open
    >
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("deleteTitle", { name: page.name })}</DialogTitle>
          <DialogDescription>
            {t(published ? "deletePublished" : "deleteDraft")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 text-sm">
          {published && page.path && targets.length ? (
            <Field>
              <FieldLabel htmlFor="delete-page-redirect">
                {t("redirectLabel", { path: page.path })}
              </FieldLabel>
              <NativeSelect
                id="delete-page-redirect"
                onChange={(event) => setTarget(event.target.value)}
                value={target}
              >
                {targets.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.page_type === "homepage"
                      ? t("redirectHome", { name: item.name })
                      : `${item.name} (${item.path ?? ""})`}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          ) : null}
          {page.in_navigation ? <p>{t("deleteMenu")}</p> : null}
          {links === undefined ? (
            <p className="text-muted-foreground">{t("linksLoading")}</p>
          ) : links.length ? (
            <div>
              <p>{t("linksTitle")}</p>
              <ul className="mt-1 list-disc pl-5">
                {links.map((link) => (
                  <li key={link.page_id}>
                    {t("linksItem", { name: link.name, count: link.links })}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-muted-foreground">
                {t(published ? "linksRedirected" : "linksBroken")}
              </p>
            </div>
          ) : (
            <p className="text-muted-foreground">{t("linksNone")}</p>
          )}
          <p className="text-muted-foreground">{t("deleteRestoreHint")}</p>
          {problem ? (
            <p className="text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button disabled={busy} onClick={onClose} variant="outline">
            {common("cancel")}
          </Button>
          <Button
            disabled={busy || links === undefined}
            onClick={() => void confirm()}
            variant="destructive"
          >
            <Trash2Icon aria-hidden="true" />
            {t("deleteConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** A restored page whose old address another page took gets a new one. */
function RestoreAddressDialog({
  page,
  onClose,
  onRestore,
}: {
  page: PageListItem;
  onClose: () => void;
  onRestore: (slug: string) => Promise<void>;
}) {
  const t = useTranslations("Sites.pagesList");
  const common = useTranslations("Common");
  const types = useTranslations("Sites");
  const former = page.path ? slugOf(page.path) : "";
  const [slug, setSlug] = useState(former ? `${former}-2` : "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const valid = /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
      open
    >
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>
            {t("restoreAddressTitle", { name: page.name })}
          </DialogTitle>
          <DialogDescription>
            {t("restoreAddressDescription", { path: page.path ?? "" })}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!valid) return;
            setBusy(true);
            setProblem(undefined);
            onRestore(slug).catch((error: unknown) => {
              setProblem(sitesErrorMessage(error, types));
              setBusy(false);
            });
          }}
        >
          <Field>
            <FieldLabel htmlFor="restore-page-slug">
              {t("restoreAddressLabel")}
            </FieldLabel>
            <Input
              aria-invalid={!valid}
              id="restore-page-slug"
              onChange={(event) => setSlug(event.target.value)}
              value={slug}
            />
          </Field>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <Button disabled={busy || !valid} type="submit">
              <RotateCcwIcon aria-hidden="true" />
              {t("restore")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
