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
    case "media_scanner_unavailable":
      return t("scannerBusy");
    case "page_limit_reached":
      return t("pageLimitReached");
    case "content_type_archived":
      return t("contentTypeArchived");
    case "content_type_not_empty":
      return t("contentTypeNotEmpty");
    case "slug_is_content_type":
      return t("slugIsContentType");
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
    case "entry_too_many_categories":
      return t("entryCategories.tooMany");
    case "term_name_taken":
      return t("terms.errors.name_taken");
    case "term_name_invalid":
      return t("terms.errors.name_invalid");
    case "term_too_deep":
      return t("terms.errors.too_deep");
    case "term_parent_invalid":
      return t("terms.errors.parent_invalid");
    case "term_in_use":
      return t("terms.errors.in_use");
    case "term_slug_taken":
      return t("terms.errors.slug_taken");
    case "term_slug_former":
      return t("terms.errors.slug_former");
    case "term_slug_invalid":
      return t("terms.errors.slug_invalid");
    case "term_not_of_type":
      return t("terms.errors.not_of_type");
    case "taxonomy_term_not_found":
      return t("terms.errors.not_found");
    case "redirect_reason_required":
      return t("terms.reasonRequired");
    case "confirmation_required":
      return t("contentTypes.confirmationRequired");
    case "entry_schedule_in_past":
      return t("scheduleInPast");
    case "entry_schedule_not_pending":
      return t("scheduleNotPending");
    case "domain_quarantined":
      return t("subdomainReason_quarantined");
    case "duplicate_rich_text_anchor":
      return t("duplicateAnchor");
    case "invalid_section_presentation":
      return t("invalidSectionPresentation");
    case "invalid_page_presentation":
      return t("invalidPagePresentation");
    case "site_template_name_taken":
      return t("ownTemplates.nameTaken");
    case "site_template_limit_reached":
      return t("ownTemplates.limitReachedShort");
    case "site_template_version_conflict":
      return t("ownTemplates.versionConflict");
    case "site_template_not_found":
      return t("ownTemplates.notFound");
    case "page_is_homepage":
      return t("pagesList.errorHomepage");
    case "page_is_last":
      return t("pagesList.errorLast");
    case "page_already_deleted":
      return t("pagesList.errorAlreadyDeleted");
    case "page_not_deleted":
      return t("pagesList.errorNotDeleted");
    case "redirect_target_unavailable":
      return t("pagesList.errorRedirectTarget");
    case "page_restore_slug_taken":
      return t("pagesList.errorSlugTaken");
    default:
      return typeof error.problem.detail === "string"
        ? error.problem.detail
        : t("problem");
  }
}
