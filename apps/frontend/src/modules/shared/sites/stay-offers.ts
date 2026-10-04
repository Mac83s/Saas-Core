"use client";

import { useEffect, useState } from "react";

import { getBookingSetup } from "@saas-core/api-client";

import { deployment } from "../../../generated/deployment";

/** Everything the editor offers of stays — the blocks in „Dodaj pustą
 *  sekcję”, their library sections, the „Noclegi” page template. */
export const isStayBlock = (type: string) => type.startsWith("core.stay_");

/**
 * Whether the company has an offer booked from–to (ADR-072, slice 5f): what
 * a stay block, a stay section and the „Noclegi” template are for. Without
 * one they would draw nothing on the published page, so the editor does not
 * offer them. Read once from the company's booking setup; `false` until it
 * answers, where the product has no public booking form, and for a person
 * who does not see the company's bookings. A section already on the page is
 * edited and drawn whatever this says.
 */
export function useStayOffers(): boolean {
  const [stays, setStays] = useState(false);
  useEffect(() => {
    if (!deployment.features.publicBooking) return;
    let current = true;
    getBookingSetup()
      .then((setup) =>
        setup.services.some(
          (service) => service.time_model === "range" && service.active,
        ),
      )
      .catch(() => false)
      .then((found) => {
        if (current) setStays(found);
      });
    return () => {
      current = false;
    };
  }, []);
  return stays;
}

/** What the library and the template gallery ask for with the company's
 *  stays in hand, and without them. */
export const stayEntitlements = (stays: boolean) =>
  stays ? ["sites.enabled", "booking.enabled"] : ["sites.enabled"];
export const stayModules = (stays: boolean) =>
  stays ? ["shared.sites", "shared.booking"] : ["shared.sites"];
