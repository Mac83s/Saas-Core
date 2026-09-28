"use client";

import { useTranslations } from "next-intl";

import type { StaffTeam } from "@saas-core/api-client";

/**
 * A person's teams in a row's width (boards 1 and 15): the first by name, the
 * rest as „+N” for the eye and by name for a screen reader.
 */
export function TeamNames({
  ids,
  teams,
}: {
  ids: string[];
  teams: StaffTeam[];
}) {
  const t = useTranslations("Teams");
  const names = teams
    .filter((team) => ids.includes(team.id))
    .map((team) => team.name);
  if (!names.length) return <>—</>;
  const [first, ...rest] = names;
  return (
    <>
      {first}
      {rest.length ? (
        <>
          <span
            aria-hidden="true"
            className="ml-1.5 rounded-sm bg-muted px-1 text-xs text-muted-foreground"
          >
            +{rest.length}
          </span>
          <span className="sr-only">
            {" "}
            {t("andMore", { names: rest.join(", ") })}
          </span>
        </>
      ) : null}
    </>
  );
}
