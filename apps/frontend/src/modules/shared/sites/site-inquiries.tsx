"use client";

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocale, useTranslations } from "next-intl";
import { MailIcon, PhoneIcon, RefreshCwIcon } from "lucide-react";

import {
  ApiProblemError,
  listSiteInquiries,
  listSites,
  markSiteInquiryRead,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@saas-core/ui/components/sheet";

import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { useMedia } from "#lib/use-media";

type Site = Awaited<ReturnType<typeof listSites>>["items"][number];
type Inquiry = Awaited<ReturnType<typeof listSiteInquiries>>["items"][number];
type Failure = "loadError" | "permission" | "plan";

function failureKey(error: unknown): Failure {
  if (error instanceof ApiProblemError) {
    if (error.problem.code === "entitlement_required") return "plan";
    if (error.problem.status === 403) return "permission";
  }
  return "loadError";
}

/** Mounted only when the organization has site editing access. The API enforces
 * the same permission and entitlement for every list/read operation. */
/** `labelledBy`: the page's own title names the list; its header is left out. */
export function SiteInquiries({ labelledBy }: { labelledBy?: string } = {}) {
  const t = useTranslations("SiteInquiries");
  const id = useId();
  const [sites, setSites] = useState<Site[]>();
  const [selectedSite, setSelectedSite] = useState("");
  const [failure, setFailure] = useState<Failure>();
  const [loading, setLoading] = useState(true);
  const request = useRef(0);

  const loadSites = useCallback(async () => {
    const current = ++request.current;
    setLoading(true);
    setFailure(undefined);
    try {
      const result = await listSites();
      if (current !== request.current) return;
      setSites(result.items);
      setSelectedSite((previous) =>
        result.items.some((site) => site.id === previous)
          ? previous
          : (result.items[0]?.id ?? ""),
      );
    } catch (error) {
      if (current === request.current) setFailure(failureKey(error));
    } finally {
      if (current === request.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial loading state is rendered before the asynchronous request settles.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSites();
    return () => {
      request.current += 1;
    };
  }, [loadSites]);

  return (
    <section
      aria-labelledby={labelledBy ?? `${id}-heading`}
      className="space-y-5"
    >
      {labelledBy ? null : (
        <header className="space-y-1">
          <h2
            className="text-xl font-semibold tracking-tight"
            id={`${id}-heading`}
          >
            {t("title")}
          </h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            {t("description")}
          </p>
        </header>
      )}
      {loading ? (
        <p role="status">{t("loading")}</p>
      ) : failure ? (
        <FailureMessage failure={failure} onRetry={() => void loadSites()} />
      ) : !sites?.length ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          {t("emptySites")}
        </p>
      ) : (
        // A changed site remounts the inbox, so an older response or
        // selection can never reveal a message from the previous website.
        // The site is a filter in the list's bar, and only where there is a
        // choice (UX-050).
        <SiteInbox
          key={selectedSite}
          siteFilter={
            sites.length > 1 ? (
              <DataTableFilter
                id={`${id}-site`}
                label={t("site")}
                onChange={(event) => setSelectedSite(event.target.value)}
                value={selectedSite}
              >
                {sites.map((site) => (
                  <option key={site.id} value={site.id}>
                    {site.name}
                  </option>
                ))}
              </DataTableFilter>
            ) : null
          }
          siteId={selectedSite}
        />
      )}
    </section>
  );
}

function FailureMessage({
  failure,
  onRetry,
}: {
  failure: Failure;
  onRetry: () => void;
}) {
  const t = useTranslations("SiteInquiries");
  return (
    <div className="space-y-3 rounded-xl border p-4">
      <p role="alert">{t(failure)}</p>
      {failure === "loadError" ? (
        <Button onClick={onRetry} type="button" variant="outline">
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}

function SiteInbox({
  siteId,
  siteFilter,
}: {
  siteId: string;
  siteFilter?: ReactNode;
}) {
  const t = useTranslations("SiteInquiries");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [items, setItems] = useState<Inquiry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>();
  const [failure, setFailure] = useState<Failure>();
  const [loading, setLoading] = useState(true);
  const [readFailure, setReadFailure] = useState<string>();
  const [reading, setReading] = useState<string>();
  const latestRequest = useRef(0);
  const retryCursor = useRef<string | undefined>(undefined);
  const active = useRef(true);
  const readKeys = useRef(new Map<string, string>());
  const pendingReads = useRef(new Set<string>());
  const selected = items.find((item) => item.id === selectedId);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  // Below the two-column width a message opens in a sheet over the list,
  // not 1700 px under it (UX-049).
  const narrow = useMedia("(max-width: 1279px)");

  useEffect(() => {
    if (!selectedId || narrow) return;
    detailHeading.current?.focus({ preventScroll: true });
  }, [narrow, selectedId]);

  const load = useCallback(
    async (nextCursor?: string) => {
      const request = ++latestRequest.current;
      retryCursor.current = nextCursor;
      setLoading(true);
      setFailure(undefined);
      try {
        const result = await listSiteInquiries(
          siteId,
          nextCursor ? { cursor: nextCursor } : undefined,
        );
        if (!active.current || request !== latestRequest.current) return;
        setItems((previous) => {
          if (!nextCursor) return result.items;
          const ids = new Set(previous.map((item) => item.id));
          return [
            ...previous,
            ...result.items.filter((item) => !ids.has(item.id)),
          ];
        });
        setCursor(result.next_cursor ?? null);
      } catch (error) {
        if (active.current && request === latestRequest.current) {
          const failure = failureKey(error);
          setFailure(failure);
          // Permission/plan revocation also clears previously fetched personal
          // data instead of leaving an obsolete detail visible under the error.
          if (failure !== "loadError") {
            setItems([]);
            setSelectedId(undefined);
          }
        }
      } finally {
        if (active.current && request === latestRequest.current)
          setLoading(false);
      }
    },
    [siteId],
  );

  useEffect(() => {
    active.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    return () => {
      active.current = false;
      latestRequest.current += 1;
    };
  }, [load]);

  async function markRead(item: Inquiry) {
    if (item.read_at || pendingReads.current.has(item.id)) return;
    pendingReads.current.add(item.id);
    setReading(item.id);
    setReadFailure(undefined);
    let key = readKeys.current.get(item.id);
    if (!key) {
      key = crypto.randomUUID();
      readKeys.current.set(item.id, key);
    }
    try {
      const updated = await markSiteInquiryRead(item.id, key);
      if (active.current)
        setItems((previous) =>
          previous.map((entry) => (entry.id === updated.id ? updated : entry)),
        );
    } catch (error) {
      if (active.current) {
        if (error instanceof ApiProblemError && error.problem.status === 403) {
          setItems([]);
          setSelectedId(undefined);
          setFailure(failureKey(error));
        } else {
          setReadFailure(item.id);
        }
      }
    } finally {
      pendingReads.current.delete(item.id);
      if (active.current)
        setReading((previous) => (previous === item.id ? undefined : previous));
    }
  }

  const date = (value: string) =>
    new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(value));

  const columns: ColumnDef<Inquiry, unknown>[] = [
    {
      id: "from",
      accessorKey: "name",
      header: t("from"),
      meta: { primary: true },
      // The name opens the message beside the list; the row shows no content.
      cell: ({ row: { original: item } }) => (
        <div className="flex flex-wrap items-center gap-2">
          <button
            aria-pressed={selectedId === item.id}
            className="rounded-sm text-left font-semibold wrap-anywhere hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-pressed:text-primary"
            onClick={() => {
              setSelectedId(item.id);
              void markRead(item);
            }}
            type="button"
          >
            {item.name}
          </button>
          {selectedId === item.id ? (
            <Badge variant="outline">{t("opened")}</Badge>
          ) : null}
        </div>
      ),
    },
    {
      id: "state",
      accessorFn: (item) => t(item.read_at ? "read" : "unread"),
      header: t("state"),
      cell: ({ row: { original: item } }) =>
        !item.read_at ? (
          <Badge variant="info">{t("unread")}</Badge>
        ) : (
          <span className="text-muted-foreground">{t("read")}</span>
        ),
    },
    {
      id: "received",
      accessorKey: "created_at",
      header: t("received"),
      cell: ({ row: { original: item } }) => (
        <time className="text-muted-foreground" dateTime={item.created_at}>
          {date(item.created_at)}
        </time>
      ),
    },
    {
      id: "source",
      accessorKey: "page_path",
      header: t("source"),
      cell: ({ row: { original: item } }) => (
        <span className="break-all text-muted-foreground">
          {item.page_path}
        </span>
      ),
    },
  ];

  const detailHeader = selected ? (
    <p className="text-sm text-muted-foreground">
      {t("received")}:{" "}
      <time dateTime={selected.created_at}>{date(selected.created_at)}</time>
    </p>
  ) : null;
  const detailBody = selected ? (
    <>
      <dl className="grid gap-3 text-sm">
        {/* A call-back form may arrive without an e-mail or a message; only
            what the visitor gave is shown. */}
        {selected.email ? (
          <div>
            <dt className="text-muted-foreground">{t("email")}</dt>
            <dd className="break-all">{selected.email}</dd>
          </div>
        ) : null}
        {selected.phone ? (
          <div>
            <dt className="text-muted-foreground">{t("phone")}</dt>
            <dd className="break-all">{selected.phone}</dd>
          </div>
        ) : null}
        <div>
          <dt className="text-muted-foreground">{t("source")}</dt>
          <dd className="break-all">{selected.page_path}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("emailStatus")}</dt>
          <dd>{t(emailStatusKey(selected.email_status))}</dd>
        </div>
      </dl>
      {selected.message ? (
        <div className="space-y-2 border-t pt-4">
          <h4 className="font-medium">{t("message")}</h4>
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed [overflow-wrap:anywhere]">
            {selected.message}
          </p>
        </div>
      ) : null}
      {readFailure === selected.id ? (
        <p role="alert" className="text-sm text-destructive">
          {t("readError")}
        </p>
      ) : null}
      {!selected.read_at ? (
        <Button
          disabled={reading === selected.id}
          onClick={() => void markRead(selected)}
          type="button"
          variant="outline"
        >
          {t(reading === selected.id ? "markingRead" : "markRead")}
        </Button>
      ) : null}
      {selected.email ? (
        <div className="space-y-2 border-t pt-4">
          <a
            className={buttonVariants()}
            href={`mailto:${encodeURIComponent(selected.email)}`}
          >
            <MailIcon aria-hidden="true" />
            {t("reply")}
          </a>
          <p className="text-xs text-muted-foreground">{t("replyHint")}</p>
        </div>
      ) : selected.phone ? (
        <div className="space-y-2 border-t pt-4">
          <a
            className={buttonVariants()}
            href={`tel:${selected.phone.replace(/[^\d+]/g, "")}`}
          >
            <PhoneIcon aria-hidden="true" />
            {t("call")}
          </a>
          <p className="text-xs text-muted-foreground">{t("callHint")}</p>
        </div>
      ) : null}
    </>
  ) : null;

  return (
    <div className="space-y-4">
      {failure ? (
        <FailureMessage
          failure={failure}
          onRetry={() => void load(retryCursor.current)}
        />
      ) : null}
      {/* A refusal leaves nothing to list; a failed page keeps what came. */}
      {failure && !items.length ? null : (
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-3">
            <DataTable
              caption={t("listLabel")}
              columns={columns}
              data={items}
              // Nothing yet says where inquiries come from and leads there,
              // in the list's own empty state (UX-050).
              emptyAction={
                <Link
                  className="font-medium text-primary hover:underline"
                  href="/panel/sites"
                >
                  {t("emptyAction")}
                </Link>
              }
              getRowId={(item) => item.id}
              labels={{ ...labels, empty: t("empty") }}
              loading={loading}
              // The API pages the inbox ("load older" below); the table shows
              // every inquiry loaded so far instead of paging them again.
              pageSize={Number.MAX_SAFE_INTEGER}
              toolbar={
                <>
                  {siteFilter}
                  <Button
                    aria-label={t("refresh")}
                    disabled={loading}
                    onClick={() => void load()}
                    title={t("refresh")}
                    type="button"
                    size="icon"
                    variant="ghost"
                  >
                    <RefreshCwIcon aria-hidden="true" />
                  </Button>
                </>
              }
            />
            {cursor ? (
              <Button
                className="w-full"
                disabled={loading}
                onClick={() => void load(cursor)}
                type="button"
                variant="outline"
              >
                {t("loadMore")}
              </Button>
            ) : null}
          </div>
          {narrow ? null : selected ? (
            <article
              aria-label={selected.name}
              // Stays in view beside a long list on a wide screen.
              className="min-w-0 space-y-5 rounded-xl border bg-card p-5 sm:p-6 xl:sticky xl:top-4"
            >
              <header className="space-y-1">
                <h3
                  className="break-words text-xl font-semibold"
                  ref={detailHeading}
                  tabIndex={-1}
                >
                  {selected.name}
                </h3>
                {detailHeader}
              </header>
              {detailBody}
            </article>
          ) : items.length ? (
            // The placeholder belongs to the wide layout only (UX-049).
            <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
              {t("choose")}
            </p>
          ) : null}
        </div>
      )}
      {narrow ? (
        <Sheet
          onOpenChange={(open) => (open ? null : setSelectedId(undefined))}
          open={Boolean(selected)}
        >
          <SheetContent closeLabel={t("close")}>
            <SheetHeader>
              <SheetTitle className="break-words">{selected?.name}</SheetTitle>
              {detailHeader}
            </SheetHeader>
            <SheetBody className="space-y-5">{detailBody}</SheetBody>
          </SheetContent>
        </Sheet>
      ) : null}
    </div>
  );
}

function emailStatusKey(status: Inquiry["email_status"]) {
  const keys = {
    unavailable: "emailUnavailable",
    queued: "emailQueued",
    processing: "emailProcessing",
    sent: "emailSent",
    delivered: "emailDelivered",
    bounced: "emailBounced",
    complained: "emailComplained",
    suppressed: "emailSuppressed",
    dead_letter: "emailDeadLetter",
  } as const;
  return status && status in keys
    ? keys[status as keyof typeof keys]
    : "emailUnknown";
}
