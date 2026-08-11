import type { ReactNode } from "react";

import "@saas-core/ui/globals.css";

export default function PublicSiteLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html>
      <body>{children}</body>
    </html>
  );
}
