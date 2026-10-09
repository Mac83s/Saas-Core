import { ApiProblemError } from "@saas-core/api-client";

type Translate = (key: string) => string;

/** A refusal in the panel's words. A refused field carries its own reason:
 *  the problem's code is then only „invalid”, and the code that says what is
 *  wrong sits on the field (`errors[].code`) — both are read. */
export function sitesErrorMessage(error: unknown, t: Translate): string {
  if (!(error instanceof ApiProblemError)) return t("problem");
  const own = knownMessage(error.problem.code, t);
  if (own !== undefined) return own;
  for (const item of error.problem.errors ?? []) {
    const named = knownMessage(item.code, t);
    if (named !== undefined) return named;
  }
  return typeof error.problem.detail === "string"
    ? error.problem.detail
    : t("problem");
}

/** Whether the server refused with this code, on the problem or on a field. */
export function refusedWith(error: unknown, code: string): boolean {
  return (
    error instanceof ApiProblemError &&
    (error.problem.code === code ||
      (error.problem.errors ?? []).some((item) => item.code === code))
  );
}

function knownMessage(
  code: string | null | undefined,
  t: Translate,
): string | undefined {
  switch (code) {
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
    case "entry_slug_taken":
      return t("entryAddress.errors.taken");
    case "entry_slug_former":
      return t("entryAddress.errors.former");
    case "entry_slug_invalid":
      return t("entryAddress.errors.invalid");
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
    case "confirmation_stale":
      return t("contentTypes.confirmationStale");
    case "erasure_needs_publish":
      return t("contentTypes.erasureNeedsPublish");
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
      return undefined;
  }
}
