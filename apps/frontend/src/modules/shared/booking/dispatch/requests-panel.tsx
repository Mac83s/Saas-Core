"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckIcon, XIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  answerBookingRequest,
  getBookingRequests,
  type OrganizationSummary,
  type QueueItem,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { Link, useRouter } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { formatDateTime, formatVisit } from "#lib/dates";
import { wallClock } from "../calendar-time";
import { DeclineRequestDialog } from "../decline-request-dialog";
import { visitName, visitPerson } from "../visit-name";

const BOOKING_MANAGE = "booking.appointment.manage";

/**
 * Kalendarz › Prośby (ADR-072 §9): customers' bookings of services taken on
 * request that still wait for the company's answer — the one whose time to
 * answer runs out first on top. Each is accepted or declined here; the same
 * two answers are in the visit's window in the calendar.
 */
export function RequestsPanel({
  organization,
}: {
  organization: OrganizationSummary | null;
}) {
  const t = useTranslations("Requests");
  const calendar = useTranslations("Calendar");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const router = useRouter();
  const zone = organization?.timezone ?? "UTC";
  const canManage = Boolean(organization?.permissions.includes(BOOKING_MANAGE));
  const [items, setItems] = useState<QueueItem[]>();
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  // The dialog stays mounted while it closes: it reports the answer only
  // once it is gone.
  const [declining, setDeclining] = useState<{
    item: QueueItem;
    open: boolean;
  }>();
  const [busy, setBusy] = useState<string>();

  const load = useCallback(async () => {
    try {
      setItems(await getBookingRequests());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    if (canManage) void load();
  }, [canManage, load]);

  const when = (item: QueueItem) =>
    formatVisit(item.starts_at, item.ends_at, locale, zone);

  /** The list and the count beside „Prośby” in the menu follow the answer. */
  async function answered(text: string) {
    setNotice(text);
    await load();
    router.refresh();
  }

  async function accept(item: QueueItem) {
    // One answer at a time: a second click on the same request waits.
    if (busy) return;
    setBusy(item.id);
    setProblem(undefined);
    try {
      const updated = await answerBookingRequest(
        item.id,
        "accept",
        crypto.randomUUID(),
      );
      await answered(
        calendar(
          updated.status === "pending_payment"
            ? "requestAcceptedAwaiting"
            : "requestAccepted",
        ),
      );
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          error.problem.code === "appointment_not_changeable"
          ? calendar("notChangeable")
          : calendar("answerError"),
      );
      // Somebody else answered it, or it expired: the list says so.
      await load();
    } finally {
      setBusy(undefined);
    }
  }

  const columns: ColumnDef<QueueItem, unknown>[] = [
    {
      id: "customer",
      accessorFn: visitName,
      header: t("colCustomer"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium">{visitName(item)}</p>
          {visitPerson(item) ? (
            <p className="text-sm">{visitPerson(item)}</p>
          ) : null}
          <p className="text-sm text-muted-foreground">
            {[item.customer_phone, item.customer_email]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {item.customer_notes ? (
            <p className="text-sm">„{item.customer_notes}”</p>
          ) : null}
        </>
      ),
    },
    {
      id: "service",
      accessorKey: "service_name",
      header: t("colService"),
      cell: ({ row: { original: item } }) => (
        <>
          <p>{item.service_name}</p>
          <p className="text-sm text-muted-foreground tabular-nums">
            {when(item)}
          </p>
        </>
      ),
    },
    {
      id: "answerBy",
      accessorFn: (item) => item.hold_expires_at ?? "",
      header: t("colAnswerBy"),
      cell: ({ row: { original: item } }) =>
        item.hold_expires_at ? (
          <time className="tabular-nums" dateTime={item.hold_expires_at}>
            {formatDateTime(item.hold_expires_at, locale, zone)}
          </time>
        ) : (
          "—"
        ),
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
              label: t("acceptFor", { customer: visitName(item) }),
              icon: <CheckIcon aria-hidden="true" />,
              inline: true,
              onSelect: () => void accept(item),
            },
            {
              label: t("declineFor", { customer: visitName(item) }),
              icon: <XIcon aria-hidden="true" />,
              inline: true,
              onSelect: () => {
                setProblem(undefined);
                setDeclining({ item, open: true });
              },
            },
            {
              label: t("openInCalendar"),
              link: (
                <Link
                  href={`/panel/calendar?view=day&date=${
                    wallClock(new Date(item.starts_at), zone).day
                  }`}
                />
              ),
            },
          ]}
          label={t("moreFor", { customer: visitName(item) })}
        />
      ),
    },
  ];

  return (
    <PanelPage
      description={t("description")}
      eyebrow={t("eyebrow")}
      notice={notice}
      title={t("title")}
    >
      {!canManage ? (
        <p className="text-muted-foreground">{t("noAccess")}</p>
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={items ?? []}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("empty") }}
            loading={!items}
          />
          <p className="text-sm text-muted-foreground">{t("footer")}</p>
        </div>
      )}
      {declining ? (
        <DeclineRequestDialog
          appointment={declining.item}
          key={declining.item.id}
          onDeclined={() => {
            setDeclining(undefined);
            void answered(calendar("requestDeclined"));
          }}
          onOpenChange={(open) =>
            setDeclining((current) =>
              current ? { ...current, open } : current,
            )
          }
          open={declining.open}
          when={when(declining.item)}
        />
      ) : null}
    </PanelPage>
  );
}
