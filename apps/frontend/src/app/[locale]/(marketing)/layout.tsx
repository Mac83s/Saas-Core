import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { SiteFooter } from "../../../marketing/components/site-footer";
import { SiteHeader } from "../../../marketing/components/site-header";
import { marketingSiteEnabled } from "../../../marketing/enabled";

export default function MarketingLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  // The proxy already answers these addresses 404 where the profile switches
  // the marketing off (`features.marketingSite`); the layout holds the same
  // line for a request that got past it.
  if (!marketingSiteEnabled) notFound();
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
