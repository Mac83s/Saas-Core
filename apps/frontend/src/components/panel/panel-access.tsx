"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { PanelAccess } from "#lib/panel-navigation";

const AccessContext = createContext<PanelAccess | null>(null);

/**
 * The membership's access for client code deep inside a screen: a hook that
 * reads in the background has nobody to hand it the access as a prop. The
 * panel's layout provides it; outside the panel there is none.
 */
export function PanelAccessProvider({
  access,
  children,
}: {
  access: PanelAccess;
  children: ReactNode;
}) {
  return (
    <AccessContext.Provider value={access}>{children}</AccessContext.Provider>
  );
}

/**
 * Whether a screen may ask a module's API in the background. Not in a
 * platform workspace that is not offered the module (ADR-077 pkt 9): the API
 * refuses it there whatever the role, so the question could only leave a 403
 * in the console. Everywhere else as before — a company's plan answers for
 * itself, and the screen says what the answer was.
 */
export function useAsksModule(module: string): boolean {
  const access = useContext(AccessContext);
  return !access?.publisher || access.modules.includes(module);
}

/**
 * Whether this is the panel of the platform's own workspace (ADR-077 pkt 9).
 * Its builder site answers at no host — what it publishes is shown by the
 * product's own pages (ADR-079 pkt 29) — so a screen that would name or open
 * the site's address asks here first. False in every company's panel, and
 * outside the panel.
 */
export function usePublisher(): boolean {
  return useContext(AccessContext)?.publisher === true;
}
