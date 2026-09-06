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
    case "site_onboarding_version_conflict":
      return t("conflict");
    case "domain_hostname_conflict":
      return t("subdomainReason_taken");
    case "entry_translation_exists":
      return t("entryTranslationExists");
    case "proposal_not_found":
      return t("proposalNotFound");
    case "proposal_superseded":
      return t("proposalSuperseded");
    case "proposal_review_mismatch":
      return t("proposalReviewExpired");
    case "entry_too_many_tags":
      return t("tagsTooMany");
    case "entry_tag_name_invalid":
      return t("tagsNameInvalid");
    case "entry_schedule_in_past":
      return t("scheduleInPast");
    case "entry_schedule_not_pending":
      return t("scheduleNotPending");
    case "domain_quarantined":
      return t("subdomainReason_quarantined");
    default:
      return typeof error.problem.detail === "string"
        ? error.problem.detail
        : t("problem");
  }
}
