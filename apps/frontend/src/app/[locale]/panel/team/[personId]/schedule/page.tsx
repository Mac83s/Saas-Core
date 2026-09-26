import { panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { PersonCard } from "../../../../../../modules/shared/booking";

export default async function PersonSchedulePage({
  params,
}: {
  params: Promise<{ personId: string }>;
}) {
  const [{ personId }, organization, user] = await Promise.all([
    params,
    getServerCurrentOrganization(),
    getServerUser(),
  ]);
  return (
    <PersonCard
      access={panelAccess(organization)}
      organization={organization}
      personId={personId}
      tab="schedule"
      user={user}
    />
  );
}
