import { getServerCurrentOrganization } from "#lib/server-auth";
import { RolesPanel } from "../../../../../modules/core/organizations";

export default async function RolesPage() {
  return <RolesPanel organization={await getServerCurrentOrganization()} />;
}
