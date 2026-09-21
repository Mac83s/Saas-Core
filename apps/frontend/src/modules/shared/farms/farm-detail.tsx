"use client";

import { useEffect, useMemo, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import {
  ArrowLeftIcon,
  KeyRoundIcon,
  MailIcon,
  MapPinIcon,
  PencilIcon,
  PhoneIcon,
  PlusIcon,
  SendIcon,
} from "lucide-react";

import {
  createFarmAnimal,
  issueFarmActivationCode,
  listFarmAnimals,
  listFarmShares,
  listFarmSpecies,
  readFarm,
  revokeFarmShare,
  sendFarmHerd,
  updateFarm,
  updateFarmAnimal,
  type Farm,
  type FarmAnimal,
  type FarmShare,
  type FarmSpecies,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardAction,
  CardContent,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";

import { Link } from "#i18n/navigation";
import { FarmForm } from "./farm-form";
import { FarmVisits, ScheduleConsent } from "./farm-visits";
import { FarmNoAccess, FarmNotice, focusRing } from "./farms-panel";
import { farmProblem, farmProblemKind, type FarmProblem } from "./problem";

const STATUSES = ["active", "sold", "culled", "dead"] as const;

type AnimalValues = {
  species: string;
  national_id: string;
  working_number: string;
  name: string;
  sex: "female" | "male" | "unknown";
  birth_date: string;
};

/**
 * One farm's card (ADR-051): who to call, what stands in the barn and what to
 * remember about it. A product's field work belongs to the product, so it is
 * not shown here. The visits tab is the one exception and only on the farmer's
 * side: those rows live in this register (ADR-052), while a company reads its
 * own visits in its own module.
 */
export function FarmDetail({
  farmId,
  canManage = false,
  canRead = false,
}: {
  farmId: string;
  /** farms.manage: edit the farm and its animals. */
  canManage?: boolean;
  /** farms.read: see the card at all. The API enforces both. */
  canRead?: boolean;
}) {
  const t = useTranslations("Farms");
  const common = useTranslations("Common");
  const format = useFormatter();
  const locale = useLocale();
  const [farm, setFarm] = useState<Farm>();
  const [species, setSpecies] = useState<FarmSpecies[]>([]);
  const [animals, setAnimals] = useState<FarmAnimal[]>();
  const [shares, setShares] = useState<FarmShare[]>([]);
  const [code, setCode] = useState<{ code: string; expires_at: string }>();
  const [search, setSearch] = useState("");
  const [problem, setProblem] = useState<FarmProblem>();
  const [failed, setFailed] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [reloads, setReloads] = useState(0);
  const refresh = () => setReloads((value) => value + 1);

  useEffect(() => {
    if (!canRead) return;
    let current = true;
    Promise.all([readFarm(farmId), listFarmSpecies(), listFarmShares(farmId)])
      .then(([loadedFarm, loadedSpecies, loadedShares]) => {
        if (!current) return;
        setFarm(loadedFarm);
        setSpecies(loadedSpecies);
        setShares(loadedShares);
        setProblem(undefined);
      })
      .catch((error: unknown) => {
        if (current) setProblem(farmProblemKind(error));
      });
    return () => {
      current = false;
    };
  }, [canRead, farmId, reloads]);

  // The server searches (a big herd is longer than one screen), and only the
  // answer to the newest query may land.
  useEffect(() => {
    if (!canRead) return;
    let current = true;
    const timer = setTimeout(() => {
      listFarmAnimals({ farmId, search: search.trim() || undefined })
        .then((found) => {
          if (current) setAnimals(found);
        })
        .catch((error: unknown) => {
          if (current) setProblem(farmProblemKind(error));
        });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [canRead, farmId, reloads, search]);

  const speciesLabel = (key: string) => {
    const entry = species.find((item) => item.key === key);
    if (!entry) return key;
    return (locale === "en" ? entry.label.en : entry.label.pl) ?? entry.key;
  };

  async function sendHerd() {
    setFailed("");
    try {
      const result = await sendFarmHerd(farmId);
      setNotice(t("herdSent", result));
      refresh();
    } catch (error) {
      setFailed(farmProblem(error, t("saveFailed")));
    }
  }

  async function issueCode() {
    setFailed("");
    try {
      setCode(await issueFarmActivationCode(farmId));
    } catch (error) {
      setFailed(farmProblem(error, t("saveFailed")));
    }
  }

  async function revoke(share: FarmShare) {
    setFailed("");
    try {
      const revoked = await revokeFarmShare(share.id);
      setShares((current) =>
        current.map((item) => (item.id === share.id ? revoked : item)),
      );
      setNotice(t("shareRevokedNotice", { name: share.partner_name }));
    } catch (error) {
      setFailed(farmProblem(error, t("saveFailed")));
    }
  }

  async function changeStatus(animal: FarmAnimal, status: string) {
    setFailed("");
    try {
      await updateFarmAnimal(animal.id, {
        status: status as (typeof STATUSES)[number],
      });
      setNotice(t("statusChanged", { tag: animal.national_id }));
      refresh();
    } catch (error) {
      setFailed(farmProblem(error, t("saveFailed")));
    }
  }

  if (!canRead)
    return (
      <div className="space-y-6">
        <BackLink />
        <FarmNoAccess />
      </div>
    );

  if (problem && !farm)
    return (
      <div className="space-y-6">
        <BackLink />
        <FarmNotice kind={problem} onRetry={refresh} />
      </div>
    );

  // Czyj to wiersz: rejestr rolnika czy karta firmy. Rdzeń nie zna typów
  // organizacji żadnego produktu (ADR-049), więc rozstrzyga to udział — a
  // `partner_is_company` mówi wprost, że po tej stronie stoi rejestr.
  const isRegistry = shares.some((share) => share.partner_is_company);
  const place = [farm?.address, farm?.village].filter(Boolean).join(", ");
  const editDialog = farm ? (
    <Dialog onOpenChange={setEditing} open={editing}>
      <DialogTrigger render={<Button size="sm" variant="outline" />}>
        <PencilIcon aria-hidden="true" />
        {t("edit")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("edit")}</DialogTitle>
          <DialogDescription>{farm.name}</DialogDescription>
        </DialogHeader>
        <FarmForm
          farm={farm}
          onSubmit={async (_values, changed) => {
            try {
              setFarm(await updateFarm(farm.id, changed));
              setEditing(false);
              setNotice(t("saved"));
              return undefined;
            } catch (error) {
              return farmProblem(error, t("saveFailed"));
            }
          }}
          submitLabel={t("save")}
        />
      </DialogContent>
    </Dialog>
  ) : null;

  return (
    <div className="space-y-6">
      <BackLink />
      {farm ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                <h1 className="text-2xl font-semibold tracking-tight wrap-anywhere">
                  {farm.name}
                </h1>
              </CardTitle>
              {canManage ? <CardAction>{editDialog}</CardAction> : null}
            </CardHeader>
            <CardContent className="space-y-4">
              <ul className="space-y-1.5 text-sm">
                {place ? (
                  <li>
                    <a
                      className={`inline-flex items-center gap-2 hover:underline ${focusRing}`}
                      href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${farm.name}, ${place}`)}`}
                      rel="noreferrer"
                      target="_blank"
                    >
                      <MapPinIcon
                        aria-hidden="true"
                        className="size-4 shrink-0 text-muted-foreground"
                      />
                      <span className="wrap-anywhere">{place}</span>
                      <span className="sr-only">{t("openMap")}</span>
                    </a>
                  </li>
                ) : null}
                {farm.keeper_name ? (
                  <li className="flex items-center gap-2">
                    <span className="text-muted-foreground">
                      {t("keeper_name")}:
                    </span>
                    <span className="wrap-anywhere">{farm.keeper_name}</span>
                  </li>
                ) : null}
                {farm.phone ? (
                  <li>
                    <a
                      className={`inline-flex items-center gap-2 hover:underline ${focusRing}`}
                      href={`tel:${farm.phone.replaceAll(" ", "")}`}
                    >
                      <PhoneIcon
                        aria-hidden="true"
                        className="size-4 shrink-0 text-muted-foreground"
                      />
                      {farm.phone}
                    </a>
                  </li>
                ) : null}
                {farm.email ? (
                  <li>
                    <a
                      className={`inline-flex items-center gap-2 hover:underline ${focusRing}`}
                      href={`mailto:${farm.email}`}
                    >
                      <MailIcon
                        aria-hidden="true"
                        className="size-4 shrink-0 text-muted-foreground"
                      />
                      <span className="wrap-anywhere">{farm.email}</span>
                    </a>
                  </li>
                ) : null}
                {place ||
                farm.keeper_name ||
                farm.phone ||
                farm.email ? null : (
                  <li className="text-muted-foreground">{t("noDetails")}</li>
                )}
              </ul>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {t("animalCount", { count: farm.animal_count })}
                </Badge>
                <Badge variant="outline">
                  {t("herd_number")}: {farm.herd_number || t("unknown")}
                </Badge>
                {farm.tax_id ? (
                  <Badge variant="outline">
                    {t("tax_id")}: {farm.tax_id}
                  </Badge>
                ) : null}
              </div>
            </CardContent>
          </Card>

          {problem ? <FarmNotice kind={problem} onRetry={refresh} /> : null}

          <Tabs defaultValue="animals">
            <TabsList>
              <TabsTab value="animals">{t("animals")}</TabsTab>
              {/* Tylko rejestr rolnika: wizyty publikują tu firmy, którym on
                  udostępnił gospodarstwo. Na karcie firmy ta zakładka nie
                  miałaby z czego się wziąć — wiersze stoją u rolnika. */}
              {isRegistry ? (
                <TabsTab value="visits">{t("visits")}</TabsTab>
              ) : null}
              <TabsTab value="notes">{t("notes")}</TabsTab>
              <TabsTab value="sharing">{t("sharing")}</TabsTab>
              <TabsIndicator />
            </TabsList>

            <TabsPanel className="space-y-4" value="animals">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div className="grid gap-1.5 sm:w-80">
                  <Label htmlFor="animals-search">{t("searchAnimals")}</Label>
                  <Input
                    id="animals-search"
                    onChange={(event) => setSearch(event.target.value)}
                    type="search"
                    value={search}
                  />
                </div>
                {canManage ? (
                  <AnimalDialog
                    farmId={farmId}
                    onAdded={(tag) => {
                      setNotice(t("animalAdded", { tag }));
                      refresh();
                    }}
                    onOpenChange={setAdding}
                    open={adding}
                    species={species}
                    speciesLabel={speciesLabel}
                  />
                ) : null}
              </div>
              {!animals ? (
                <div aria-busy="true" className="space-y-2">
                  <span className="sr-only">{t("loadingAnimals")}</span>
                  {[0, 1, 2].map((row) => (
                    <div
                      className="h-12 animate-pulse rounded-lg bg-muted"
                      key={row}
                    />
                  ))}
                </div>
              ) : animals.length === 0 ? (
                <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-muted-foreground">
                  {search.trim() ? t("noAnimalResults") : t("noAnimals")}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <caption className="sr-only">{t("animalsCaption")}</caption>
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="py-2 pr-3 font-medium" scope="col">
                          {t("tag")}
                        </th>
                        <th className="py-2 pr-3 font-medium" scope="col">
                          {t("status")}
                        </th>
                        <th
                          className="hidden py-2 font-medium sm:table-cell"
                          scope="col"
                        >
                          {t("lastChange")}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {animals.map((animal) => (
                        <tr key={animal.id}>
                          <th
                            className="py-2 pr-3 text-left align-middle font-normal"
                            scope="row"
                          >
                            <p className="font-mono font-medium wrap-anywhere">
                              {animal.national_id}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {[
                                animal.name,
                                animal.working_number &&
                                  `#${animal.working_number}`,
                                speciesLabel(animal.species),
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                          </th>
                          <td className="py-2 pr-3 align-middle">
                            {canManage ? (
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
                            ) : (
                              <Badge variant="secondary">
                                {t(`status_${animal.status}`)}
                              </Badge>
                            )}
                          </td>
                          <td className="hidden py-2 align-middle text-muted-foreground tabular-nums sm:table-cell">
                            {format.dateTime(new Date(animal.updated_at), {
                              dateStyle: "medium",
                            })}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </TabsPanel>

            {isRegistry ? (
              <TabsPanel className="space-y-4" value="visits">
                <p className="text-sm text-muted-foreground">
                  {t("visitsDescription")}
                </p>
                <FarmVisits farmId={farmId} />
              </TabsPanel>
            ) : null}

            <TabsPanel className="space-y-4" value="notes">
              {farm.notes ? (
                <p className="text-sm whitespace-pre-line">{farm.notes}</p>
              ) : (
                <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-muted-foreground">
                  {t("noNotes")}
                </p>
              )}
              {/* The note is edited in the farm's form, whose dialog is the
                  one in the header — this only opens it. */}
              {canManage ? (
                <Button
                  onClick={() => setEditing(true)}
                  size="sm"
                  variant="outline"
                >
                  <PencilIcon aria-hidden="true" />
                  {t("editNotes")}
                </Button>
              ) : null}
            </TabsPanel>

            <TabsPanel className="space-y-4" value="sharing">
              <p className="text-sm text-muted-foreground">
                {t("sharingDescription")}
              </p>
              {shares.length === 0 ? (
                <p className="rounded-xl border border-dashed bg-muted/30 p-6 text-muted-foreground">
                  {t("noShares")}
                </p>
              ) : (
                <ul className="divide-y rounded-xl border">
                  {shares.map((share) => (
                    <li className="space-y-3 p-4" key={share.id}>
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-medium wrap-anywhere">
                            {share.partner_name || t("unknown")}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            {t(
                              share.partner_is_company
                                ? "shareFromCompany"
                                : "shareToFarmer",
                              {
                                date: format.dateTime(
                                  new Date(share.granted_at),
                                  {
                                    dateStyle: "medium",
                                  },
                                ),
                              },
                            )}
                          </p>
                        </div>
                        {share.status === "active" ? (
                          share.partner_is_company && canManage ? (
                            <Button
                              onClick={() => revoke(share)}
                              size="sm"
                              variant="outline"
                            >
                              {t("revokeShare")}
                            </Button>
                          ) : canManage ? (
                            /* Strona firmy: dosyła stado do rejestru hodowcy
                               — kod przekazania zamraża kartę w chwili
                               wydania, więc sztuki dopisane później same tam
                               nie trafią. */
                            <Button
                              onClick={sendHerd}
                              size="sm"
                              variant="outline"
                            >
                              <SendIcon aria-hidden="true" />
                              {t("sendHerd")}
                            </Button>
                          ) : (
                            <Badge variant="outline">{t("shareActive")}</Badge>
                          )
                        ) : (
                          <Badge variant="secondary">{t("shareRevoked")}</Badge>
                        )}
                      </div>
                      {/* Zgoda rolnika na grafik firmy (ADR-052 pkt 4): jego
                          strona, jego decyzja — firma jej sobie nie nada.
                          Cofnięty udział nie ma czego dotyczyć. */}
                      {share.partner_is_company && share.status === "active" ? (
                        <ScheduleConsent
                          canManage={canManage}
                          onChanged={(saved, allowed) => {
                            setShares((current) =>
                              current.map((item) =>
                                item.id === saved.id ? saved : item,
                              ),
                            );
                            setNotice(
                              t(
                                allowed
                                  ? "scheduleConsentOnNotice"
                                  : "scheduleConsentOffNotice",
                                { name: saved.partner_name || t("unknown") },
                              ),
                            );
                          }}
                          share={share}
                        />
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              {/* Kod wydaje firma, i tylko dopóki karta nie jest połączona:
                  po połączeniu API odpowiada 409, a przycisk obiecywałby coś,
                  czego nie da się zrobić. Na własnym rejestrze rolnika
                  gospodarstwo i tak jest już jego. */}
              {canManage &&
              !shares.some(
                (share) =>
                  share.status === "active" && !share.partner_is_company,
              ) &&
              !shares.some((share) => share.partner_is_company) ? (
                <div className="space-y-2">
                  <Button onClick={issueCode} size="sm" variant="outline">
                    <KeyRoundIcon aria-hidden="true" />
                    {t("issueCode")}
                  </Button>
                  {code ? (
                    <div aria-live="polite" className="space-y-1">
                      <p className="font-mono text-lg tracking-widest select-all">
                        {code.code}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {t("codeHint", {
                          date: format.dateTime(new Date(code.expires_at), {
                            dateStyle: "medium",
                          }),
                        })}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </TabsPanel>
          </Tabs>

          {failed ? (
            <p className="text-sm text-destructive" role="alert">
              {failed}
            </p>
          ) : null}
          <p aria-live="polite" className="text-sm text-success-foreground">
            {notice}
          </p>
        </>
      ) : (
        <div aria-busy="true" className="space-y-2">
          <span className="sr-only">{t("loading")}</span>
          <div className="h-36 animate-pulse rounded-xl bg-muted" />
          <div className="h-48 animate-pulse rounded-xl bg-muted" />
        </div>
      )}
    </div>
  );
}

function BackLink() {
  const t = useTranslations("Farms");
  return (
    <Link
      className={`inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground ${focusRing}`}
      href="/panel/farms"
    >
      <ArrowLeftIcon aria-hidden="true" className="size-4" />
      {t("back")}
    </Link>
  );
}

/** Adding one animal: species and the number on its tag is the whole of it. */
function AnimalDialog({
  farmId,
  onAdded,
  onOpenChange,
  open,
  species,
  speciesLabel,
}: {
  farmId: string;
  onAdded: (tag: string) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  species: FarmSpecies[];
  speciesLabel: (key: string) => string;
}) {
  const t = useTranslations("Farms");
  const common = useTranslations("Common");
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
  const form = useForm<AnimalValues>({
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

  async function submit(values: AnimalValues) {
    try {
      const animal = await createFarmAnimal({
        farm_id: farmId,
        species: values.species as "cattle",
        national_id: values.national_id,
        working_number: values.working_number,
        name: values.name,
        sex: values.sex,
        birth_date: values.birth_date || null,
      });
      form.reset();
      onOpenChange(false);
      onAdded(animal.national_id);
    } catch (error) {
      form.setError("root", {
        type: "server",
        message: farmProblem(error, t("saveFailed")),
      });
    }
  }

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogTrigger render={<Button />}>
        <PlusIcon aria-hidden="true" />
        {t("addAnimal")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("addAnimal")}</DialogTitle>
          <DialogDescription>{t("addAnimalDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          noValidate
          onSubmit={form.handleSubmit(submit)}
        >
          <FieldGroup>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel htmlFor="animal-species">{t("species")}</FieldLabel>
                <NativeSelect id="animal-species" {...form.register("species")}>
                  {species.map((entry) => (
                    <option
                      disabled={!entry.active}
                      key={entry.key}
                      value={entry.key}
                    >
                      {speciesLabel(entry.key)}
                      {entry.active ? "" : ` (${t("soon")})`}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field data-invalid={Boolean(form.formState.errors.national_id)}>
                <FieldLabel htmlFor="animal-tag">{t("tag")}</FieldLabel>
                <Input
                  aria-invalid={Boolean(form.formState.errors.national_id)}
                  id="animal-tag"
                  placeholder="PL 005432198765"
                  {...form.register("national_id")}
                />
                <FieldError errors={[form.formState.errors.national_id]} />
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-working">
                  {t("workingNumber")}
                </FieldLabel>
                <Input
                  id="animal-working"
                  {...form.register("working_number")}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-name">{t("animalName")}</FieldLabel>
                <Input id="animal-name" {...form.register("name")} />
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-sex">{t("sex")}</FieldLabel>
                <NativeSelect id="animal-sex" {...form.register("sex")}>
                  <option value="female">{t("sex_female")}</option>
                  <option value="male">{t("sex_male")}</option>
                  <option value="unknown">{t("sex_unknown")}</option>
                </NativeSelect>
              </Field>
              <Field>
                <FieldLabel htmlFor="animal-birth">{t("birthDate")}</FieldLabel>
                <Input
                  id="animal-birth"
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
            {form.formState.isSubmitting ? t("saving") : t("addAnimal")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
