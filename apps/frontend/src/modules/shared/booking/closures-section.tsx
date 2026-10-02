"use client";

import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CopyIcon, PencilIcon, PlusIcon } from "lucide-react";

import {
  copyBookingClosuresToNextYear,
  createBookingClosure,
  deleteBookingClosure,
  listBookingClosures,
  updateBookingClosure,
  type BookingClosure,
  type PlaceSetup,
} from "@saas-core/api-client";
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
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import { problemText } from "./people/person-dialogs";

const asDay = (value: string) => new Date(`${value}T12:00:00`);

/**
 * Dni zamknięte (B11, ADR-078 pkt 17): days the company — or one of its places —
 * takes no bookings, whatever the hours say. Christmas recurs, so a year's
 * closures copy to the next one.
 */
export function ClosuresSection({ places }: { places: PlaceSetup[] }) {
  const t = useTranslations("ServicesSetup");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [items, setItems] = useState<BookingClosure[]>();
  const [editing, setEditing] = useState<{ item?: BookingClosure }>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();

  const load = useCallback(async () => {
    try {
      setItems(await listBookingClosures());
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  const placeName = (id: string | null) =>
    id
      ? (places.find((place) => place.id === id)?.name ?? "—")
      : t("wholeCompany");
  const days = (item: BookingClosure) =>
    format.dateTimeRange(asDay(item.starts_on), asDay(item.ends_on), {
      dateStyle: "medium",
    });
  const latestYear = Math.max(
    0,
    ...(items ?? []).map((item) => Number(item.starts_on.slice(0, 4))),
  );

  async function remove(item: BookingClosure) {
    setProblem(undefined);
    try {
      await deleteBookingClosure(item.id, item.version, crypto.randomUUID());
      setNotice(t("closureRemoved", { days: days(item) }));
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
        }),
      );
    }
    void load();
  }

  async function copy() {
    setProblem(undefined);
    try {
      const count = await copyBookingClosuresToNextYear(
        latestYear,
        crypto.randomUUID(),
      );
      setNotice(t("closuresCopied", { count, year: latestYear + 1 }));
    } catch (error) {
      setProblem(problemText(error, t("failed"), t("forbidden")));
    }
    void load();
  }

  const columns: ColumnDef<BookingClosure, unknown>[] = [
    {
      id: "days",
      accessorKey: "starts_on",
      header: t("colClosedDays"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <>
          <p className="font-medium">{days(item)}</p>
          {item.note ? (
            <p className="text-sm text-muted-foreground wrap-anywhere">
              {item.note}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "place",
      header: t("colPlace"),
      enableSorting: false,
      cell: ({ row: { original: item } }) => placeName(item.location_id),
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
              label: t("editFor", { name: days(item) }),
              icon: <PencilIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => {
                setReturnTo(trigger ?? null);
                setEditing({ item });
              },
            },
            {
              label: t("removeClosure"),
              onSelect: () => void remove(item),
            },
          ]}
          label={t("actionsFor", { name: days(item) })}
        />
      ),
    },
  ];

  return (
    <PanelSection
      actions={
        <div className="flex flex-wrap gap-2">
          {latestYear ? (
            <Button onClick={() => void copy()} variant="outline">
              <CopyIcon aria-hidden="true" />
              {t("copyClosures", { from: latestYear, to: latestYear + 1 })}
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
            {t("addClosure")}
          </Button>
        </div>
      }
      description={t("closuresHint")}
      title={t("closuresTitle")}
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
        caption={t("closuresCaption")}
        columns={columns}
        data={items ?? []}
        getRowId={(item) => item.id}
        labels={{ ...labels, empty: t("noClosures") }}
        loading={!items}
      />
      {editing ? (
        <ClosureDialog
          finalFocus={returnTo}
          item={editing.item}
          onOpenChange={(open) => {
            if (!open) {
              setEditing(undefined);
              void load();
            }
          }}
          onSaved={(saved, created) => {
            setEditing(undefined);
            setNotice(
              t(created ? "closureAdded" : "closureSaved", {
                days: days(saved),
              }),
            );
            void load();
          }}
          places={places.filter(
            (place) => place.active || place.id === editing.item?.location_id,
          )}
        />
      ) : null}
    </PanelSection>
  );
}

function ClosureDialog({
  finalFocus,
  item,
  places,
  onOpenChange,
  onSaved,
}: {
  finalFocus: HTMLElement | null;
  item?: BookingClosure;
  places: PlaceSetup[];
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: BookingClosure, created: boolean) => void;
}) {
  const t = useTranslations("ServicesSetup");
  const common = useTranslations("Common");
  const [startsOn, setStartsOn] = useState(item?.starts_on ?? "");
  const [endsOn, setEndsOn] = useState(item?.ends_on ?? "");
  const [placeId, setPlaceId] = useState(item?.location_id ?? "");
  const [note, setNote] = useState(item?.note ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  async function save() {
    if (!startsOn || !endsOn) {
      setProblem(t("closureDatesRequired"));
      return;
    }
    if (endsOn < startsOn) {
      setProblem(t("closureEndBeforeStart"));
      return;
    }
    setBusy(true);
    setProblem(undefined);
    const body = {
      starts_on: startsOn,
      ends_on: endsOn,
      location_id: placeId || null,
      note: note.trim(),
    };
    try {
      onSaved(
        item
          ? await updateBookingClosure(
              item.id,
              { ...body, expected_version: item.version },
              idempotencyKey,
            )
          : await createBookingClosure(body, idempotencyKey),
        !item,
      );
    } catch (error) {
      setProblem(
        problemText(error, t("failed"), t("forbidden"), {
          booking_version_conflict: t("versionConflict"),
        }),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
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
              {t(item ? "editClosureTitle" : "newClosureTitle")}
            </DialogTitle>
            <DialogDescription>{t("closureHint")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="closure-from">{t("closureFrom")}</FieldLabel>
              <Input
                id="closure-from"
                onChange={(event) => setStartsOn(event.target.value)}
                type="date"
                value={startsOn}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="closure-to">{t("closureTo")}</FieldLabel>
              <Input
                id="closure-to"
                onChange={(event) => setEndsOn(event.target.value)}
                type="date"
                value={endsOn}
              />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="closure-place">{t("placeField")}</FieldLabel>
            <NativeSelect
              id="closure-place"
              onChange={(event) => setPlaceId(event.target.value)}
              value={placeId}
            >
              <option value="">{t("wholeCompany")}</option>
              {places.map((place) => (
                <option key={place.id} value={place.id}>
                  {place.name}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor="closure-note">{t("closureNote")}</FieldLabel>
            <Input
              autoComplete="off"
              id="closure-note"
              maxLength={160}
              onChange={(event) => setNote(event.target.value)}
              value={note}
            />
          </Field>
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
