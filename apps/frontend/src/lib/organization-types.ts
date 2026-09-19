import { deployment } from "../generated/deployment";

/** A kind of organization the product declares (ADR-050). */
export type OrganizationTypeInfo = {
  key: string;
  label: { pl: string; en: string };
  description: { pl: string; en: string } | null;
  modules: readonly string[];
  planKeys: readonly string[];
  selfSignup: boolean;
};

const types: readonly OrganizationTypeInfo[] = deployment.organizationTypes;

/** The kinds a person may create themselves — the sign-up question. */
export const selfSignupTypes = types.filter((type) => type.selfSignup);

/** The type of an organization; the product's default when unknown. */
export function organizationType(key?: string | null): OrganizationTypeInfo {
  return types.find((type) => type.key === key) ?? types[0];
}

/**
 * The modules an organization may use: every core module plus its type's.
 * The API enforces the same list; this only keeps the panel from offering
 * what would answer 404.
 */
export function modulesFor(key?: string | null): Set<string> {
  const allowed = new Set(organizationType(key).modules);
  return new Set(
    deployment.modules.filter(
      (module) => module.startsWith("core.") || allowed.has(module),
    ),
  );
}

export function typeText(
  text: { pl: string; en: string } | null,
  locale: string,
): string {
  if (!text) return "";
  return locale === "en" ? text.en : text.pl;
}
