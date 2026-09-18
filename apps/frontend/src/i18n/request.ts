import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { product } from "../product";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;
  const core: Record<string, Record<string, unknown>> = (
    await import(`../../messages/${locale}.json`)
  ).default;

  // A product adds namespaces and keys; it does not get to drop core's (ADR-049).
  const messages = { ...core };
  for (const [namespace, entries] of Object.entries(
    product.messages?.[locale] ?? {},
  )) {
    messages[namespace] = { ...core[namespace], ...entries };
  }
  return { locale, messages };
});
