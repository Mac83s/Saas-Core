"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { PlusIcon } from "lucide-react";

import {
  createFarmAnimalHealth,
  listFarmAnimalHealth,
  updateFarmAnimal,
  type FarmAnimal,
  type FarmAnimalHealthEntry,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { Link } from "#i18n/navigation";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import productAnimalSections from "../../../product/animal-sections";
import { farmProblem } from "./problem";

/** `AnimalStatus` of the register (models.py). Core knows no health status. */
export const ANIMAL_STATUSES = ["active", "sold", "culled", "dead"] as const;
export type AnimalStatus = (typeof ANIMAL_STATUSES)[number];

const SEXES = ["female", "male", "unknown"] as const;

/** `HealthEntryKind` of the register (models.py). A vertical says what it did
 * in `source` and `details`; the register only shows the kind. */
export const ENTRY_KINDS = [
  "note",
  "alert",
  "treatment",
  "medication",
  "visit",
] as const;

/**
 * One animal, as the register knows it, plus whatever the product adds about
 * it (ADR-051: the trimming, its ICAR codes and check-ups live in HoofCare,
 * not here). A dialog rather than a page of its own, because the row the
 * person clicked already carries the animal — the API has no read-by-id.
 */
export function AnimalCard({
  access,
  animal,
  canManage,
  onChanged,
  onClose,
  returnTo,
}: {
  access: PanelAccess;
  animal: FarmAnimal;
  canManage: boolean;
  onChanged: () => void;
  onClose: () => void;
  returnTo: HTMLElement | null;
}) {
  const t = useTranslations("Animals");
  const common = useTranslations("Common");
  const format = useFormatter();
  const [status, setStatus] = useState(animal.status);
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<FarmAnimalHealthEntry[]>();
  const [kinds, setKinds] = useState<string[]>([]);
  const [since, setSince] = useState("");
  const [writing, setWriting] = useState(false);
  const [draft, setDraft] = useState({
    kind: "note",
    summary: "",
    private: false,
  });
  const [reloads, setReloads] = useState(0);

  // The animal's file: what happened to it, whoever recorded it (ADR-051 pt 8).
  // The server filters, because the list is capped — filtering here would hide
  // the older entries the feed exists to show.
  useEffect(() => {
    let current = true;
    listFarmAnimalHealth(animal.id, { kinds, from: since || undefined })
      .then((entries) => {
        if (current) setHistory(entries);
      })
      .catch(() => {
        if (current) setHistory([]);
      });
    return () => {
      current = false;
    };
  }, [animal.id, kinds, reloads, since]);

  const known = <T extends string>(values: readonly T[], value: string) =>
    values.find((entry) => entry === value);
  const statusKey = known(ANIMAL_STATUSES, status);
  const sexKey = known(SEXES, animal.sex);
  const date = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium" });

  async function changeStatus(next: string) {
    const previous = status;
    setStatus(next);
    setBusy(true);
    setProblem(undefined);
    try {
      await updateFarmAnimal(animal.id, { status: next as AnimalStatus });
      onChanged();
    } catch (error) {
      setStatus(previous);
      setProblem(farmProblem(error, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  }

  const sections = productAnimalSections.filter((section) =>
    allows(access, section),
  );

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      open
    >
      <DialogContent
        className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
        closeLabel={common("close")}
        finalFocus={() => returnTo ?? true}
      >
        <DialogHeader>
          <DialogTitle className="font-mono wrap-anywhere">
            {animal.national_id}
          </DialogTitle>
          <DialogDescription>
            {[animal.name, animal.working_number && `#${animal.working_number}`]
              .filter(Boolean)
              .join(" · ") || t("cardTitle")}
          </DialogDescription>
        </DialogHeader>

        <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Fact label={t("farm")}>
            <Link
              className="text-primary underline-offset-4 hover:underline"
              href={`/panel/farms/${animal.farm_id}`}
            >
              {animal.farm_name}
            </Link>
          </Fact>
          <Fact label={t("sex")}>
            {sexKey ? t(`sex_${sexKey}`) : animal.sex}
          </Fact>
          <Fact label={t("birthDate")}>
            {animal.birth_date ? date(animal.birth_date) : t("unknown")}
          </Fact>
          <Fact label={t("updatedAt")}>{date(animal.updated_at)}</Fact>
          {animal.notes ? (
            <Fact className="sm:col-span-2" label={t("notes")}>
              <span className="whitespace-pre-line">{animal.notes}</span>
            </Fact>
          ) : null}
        </dl>

        {canManage ? (
          <Field>
            <FieldLabel htmlFor="animal-card-status">{t("status")}</FieldLabel>
            <NativeSelect
              disabled={busy}
              id="animal-card-status"
              onChange={(event) => void changeStatus(event.target.value)}
              value={status}
            >
              {ANIMAL_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {t(`status_${value}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
        ) : (
          <p className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">{t("status")}:</span>
            <Badge variant="secondary">
              {statusKey ? t(`status_${statusKey}`) : status}
            </Badge>
          </p>
        )}
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}

        <section className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="font-semibold">{t("history")}</h3>
            {canManage ? (
              <Button
                onClick={() => setWriting((open) => !open)}
                size="sm"
                variant="outline"
              >
                <PlusIcon aria-hidden="true" />
                {t("addEntry")}
              </Button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-end gap-2">
            {ENTRY_KINDS.map((value) => {
              const on = kinds.includes(value);
              return (
                <Button
                  aria-pressed={on}
                  key={value}
                  onClick={() =>
                    setKinds((current) =>
                      on
                        ? current.filter((item) => item !== value)
                        : [...current, value],
                    )
                  }
                  size="sm"
                  variant={on ? "default" : "outline"}
                >
                  {t(`kind_${value}`)}
                </Button>
              );
            })}
            <Field className="w-auto">
              <FieldLabel htmlFor="animal-history-since">
                {t("historySince")}
              </FieldLabel>
              <Input
                className="w-44"
                id="animal-history-since"
                onChange={(event) => setSince(event.target.value)}
                type="date"
                value={since}
              />
            </Field>
          </div>

          {writing ? (
            <form
              className="space-y-3 rounded-xl border p-3"
              onSubmit={async (event) => {
                event.preventDefault();
                setProblem(undefined);
                try {
                  await createFarmAnimalHealth(animal.id, {
                    kind: draft.kind as (typeof ENTRY_KINDS)[number],
                    summary: draft.summary,
                    private: draft.private,
                  });
                  setDraft({ kind: "note", summary: "", private: false });
                  setWriting(false);
                  setReloads((value) => value + 1);
                } catch (error) {
                  setProblem(farmProblem(error, t("saveFailed")));
                }
              }}
            >
              <Field>
                <FieldLabel htmlFor="animal-entry-kind">{t("kind")}</FieldLabel>
                <NativeSelect
                  id="animal-entry-kind"
                  onChange={(event) =>
                    setDraft({ ...draft, kind: event.target.value })
                  }
                  value={draft.kind}
                >
                  {ENTRY_KINDS.map((value) => (
                    <option key={value} value={value}>
                      {t(`kind_${value}`)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-entry-summary">
                  {t("entrySummary")}
                </FieldLabel>
                <Input
                  id="animal-entry-summary"
                  maxLength={240}
                  onChange={(event) =>
                    setDraft({ ...draft, summary: event.target.value })
                  }
                  required
                  value={draft.summary}
                />
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input
                  checked={draft.private}
                  onChange={(event) =>
                    setDraft({ ...draft, private: event.target.checked })
                  }
                  type="checkbox"
                />
                {t("entryPrivate")}
              </label>
              <Button disabled={!draft.summary.trim()} size="sm" type="submit">
                {t("save")}
              </Button>
            </form>
          ) : null}

          {history && history.length > 0 ? (
            <ol className="space-y-3">
              {history.map((item) => (
                <li className="rounded-xl border p-3" key={item.id}>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="secondary">{t(`kind_${item.kind}`)}</Badge>
                    {item.private ? (
                      <Badge variant="outline">{t("entryPrivateBadge")}</Badge>
                    ) : null}
                  </div>
                  <p className="mt-1 text-sm">{item.summary}</p>
                  <p className="text-xs text-muted-foreground">
                    {[
                      date(item.occurred_on),
                      item.author_name,
                      item.author_is_external
                        ? item.author_organization_name
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-muted-foreground">{t("noHistory")}</p>
          )}
        </section>

        {/* What the trade records about this animal, from the product's own
            endpoints; core ships none (ADR-049). */}
        {sections.map(({ component: Section, id }) => (
          <Section animalId={animal.id} farmId={animal.farm_id} key={id} />
        ))}
      </DialogContent>
    </Dialog>
  );
}

function Fact({
  children,
  className,
  label,
}: {
  children: ReactNode;
  className?: string;
  label: string;
}) {
  return (
    <div className={className}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="wrap-anywhere">{children}</dd>
    </div>
  );
}
