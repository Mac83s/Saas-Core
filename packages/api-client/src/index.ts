import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

const client = createClient<paths>({ baseUrl: "" });

export type HealthStatus = components["schemas"]["Health"];
export type UserSummary = components["schemas"]["UserSummary"];
export type SessionSummary = components["schemas"]["SessionSummary"];
export type RegistrationInput = components["schemas"]["Registration"];
export type LoginInput = components["schemas"]["Login"];
export type PasswordResetRequestInput =
  components["schemas"]["PasswordResetRequest"];
export type PasswordResetConfirmInput =
  components["schemas"]["PasswordResetConfirm"];
export type ProblemDetails = components["schemas"]["ProblemDetails"];
export type TotpSetup = components["schemas"]["TotpSetup"];
export type TotpConfirmResult = components["schemas"]["TotpConfirmResult"];
export type OrganizationSummary = components["schemas"]["OrganizationSummary"];
export type OrganizationCreateInput =
  components["schemas"]["OrganizationCreate"];
export type OrganizationUpdateInput =
  components["schemas"]["PatchedOrganizationUpdate"];
export type InvitationSummary = components["schemas"]["InvitationSummary"];
export type InvitationCreateInput = components["schemas"]["InvitationCreate"];
export type MembershipSummary = components["schemas"]["MembershipSummary"];
export type MembershipUpdateInput =
  components["schemas"]["PatchedMembershipUpdate"];
export type EntitlementSupportReport =
  components["schemas"]["EntitlementSupportReport"];
export type EntitlementSupportItem =
  components["schemas"]["EntitlementSupportItem"];
export type CustomerBillingOverview =
  components["schemas"]["CustomerBillingOverview"];
export type CustomerPlan = components["schemas"]["CustomerPlan"];
export type CustomerSubscription =
  components["schemas"]["CustomerSubscription"];
export type BillingSession = components["schemas"]["BillingSession"];
export type TrialActivationResult =
  components["schemas"]["TrialActivationResult"];
export type SiteSummary = components["schemas"]["SiteSummary"];
export type SiteCreateInput = components["schemas"]["SiteCreate"];
export type SiteList = components["schemas"]["SiteList"];
export type PageSummary = components["schemas"]["PageSummary"];
export type PageCreateInput = components["schemas"]["PageCreate"];
export type PageList = components["schemas"]["PageList"];
export type PageDraft = components["schemas"]["PageDraft"];
export type DraftSaveInput = components["schemas"]["DraftSave"];
export type PageTranslation = components["schemas"]["PageTranslation"];
export type PageTranslationList = components["schemas"]["PageTranslationList"];
export type PageTranslationSaveInput =
  components["schemas"]["PageTranslationSave"];
export type SiteLocalizationReport =
  components["schemas"]["SiteLocalizationReport"];
export type SitePublication = components["schemas"]["SitePublication"];
export type SitePublicationList = components["schemas"]["SitePublicationList"];
export type SiteDomain = components["schemas"]["SiteDomain"];
export type SiteDomainList = components["schemas"]["SiteDomainList"];
export type DomainCreateInput = components["schemas"]["DomainCreate"];
export type DomainActionInput = components["schemas"]["DomainAction"];
export type PlatformDomainChangeInput =
  components["schemas"]["PlatformDomainChange"];
export type SiteOnboarding = components["schemas"]["SiteOnboarding"];
export type SiteOnboardingSaveInput =
  components["schemas"]["SiteOnboardingSave"];
export type SubdomainAvailability =
  components["schemas"]["SubdomainAvailability"];
export type PublicSitePage = components["schemas"]["PublicSitePage"];
export type MediaAsset = components["schemas"]["MediaAsset"];
export type MediaAssetList = components["schemas"]["MediaAssetList"];
export type MediaUploadInput = components["schemas"]["MediaUploadCreate"];
export type MediaUpload = components["schemas"]["MediaUpload"];
export type NotificationPreference = components["schemas"]["Preference"];
export type NotificationTemplateCatalog =
  components["schemas"]["TemplateCatalog"];
export type NotificationTemplatePreview =
  components["schemas"]["TemplatePreviewResult"];
export type IntegrationApiKey = components["schemas"]["ApiKey"];
export type IntegrationWebhook = components["schemas"]["Webhook"];
export type NotificationSupportHealth = components["schemas"]["SupportHealth"];
export type BookingCatalog = components["schemas"]["Catalog"];
export type BookingAppointment = components["schemas"]["Appointment"];
export type BookingAppointmentList = components["schemas"]["AppointmentList"];
export type BookingAppointmentInput =
  components["schemas"]["AppointmentCreate"];
export type BookingSlotList = components["schemas"]["SlotList"];
export type BookingCatalogInput = components["schemas"]["CatalogCreate"];
export type BookingScheduleInput = components["schemas"]["ScheduleCreate"];

export type LoginResult =
  { kind: "authenticated"; user: UserSummary } | { kind: "mfa_required" };

export class ApiProblemError extends Error {
  constructor(public readonly problem: ProblemDetails) {
    super(problemMessage(problem));
    this.name = "ApiProblemError";
  }
}

export async function getHealth(): Promise<HealthStatus> {
  const { data, error, response } = await client.GET("/api/v1/health/");
  if (error || !data) {
    throw new Error(`Health API zwróciło status ${response.status}`);
  }
  return data;
}

export async function getCurrentUser(): Promise<UserSummary> {
  const { data, error, response } = await client.GET("/api/v1/auth/me/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function registerAccount(
  input: RegistrationInput,
): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/register/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function loginAccount(input: LoginInput): Promise<LoginResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST("/api/v1/auth/login/", {
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !data) throwProblem(error, response);
  if (response.status === 202) return { kind: "mfa_required" };
  return { kind: "authenticated", user: data as UserSummary };
}

export async function completeMfaLogin(code: string): Promise<UserSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/login/mfa/",
    {
      body: { code },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function beginTotpSetup(): Promise<TotpSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/mfa/totp/setup/",
    {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function confirmTotpSetup(
  code: string,
): Promise<TotpConfirmResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/mfa/totp/confirm/",
    {
      body: { code },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function logoutAccount(): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST("/api/v1/auth/logout/", {
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !response.ok) throwProblem(error, response);
}

export async function requestEmailVerification(email: string): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/email-verifications/resend/",
    {
      body: { email },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function confirmEmailVerification(token: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/email-verifications/confirm/",
    {
      body: { token },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
}

export async function requestPasswordReset(
  input: PasswordResetRequestInput,
): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/password-resets/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.detail;
}

export async function confirmPasswordReset(
  input: PasswordResetConfirmInput,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/password-resets/confirm/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
}

export async function listSessions(): Promise<SessionSummary[]> {
  const { data, error, response } = await client.GET("/api/v1/auth/sessions/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeSession(sessionId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/auth/sessions/{session_id}/",
    {
      params: { path: { session_id: sessionId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function listOrganizations(): Promise<OrganizationSummary[]> {
  const { data, error, response } = await client.GET("/api/v1/organizations/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getEntitlementSupportReport(): Promise<EntitlementSupportReport> {
  const { data, error, response } = await client.GET(
    "/api/v1/billing/support/entitlements/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getCustomerBillingOverview(): Promise<CustomerBillingOverview> {
  const { data, error, response } = await client.GET(
    "/api/v1/billing/overview/",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createBillingCheckout(
  plan: string,
  idempotencyKey: string,
): Promise<BillingSession> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/billing/checkout/",
    {
      body: { plan },
      credentials: "same-origin",
      headers: {
        "Idempotency-Key": idempotencyKey,
        "X-CSRFToken": csrfToken,
      },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createBillingPortal(): Promise<BillingSession> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/billing/portal/",
    {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function activateBillingTrial(
  checkoutSessionId: string,
): Promise<TrialActivationResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/billing/trial-activation/",
    {
      body: { checkout_session_id: checkoutSessionId },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getCurrentOrganization(): Promise<OrganizationSummary> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createOrganization(
  input: OrganizationCreateInput,
): Promise<OrganizationSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/organizations/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function selectActiveOrganization(
  organizationId: string,
): Promise<OrganizationSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/session/active-organization/",
    {
      body: { organization_id: organizationId },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.organization;
}

export async function updateCurrentOrganization(
  input: OrganizationUpdateInput,
): Promise<OrganizationSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/organizations/current/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function archiveCurrentOrganization(): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/organizations/current/",
    {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function listInvitations(): Promise<InvitationSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/invitations/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createInvitation(
  input: InvitationCreateInput,
): Promise<InvitationSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/organizations/current/invitations/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeInvitation(invitationId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/organizations/current/invitations/{invitation_id}/",
    {
      params: { path: { invitation_id: invitationId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function acceptInvitation(
  token: string,
): Promise<MembershipSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/invitations/accept/",
    {
      body: { token },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listMemberships(): Promise<MembershipSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/members/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateMembership(
  membershipId: string,
  input: MembershipUpdateInput,
): Promise<MembershipSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/organizations/current/members/{membership_id}/",
    {
      params: { path: { membership_id: membershipId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function leaveCurrentOrganization(): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/organizations/current/members/me/leave/",
    {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function transferOwnership(membershipId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/organizations/current/ownership-transfer/",
    {
      body: { membership_id: membershipId },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function listSites(): Promise<SiteList> {
  const { data, error, response } = await client.GET("/api/v1/sites/", {
    params: { query: { limit: 100 } },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createSite(
  input: SiteCreateInput,
  idempotencyKey: string,
): Promise<SiteSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST("/api/v1/sites/", {
    params: { header: { "Idempotency-Key": idempotencyKey } },
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSitePages(siteId: string): Promise<PageList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/pages/",
    {
      params: { path: { site_id: siteId }, query: { limit: 100 } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createSitePage(
  siteId: string,
  input: PageCreateInput,
  idempotencyKey: string,
): Promise<PageSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/pages/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { site_id: siteId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getSiteLocalizationReport(
  siteId: string,
): Promise<SiteLocalizationReport> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/localization/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function publishSite(
  siteId: string,
  idempotencyKey: string,
): Promise<SitePublication> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/publications/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { site_id: siteId },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSitePublications(
  siteId: string,
): Promise<SitePublicationList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/publications/",
    {
      params: { path: { site_id: siteId }, query: { limit: 100 } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function rollbackSitePublication(
  siteId: string,
  publicationId: string,
  idempotencyKey: string,
): Promise<SitePublication> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/publications/{publication_id}/rollback/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { publication_id: publicationId, site_id: siteId },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSiteDomains(siteId: string): Promise<SiteDomainList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/domains/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createSiteDomain(
  siteId: string,
  input: DomainCreateInput,
  idempotencyKey: string,
): Promise<SiteDomain> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/domains/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { site_id: siteId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function mutateSiteDomain(
  domainId: string,
  input: DomainActionInput,
  idempotencyKey: string,
): Promise<SiteDomain> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/domains/{domain_id}/actions/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { domain_id: domainId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getSubdomainAvailability(
  label: string,
): Promise<SubdomainAvailability> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/subdomain-availability/",
    {
      params: { query: { label } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getSiteOnboarding(): Promise<SiteOnboarding> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/onboarding/",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function saveSiteOnboarding(
  input: SiteOnboardingSaveInput,
  idempotencyKey: string,
): Promise<SiteOnboarding> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/onboarding/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function completeSiteOnboarding(
  idempotencyKey: string,
): Promise<SiteSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/onboarding/complete/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function changePlatformDomain(
  siteId: string,
  input: PlatformDomainChangeInput,
  idempotencyKey: string,
): Promise<SiteDomain> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/{site_id}/platform-domain/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { site_id: siteId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getPageDraft(pageId: string): Promise<PageDraft> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/draft/",
    {
      params: { path: { page_id: pageId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function savePageDraft(
  pageId: string,
  input: DraftSaveInput,
  idempotencyKey: string,
): Promise<PageDraft> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/draft/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getPageDraftPreview(
  pageId: string,
  versionId: string,
): Promise<PageDraft> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/preview/{version_id}/",
    {
      params: { path: { page_id: pageId, version_id: versionId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listPageTranslations(
  pageId: string,
): Promise<PageTranslationList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/translations/",
    {
      params: { path: { page_id: pageId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function savePageTranslation(
  pageId: string,
  locale: string,
  input: PageTranslationSaveInput,
  idempotencyKey: string,
): Promise<PageTranslation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { locale, page_id: pageId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listMediaAssets(): Promise<MediaAssetList> {
  const { data, error, response } = await client.GET("/api/v1/media/", {
    params: { query: { limit: 100 } },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function initiateMediaUpload(
  input: MediaUploadInput,
  idempotencyKey: string,
): Promise<MediaUpload> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/media/uploads/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function completeMediaUpload(
  assetId: string,
): Promise<MediaAsset> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/media/uploads/{asset_id}/complete/",
    {
      params: { path: { asset_id: assetId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getNotificationPreferences(): Promise<NotificationPreference> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/preferences/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateNotificationPreferences(
  input: NotificationPreference,
): Promise<NotificationPreference> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/notifications/preferences/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getNotificationTemplates(): Promise<NotificationTemplateCatalog> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/templates/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function previewNotificationTemplate(input: {
  key: string;
  version: number;
  locale: "pl" | "en";
  context: Record<string, unknown>;
}): Promise<NotificationTemplatePreview> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/notifications/templates/preview/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listIntegrationApiKeys(): Promise<IntegrationApiKey[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/integrations/api-keys/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createIntegrationApiKey(input: {
  name: string;
  scopes: string[];
}): Promise<IntegrationApiKey> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/notifications/integrations/api-keys/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listIntegrationWebhooks(): Promise<IntegrationWebhook[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/integrations/webhooks/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createIntegrationWebhook(input: {
  name: string;
  url: string;
  events: string[];
}): Promise<IntegrationWebhook> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/notifications/integrations/webhooks/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getNotificationSupportHealth(): Promise<NotificationSupportHealth> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/support/health/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function retryNotificationMessage(
  messageId: string,
  reason: string,
): Promise<components["schemas"]["MessageStatus"]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/notifications/support/messages/{message_id}/retry/",
    {
      params: { path: { message_id: messageId } },
      body: { reason },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getBookingCatalog(): Promise<BookingCatalog> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/catalog/",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createBookingCatalogItem(
  input: BookingCatalogInput,
): Promise<{ id: string }> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/catalog/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data as { id: string };
}

export async function configureBookingSchedule(
  input: BookingScheduleInput,
): Promise<{ id: string }> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/schedule/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data as { id: string };
}

export async function listBookingAppointments(): Promise<BookingAppointment[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/appointments/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function getBookingSlots(query: {
  service_id: string;
  location_id: string;
  from: string;
  to: string;
}): Promise<BookingSlotList> {
  const { data, error, response } = await client.GET("/api/v1/booking/slots/", {
    params: { query },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createBookingAppointment(
  input: BookingAppointmentInput,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function cancelBookingAppointment(
  appointmentId: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/cancel/",
    {
      params: {
        path: { appointment_id: appointmentId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function rescheduleBookingAppointment(
  appointmentId: string,
  startsAt: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/reschedule/",
    {
      params: {
        path: { appointment_id: appointmentId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: { starts_at: startsAt },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getPublicBookingCatalog(
  publicSlug: string,
): Promise<BookingCatalog> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/public/{public_slug}/",
    { params: { path: { public_slug: publicSlug } }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getPublicBookingSlots(
  publicSlug: string,
  query: { service_id: string; location_id: string; from: string; to: string },
): Promise<BookingSlotList> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/public/{public_slug}/slots/",
    { params: { path: { public_slug: publicSlug }, query }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createPublicBookingAppointment(
  publicSlug: string,
  input: BookingAppointmentInput,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const { data, error, response } = await client.POST(
    "/api/v1/booking/public/{public_slug}/appointments/",
    {
      params: {
        path: { public_slug: publicSlug },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: input,
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getSelfServiceBooking(
  token: string,
): Promise<BookingAppointment> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/self-service/{token}/",
    { params: { path: { token } }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function rescheduleSelfServiceBooking(
  token: string,
  startsAt: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const { data, error, response } = await client.POST(
    "/api/v1/booking/self-service/{token}/reschedule/",
    {
      params: {
        path: { token },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: { starts_at: startsAt },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function cancelSelfServiceBooking(
  token: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const { data, error, response } = await client.POST(
    "/api/v1/booking/self-service/{token}/cancel/",
    {
      params: {
        path: { token },
        header: { "Idempotency-Key": idempotencyKey },
      },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

async function getCsrfToken(): Promise<string> {
  const cookieToken = readCookie("csrftoken");
  if (cookieToken) return cookieToken;
  const { data, error, response } = await client.GET("/api/v1/auth/csrf/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data.csrf_token;
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const prefix = `${name}=`;
  const rawValue = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix))
    ?.slice(prefix.length);
  if (!rawValue) return undefined;
  try {
    return decodeURIComponent(rawValue);
  } catch {
    return undefined;
  }
}

function throwProblem(error: unknown, response: Response): never {
  if (isProblemDetails(error)) throw new ApiProblemError(error);
  throw new Error(`API zwróciło status ${response.status}`);
}

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "code" in value &&
    "status" in value
  );
}

function problemMessage(problem: ProblemDetails): string {
  if (typeof problem.detail === "string") return problem.detail;
  return problem.title;
}
