import { panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization, getServerUser } from "#lib/server-auth";
import { PeoplePanel } from "../../../../modules/shared/booking";

export default async function PeoplePage() {
  const [organization, user] = await Promise.all([
    getServerCurrentOrganization(),
    getServerUser(),
  ]);
  return (
    <PeoplePanel
      access={panelAccess(organization)}
      organization={organization}
      userId={user?.id}
    />
  );
}
