"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  createHoofCareAnimal,
  createHoofCareFarm,
  listHoofCareAnimals,
  listHoofCareFarms,
  listHoofCareVisits,
  type HoofCareAnimal,
  type HoofCareFarm,
  type HoofCareVisit,
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
import { Input } from "@saas-core/ui/components/input";
import { Label } from "@saas-core/ui/components/label";
import { NativeSelect } from "@saas-core/ui/components/native-select";

/** Farms, their animals and the visits booked for them. */
export function HerdPanel() {
  const t = useTranslations("HoofCare");
  const [farms, setFarms] = useState<HoofCareFarm[]>([]);
  const [animals, setAnimals] = useState<HoofCareAnimal[]>([]);
  const [visits, setVisits] = useState<HoofCareVisit[]>([]);
  const [selectedFarm, setSelectedFarm] = useState("");
  const [problem, setProblem] = useState<string>();
  const [pending, setPending] = useState(false);

  const [farmName, setFarmName] = useState("");
  const [farmVillage, setFarmVillage] = useState("");
  const [animalTag, setAnimalTag] = useState("");
  const [animalName, setAnimalName] = useState("");

  const report = useCallback((error: unknown) => {
    setProblem(error instanceof ApiProblemError ? error.message : String(error));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextFarms, nextVisits] = await Promise.all([
        listHoofCareFarms(),
        listHoofCareVisits(),
      ]);
      setFarms(nextFarms);
      setVisits(nextVisits);
      setAnimals(await listHoofCareAnimals(selectedFarm || undefined));
      setProblem(undefined);
    } catch (error) {
      report(error);
    }
  }, [report, selectedFarm]);

  useEffect(() => {
    // The loader only updates state after its awaited requests settle.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  async function addFarm(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      await createHoofCareFarm({ name: farmName, village: farmVillage });
      setFarmName("");
      setFarmVillage("");
      await refresh();
    } catch (error) {
      report(error);
    } finally {
      setPending(false);
    }
  }

  async function addAnimal(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedFarm) return;
    setPending(true);
    try {
      await createHoofCareAnimal({
        farm_id: selectedFarm,
        national_id: animalTag,
        name: animalName,
      });
      setAnimalTag("");
      setAnimalName("");
      await refresh();
    } catch (error) {
      report(error);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("subtitle")}</p>
      </header>

      {problem ? (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("farms")}</CardTitle>
          <CardDescription>{t("farmsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <form className="flex flex-wrap items-end gap-3" onSubmit={addFarm}>
            <div className="flex flex-col gap-1">
              <Label htmlFor="farm-name">{t("farmName")}</Label>
              <Input
                id="farm-name"
                value={farmName}
                onChange={(event) => setFarmName(event.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="farm-village">{t("farmVillage")}</Label>
              <Input
                id="farm-village"
                value={farmVillage}
                onChange={(event) => setFarmVillage(event.target.value)}
              />
            </div>
            <Button type="submit" disabled={pending || farmName.trim() === ""}>
              {t("addFarm")}
            </Button>
          </form>

          {farms.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noFarms")}</p>
          ) : (
            <ul className="divide-y">
              {farms.map((farm) => (
                <li key={farm.id} className="flex items-center justify-between py-2">
                  <span>
                    <span className="font-medium">{farm.name}</span>
                    {farm.village ? (
                      <span className="text-muted-foreground text-sm"> · {farm.village}</span>
                    ) : null}
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedFarm(farm.id)}
                  >
                    {t("showAnimals")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("animals")}</CardTitle>
          <CardDescription>{t("animalsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="animal-farm">{t("farm")}</Label>
            <NativeSelect
              id="animal-farm"
              value={selectedFarm}
              onChange={(event) => setSelectedFarm(event.target.value)}
            >
              <option value="">{t("allFarms")}</option>
              {farms.map((farm) => (
                <option key={farm.id} value={farm.id}>
                  {farm.name}
                </option>
              ))}
            </NativeSelect>
          </div>

          <form className="flex flex-wrap items-end gap-3" onSubmit={addAnimal}>
            <div className="flex flex-col gap-1">
              <Label htmlFor="animal-tag">{t("animalTag")}</Label>
              <Input
                id="animal-tag"
                value={animalTag}
                onChange={(event) => setAnimalTag(event.target.value)}
                placeholder="PL 05432198765"
                required
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="animal-name">{t("animalName")}</Label>
              <Input
                id="animal-name"
                value={animalName}
                onChange={(event) => setAnimalName(event.target.value)}
              />
            </div>
            <Button
              type="submit"
              disabled={pending || selectedFarm === "" || animalTag.trim() === ""}
            >
              {t("addAnimal")}
            </Button>
          </form>
          {selectedFarm === "" ? (
            <p className="text-muted-foreground text-sm">{t("pickFarmFirst")}</p>
          ) : null}

          {animals.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noAnimals")}</p>
          ) : (
            <ul className="divide-y">
              {animals.map((animal) => (
                <li key={animal.id} className="flex items-center justify-between py-2">
                  <span>
                    <span className="font-medium">{animal.national_id}</span>
                    {animal.name ? (
                      <span className="text-muted-foreground text-sm"> · {animal.name}</span>
                    ) : null}
                  </span>
                  <span className="text-muted-foreground text-sm">{animal.farm_name}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("visits")}</CardTitle>
          <CardDescription>{t("visitsDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {visits.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noVisits")}</p>
          ) : (
            <ul className="divide-y">
              {visits.map((visit) => (
                <li key={visit.id} className="flex items-center justify-between py-2">
                  <span className="font-medium">{visit.farm_name}</span>
                  <span className="flex items-center gap-3">
                    <span className="text-muted-foreground text-sm">
                      {new Date(visit.starts_at).toLocaleString()}
                    </span>
                    <Badge variant="secondary">{visit.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
