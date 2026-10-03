import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { AssistantPanel } from "../../../../modules/shared/assistant";

export default async function AssistantPage() {
  const organization = await getServerCurrentOrganization();
  if (
    !organization ||
    !allows(panelAccess(organization), {
      module: "shared.assistant",
      permission: "assistant.use",
    })
  )
    notFound();
  return (
    <AssistantPanel
      canManageBilling={organization.role === "owner"}
      key={organization.id}
    />
  );
}
