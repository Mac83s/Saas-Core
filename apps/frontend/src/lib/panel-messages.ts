import { createTranslator, type Messages as IntlMessages } from "next-intl";
import { getLocale, getMessages, getTimeZone } from "next-intl/server";
import { cache } from "react";

import { mergeMessages } from "#i18n/merge-messages";
import type { OrganizationTypeMessages } from "#lib/product-extension";
// Server-only through `server-auth`: never in the client menu's bundle.
import { getServerCurrentOrganization } from "#lib/server-auth";
import organizationMessages from "../product/organization-messages";

type Messages = Record<string, unknown>;

/**
 * The words the product changes for this kind of organization in this
 * locale, or null when it changes none (UX-080). An unknown type — no active
 * company, or one refusing the account until it turns on 2FA (35a) — keeps
 * the product's own words.
 */
export function typeMessages(
  type: string | null | undefined,
  locale: string,
  source: OrganizationTypeMessages = organizationMessages,
): Messages | null {
  if (!type) return null;
  const words = source[type]?.[locale as "pl" | "en"];
  return words && Object.keys(words).length > 0 ? words : null;
}

/**
 * The panel's messages for the active organization, once per request. Only
 * a type with words of its own gets a second set (`overridden`): every other
 * account keeps the one the root layout already sent.
 */
export const getPanelMessages = cache(
  async (): Promise<{ messages: Messages; overridden: boolean }> => {
    const [locale, messages, organization] = await Promise.all([
      getLocale(),
      getMessages(),
      getServerCurrentOrganization(),
    ]);
    const words = typeMessages(organization?.organization_type, locale);
    return words
      ? { messages: mergeMessages(messages, words), overridden: true }
      : { messages, overridden: false };
  },
);

/**
 * `getTranslations` for the panel's server pages: the same keys, with the
 * organization type's words laid over them. A panel page uses this, so its
 * title says what the client components under it say.
 */
export async function getPanelTranslations(namespace: string) {
  const [locale, timeZone, { messages }] = await Promise.all([
    getLocale(),
    getTimeZone(),
    getPanelMessages(),
  ]);
  // Keyed like `getTranslations`: the messages carry no static type here.
  return createTranslator<IntlMessages, string>({
    locale,
    timeZone,
    messages: messages as IntlMessages,
    namespace,
  });
}
