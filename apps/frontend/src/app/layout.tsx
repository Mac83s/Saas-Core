import type { Metadata } from "next";
import type { ReactNode } from "react";

import "@saas-core/ui/globals.css";

export const metadata: Metadata = {
  title: "SaaS Core",
  description: "Panel kontrolny platformy SaaS Core",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="pl">
      <body>{children}</body>
    </html>
  );
}
