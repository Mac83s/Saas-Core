import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

const client = createClient<paths>({ baseUrl: "" });

export type SeoAuditOrder = components["schemas"]["AuditOrder"];
export type SeoAuditSummary = components["schemas"]["AuditOrderSummary"];
export type SeoAuditList = components["schemas"]["AuditList"];
export type SeoAuditOffer = components["schemas"]["AuditOffer"];
export type SeoAuditInput = components["schemas"]["AuditRequest"];

export async function getSeoAuditOffer(): Promise<SeoAuditOffer> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/audit-offer/",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSeoAudits(cursor?: string): Promise<SeoAuditList> {
  const { data, error, response } = await client.GET("/api/v1/seo/audits/", {
    params: { query: { limit: 50, ...(cursor ? { cursor } : {}) } },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readSeoAudit(orderId: string): Promise<SeoAuditOrder> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/audits/{order_id}/",
    {
      params: { path: { order_id: orderId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function requestSeoAudit(
  input: SeoAuditInput,
): Promise<SeoAuditOrder> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST("/api/v1/seo/audits/", {
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

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
export type RoleSummary = components["schemas"]["RoleSummary"];
export type RoleCatalog = components["schemas"]["RoleCatalog"];
export type RoleCreateInput = components["schemas"]["RoleCreate"];
export type RoleUpdateInput = components["schemas"]["PatchedRoleUpdate"];
export type MembershipUpdateInput =
  components["schemas"]["PatchedMembershipUpdate"];
export type EntitlementSupportReport =
  components["schemas"]["EntitlementSupportReport"];
export type EntitlementSupportItem =
  components["schemas"]["EntitlementSupportItem"];
export type AppNotificationInbox =
  components["schemas"]["AppNotificationInbox"];
export type AppNotification = components["schemas"]["AppNotification"];
export type CustomerCreditsOverview =
  components["schemas"]["CustomerCreditsOverview"];
export type CreditPack = components["schemas"]["CreditPack"];
export type CreditPurchase = components["schemas"]["CreditPurchase"];
/** A plan as the public pricing page shows it — no organization attached. */
export type PublicPlan = components["schemas"]["PublicPlan"];
export type CustomerBillingOverview =
  components["schemas"]["CustomerBillingOverview"];
export type BillingDetails = components["schemas"]["BillingDetails"];
export type BillingDetailsState = components["schemas"]["BillingDetailsState"];
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
export type PageTemplateImportInput =
  components["schemas"]["PageTemplateImport"];
export type PageTranslation = components["schemas"]["PageTranslation"];
export type PageTranslationList = components["schemas"]["PageTranslationList"];
export type PageTranslationSaveInput =
  components["schemas"]["PageTranslationSave"];
export type SiteLocalizationReport =
  components["schemas"]["SiteLocalizationReport"];
export type SitePublication = components["schemas"]["SitePublication"];
export type SitePublicationList = components["schemas"]["SitePublicationList"];
export type SiteNavigation = components["schemas"]["SiteNavigation"];
export type SiteRedirect = components["schemas"]["SiteRedirect"];
export type AutomationConnection =
  components["schemas"]["AutomationConnection"];
export type ContentProposal = components["schemas"]["ContentProposal"];
export type ContentProposalDetail =
  components["schemas"]["ContentProposalDetail"];
export type PageUrlChangeInput = components["schemas"]["PageUrlChange"];
export type ContentCollection = components["schemas"]["ContentCollection"];
export type ContentEntry = components["schemas"]["ContentEntry"];
export type ContentEntryDraft = components["schemas"]["ContentEntryDraft"];
export type EntrySchedule = components["schemas"]["EntryScheduleState"];
export type ContentTag = components["schemas"]["ContentTag"];
export type ContentEntryPublication =
  components["schemas"]["ContentEntryPublication"];
export type SiteNavigationItem = components["schemas"]["NavigationItem"];
export type SiteNavigationSaveInput =
  components["schemas"]["SiteNavigationSave"];
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
export type BookingPublicCatalog = components["schemas"]["PublicCatalog"];
export type BookingAppointment = components["schemas"]["Appointment"];
export type BookingPublicAppointment =
  components["schemas"]["PublicAppointment"];
export type BookingMaterialInput = components["schemas"]["MaterialInput"];
export type BookingMaterialLine = components["schemas"]["MaterialLine"];
export type BookingAppointmentList = components["schemas"]["AppointmentList"];
export type BookingAppointmentInput =
  components["schemas"]["AppointmentCreate"];
/** The customer's booking: service, place, time; never a person (ADR-058 §4). */
export type BookingPublicAppointmentInput =
  components["schemas"]["PublicAppointmentCreate"];
export type BookingSlotList = components["schemas"]["SlotList"];
export type BookingSlotTimeList = components["schemas"]["SlotTimeList"];
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

/** The person's own name (greeting, initials, who did the visit). */
export async function updateCurrentUser(
  input: components["schemas"]["PatchedUserUpdate"],
): Promise<UserSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH("/api/v1/auth/me/", {
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
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

export async function getNotificationInbox(): Promise<AppNotificationInbox> {
  const { data, error, response } = await client.GET(
    "/api/v1/notifications/inbox/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function markNotificationsRead(
  ids?: string[],
): Promise<AppNotificationInbox> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/notifications/inbox/read/",
    {
      body: ids && ids.length > 0 ? { ids } : {},
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
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

export async function updateBillingDetails(
  details: BillingDetails,
): Promise<BillingDetailsState> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/billing/details/",
    {
      body: details,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getCustomerCredits(): Promise<CustomerCreditsOverview> {
  const { data, error, response } = await client.GET(
    "/api/v1/billing/credits/",
    {
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createCreditCheckout(
  pack: string,
  idempotencyKey: string,
): Promise<BillingSession> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/billing/credits/checkout/",
    {
      body: { pack },
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

/** The roles the organization can hand out: its type's and its own (ADR-050). */
export async function listRoles(): Promise<RoleCatalog> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/roles/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createRole(input: RoleCreateInput): Promise<RoleSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/organizations/current/roles/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateRole(
  roleKey: string,
  input: RoleUpdateInput,
): Promise<RoleSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/organizations/current/roles/{role_key}/",
    {
      params: { path: { role_key: roleKey } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function deleteRole(roleKey: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/organizations/current/roles/{role_key}/",
    {
      params: { path: { role_key: roleKey } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error) throwProblem(error, response);
}

export async function listMemberships(): Promise<MembershipSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/members/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type HistoryPage = components["schemas"]["HistoryPage"];
export type HistoryEntry = components["schemas"]["HistoryEntry"];

/** The organization's history of changes, newest first (owner and admin). */
export async function readOrganizationHistory(
  query: { page?: number; pageSize?: number; action?: string } = {},
): Promise<HistoryPage> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/history/",
    {
      params: {
        query: {
          page: query.page,
          page_size: query.pageSize,
          action: query.action || undefined,
        },
      },
      credentials: "same-origin",
      cache: "no-store",
    },
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

export async function importPageTemplate(
  pageId: string,
  input: PageTemplateImportInput,
  idempotencyKey: string,
): Promise<PageDraft> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/template-import/",
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

/** Authenticated, tenant-scoped processed image; never a public storage URL. */
export async function getMediaAssetPreview(
  assetId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const { data, error, response } = await client.GET(
    "/api/v1/media/{asset_id}/preview/",
    {
      params: { path: { asset_id: assetId } },
      credentials: "same-origin",
      cache: "no-store",
      parseAs: "blob",
      signal,
    },
  );
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

export async function listBookingAppointments(
  filters: { mine?: boolean } = {},
): Promise<BookingAppointment[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/appointments/",
    {
      params: filters.mine ? { query: { mine: true } } : undefined,
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

/** Renames, (de)activates or links a calendar entry to a team member. */
export async function updateBookingStaff(
  staffId: string,
  input: components["schemas"]["PatchedStaffUpdate"],
): Promise<components["schemas"]["Staff"]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/catalog/staff/{staff_id}/",
    {
      params: { path: { staff_id: staffId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
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

/** The visit took place: its products leave the warehouse (ADR-055). */
export async function completeBookingAppointment(
  appointmentId: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/complete/",
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

/** Products one visit takes; the stock reservation follows them. */
export async function setBookingAppointmentMaterials(
  appointmentId: string,
  materials: BookingMaterialInput[],
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/appointments/{appointment_id}/materials/",
    {
      params: { path: { appointment_id: appointmentId } },
      body: { materials },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Products every visit of this service takes from the warehouse. */
export async function setBookingServiceMaterials(
  serviceId: string,
  materials: BookingMaterialInput[],
): Promise<BookingMaterialInput[]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/catalog/services/{service_id}/materials/",
    {
      params: { path: { service_id: serviceId } },
      body: { materials },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.materials;
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
): Promise<BookingPublicCatalog> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/public/{public_slug}/",
    { params: { path: { public_slug: publicSlug } }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Days with a free start, for the customer's day picker (ADR-058 §5). */
export async function getPublicBookingDays(
  publicSlug: string,
  query: { service_id: string; location_id: string; from: string; to: string },
): Promise<string[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/public/{public_slug}/days/",
    { params: { path: { public_slug: publicSlug }, query }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

/** Free starts of one day, each once; who takes it is the server's pick. */
export async function getPublicBookingTimes(
  publicSlug: string,
  query: { service_id: string; location_id: string; date: string },
): Promise<BookingSlotTimeList["items"]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/public/{public_slug}/times/",
    { params: { path: { public_slug: publicSlug }, query }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createPublicBookingAppointment(
  publicSlug: string,
  input: BookingPublicAppointmentInput,
  idempotencyKey: string,
): Promise<BookingPublicAppointment> {
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
): Promise<BookingPublicAppointment> {
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
): Promise<BookingPublicAppointment> {
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
): Promise<BookingPublicAppointment> {
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

export async function getSiteNavigation(
  siteId: string,
): Promise<SiteNavigation> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/navigation/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function saveSiteNavigation(
  siteId: string,
  input: SiteNavigationSaveInput,
): Promise<SiteNavigation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/{site_id}/navigation/",
    {
      params: { path: { site_id: siteId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listContentCollections(
  siteId: string,
): Promise<ContentCollection[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/collections/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createContentCollection(
  siteId: string,
  input: {
    key: string;
    name: string;
    kind: "blog" | "news" | "guide";
    base_path: string;
  },
  idempotencyKey: string,
): Promise<ContentCollection> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/collections/",
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

export type AutomationPolicy = "manual" | "proposed" | "automated";

export async function setCollectionAutomationPolicy(
  collectionId: string,
  policy: AutomationPolicy,
): Promise<ContentCollection> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/collections/{collection_id}/policy/",
    {
      params: { path: { collection_id: collectionId } },
      body: { automation_policy: policy },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type PageTypeValue =
  | "homepage"
  | "landing"
  | "service"
  | "about"
  | "contact"
  | "legal"
  | "article_index"
  | "article";

export async function setPageType(
  pageId: string,
  pageType: PageTypeValue,
): Promise<PageSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/type/",
    {
      params: { path: { page_id: pageId } },
      body: { page_type: pageType },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Moves a published page, leaving a permanent redirect behind.
 *
 *  Session-only by design: the endpoint refuses API keys, because whether a
 *  ranking address is worth moving is not an optimiser's call to make. */
export async function changePageUrl(
  pageId: string,
  input: PageUrlChangeInput,
): Promise<SiteRedirect> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/url/",
    {
      params: { path: { page_id: pageId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSiteRedirects(
  siteId: string,
): Promise<SiteRedirect[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/redirects/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function deleteSiteRedirect(redirectId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/sites/redirects/{redirect_id}/",
    {
      params: { path: { redirect_id: redirectId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error) throwProblem(error, response);
}

export async function listContentProposals(): Promise<ContentProposal[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/proposals/",
    {
      credentials: "same-origin",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readContentProposal(
  proposalId: string,
): Promise<ContentProposalDetail> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/proposals/{proposal_id}/",
    {
      params: { path: { proposal_id: proposalId } },
      credentials: "same-origin",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function acceptContentProposal(
  proposalId: string,
  reviewToken: string,
): Promise<components["schemas"]["ProposalAcceptResult"]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/proposals/{proposal_id}/accept/",
    {
      params: { path: { proposal_id: proposalId } },
      body: { review_token: reviewToken },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Rejecting restores the previous content in a fresh draft version.
 *
 *  Nothing is deleted, so a rejected proposal can still be read afterwards. */
export async function discardContentProposal(
  proposalId: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/sites/proposals/{proposal_id}/discard/",
    {
      params: { path: { proposal_id: proposalId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error) throwProblem(error, response);
}

export async function listAutomationConnections(): Promise<
  AutomationConnection[]
> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/connections/",
    { credentials: "same-origin" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeAutomationGrant(
  grantId: string,
  reason: string,
): Promise<AutomationConnection[]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/connections/{grant_id}/revoke/",
    {
      params: { path: { grant_id: grantId } },
      body: { reason },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function setPageAutomationPolicy(
  pageId: string,
  policy: AutomationPolicy,
): Promise<PageSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/policy/",
    {
      params: { path: { page_id: pageId } },
      body: { automation_policy: policy },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function setCollectionNavigation(
  collectionId: string,
  show: boolean,
): Promise<ContentCollection> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/collections/{collection_id}/navigation/",
    {
      params: { path: { collection_id: collectionId } },
      body: { show_in_navigation: show },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listContentEntries(
  collectionId: string,
): Promise<{ items: ContentEntry[]; next_cursor: string | null }> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/collections/{collection_id}/entries/",
    {
      params: { path: { collection_id: collectionId }, query: { limit: 100 } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createContentEntry(
  collectionId: string,
  input: { slug: string; locale: "pl" | "en"; title: string },
  idempotencyKey: string,
): Promise<ContentEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/collections/{collection_id}/entries/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { collection_id: collectionId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listEntryTranslations(
  entryId: string,
): Promise<ContentEntry[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/entries/{entry_id}/translations/",
    {
      params: { path: { entry_id: entryId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createEntryTranslation(
  entryId: string,
  input: { slug: string; locale: "pl" | "en"; title: string },
  idempotencyKey: string,
): Promise<ContentEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/entries/{entry_id}/translations/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { entry_id: entryId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getContentEntryDraft(
  entryId: string,
): Promise<ContentEntryDraft> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/entries/{entry_id}/draft/",
    {
      params: { path: { entry_id: entryId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function saveContentEntryDraft(
  entryId: string,
  input: {
    expected_version: number;
    blocks: Record<string, unknown>[];
    media_asset_ids?: string[];
  },
  idempotencyKey: string,
): Promise<ContentEntryDraft> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/entries/{entry_id}/draft/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { entry_id: entryId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function publishContentEntry(
  entryId: string,
  idempotencyKey: string,
): Promise<ContentEntryPublication> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/entries/{entry_id}/publication/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { entry_id: entryId },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Asks for this article to go live at a stated moment.
 *
 *  The moment is sent as an absolute instant, so "Monday 07:00" means the
 *  operator's Monday and not the server's. */
/** Replaces the whole set of subjects an article is filed under.
 *
 *  Names, not addresses: the operator writes what a reader sees and the
 *  address follows from it. */
export async function setContentEntryTags(
  entryId: string,
  names: string[],
): Promise<ContentTag[]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/entries/{entry_id}/tags/",
    {
      params: { path: { entry_id: entryId } },
      body: { names },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function scheduleContentEntry(
  entryId: string,
  publishAt: string,
): Promise<EntrySchedule> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/entries/{entry_id}/schedule/",
    {
      params: { path: { entry_id: entryId } },
      body: { publish_at: publishAt },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function cancelContentEntrySchedule(
  entryId: string,
): Promise<EntrySchedule> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.DELETE(
    "/api/v1/sites/entries/{entry_id}/schedule/",
    {
      params: { path: { entry_id: entryId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function withdrawContentEntry(
  entryId: string,
): Promise<ContentEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.DELETE(
    "/api/v1/sites/entries/{entry_id}/publication/",
    {
      params: { path: { entry_id: entryId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type GscGrant = components["schemas"]["GscGrant"];
export type GscGrantList = components["schemas"]["GscGrantList"];
export type GscProperties = components["schemas"]["GscProperties"];
export type GscAuthorization = components["schemas"]["GscAuthorization"];
export type GscSync = components["schemas"]["GscSync"];
export type GscMetrics = components["schemas"]["GscMetrics"];
export type GscDisconnected = components["schemas"]["GscDisconnected"];
export type GscGrantInput = components["schemas"]["GscGrantInput"];
export type GscSyncInput = components["schemas"]["GscSyncInput"];
export type GscAuthorizeInput = components["schemas"]["GscAuthorizeInput"];
export type GscDisconnectInput = components["schemas"]["GscDisconnectInput"];

export async function prepareSeoGsc(input: {
  site_id: string;
}): Promise<GscProperties> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/prepare/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function authorizeSeoGsc(
  input: GscAuthorizeInput,
): Promise<GscAuthorization> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/authorize/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createSeoGscGrant(
  input: GscGrantInput,
): Promise<GscGrant> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/grants/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function disconnectSeoGsc(
  input: GscDisconnectInput,
): Promise<GscDisconnected> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/disconnect/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function syncSeoGsc(
  grantId: string,
  input: GscSyncInput,
): Promise<GscSync> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/grants/{grant_id}/sync/",
    {
      params: { path: { grant_id: grantId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeSeoGsc(
  grantId: string,
  _input: Record<string, never>,
): Promise<GscGrant> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/grants/{grant_id}/revoke/",
    {
      params: { path: { grant_id: grantId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getSeoGscProperties(
  siteId: string,
): Promise<GscProperties> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/properties/",
    {
      params: { query: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listSeoGscGrants(
  siteId: string,
  cursor?: string,
): Promise<GscGrantList> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/grants/",
    {
      params: { query: { site_id: siteId, ...(cursor ? { cursor } : {}) } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readSeoGscGrant(grantId: string): Promise<GscGrant> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/grants/{grant_id}/",
    {
      params: { path: { grant_id: grantId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readSeoGscMetrics(
  grantId: string,
  syncRunId: string,
  page = 1,
): Promise<GscMetrics> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/grants/{grant_id}/metrics/",
    {
      params: {
        path: { grant_id: grantId },
        query: { sync_run_id: syncRunId, page, page_size: 25 },
      },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function retrySeoGscGrant(grantId: string): Promise<GscGrant> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/seo/gsc/grants/{grant_id}/",
    {
      params: { path: { grant_id: grantId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type GscConnection = components["schemas"]["GscConnection"];
export type GscSyncHistory = components["schemas"]["GscSyncHistory"];
export async function getSeoGscConnection(
  siteId: string,
): Promise<GscConnection> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/connection/",
    {
      params: { query: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export async function listSeoGscSyncs(
  grantId: string,
): Promise<GscSyncHistory> {
  const { data, error, response } = await client.GET(
    "/api/v1/seo/gsc/grants/{grant_id}/sync/",
    {
      params: { path: { grant_id: grantId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

// ── Farm register (shared.farms, ADR-051) ─────────────────────────────────
export type Farm = components["schemas"]["Farm"];
export type FarmInput = components["schemas"]["FarmInput"];
export type FarmUpdateInput = components["schemas"]["PatchedFarmUpdate"];
export type FarmAnimal = components["schemas"]["Animal"];
export type FarmAnimalInput = components["schemas"]["AnimalInput"];
export type FarmAnimalUpdateInput =
  components["schemas"]["PatchedAnimalUpdate"];
export type FarmSpecies = components["schemas"]["FarmSpecies"];

export async function listFarms(search?: string): Promise<Farm[]> {
  const { data, error, response } = await client.GET("/api/v1/farms/", {
    params: search ? { query: { q: search } } : undefined,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readFarm(farmId: string): Promise<Farm> {
  const { data, error, response } = await client.GET(
    "/api/v1/farms/{farm_id}/",
    {
      params: { path: { farm_id: farmId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createFarm(input: FarmInput): Promise<Farm> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST("/api/v1/farms/", {
    body: input,
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken },
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateFarm(
  farmId: string,
  input: FarmUpdateInput,
): Promise<Farm> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/farms/{farm_id}/",
    {
      params: { path: { farm_id: farmId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listFarmAnimals(
  filters: {
    farmId?: string;
    search?: string;
    review?: boolean;
  } = {},
): Promise<FarmAnimal[]> {
  const query: { farm_id?: string; q?: string; review?: boolean } = {};
  if (filters.farmId) query.farm_id = filters.farmId;
  if (filters.search) query.q = filters.search;
  if (filters.review) query.review = true;
  const { data, error, response } = await client.GET("/api/v1/farms/animals/", {
    params: { query },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export type FarmAnimalHealthEntry = components["schemas"]["AnimalHealthEntry"];
export type FarmAnimalHealthInput = components["schemas"]["AnimalHealthInput"];

/** The animal's file, newest first — filters run on the server (ADR-051 pt 8). */
export async function listFarmAnimalHealth(
  animalId: string,
  filters: {
    kinds?: string[];
    author?: "mine" | "others";
    from?: string;
    to?: string;
  } = {},
): Promise<FarmAnimalHealthEntry[]> {
  const query: {
    kind?: string[];
    author?: string;
    from?: string;
    to?: string;
  } = {};
  if (filters.kinds?.length) query.kind = filters.kinds;
  if (filters.author) query.author = filters.author;
  if (filters.from) query.from = filters.from;
  if (filters.to) query.to = filters.to;
  const { data, error, response } = await client.GET(
    "/api/v1/farms/animals/{animal_id}/health/",
    {
      params: { path: { animal_id: animalId }, query },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Zdjęcie z wpisu kartoteki: plik zostaje u autora, wchodzimy przez wpis. */
export async function getFarmHealthPhoto(
  entryId: string,
  mediaId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const { data, error, response } = await client.GET(
    "/api/v1/farms/health/{entry_id}/photos/{media_id}/",
    {
      params: { path: { entry_id: entryId, media_id: mediaId } },
      credentials: "same-origin",
      cache: "no-store",
      parseAs: "blob",
      signal,
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** An entry written by hand, in this register. */
export async function createFarmAnimalHealth(
  animalId: string,
  input: FarmAnimalHealthInput,
): Promise<FarmAnimalHealthEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/animals/{animal_id}/health/",
    {
      params: { path: { animal_id: animalId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createFarmAnimal(
  input: FarmAnimalInput,
): Promise<FarmAnimal> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/animals/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateFarmAnimal(
  animalId: string,
  input: FarmAnimalUpdateInput,
): Promise<FarmAnimal> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/farms/animals/{animal_id}/",
    {
      params: { path: { animal_id: animalId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type InventoryItem = components["schemas"]["InventoryItem"];
export type InventoryItemInput = components["schemas"]["InventoryItemInput"];
export type InventoryBalance = components["schemas"]["InventoryBalance"];
export type InventoryMovement = components["schemas"]["InventoryMovement"];
export type InventoryCategory = components["schemas"]["InventoryCategory"];
export type StockLocation = components["schemas"]["StockLocation"];
export type Supplier = components["schemas"]["Supplier"];
export type StockDocument = components["schemas"]["StockDocument"];
export type StockDocumentInput = components["schemas"]["StockDocumentInput"];
export type StockDocumentKind = components["schemas"]["StockDocumentKindEnum"];

type Fetch = (
  path: never,
  init: never,
) => Promise<{ data?: unknown; error?: unknown; response: Response }>;

// ponytail: two generic callers for the warehouse's many endpoints. The path is
// checked against the schema; the response type is the wrapper's promise.
async function inventoryRead<T>(
  path: keyof paths,
  query: Record<string, string | boolean | undefined> = {},
): Promise<T> {
  const params = Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) => value !== undefined && value !== "",
    ),
  );
  const { data, error, response } = await (client.GET as Fetch)(
    path as never,
    {
      params: { query: params },
      credentials: "same-origin",
      cache: "no-store",
    } as never,
  );
  if (error || !data) throwProblem(error, response);
  return data as T;
}

async function inventoryWrite<T>(
  method: "POST" | "PATCH" | "DELETE",
  path: keyof paths,
  pathParams: Record<string, string>,
  body?: unknown,
): Promise<T> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await (client[method] as Fetch)(
    path as never,
    {
      params: { path: pathParams },
      ...(body === undefined ? {} : { body }),
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    } as never,
  );
  if (error || !response.ok) throwProblem(error, response);
  return data as T;
}

/** Kategorie firmy; zestaw startowy deklaruje produkt (ADR-055). */
export function listInventoryCategories(): Promise<InventoryCategory[]> {
  return inventoryRead("/api/v1/inventory/categories/");
}

export function createInventoryCategory(
  name: string,
): Promise<InventoryCategory> {
  return inventoryWrite("POST", "/api/v1/inventory/categories/", {}, { name });
}

export function renameInventoryCategory(
  categoryId: string,
  name: string,
): Promise<InventoryCategory> {
  return inventoryWrite(
    "PATCH",
    "/api/v1/inventory/categories/{category_id}/",
    { category_id: categoryId },
    { name },
  );
}

export function deleteInventoryCategory(categoryId: string): Promise<void> {
  return inventoryWrite(
    "DELETE",
    "/api/v1/inventory/categories/{category_id}/",
    { category_id: categoryId },
  );
}

/** Magazyny firmy i zapasy osób. */
export function listStockLocations(): Promise<StockLocation[]> {
  return inventoryRead("/api/v1/inventory/locations/");
}

export function createWarehouse(name: string): Promise<StockLocation> {
  return inventoryWrite("POST", "/api/v1/inventory/locations/", {}, { name });
}

export function updateStockLocation(
  locationId: string,
  input: { name?: string; active?: boolean },
): Promise<StockLocation> {
  return inventoryWrite(
    "PATCH",
    "/api/v1/inventory/locations/{location_id}/",
    { location_id: locationId },
    input,
  );
}

export function listSuppliers(): Promise<Supplier[]> {
  return inventoryRead("/api/v1/inventory/suppliers/");
}

export function saveSupplier(
  input: Partial<Omit<Supplier, "id">> & { name: string },
  supplierId?: string,
): Promise<Supplier> {
  return supplierId
    ? inventoryWrite(
        "PATCH",
        "/api/v1/inventory/suppliers/{supplier_id}/",
        { supplier_id: supplierId },
        input,
      )
    : inventoryWrite("POST", "/api/v1/inventory/suppliers/", {}, input);
}

/** Katalog towarów firmy: jedna pozycja to jeden SKU. */
export function listInventoryItems(
  filters: { category?: string; search?: string } = {},
): Promise<InventoryItem[]> {
  return inventoryRead("/api/v1/inventory/items/", {
    category: filters.category,
    q: filters.search,
  });
}

export function createInventoryItem(
  input: InventoryItemInput,
): Promise<InventoryItem> {
  return inventoryWrite("POST", "/api/v1/inventory/items/", {}, input);
}

export function updateInventoryItem(
  itemId: string,
  input: Partial<InventoryItemInput>,
): Promise<InventoryItem> {
  return inventoryWrite(
    "PATCH",
    "/api/v1/inventory/items/{item_id}/",
    { item_id: itemId },
    input,
  );
}

/** Stany jednego miejsca; bez filtrów — magazyn główny. */
export function listInventoryBalances(
  filters: { locationId?: string; holderId?: string; mine?: boolean } = {},
): Promise<InventoryBalance[]> {
  return inventoryRead("/api/v1/inventory/balances/", {
    location_id: filters.locationId,
    holder_id: filters.holderId,
    mine: filters.mine || undefined,
  });
}

export function listInventoryMovements(
  filters: { itemId?: string; locationId?: string } = {},
): Promise<InventoryMovement[]> {
  return inventoryRead("/api/v1/inventory/movements/", {
    item_id: filters.itemId,
    location_id: filters.locationId,
  });
}

export function listStockDocuments(
  filters: { kind?: string; status?: string } = {},
): Promise<StockDocument[]> {
  return inventoryRead("/api/v1/inventory/documents/", filters);
}

export function createStockDocument(
  input: StockDocumentInput,
): Promise<StockDocument> {
  return inventoryWrite("POST", "/api/v1/inventory/documents/", {}, input);
}

export function updateStockDocument(
  documentId: string,
  input: Partial<StockDocumentInput>,
): Promise<StockDocument> {
  return inventoryWrite(
    "PATCH",
    "/api/v1/inventory/documents/{document_id}/",
    { document_id: documentId },
    input,
  );
}

/** Zatwierdzenie: wiersze stają się ruchami, dokument dostaje numer. */
export function postStockDocument(documentId: string): Promise<StockDocument> {
  return inventoryWrite(
    "POST",
    "/api/v1/inventory/documents/{document_id}/post/",
    { document_id: documentId },
  );
}

/** Korekta: nowy dokument, który cofa ruchy zatwierdzonego. */
export function correctStockDocument(
  documentId: string,
  note = "",
): Promise<StockDocument> {
  return inventoryWrite(
    "POST",
    "/api/v1/inventory/documents/{document_id}/correct/",
    { document_id: documentId },
    { note },
  );
}

export function receiveInventory(
  input: components["schemas"]["InventoryReceiptInput"],
): Promise<StockDocument> {
  return inventoryWrite("POST", "/api/v1/inventory/receipts/", {}, input);
}

/** Wydanie pracownikowi: pakiet, z którym wyjeżdża w teren. */
export function issueInventory(
  input: components["schemas"]["InventoryIssueInput"],
): Promise<StockDocument> {
  return inventoryWrite("POST", "/api/v1/inventory/issues/", {}, input);
}

export function returnInventory(
  input: components["schemas"]["InventoryIssueInput"],
): Promise<StockDocument> {
  return inventoryWrite("POST", "/api/v1/inventory/returns/", {}, input);
}

export type FarmShare = components["schemas"]["FarmShare"];
export type FarmTakeover = components["schemas"]["FarmTakeover"];

/** The code a company hands the farmer for one of its cards (ADR-051). */
export async function issueFarmActivationCode(
  farmId: string,
): Promise<components["schemas"]["FarmActivationCode"]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/{farm_id}/activation-code/",
    {
      params: { path: { farm_id: farmId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The farmer takes the herd over with the code. */
export async function redeemFarmActivationCode(
  code: string,
): Promise<FarmTakeover> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/activation/redeem/",
    {
      body: { code },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type FarmHerdPush = components["schemas"]["FarmHerdPush"];

/** Wyślij stado tej karty do rejestru rolnika (ADR-051 pt 7). */
export async function sendFarmHerd(farmId: string): Promise<FarmHerdPush> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/{farm_id}/send-herd/",
    {
      params: { path: { farm_id: farmId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listFarmShares(farmId: string): Promise<FarmShare[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/farms/{farm_id}/shares/",
    {
      params: { path: { farm_id: farmId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function revokeFarmShare(shareId: string): Promise<FarmShare> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/shares/{share_id}/revoke/",
    {
      params: { path: { share_id: shareId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Kartoteka wizyt gospodarstwa w rejestrze rolnika (ADR-052). */
export type FarmVisit = components["schemas"]["FarmVisitEntry"];

export async function listFarmVisits(farmId: string): Promise<FarmVisit[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/farms/{farm_id}/visits/",
    {
      params: { path: { farm_id: farmId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Zgoda rolnika na grafik firmy; przestawia ją tylko strona rejestru. */
export async function setFarmShareSchedule(
  shareId: string,
  allowed: boolean,
): Promise<FarmShare> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/shares/{share_id}/schedule/",
    {
      params: { path: { share_id: shareId } },
      body: { can_publish_schedule: allowed },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listFarmSpecies(): Promise<FarmSpecies[]> {
  const { data, error, response } = await client.GET("/api/v1/farms/species/", {
    credentials: "same-origin",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

// ── For product modules (ADR-049) ───────────────────────────────────────────
// A product's vertical calls its own endpoints with the same client, CSRF and
// Problem Details handling as core, from its own files — so it never has to
// edit this one.
export { client, getCsrfToken, throwProblem };
export type { components, paths };

export async function getSiteAppearance(siteId: string) {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/appearance/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export async function saveSiteAppearance(
  siteId: string,
  input: components["schemas"]["SiteAppearanceSave"],
  idempotencyKey: string,
) {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/{site_id}/appearance/",
    {
      params: {
        path: { site_id: siteId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Copies one allowlisted demo photo through the tenant media lifecycle. */
export async function materializeTemplatePhoto(
  photoId: string,
  idempotencyKey: string,
): Promise<components["schemas"]["TemplatePhoto"]> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/template-media/{photo_id}/materialize/",
    {
      params: {
        path: { photo_id: photoId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export type OrganizationProfile = components["schemas"]["OrganizationProfile"];
export type PublicProfileSummary = components["schemas"]["ProfileSummary"];
export type CatalogState = components["schemas"]["CatalogState"];
export type CatalogItem = components["schemas"]["CatalogItem"];
export type CatalogPage = components["schemas"]["CatalogPage"];
export type CatalogProfile = components["schemas"]["CatalogProfile"];
export type CatalogDictionary = components["schemas"]["CatalogDictionary"];
export type CatalogSearch = {
  city?: string;
  category?: string;
  q?: string;
  page?: number;
};

/**
 * The company's own business card, created on first read (ADR-053 §2).
 *
 * Reading it has a side effect by design: core cannot create the profile, so
 * this is where it comes into being. Safe to call again — the second call
 * returns the same row.
 */
export async function readOrganizationProfile(): Promise<OrganizationProfile> {
  const { data, error, response } = await client.GET(
    "/api/v1/profiles/organization/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function publishOrganizationProfile(): Promise<OrganizationProfile> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/profiles/organization/catalog/",
    { credentials: "same-origin", headers: { "X-CSRFToken": csrfToken } },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function withdrawOrganizationProfile(): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/profiles/organization/catalog/",
    { credentials: "same-origin", headers: { "X-CSRFToken": csrfToken } },
  );
  if (error) throwProblem(error, response);
}

export async function updateProfile(
  profileId: string,
  body: components["schemas"]["ProfileUpdate"],
): Promise<PublicProfileSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/profiles/{profile_id}/",
    {
      params: { path: { profile_id: profileId } },
      body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Public, unauthenticated: no session and no tenant header (ADR-053 §4). */
export async function searchCatalog(
  search: CatalogSearch = {},
): Promise<CatalogPage> {
  const { data, error, response } = await client.GET(
    "/api/v1/public/catalog/",
    { params: { query: search }, cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readCatalogProfile(
  citySlug: string,
  slug: string,
): Promise<CatalogProfile> {
  const { data, error, response } = await client.GET(
    "/api/v1/public/catalog/{city_slug}/{slug}/",
    {
      params: { path: { city_slug: citySlug, slug } },
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function readCatalogDictionary(): Promise<CatalogDictionary> {
  const { data, error, response } = await client.GET(
    "/api/v1/public/catalog/dictionary/",
    { cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type SiteInquiry = components["schemas"]["SiteInquiry"];
export type SiteInquirySubmit = components["schemas"]["SiteInquirySubmit"];
export async function submitPublicSiteInquiry(
  input: SiteInquirySubmit,
  idempotencyKey: string,
) {
  const { data, error, response } = await client.POST(
    "/api/v1/public/site/inquiries/",
    {
      body: input,
      params: { header: { "Idempotency-Key": idempotencyKey } },
      credentials: "omit",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export async function listSiteInquiries(
  siteId: string,
  options: { cursor?: string; limit?: number } = {},
) {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/inquiries/",
    {
      params: { path: { site_id: siteId }, query: options },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export async function getSiteInquiry(inquiryId: string) {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/inquiries/{inquiry_id}/",
    {
      params: { path: { inquiry_id: inquiryId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
export async function markSiteInquiryRead(
  inquiryId: string,
  idempotencyKey: string,
) {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/inquiries/{inquiry_id}/read/",
    {
      params: {
        path: { inquiry_id: inquiryId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}
