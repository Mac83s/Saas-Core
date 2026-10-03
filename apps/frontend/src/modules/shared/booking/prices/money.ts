/**
 * Amounts are whole minor units (ADR-072 §7); a person types and reads major
 * ones. Nothing here works a price out — only how an amount is written.
 */

export function formatMoney(
  minor: number,
  currency: string,
  locale: string,
): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(
    minor / 100,
  );
}

/** "150", "150,5" or "150.50" as minor units; null for anything else. */
export function parseAmount(text: string): number | null {
  const match = /^(\d{1,7})(?:[.,](\d{1,2}))?$/.exec(text.replace(/\s/g, ""));
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
}

/** Minor units as the text of an amount field: "150,00" in Polish. */
export function amountText(
  minor: number | null | undefined,
  locale: string,
): string {
  if (minor === null || minor === undefined) return "";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    useGrouping: false,
  }).format(minor / 100);
}
