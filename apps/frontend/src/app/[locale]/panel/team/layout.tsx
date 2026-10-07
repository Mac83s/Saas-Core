import type { ReactNode } from "react";

import { companyOnly } from "#lib/company-only";

/** „Zespół” and every page under it: a company's, not a platform workspace's. */
export default async function TeamLayout({
  children,
}: {
  children: ReactNode;
}) {
  await companyOnly();
  return children;
}
