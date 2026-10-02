import type { BookingAppointment } from "@saas-core/api-client";

type Named = Pick<BookingAppointment, "title" | "customer_name">;

/**
 * What the calendar calls a visit: the name the module that owns it gives it —
 * a herd visit's farm (UX plan W2) — else the customer's.
 */
export function visitName(appointment: Named): string {
  return appointment.title || appointment.customer_name;
}

/** The customer, when the visit goes by another name; null when they are its name. */
export function visitPerson(appointment: Named): string | null {
  return appointment.title ? appointment.customer_name : null;
}
