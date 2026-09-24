"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  updateFarmAnimal,
  type FarmAnimal,
  type FarmAnimalUpdateInput,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { ANIMAL_STATUSES } from "./animal-card";
import { farmProblem } from "./problem";

type Values = {
  national_id: string;
  name: string;
  working_number: string;
  sex: "female" | "male" | "unknown";
  birth_date: string;
  status: (typeof ANIMAL_STATUSES)[number];
};

/**
 * Editing one animal of the register: the row's everyday "Edytuj" (ADR-057),
 * on the list of all animals and on a farm's page alike. Only what changed is
 * sent, so a field someone else edited meanwhile is not written back.
 */
export function AnimalEditDialog({
  animal,
  onClose,
  onSaved,
  returnTo,
}: {
  animal: FarmAnimal;
  onClose: () => void;
  onSaved: (animal: FarmAnimal) => void;
  /** The row's button, which gets focus back. */
  returnTo: HTMLElement | null;
}) {
  const t = useTranslations("Animals");
  const common = useTranslations("Common");
  const schema = useMemo(
    () =>
      z.object({
        national_id: z.string().trim().min(4, t("tagRequired")),
        name: z.string(),
        working_number: z.string(),
        sex: z.enum(["female", "male", "unknown"]),
        birth_date: z.string(),
        status: z.enum(ANIMAL_STATUSES),
      }),
    [t],
  );
  const initial: Values = {
    national_id: animal.national_id,
    name: animal.name,
    working_number: animal.working_number,
    sex: animal.sex as Values["sex"],
    birth_date: animal.birth_date ?? "",
    status: animal.status as Values["status"],
  };
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: initial,
  });
  const errors = form.formState.errors;

  async function save(values: Values) {
    const changed: FarmAnimalUpdateInput = {};
    for (const key of Object.keys(values) as (keyof Values)[])
      if (values[key] !== initial[key])
        Object.assign(changed, {
          [key]: key === "birth_date" ? values[key] || null : values[key],
        });
    if (Object.keys(changed).length === 0) return onClose();
    try {
      onSaved(await updateFarmAnimal(animal.id, changed));
    } catch (error) {
      form.setError("root", {
        type: "server",
        message: farmProblem(error, t("saveFailed")),
      });
    }
  }

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      open
    >
      <DialogContent
        closeLabel={common("close")}
        finalFocus={() => returnTo ?? true}
      >
        <DialogHeader>
          <DialogTitle>{t("edit")}</DialogTitle>
          <DialogDescription className="font-mono">
            {animal.national_id}
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(event) => void form.handleSubmit(save)(event)}
        >
          <FieldGroup>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field data-invalid={Boolean(errors.national_id)}>
                <FieldLabel htmlFor="edit-animal-tag">{t("tag")}</FieldLabel>
                <Input
                  aria-invalid={Boolean(errors.national_id)}
                  id="edit-animal-tag"
                  {...form.register("national_id")}
                />
                <FieldError errors={[errors.national_id]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="edit-animal-name">
                  {t("animalName")}
                </FieldLabel>
                <Input id="edit-animal-name" {...form.register("name")} />
              </Field>
              <Field>
                <FieldLabel htmlFor="edit-animal-working">
                  {t("workingNumber")}
                </FieldLabel>
                <Input
                  id="edit-animal-working"
                  {...form.register("working_number")}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="edit-animal-sex">{t("sex")}</FieldLabel>
                <NativeSelect id="edit-animal-sex" {...form.register("sex")}>
                  <option value="female">{t("sex_female")}</option>
                  <option value="male">{t("sex_male")}</option>
                  <option value="unknown">{t("sex_unknown")}</option>
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="edit-animal-birth">
                  {t("birthDate")}
                </FieldLabel>
                <Input
                  id="edit-animal-birth"
                  type="date"
                  {...form.register("birth_date")}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="edit-animal-status">
                  {t("status")}
                </FieldLabel>
                <NativeSelect
                  id="edit-animal-status"
                  {...form.register("status")}
                >
                  {ANIMAL_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {t(`status_${value}`)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
          </FieldGroup>
          {errors.root ? (
            <p className="text-sm text-destructive" role="alert">
              {errors.root.message}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {form.formState.isSubmitting ? t("saving") : t("saveChanges")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
