/** An amount in minor units as people read it. Nothing here adds amounts up:
 *  every number on an order is the server's (ADR-073 §3). */
export function formatMoney(
  minor: number,
  currency: string,
  locale: string,
): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(
    minor / 100,
  );
}
