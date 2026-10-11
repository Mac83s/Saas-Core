"use client";

import { useEffect, useMemo, useState } from "react";

import {
  listBookingFormFields,
  type BookingFormField,
} from "@saas-core/api-client";

import type { OwnField } from "../public-booking-parts";

/**
 * The offer's own form fields as the panel's booking dialogs ask them
 * (ADR-072, slice 5j): what the public form asks of this offer, in its
 * order — without the consents, which only the customer gives (the consent
 * journal cannot say a box was ticked for somebody). The office answers the
 * mandatory ones for the caller, except those the company lets the team leave
 * empty (`mandatory_for_staff`); the server requires the same.
 *
 * A list that did not load asks nothing here: the server still refuses a
 * booking without a mandatory answer and says which.
 */
export function useOfferFields(serviceId: string): OwnField[] {
  const [fields, setFields] = useState<BookingFormField[]>([]);
  useEffect(() => {
    let live = true;
    listBookingFormFields()
      .then((list) => {
        if (live) setFields(list.items);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  return useMemo(
    () =>
      fields
        .filter(
          (field) =>
            field.active &&
            field.kind !== "consent" &&
            field.service_id === serviceId,
        )
        .sort((a, b) => a.position - b.position)
        .map((field) => ({
          id: field.id,
          service_id: field.service_id,
          name: field.name,
          kind: field.kind,
          // An older backend sends no flag: the team stays bound then.
          mandatory: field.mandatory && field.mandatory_for_staff !== false,
          // The panel speaks the company's own language: the words are theirs.
          options: field.options.map((value) => ({ value, label: value })),
        })),
    [fields, serviceId],
  );
}
