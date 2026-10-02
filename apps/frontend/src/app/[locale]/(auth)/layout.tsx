import type { Metadata } from "next";
import type { ReactNode } from "react";

// Sign-in, registration and password pages are doors, not content: a search
// result pointing at one helps nobody (ADR-071).
export const metadata: Metadata = { robots: { index: false, follow: true } };

export default function AuthLayout({ children }: { children: ReactNode }) {
  return children;
}
