import type { ReactNode } from "react";

import { companyOnly } from "#lib/company-only";

/** „Kalendarz” and every page under it: a company's, not a platform workspace's. */
export default async function CalendarLayout({
  children,
}: {
  children: ReactNode;
}) {
  await companyOnly();
  return children;
}
