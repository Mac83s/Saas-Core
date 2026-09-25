"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { EyeIcon, PencilIcon, PlusIcon, WarehouseIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";

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
  DataTable,
  DataTableField,
  DataTableFilter,
  DataTableSearch,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { ANIMAL_STATUSES, AnimalCard } from "./animal-card";
import { AnimalEditDialog } from "./animal-edit-dialog";
import { farmProblem } from "./problem";
import { Withdrawal } from "./withdrawal";

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
  const farmsText = useTranslations("Farms");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  // A farm's row in the register leads here with that farm already chosen.
  const params = useSearchParams();
  const hasOrganization = access.permissions !== null;
  const canRead = hasOrganization && allows(access, { permission: READ });
  const canManage = hasOrganization && allows(access, { permission: MANAGE });

  const [animals, setAnimals] = useState<FarmAnimal[]>();
  const [farms, setFarms] = useState<Farm[]>([]);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [farmId, setFarmId] = useState(params?.get("farm") ?? "");
  const [status, setStatus] = useState("");
  const [review, setReview] = useState(false);
  const [version, setVersion] = useState(0);
  const [adding, setAdding] = useState(false);
  const [opened, setOpened] = useState<FarmAnimal>();
  const [editing, setEditing] = useState<FarmAnimal>();
  const [notice, setNotice] = useState("");
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
        review: review || undefined,
      });
      if (request !== latest.current) return;
      setAnimals(found);
      setFailed(false);
    } catch {
      if (request === latest.current) setFailed(true);
    }
  }, [farmId, review, search]);

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
  const filtered = Boolean(search.trim() || farmId || status || review);
  // Wpisane przez firmę, jeszcze nieprzejrzane (ADR-051 pt 7). Nic nie znika:
  // hodowca decyduje, co z tym zrobić.
  const toReview = (animals ?? []).filter(
    (animal) => animal.review_requested_at,
  ).length;
  const statusLabel = (value: string) => {
    const key = ANIMAL_STATUSES.find((entry) => entry === value);
    return key ? t(`status_${key}`) : value;
  };

  const open = (animal: FarmAnimal, target: HTMLElement | null) => {
    setReturnTo(target);
    setOpened(animal);
  };

  const columns: ColumnDef<FarmAnimal, unknown>[] = [
    {
      id: "tag",
      accessorKey: "national_id",
      header: t("tag"),
      meta: { primary: true },
      cell: ({ row: { original: animal } }) => (
        <>
          <Button
            className="h-auto p-0 font-mono wrap-anywhere"
            onClick={(event) => open(animal, event.currentTarget)}
            type="button"
            variant="link"
          >
            {animal.national_id}
          </Button>
          {animal.review_requested_at ? (
            <Badge className="ml-2" variant="outline">
              {t("reviewBadge")}
            </Badge>
          ) : null}
          {animal.withdrawal_milk_until || animal.withdrawal_meat_until ? (
            <span className="mt-1 block">
              <Withdrawal
                meat={animal.withdrawal_meat_until}
                milk={animal.withdrawal_milk_until}
              />
            </span>
          ) : null}
        </>
      ),
    },
    {
      id: "name",
      accessorFn: (animal) => animal.name || animal.working_number,
      header: t("nameColumn"),
      cell: ({ row: { original: animal } }) => (
        <span className="wrap-anywhere">
          {animal.name || (animal.working_number ? "" : "—")}
          {animal.working_number ? (
            <span className="text-muted-foreground">
              {animal.name ? " · " : ""}#{animal.working_number}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "farm",
      accessorKey: "farm_name",
      header: t("farm"),
      cell: ({ row: { original: animal } }) => (
        <span className="wrap-anywhere">{animal.farm_name}</span>
      ),
    },
    {
      id: "status",
      accessorFn: (animal) => statusLabel(animal.status),
      header: t("status"),
      cell: ({ row: { original: animal } }) => (
        <Badge variant={animal.status === "active" ? "secondary" : "outline"}>
          {statusLabel(animal.status)}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: t("actions"),
      meta: { actions: true },
      cell: ({ row: { original: animal } }) => (
        <RowActions
          items={[
            {
              label: t("openCard"),
              icon: <EyeIcon aria-hidden="true" />,
              inline: true,
              onSelect: (trigger) => open(animal, trigger),
            },
            // Editing is always in sight where it is allowed (ADR-057).
            ...(canManage
              ? [
                  {
                    label: t("edit"),
                    icon: <PencilIcon aria-hidden="true" />,
                    inline: true,
                    onSelect: (trigger: HTMLElement | null) => {
                      setReturnTo(trigger);
                      setEditing(animal);
                    },
                  },
                ]
              : []),
            {
              label: t("openFarm"),
              icon: <WarehouseIcon aria-hidden="true" />,
              link: <Link href={`/panel/farms/${animal.farm_id}`} />,
            },
          ]}
          label={t("actionsFor", { tag: animal.national_id })}
        />
      ),
    },
  ];

  const toolbar = (
    <>
      <DataTableSearch
        id="animal-search"
        label={t("search")}
        onChange={setSearch}
        placeholder={t("searchHint")}
        value={search}
      />
      <DataTableField htmlFor="animal-farm" label={t("farm")}>
        <FarmField
          allLabel={t("allFarms")}
          emptyLabel={t("noFarmMatches")}
          farms={farms}
          id="animal-farm"
          onChange={setFarmId}
          value={farmId}
        />
      </DataTableField>
      <DataTableFilter
        id="animal-status"
        label={t("status")}
        onChange={(event) => setStatus(event.target.value)}
        value={status}
      >
        <option value="">{t("allStatuses")}</option>
        {ANIMAL_STATUSES.map((value) => (
          <option key={value} value={value}>
            {t(`status_${value}`)}
          </option>
        ))}
      </DataTableFilter>
      <Button
        aria-pressed={review}
        onClick={() => setReview((on) => !on)}
        type="button"
        variant={review ? "default" : "outline"}
      >
        {toReview > 0 && !review
          ? t("reviewFilterCount", { count: toReview })
          : t("reviewFilter")}
      </Button>
    </>
  );

  return (
    <PanelPage
      actions={
        canRead && canManage ? (
          <Button onClick={openAdd} type="button">
            <PlusIcon aria-hidden="true" />
            {t("add")}
          </Button>
        ) : null
      }
      description={t("description")}
      // The same register as the farms, seen by animal.
      eyebrow={farmsText("eyebrow")}
      notice={notice}
      title={t("title")}
    >
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
      ) : failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <DataTable
            caption={t("tableCaption")}
            columns={columns}
            data={rows}
            // The one next step, next to the empty list.
            emptyAction={
              !filtered && canManage ? (
                <Button onClick={openAdd} type="button">
                  <PlusIcon aria-hidden="true" />
                  {t("add")}
                </Button>
              ) : undefined
            }
            getRowId={(animal) => animal.id}
            labels={{
              ...labels,
              empty: filtered ? t("noResults") : t("empty"),
              loading: common("loading"),
            }}
            loading={!animals}
            toolbar={toolbar}
          />
          <p aria-live="polite" className="text-sm text-muted-foreground">
            {animals ? t("found", { count: rows.length }) : ""}
          </p>
        </div>
      )}

      {editing ? (
        <AnimalEditDialog
          animal={editing}
          key={editing.id}
          onClose={() => setEditing(undefined)}
          onSaved={(saved) => {
            setEditing(undefined);
            setNotice(t("saved", { tag: saved.national_id }));
            setVersion((value) => value + 1);
          }}
          returnTo={returnTo}
        />
      ) : null}

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
    </PanelPage>
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
