"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { MailIcon, RefreshCwIcon } from "lucide-react";

import {
  ApiProblemError,
  listSiteInquiries,
  listSites,
  markSiteInquiryRead,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";

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
export function SiteInquiries() {
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
    <section aria-labelledby={`${id}-heading`} className="space-y-5">
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
      {loading ? (
        <p role="status">{t("loading")}</p>
      ) : failure ? (
        <FailureMessage failure={failure} onRetry={() => void loadSites()} />
      ) : !sites?.length ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          {t("emptySites")}
        </p>
      ) : (
        <>
          <div className="max-w-md space-y-2">
            <Label htmlFor={`${id}-site`}>{t("site")}</Label>
            <NativeSelect
              id={`${id}-site`}
              value={selectedSite}
              onChange={(event) => setSelectedSite(event.target.value)}
            >
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </NativeSelect>
          </div>
          {/* A changed site remounts the inbox, so an older response or selection
              can never reveal a message from the previous website. */}
          <SiteInbox key={selectedSite} siteId={selectedSite} />
        </>
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

function SiteInbox({ siteId }: { siteId: string }) {
  const t = useTranslations("SiteInquiries");
  const locale = useLocale();
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

  useEffect(() => {
    if (!selectedId) return;
    detailHeading.current?.focus({ preventScroll: true });
    if (window.matchMedia?.("(max-width: 1023px)")?.matches) {
      detailHeading.current?.scrollIntoView?.({ block: "start" });
    }
  }, [selectedId]);

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <Button
          disabled={loading}
          onClick={() => void load()}
          type="button"
          variant="outline"
        >
          <RefreshCwIcon aria-hidden="true" />
          {t("refresh")}
        </Button>
      </div>
      {failure ? (
        <FailureMessage
          failure={failure}
          onRetry={() => void load(retryCursor.current)}
        />
      ) : null}
      {loading ? <p role="status">{t("loading")}</p> : null}
      {!loading && !failure && !items.length ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          {t("empty")}
        </p>
      ) : null}
      {items.length ? (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(15rem,0.8fr)_minmax(0,1.4fr)]">
          <div className="space-y-3">
            <ul
              aria-label={t("listLabel")}
              className="max-h-[36rem] space-y-2 overflow-y-auto p-1"
            >
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    aria-pressed={selectedId === item.id}
                    className="flex min-h-20 w-full flex-col gap-2 rounded-xl border p-4 text-left transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-pressed:border-primary aria-pressed:bg-primary/5"
                    onClick={() => {
                      setSelectedId(item.id);
                      void markRead(item);
                    }}
                    type="button"
                  >
                    <span className="flex w-full flex-wrap items-center justify-between gap-2">
                      <span className="min-w-0 break-words font-semibold">
                        {item.name}
                      </span>
                      {!item.read_at ? (
                        <Badge>{t("unread")}</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {t("read")}
                        </span>
                      )}
                    </span>
                    <time
                      className="text-xs text-muted-foreground"
                      dateTime={item.created_at}
                    >
                      {date(item.created_at)}
                    </time>
                    <span className="break-all text-sm text-muted-foreground">
                      {item.page_path}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
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
          {selected ? (
            <article
              aria-label={selected.name}
              className="min-w-0 space-y-5 rounded-xl border bg-card p-5 sm:p-6"
            >
              <header className="space-y-1">
                <h3
                  className="break-words text-xl font-semibold"
                  ref={detailHeading}
                  tabIndex={-1}
                >
                  {selected.name}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {t("received")}:{" "}
                  <time dateTime={selected.created_at}>
                    {date(selected.created_at)}
                  </time>
                </p>
              </header>
              <dl className="grid gap-3 text-sm">
                <div>
                  <dt className="text-muted-foreground">{t("email")}</dt>
                  <dd className="break-all">{selected.email}</dd>
                </div>
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
              <div className="space-y-2 border-t pt-4">
                <h4 className="font-medium">{t("message")}</h4>
                <p className="whitespace-pre-wrap break-words text-sm leading-relaxed [overflow-wrap:anywhere]">
                  {selected.message}
                </p>
              </div>
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
              <div className="space-y-2 border-t pt-4">
                <a
                  className={buttonVariants()}
                  href={`mailto:${encodeURIComponent(selected.email)}`}
                >
                  <MailIcon aria-hidden="true" />
                  {t("reply")}
                </a>
                <p className="text-xs text-muted-foreground">
                  {t("replyHint")}
                </p>
              </div>
            </article>
          ) : (
            <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
              {t("choose")}
            </p>
          )}
        </div>
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
