import { ApiProblemError } from "@saas-core/api-client";

type Translate = (key: string) => string;

export function sitesErrorMessage(error: unknown, t: Translate): string {
  if (!(error instanceof ApiProblemError)) return t("problem");
  switch (error.problem.code) {
    case "organization_permission_denied":
    case "entitlement_required":
      return t("noAccess");
    case "quota_exceeded":
      return t("quotaExceeded");
    case "site_publication_not_ready":
      return t("notReady");
    case "draft_version_conflict":
    case "translation_version_conflict":
    case "site_publication_already_current":
    case "sites_idempotency_conflict":
      return t("conflict");
    default:
      return typeof error.problem.detail === "string"
        ? error.problem.detail
        : t("problem");
  }
}
