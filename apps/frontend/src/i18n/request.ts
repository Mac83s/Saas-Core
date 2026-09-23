import { hasLocale } from "next-intl";
import { getRequestConfig } from "next-intl/server";

import { product } from "../product";
import { mergeMessages } from "./merge-messages";
import { routing } from "./routing";

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested)
    ? requested
    : routing.defaultLocale;
  const core = (await import(`../../messages/${locale}.json`)).default;
  const messages = mergeMessages(core, product.messages?.[locale] ?? {});
  // Without a zone next-intl formats in the server's, and the containers run
  // in UTC: an 08:00 visit read "06:00". Screens that know the organization's
  // zone pass it themselves.
  // ponytail: one zone per deployment; per-organization zones when a product
  // serves more than one country.
  return {
    locale,
    messages,
    timeZone: process.env.APP_TIME_ZONE ?? "Europe/Warsaw",
  };
});
