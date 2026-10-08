import { offersContentTypes, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import {
  SitesPanel,
  type SitesSection,
} from "../../../../modules/shared/sites";

/** Every page of "Strona internetowa" (ADR-057): the same panel, its own part. */
export async function sitesPage(
  section: SitesSection,
  page?: { pageId?: string; preview?: boolean; typeId?: string },
) {
  const organization = await getServerCurrentOrganization();
  return (
    <SitesPanel
      key={organization?.id ?? "no-organization"}
      canManageBilling={organization?.role === "owner"}
      contentTypesOffered={offersContentTypes(panelAccess(organization))}
      pageId={page?.pageId}
      previewOnOpen={page?.preview}
      section={section}
      typeId={page?.typeId}
    />
  );
}
