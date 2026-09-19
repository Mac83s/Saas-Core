"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ArrowLeftIcon, PencilIcon, PlusIcon } from "lucide-react";

import {
  createFarmAnimal,
  listFarmAnimals,
  listFarmSpecies,
  readFarm,
  updateFarm,
  updateFarmAnimal,
  type Farm,
  type FarmAnimal,
  type FarmSpecies,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
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

import { Link } from "#i18n/navigation";
import { FarmForm } from "./farm-form";
import { farmProblem } from "./problem";

const STATUSES = ["active", "sold", "culled", "dead"] as const;
type AnimalValues = {
  species: string;
  national_id: string;
  working_number: string;
  name: string;
  sex: "female" | "male" | "unknown";
  birth_date: string;
};

/** One farm: its details and the animals standing in it (ADR-051). */
export function FarmDetail({ farmId }: { farmId: string }) {
  const t = useTranslations("Farms");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [farm, setFarm] = useState<Farm>();
  const [animals, setAnimals] = useState<FarmAnimal[]>([]);
  const [species, setSpecies] = useState<FarmSpecies[]>([]);
  const [search, setSearch] = useState("");
  const [problem, setProblem] = useState<string>();
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const [loadedFarm, loadedAnimals, loadedSpecies] = await Promise.all([
        readFarm(farmId),
        listFarmAnimals({ farmId }),
        listFarmSpecies(),
      ]);
      setFarm(loadedFarm);
      setAnimals(loadedAnimals);
      setSpecies(loadedSpecies);
      setProblem(undefined);
    } catch (error) {
      setProblem(farmProblem(error, t("loadFailed")));
    }
  }, [farmId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  const visible = useMemo(() => {
    const needle = search.replaceAll(/\s/g, "").toUpperCase();
    if (!needle) return animals;
    return animals.filter(
      (animal) =>
        animal.national_id.includes(needle) ||
        animal.working_number.toUpperCase() === needle ||
        animal.name.toUpperCase().includes(needle),
    );
  }, [animals, search]);

  const schema = useMemo(
    () =>
      z.object({
        species: z.string().min(1),
        national_id: z.string().trim().min(4, t("tagRequired")),
        working_number: z.string(),
        name: z.string(),
        sex: z.enum(["female", "male", "unknown"]),
        birth_date: z.string(),
      }),
    [t],
  );
  const animalForm = useForm<AnimalValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      species: "cattle",
      national_id: "",
      working_number: "",
      name: "",
      sex: "female",
      birth_date: "",
    },
  });

  async function addAnimal(values: AnimalValues) {
    try {
      await createFarmAnimal({
        farm_id: farmId,
        species: values.species as "cattle",
        national_id: values.national_id,
        working_number: values.working_number,
        name: values.name,
        sex: values.sex,
        birth_date: values.birth_date || null,
      });
      animalForm.reset();
      setAdding(false);
      await load();
    } catch (error) {
      animalForm.setError("root", {
        type: "server",
        message: farmProblem(error, t("saveFailed")),
      });
    }
  }

  async function changeStatus(animal: FarmAnimal, status: string) {
    try {
      await updateFarmAnimal(animal.id, {
        status: status as (typeof STATUSES)[number],
      });
      await load();
    } catch (error) {
      setProblem(farmProblem(error, t("saveFailed")));
    }
  }

  const label = (entry: FarmSpecies) =>
    (locale === "en" ? entry.label.en : entry.label.pl) ?? entry.key;

  return (
    <div className="space-y-6">
      <Link
        className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        href="/panel/farms"
      >
        <ArrowLeftIcon aria-hidden="true" className="size-4" />
        {t("back")}
      </Link>
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      {farm ? (
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-4">
            <div className="min-w-0">
              <CardTitle className="text-xl">{farm.name}</CardTitle>
              <CardDescription>
                {[
                  farm.address || farm.village,
                  farm.keeper_name,
                  farm.phone,
                  farm.email,
                ]
                  .filter(Boolean)
                  .join(" · ") || t("noDetails")}
              </CardDescription>
            </div>
            <Button
              onClick={() => setEditing(true)}
              size="sm"
              type="button"
              variant="outline"
            >
              <PencilIcon aria-hidden="true" />
              {t("edit")}
            </Button>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Badge variant="outline">
              {t("herd_number")}: {farm.herd_number || t("unknown")}
            </Badge>
            {farm.tax_id ? (
              <Badge variant="outline">
                {t("tax_id")}: {farm.tax_id}
              </Badge>
            ) : null}
            <Badge variant="secondary">
              {t("animalCount", { count: animals.length })}
            </Badge>
          </CardContent>
        </Card>
      ) : null}
      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>{t("animals")}</CardTitle>
            <CardDescription>{t("animalsDescription")}</CardDescription>
          </div>
          <Button onClick={() => setAdding(true)} size="sm" type="button">
            <PlusIcon aria-hidden="true" />
            {t("addAnimal")}
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          <Input
            aria-label={t("searchAnimals")}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("searchAnimals")}
            value={search}
          />
          {visible.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noAnimals")}</p>
          ) : null}
          {visible.map((animal) => (
            <div
              className="flex flex-col gap-2 rounded-lg border p-3 sm:flex-row sm:items-center"
              key={animal.id}
            >
              <div className="min-w-0 flex-1">
                <p className="font-mono text-sm font-medium">
                  {animal.national_id}
                </p>
                <p className="text-sm text-muted-foreground">
                  {[
                    animal.name,
                    animal.working_number && `#${animal.working_number}`,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
              </div>
              <NativeSelect
                aria-label={`${t("status")}: ${animal.national_id}`}
                onChange={(event) =>
                  void changeStatus(animal, event.target.value)
                }
                value={animal.status}
              >
                {STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {t(`status_${status}`)}
                  </option>
                ))}
              </NativeSelect>
            </div>
          ))}
        </CardContent>
      </Card>
      <Dialog onOpenChange={setEditing} open={editing}>
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("edit")}</DialogTitle>
            <DialogDescription>{farm?.name}</DialogDescription>
          </DialogHeader>
          {farm ? (
            <FarmForm
              farm={farm}
              onSubmit={async (values) => {
                try {
                  setFarm(await updateFarm(farm.id, values));
                  setEditing(false);
                  return undefined;
                } catch (error) {
                  return farmProblem(error, t("saveFailed"));
                }
              }}
              submitLabel={t("save")}
            />
          ) : null}
        </DialogContent>
      </Dialog>
      <Dialog onOpenChange={setAdding} open={adding}>
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("addAnimal")}</DialogTitle>
            <DialogDescription>{t("addAnimalDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            noValidate
            onSubmit={animalForm.handleSubmit(addAnimal)}
          >
            <FieldGroup>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field>
                  <FieldLabel htmlFor="animal-species">
                    {t("species")}
                  </FieldLabel>
                  <NativeSelect
                    id="animal-species"
                    {...animalForm.register("species")}
                  >
                    {species.map((entry) => (
                      <option
                        disabled={!entry.active}
                        key={entry.key}
                        value={entry.key}
                      >
                        {label(entry)}
                        {entry.active ? "" : ` (${t("soon")})`}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <Field
                  data-invalid={Boolean(
                    animalForm.formState.errors.national_id,
                  )}
                >
                  <FieldLabel htmlFor="animal-tag">{t("tag")}</FieldLabel>
                  <Input
                    id="animal-tag"
                    placeholder="PL 005432198765"
                    {...animalForm.register("national_id")}
                  />
                  <FieldError
                    errors={[animalForm.formState.errors.national_id]}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="animal-working">
                    {t("workingNumber")}
                  </FieldLabel>
                  <Input
                    id="animal-working"
                    {...animalForm.register("working_number")}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="animal-name">
                    {t("animalName")}
                  </FieldLabel>
                  <Input id="animal-name" {...animalForm.register("name")} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="animal-sex">{t("sex")}</FieldLabel>
                  <NativeSelect id="animal-sex" {...animalForm.register("sex")}>
                    <option value="female">{t("sex_female")}</option>
                    <option value="male">{t("sex_male")}</option>
                    <option value="unknown">{t("sex_unknown")}</option>
                  </NativeSelect>
                </Field>
                <Field>
                  <FieldLabel htmlFor="animal-birth">
                    {t("birthDate")}
                  </FieldLabel>
                  <Input
                    id="animal-birth"
                    type="date"
                    {...animalForm.register("birth_date")}
                  />
                </Field>
              </div>
            </FieldGroup>
            {animalForm.formState.errors.root ? (
              <p className="text-sm text-destructive" role="alert">
                {animalForm.formState.errors.root.message}
              </p>
            ) : null}
            <Button disabled={animalForm.formState.isSubmitting} type="submit">
              {animalForm.formState.isSubmitting ? t("saving") : t("addAnimal")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
