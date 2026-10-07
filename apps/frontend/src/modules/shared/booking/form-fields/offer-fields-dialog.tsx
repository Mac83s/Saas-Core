"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { PencilIcon, PlusIcon } from "lucide-react";

import {
  ApiProblemError,
  createBookingFormField,
  listBookingFormFields,
  updateBookingFormField,
  type BookingFormField,
  type BookingFormFieldList,
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
import { Textarea } from "@saas-core/ui/components/textarea";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  ItemTranslationsSheet,
  type TranslatedItem,
} from "../item-translations-sheet";

type Limits = BookingFormFieldList["limits"];
type Kind = BookingFormField["kind"];

/** The server's refusals the panel says in its own language. */
const REFUSALS = [
  "name_taken",
  "options_required",
  "options_too_many",
  "option_too_long",
  "options_repeated",
  "fields_too_many",
];

/**
 * „Pola formularza” of one offer (ADR-072, slice 5j): what its booking form
 * asks the customer beyond a name and a contact — a licence number, a pet's
 * name, an arrival hour — and its own boxes to tick. Each field saves on its
 * own; the dialog only closes. What customers answer is read with their
 * booking, never here.
 */
export function OfferFieldsDialog({
  finalFocus,
  onOpenChange,
  service,
}: {
  finalFocus: HTMLElement | null;
  onOpenChange: (open: boolean) => void;
  service: ServiceSetup;
}) {
  const t = useTranslations("FormFields");
  const common = useTranslations("Common");
  const translations = useTranslations("Translations");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const [list, setList] = useState<BookingFormFieldList>();
  const [editing, setEditing] = useState<{ item?: BookingFormField }>();
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);
  const [translating, setTranslating] = useState<TranslatedItem>();
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();

  const load = useCallback(async () => {
    try {
      setList(await listBookingFormFields());
    } catch {
      setProblem(t("loadFailed"));
    }
  }, [t]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the list is read when the dialog opens
    void load();
  }, [load]);

  const fields = (list?.items ?? []).filter(
    (item) => item.service_id === service.id,
  );
  const kindName = (kind: Kind) => {
    const found = list?.limits.kinds.find((item) => item.value === kind);
    return found?.label[locale] ?? found?.label.en ?? kind;
  };

  async function toggle(item: BookingFormField) {
    setProblem(undefined);
    try {
      await updateBookingFormField(
        item.id,
        { active: !item.active, expected_version: item.version },
        crypto.randomUUID(),
      );
      setNotice(
        t(item.active ? "switchedOff" : "switchedOn", { name: item.name }),
      );
    } catch (error) {
      setProblem(refusalText(error, t, list?.limits));
    }
    await load();
  }

  const columns: ColumnDef<BookingFormField, unknown>[] = [
    {
      id: "name",
      accessorKey: "name",
      header: t("colField"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <p className="font-medium wrap-anywhere">
          {item.name}
          {item.active ? null : (
            <Badge className="ml-2" variant="outline">
              {t("off")}
            </Badge>
          )}
        </p>
      ),
    },
    {
      id: "kind",
      header: t("colKind"),
      enableSorting: false,
      cell: ({ row: { original: item } }) =>
        [
          kindName(item.kind),
          item.options.length ? item.options.join(" / ") : undefined,
          t(item.mandatory ? "mandatory" : "optional"),
        ]
          .filter(Boolean)
          .join(" · "),
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
              label: translations("action"),
              onSelect: () =>
                setTranslating({ kind: "field", id: item.id, name: item.name }),
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
    <Dialog onOpenChange={onOpenChange} open>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-3xl"
        closeLabel={common("close")}
        finalFocus={() => finalFocus ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("titleFor", { name: service.name })}</DialogTitle>
          <DialogDescription>{t("hint")}</DialogDescription>
        </DialogHeader>
        <PanelSection
          actions={
            <Button
              disabled={!list}
              onClick={(event) => {
                setReturnTo(event.currentTarget);
                setEditing({});
              }}
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("add")}
            </Button>
          }
          description={t("sensitiveHint")}
          title={t("listTitle")}
        >
          <p
            className="text-sm text-success-foreground empty:hidden"
            role="status"
          >
            {notice}
          </p>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DataTable
            caption={t("listTitle")}
            columns={columns}
            data={fields}
            getRowId={(item) => item.id}
            labels={{ ...labels, empty: t("empty") }}
          />
        </PanelSection>
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            {common("close")}
          </DialogClose>
        </DialogFooter>
        {editing && list ? (
          <FieldDialog
            finalFocus={returnTo}
            item={editing.item}
            kindName={kindName}
            limits={list.limits}
            onOpenChange={(open) => {
              if (!open) {
                setEditing(undefined);
                void load();
              }
            }}
            onSaved={async (saved, created) => {
              setEditing(undefined);
              setProblem(undefined);
              setNotice(t(created ? "added" : "saved", { name: saved.name }));
              await load();
            }}
            serviceId={service.id}
          />
        ) : null}
        <ItemTranslationsSheet
          item={translating}
          onClose={() => setTranslating(undefined)}
        />
      </DialogContent>
    </Dialog>
  );
}

function refusalText(
  error: unknown,
  t: ReturnType<typeof useTranslations<"FormFields">>,
  limits: Limits | undefined,
): string {
  if (!(error instanceof ApiProblemError)) return t("failed");
  if (error.problem.code === "booking_version_conflict")
    return t("versionConflict");
  const code = error.problem.errors?.[0]?.code ?? "";
  return REFUSALS.includes(code)
    ? t(`refused_${code}` as "refused_name_taken", {
        fields: limits?.max_fields ?? 20,
        options: limits?.max_options ?? 20,
        length: limits?.max_option_length ?? 80,
      })
    : t("failed");
}

function FieldDialog({
  finalFocus,
  item,
  kindName,
  limits,
  onOpenChange,
  onSaved,
  serviceId,
}: {
  finalFocus: HTMLElement | null;
  item?: BookingFormField;
  kindName: (kind: Kind) => string;
  limits: Limits;
  onOpenChange: (open: boolean) => void;
  onSaved: (saved: BookingFormField, created: boolean) => void;
  serviceId: string;
}) {
  const t = useTranslations("FormFields");
  const common = useTranslations("Common");
  const [name, setName] = useState(item?.name ?? "");
  const [kind, setKind] = useState<Kind>(item?.kind ?? "text");
  const [options, setOptions] = useState((item?.options ?? []).join("\n"));
  const [mandatory, setMandatory] = useState(item?.mandatory ?? false);
  const [position, setPosition] = useState(String(item?.position ?? ""));
  const [active, setActive] = useState(item?.active ?? true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const consent = kind === "consent";

  async function save() {
    if (!name.trim()) return setProblem(t("nameRequired"));
    const lines = options
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (kind === "choice" && lines.length < limits.min_options)
      return setProblem(t("refused_options_required"));
    const order = Number(position);
    if (
      item &&
      !(position.trim() !== "" && Number.isInteger(order) && order >= 0)
    )
      return setProblem(t("positionInvalid"));
    const body = {
      name: name.trim(),
      kind,
      // Options are a choice's alone: the server drops them otherwise.
      options: kind === "choice" ? lines : [],
      mandatory,
    };
    setBusy(true);
    setProblem(undefined);
    try {
      onSaved(
        item
          ? await updateBookingFormField(
              item.id,
              {
                ...body,
                position: order,
                active,
                expected_version: item.version,
              },
              idempotencyKey,
            )
          : await createBookingFormField(
              { ...body, service_id: serviceId },
              idempotencyKey,
            ),
        !item,
      );
    } catch (error) {
      setProblem(refusalText(error, t, limits));
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
            <DialogTitle>{t(item ? "editTitle" : "newTitle")}</DialogTitle>
            <DialogDescription>{t("dialogHint")}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor="form-field-kind">{t("kind")}</FieldLabel>
            <NativeSelect
              id="form-field-kind"
              onChange={(event) => setKind(event.target.value as Kind)}
              value={kind}
            >
              {limits.kinds.map((option) => (
                <option key={option.value} value={option.value}>
                  {kindName(option.value)}
                </option>
              ))}
            </NativeSelect>
            {consent ? (
              <FieldDescription>{t("consentHint")}</FieldDescription>
            ) : null}
          </Field>
          <Field>
            <FieldLabel htmlFor="form-field-name">
              {t(consent ? "nameConsent" : "name")}
            </FieldLabel>
            <Input
              autoComplete="off"
              id="form-field-name"
              maxLength={limits.max_name_length}
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
            <FieldDescription>
              {t(consent ? "nameConsentHint" : "nameHint")}
            </FieldDescription>
          </Field>
          {kind === "choice" ? (
            <Field>
              <FieldLabel htmlFor="form-field-options">
                {t("options")}
              </FieldLabel>
              <Textarea
                id="form-field-options"
                onChange={(event) => setOptions(event.target.value)}
                rows={4}
                value={options}
              />
              <FieldDescription>
                {t("optionsHint", {
                  min: limits.min_options,
                  max: limits.max_options,
                })}
              </FieldDescription>
            </Field>
          ) : null}
          <Field>
            <FieldLabel htmlFor="form-field-mandatory">{t("who")}</FieldLabel>
            <NativeSelect
              id="form-field-mandatory"
              onChange={(event) =>
                setMandatory(event.target.value === "mandatory")
              }
              value={mandatory ? "mandatory" : "optional"}
            >
              <option value="optional">{t("who_optional")}</option>
              <option value="mandatory">
                {t(consent ? "who_mandatory_consent" : "who_mandatory")}
              </option>
            </NativeSelect>
          </Field>
          {item ? (
            <>
              <Field className="w-40">
                <FieldLabel htmlFor="form-field-position">
                  {t("position")}
                </FieldLabel>
                <Input
                  id="form-field-position"
                  inputMode="numeric"
                  min={0}
                  onChange={(event) => setPosition(event.target.value)}
                  type="number"
                  value={position}
                />
                <FieldDescription>{t("positionHint")}</FieldDescription>
              </Field>
              <label
                className="flex min-h-11 items-center gap-2 text-sm"
                htmlFor="form-field-active"
              >
                <input
                  checked={active}
                  className="size-4"
                  id="form-field-active"
                  onChange={(event) => setActive(event.target.checked)}
                  type="checkbox"
                />
                {t("active")}
              </label>
            </>
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
