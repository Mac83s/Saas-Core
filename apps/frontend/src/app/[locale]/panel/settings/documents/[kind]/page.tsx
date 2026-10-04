import { notFound } from "next/navigation";

import { allows, panelAccess } from "#lib/panel-navigation";
import { getServerCurrentOrganization } from "#lib/server-auth";
import { CustomerDocumentPanel } from "../../../../../../modules/shared/customers";

const KINDS = [
  "booking_terms",
  "shop_terms",
  "privacy_policy",
  "cancellation_policy",
] as const;

export default async function CustomerDocumentPage({
  params,
}: {
  params: Promise<{ kind: string }>;
}) {
  const { kind } = await params;
  const known = KINDS.find((item) => item === kind);
  const organization = await getServerCurrentOrganization();
  const access = organization ? panelAccess(organization) : undefined;
  if (
    !known ||
    !access ||
    !allows(access, {
      module: "shared.customers",
      permission: "customers.read",
    })
  ) {
    notFound();
  }
  return (
    <CustomerDocumentPanel
      canManage={allows(access, {
        module: "shared.customers",
        permission: "customers.manage",
      })}
      kind={known}
      // „Tłumaczenia” is an entry of „Strona internetowa”: an organization
      // without websites reaches what waits for acceptance from here only.
      website={access.modules.includes("shared.sites")}
    />
  );
}
