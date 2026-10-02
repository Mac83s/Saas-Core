import type { SettingOptions } from "@saas-core/api-client";

/**
 * The currencies a company may choose, as the API offers them (ADR-078):
 * `[code, "Name (CODE)"]` in the panel's language. A company that already
 * keeps a currency the platform no longer offers still sees its own.
 */
export function currencyChoices(
  options: SettingOptions | null,
  locale: string,
  current?: string,
): [string, string][] {
  const entry = options?.keys.find(
    (item) => item.key === "organization.currency",
  );
  const choices: [string, string][] = (entry?.values ?? []).map((value) => [
    value.value,
    `${locale === "en" ? value.label.en : value.label.pl} (${value.value})`,
  ]);
  if (current && !choices.some(([code]) => code === current)) {
    const name = new Intl.DisplayNames(locale, { type: "currency" }).of(
      current,
    );
    choices.push([current, name ? `${name} (${current})` : current]);
  }
  return choices;
}

/** The currency a new company starts with. */
export function defaultCurrency(
  options: SettingOptions | null,
): string | undefined {
  const entry = options?.keys.find(
    (item) => item.key === "organization.currency",
  );
  return typeof entry?.default === "string" ? entry.default : undefined;
}
