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

/**
 * What fits a narrow block (UX-028): a person as „Barbara W.”, a module's
 * name of the visit (a farm) whole — its distinguishing word is the last.
 */
export function visitShortName(a: Named): string {
  if (a.title) return a.title;
  const words = a.customer_name.trim().split(/\s+/);
  if (words.length < 2) return a.customer_name;
  const last = words[words.length - 1] ?? "";
  return `${words[0]} ${last.charAt(0)}.`;
}
