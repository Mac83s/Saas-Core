import type { ReactNode } from "react";

import { SiteFooter } from "../../../marketing/components/site-footer";
import { SiteHeader } from "../../../marketing/components/site-header";

export default function MarketingLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
