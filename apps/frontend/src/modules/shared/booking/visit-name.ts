/** A visit as far as its name goes; a just-booked one may not have a title yet. */
type Named = { customer_name: string; title?: string };

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
