"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { PlusIcon, SearchIcon } from "lucide-react";

import {
  createFarmAnimal,
  listFarmAnimals,
  listFarms,
  type Farm,
  type FarmAnimal,
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
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { allows, type PanelAccess } from "#lib/panel-navigation";
import { ANIMAL_STATUSES, AnimalCard } from "./animal-card";
import { farmProblem } from "./problem";

// The API decides; these only keep the screen from offering a 403.
const READ = "farms.read";
const MANAGE = "farms.manage";

/** Above this many farms the picker gets a filter instead of a list (ADR-020). */
const FILTERABLE = 20;

type NewAnimal = {
  farm_id: string;
  national_id: string;
  name: string;
  working_number: string;
  sex: "female" | "male" | "unknown";
  birth_date: string;
};

/**
 * Every animal of every farm in the organization, in one list (ADR-051): the
 * register a trimmer works from in the barn, where the farm is a filter rather
 * than the way in. What a trade records about an animal is the product's, so
 * the columns here are the register's own — the rest lives in the card's
 * product sections.
 */
export function AnimalsPanel({ access }: { access: PanelAccess }) {
  const t = useTranslations("Animals");
  const common = useTranslations("Common");
  const hasOrganization = access.permissions !== null;
  const canRead = hasOrganization && allows(access, { permission: READ });
  const canManage = hasOrganization && allows(access, { permission: MANAGE });

  const [animals, setAnimals] = useState<FarmAnimal[]>();
  const [farms, setFarms] = useState<Farm[]>([]);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [farmId, setFarmId] = useState("");
  const [status, setStatus] = useState("");
  const [version, setVersion] = useState(0);
  const [adding, setAdding] = useState(false);
  const [opened, setOpened] = useState<FarmAnimal>();
  // The row that opened the card gets focus back when it closes.
  const [returnTo, setReturnTo] = useState<HTMLElement | null>(null);

  // Only the answer to the newest query may land: an older, slower search
  // would otherwise replace the list under a newer one.
  const latest = useRef(0);
  const load = useCallback(async () => {
    const request = ++latest.current;
    try {
      const found = await listFarmAnimals({
        farmId: farmId || undefined,
        search: search.trim() || undefined,
      });
      if (request !== latest.current) return;
      setAnimals(found);
      setFailed(false);
    } catch {
      if (request === latest.current) setFailed(true);
    }
  }, [farmId, search]);

  useEffect(() => {
    if (!canRead) return;
    const timer = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer);
  }, [canRead, load, version]);

  // The farms of the filter and of the form: one list, loaded once. Deriving
  // them from the animals would hide a farm with no animals — and collapse to
  // one option as soon as the filter is used.
  useEffect(() => {
    if (!canRead) return;
    void listFarms()
      .then(setFarms)
      .catch(() => setFarms([]));
  }, [canRead]);

  const schema = useMemo(
    () =>
      z.object({
        farm_id: z.string().min(1, t("farmRequired")),
        national_id: z.string().trim().min(4, t("tagRequired")),
        name: z.string(),
        working_number: z.string(),
        sex: z.enum(["female", "male", "unknown"]),
        birth_date: z.string(),
      }),
    [t],
  );
  const form = useForm<NewAnimal>({
    resolver: zodResolver(schema),
    defaultValues: {
      farm_id: "",
      national_id: "",
      name: "",
      working_number: "",
      sex: "female",
      birth_date: "",
    },
  });

  // `watch()` would opt the whole panel out of the React Compiler.
  const chosenFarm = useWatch({ control: form.control, name: "farm_id" });

  function openAdd() {
    // The farm being looked at is the one most likely being added to.
    form.reset({
      farm_id: farmId,
      national_id: "",
      name: "",
      working_number: "",
      sex: "female",
      birth_date: "",
    });
    setAdding(true);
  }

  async function add(values: NewAnimal) {
    try {
      // ponytail: no species field — the catalogue has one active species and
      // the API defaults it (services._clean_animal). Add a picker when a
      // second one goes active.
      await createFarmAnimal({
        farm_id: values.farm_id,
        national_id: values.national_id,
        name: values.name,
        working_number: values.working_number,
        sex: values.sex,
        birth_date: values.birth_date || null,
      });
      setAdding(false);
      setVersion((value) => value + 1);
    } catch (error) {
      form.setError("root", {
        type: "server",
        message: farmProblem(error, t("saveFailed")),
      });
    }
  }

  // ponytail: the API has no status filter (services.list_animals), so the page
  // it returns is filtered here. Ceiling: its PAGE_LIMIT of 500 rows; a
  // `status` query parameter moves it to the server.
  const rows = (animals ?? []).filter(
    (animal) => !status || animal.status === status,
  );
  const filtered = Boolean(search.trim() || farmId || status);
  const statusLabel = (value: string) => {
    const key = ANIMAL_STATUSES.find((entry) => entry === value);
    return key ? t(`status_${key}`) : value;
  };

  const addButton = (
    <Button onClick={openAdd} type="button">
      <PlusIcon aria-hidden="true" />
      {t("add")}
    </Button>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-muted-foreground">{t("description")}</p>
        </div>
        {canRead && canManage ? addButton : null}
      </div>

      {!canRead ? (
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>
                {t(hasOrganization ? "noAccessTitle" : "noOrganizationTitle")}
              </h2>
            </CardTitle>
            <CardDescription>
              {t(hasOrganization ? "noAccess" : "noOrganization")}
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>
              <h2>{t("listTitle")}</h2>
            </CardTitle>
            <CardDescription>{t("listDescription")}</CardDescription>
            <div className="grid gap-4 pt-2 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr]">
              <Field>
                <FieldLabel htmlFor="animal-search">{t("search")}</FieldLabel>
                <div className="relative">
                  <SearchIcon
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                  />
                  <Input
                    aria-describedby="animal-search-hint"
                    className="pl-9"
                    id="animal-search"
                    onChange={(event) => setSearch(event.target.value)}
                    value={search}
                  />
                </div>
                <FieldDescription id="animal-search-hint">
                  {t("searchHint")}
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-farm">{t("farm")}</FieldLabel>
                <FarmField
                  allLabel={t("allFarms")}
                  emptyLabel={t("noFarmMatches")}
                  farms={farms}
                  id="animal-farm"
                  onChange={setFarmId}
                  value={farmId}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-status">{t("status")}</FieldLabel>
                <NativeSelect
                  id="animal-status"
                  onChange={(event) => setStatus(event.target.value)}
                  value={status}
                >
                  <option value="">{t("allStatuses")}</option>
                  {ANIMAL_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {t(`status_${value}`)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {failed ? (
              <div className="flex flex-wrap items-center gap-3" role="alert">
                <p className="text-sm text-destructive">{t("loadError")}</p>
                <Button onClick={() => void load()} variant="outline">
                  {t("retry")}
                </Button>
              </div>
            ) : !animals ? (
              <div aria-busy="true" className="space-y-2">
                <span className="sr-only">{common("loading")}</span>
                {[0, 1, 2].map((row) => (
                  <div
                    className="h-12 animate-pulse rounded-lg bg-muted"
                    key={row}
                  />
                ))}
              </div>
            ) : rows.length === 0 ? (
              <div className="space-y-3 py-4 text-center">
                <p className="text-muted-foreground">
                  {filtered ? t("noResults") : t("empty")}
                </p>
                {!filtered && canManage ? addButton : null}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">{t("tableCaption")}</caption>
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="py-2 pr-3 font-medium" scope="col">
                        {t("tag")}
                      </th>
                      <th className="py-2 pr-3 font-medium" scope="col">
                        {t("nameColumn")}
                      </th>
                      <th className="py-2 pr-3 font-medium" scope="col">
                        {t("farm")}
                      </th>
                      <th className="py-2 font-medium" scope="col">
                        {t("status")}
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {rows.map((animal) => (
                      <tr key={animal.id}>
                        <td className="py-2 pr-3 align-top">
                          <Button
                            className="h-auto p-0 font-mono wrap-anywhere"
                            onClick={(event) => {
                              setReturnTo(event.currentTarget);
                              setOpened(animal);
                            }}
                            type="button"
                            variant="link"
                          >
                            {animal.national_id}
                          </Button>
                        </td>
                        <td className="py-3 pr-3 align-top wrap-anywhere">
                          {animal.name || (animal.working_number ? "" : "—")}
                          {animal.working_number ? (
                            <span className="text-muted-foreground">
                              {animal.name ? " · " : ""}#{animal.working_number}
                            </span>
                          ) : null}
                        </td>
                        <td className="py-3 pr-3 align-top wrap-anywhere">
                          {animal.farm_name}
                        </td>
                        <td className="py-3 align-top">
                          <Badge
                            variant={
                              animal.status === "active"
                                ? "secondary"
                                : "outline"
                            }
                          >
                            {statusLabel(animal.status)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p aria-live="polite" className="text-sm text-muted-foreground">
              {animals && !failed ? t("found", { count: rows.length }) : ""}
            </p>
          </CardContent>
        </Card>
      )}

      {opened ? (
        <AnimalCard
          access={access}
          animal={opened}
          canManage={canManage}
          key={opened.id}
          onChanged={() => setVersion((value) => value + 1)}
          onClose={() => setOpened(undefined)}
          returnTo={returnTo}
        />
      ) : null}

      <Dialog onOpenChange={setAdding} open={adding}>
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("add")}</DialogTitle>
            <DialogDescription>{t("addDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            noValidate
            onSubmit={(event) => void form.handleSubmit(add)(event)}
          >
            <FieldGroup>
              <Field data-invalid={Boolean(form.formState.errors.farm_id)}>
                <FieldLabel htmlFor="new-animal-farm">{t("farm")}</FieldLabel>
                <FarmField
                  emptyLabel={t("noFarmMatches")}
                  farms={farms}
                  id="new-animal-farm"
                  invalid={Boolean(form.formState.errors.farm_id)}
                  onChange={(value) =>
                    form.setValue("farm_id", value, { shouldValidate: true })
                  }
                  placeholder={t("chooseFarm")}
                  value={chosenFarm}
                />
                <FieldError errors={[form.formState.errors.farm_id]} />
              </Field>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  data-invalid={Boolean(form.formState.errors.national_id)}
                >
                  <FieldLabel htmlFor="new-animal-tag">{t("tag")}</FieldLabel>
                  <Input
                    aria-invalid={Boolean(form.formState.errors.national_id)}
                    id="new-animal-tag"
                    placeholder="PL 005432198765"
                    {...form.register("national_id")}
                  />
                  <FieldError errors={[form.formState.errors.national_id]} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="new-animal-name">
                    {t("animalName")}
                  </FieldLabel>
                  <Input id="new-animal-name" {...form.register("name")} />
                </Field>
                <Field>
                  <FieldLabel htmlFor="new-animal-working">
                    {t("workingNumber")}
                  </FieldLabel>
                  <Input
                    id="new-animal-working"
                    {...form.register("working_number")}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="new-animal-sex">{t("sex")}</FieldLabel>
                  <NativeSelect id="new-animal-sex" {...form.register("sex")}>
                    <option value="female">{t("sex_female")}</option>
                    <option value="male">{t("sex_male")}</option>
                    <option value="unknown">{t("sex_unknown")}</option>
                  </NativeSelect>
                </Field>
                <Field className="sm:col-span-2">
                  <FieldLabel htmlFor="new-animal-birth">
                    {t("birthDate")}
                  </FieldLabel>
                  <Input
                    id="new-animal-birth"
                    type="date"
                    {...form.register("birth_date")}
                  />
                </Field>
              </div>
            </FieldGroup>
            {form.formState.errors.root ? (
              <p className="text-sm text-destructive" role="alert">
                {form.formState.errors.root.message}
              </p>
            ) : null}
            <Button disabled={form.formState.isSubmitting} type="submit">
              {form.formState.isSubmitting ? t("saving") : t("add")}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/**
 * Which farm — as a list while the list is short, with a filter once it is not
 * (ADR-020). `allLabel` makes it a filter that may stand on "all".
 */
function FarmField({
  allLabel,
  emptyLabel,
  farms,
  id,
  invalid,
  onChange,
  placeholder,
  value,
}: {
  allLabel?: string;
  emptyLabel: string;
  farms: Farm[];
  id: string;
  invalid?: boolean;
  onChange: (farmId: string) => void;
  placeholder?: string;
  value: string;
}) {
  if (farms.length > FILTERABLE)
    return (
      <Combobox
        items={farms}
        itemToStringLabel={(item: Farm) => item.name}
        itemToStringValue={(item: Farm) => item.id}
        onValueChange={(item: Farm | null) => onChange(item?.id ?? "")}
        value={farms.find((farm) => farm.id === value) ?? null}
      >
        <ComboboxInput
          aria-invalid={invalid}
          id={id}
          placeholder={allLabel ?? placeholder}
          showClear={Boolean(allLabel)}
        />
        <ComboboxContent>
          <ComboboxEmpty>{emptyLabel}</ComboboxEmpty>
          <ComboboxList>
            {farms.map((farm) => (
              <ComboboxItem key={farm.id} value={farm}>
                {farm.name}
              </ComboboxItem>
            ))}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    );
  return (
    <NativeSelect
      aria-invalid={invalid}
      id={id}
      onChange={(event) => onChange(event.target.value)}
      value={value}
    >
      <option value="">{allLabel ?? placeholder}</option>
      {farms.map((farm) => (
        <option key={farm.id} value={farm.id}>
          {farm.name}
        </option>
      ))}
    </NativeSelect>
  );
}
