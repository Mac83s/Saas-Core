import { panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { PersonCard } from "../../../../../modules/shared/booking";

export default async function PersonPage({
  params,
}: {
  params: Promise<{ personId: string }>;
}) {
  const [{ personId }, organization, user] = await Promise.all([
    params,
    getServerCurrentOrganization(),
    getServerUser(),
  ]);
  // The API decides who sees whom; "me" is everybody's own card.
  return (
    <PersonCard
      access={panelAccess(organization)}
      organization={organization}
      personId={personId}
      tab="overview"
      user={user}
    />
  );
}
