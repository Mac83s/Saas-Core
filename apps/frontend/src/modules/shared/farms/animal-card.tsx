"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";

import { updateFarmAnimal, type FarmAnimal } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { Link } from "#i18n/navigation";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import productAnimalSections from "../../../product/animal-sections";
import { farmProblem } from "./problem";

/** `AnimalStatus` of the register (models.py). Core knows no health status. */
export const ANIMAL_STATUSES = ["active", "sold", "culled", "dead"] as const;
export type AnimalStatus = (typeof ANIMAL_STATUSES)[number];

const SEXES = ["female", "male", "unknown"] as const;

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
