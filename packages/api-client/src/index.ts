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

export type ImageGenerationOffer =
  components["schemas"]["ImageGenerationOffer"];
export type ImageGenerationJob = components["schemas"]["ImageGenerationJob"];
export type ImageGenerationInput =
  components["schemas"]["ImageGenerationRequest"];
export type ImageGenerationAspect =
  components["schemas"]["ImageGenerationAspectEnum"];

export async function getImageGenerationOffer(): Promise<ImageGenerationOffer> {
  const { data, error, response } = await client.GET(
    "/api/v1/image-generation/offer/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function requestImageGeneration(
  input: ImageGenerationInput,
  idempotencyKey: string,
): Promise<ImageGenerationJob> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/image-generation/jobs/",
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

export async function getImageGenerationJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<ImageGenerationJob> {
  const { data, error, response } = await client.GET(
    "/api/v1/image-generation/jobs/{job_id}/",
    {
      params: { path: { job_id: jobId } },
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
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
/** A setting a company may choose and what it may choose (ADR-078). */
export type SettingOption = components["schemas"]["SettingOption"];
export type SettingOptions = components["schemas"]["SettingOptions"];
export type SettingsSchema = components["schemas"]["SettingsSchema"];
export type SettingsGroupSchema = components["schemas"]["SettingsGroupSchema"];
export type SettingEffect = components["schemas"]["SettingEffect"];
/** The platform's values for its operators (platform settings, phase 2). */
export type PlatformSchema = components["schemas"]["PlatformSchema"];
export type PlatformKey = components["schemas"]["PlatformKey"];
export type PlatformValue = components["schemas"]["PlatformValue"];
export type PlatformPreview = components["schemas"]["PlatformPreview"];
export type PlatformHistoryItem = components["schemas"]["PlatformHistoryItem"];
export type PlatformChange = components["schemas"]["PlatformChange"];

type SettingsGroupPath = {
  [
    P in keyof paths
  ]: P extends `/api/v1/organizations/current/settings/${infer G}/`
    ? G extends "schema" | `${string}/preview`
      ? never
      : P
    : never;
}[keyof paths];
type SettingsPreviewPath = {
  [
    P in keyof paths
  ]: P extends `/api/v1/organizations/current/settings/${string}/preview/`
    ? P
    : never;
}[keyof paths];
/** A settings group, e.g. "booking.reminders" — one per declared group. */
export type SettingsGroupKey =
  SettingsGroupPath extends `/api/v1/organizations/current/settings/${infer G}/`
    ? G
    : never;
/** Any group's values, sources and version token, as its own operation types it. */
export type SettingsGroupState =
  paths[SettingsGroupPath]["get"]["responses"][200]["content"]["application/json"];
export type SettingsGroupPreview =
  paths[SettingsPreviewPath]["post"]["responses"][200]["content"]["application/json"];
/** A change of any group: its fields by name, `null` keeps one, `reset` gives back. */
export type SettingsGroupChange = {
  expected_version: string;
  reset?: string[];
  [field: string]: unknown;
};
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
export type PageListItem = components["schemas"]["PageListItem"];
export type PageDeletion = components["schemas"]["PageDeletion"];
export type PageIncomingLink = components["schemas"]["PageIncomingLink"];
export type PageDraft = components["schemas"]["PageDraft"];
export type PageVersionSummary = components["schemas"]["PageVersionSummary"];
export type PageVersionList = components["schemas"]["PageVersionList"];
export type SiteTemplate = components["schemas"]["SiteTemplate"];
export type SiteTemplateList = components["schemas"]["SiteTemplateList"];
export type SiteTemplateCreateInput =
  components["schemas"]["SiteTemplateCreate"];
export type SiteTemplateVersionCreateInput =
  components["schemas"]["SiteTemplateVersionCreate"];
export type DraftSaveInput = components["schemas"]["DraftSave"];
export type PageTemplateImportInput =
  components["schemas"]["PageTemplateImport"];
export type OwnTemplateImportInput = components["schemas"]["OwnTemplateImport"];
export type PageTranslation = components["schemas"]["PageTranslation"];
export type PageTranslationList = components["schemas"]["PageTranslationList"];
export type PageTranslationSaveInput =
  components["schemas"]["PageTranslationSave"];
export type SiteLocalizationReport =
  components["schemas"]["SiteLocalizationReport"];
// A page's body in another language (ADR-070, TL8/TL9c) and the decisions on
// it, edited in the editor's language mode (TL15).
export type LocaleBody = components["schemas"]["LocaleBody"];
export type LocaleBodyUnit = components["schemas"]["LocaleBodyUnit"];
export type LocaleBodySaveInput = components["schemas"]["LocaleBodySave"];
export type LocaleBodyVersionList =
  components["schemas"]["LocaleBodyVersionList"];
export type LocaleBodyVersionPreview =
  components["schemas"]["LocaleBodyVersionPreview"];
export type LanguageDecision = components["schemas"]["LanguageDecision"];
export type PublicationPlan = components["schemas"]["PublicationPlan"];
export type PlannedLanguage = components["schemas"]["PlannedLanguage"];
export type LocaleBatchItem = components["schemas"]["LocaleBatchItem"];
export type LocaleBatchAcceptInput = components["schemas"]["LocaleBatchAccept"];
export type LocaleBatchResult = components["schemas"]["LocaleBatchResult"];
export type TranslationOverview = components["schemas"]["TranslationOverview"];
export type TranslationOverviewQuery = NonNullable<
  paths["/api/v1/sites/{site_id}/translations/"]["get"]["parameters"]["query"]
>;
export type SiteTexts = components["schemas"]["SiteTexts"];
export type SiteTextsSaveInput = components["schemas"]["SiteTextsSave"];
export type SiteTextsPublication =
  components["schemas"]["SiteTextsPublication"];
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
export type ContentEntryMetadataInput =
  components["schemas"]["PatchedContentEntryMetadata"];
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
export type BookingVisitPlace = components["schemas"]["VisitPlaceInput"];
export type BookingPlaceSuggestion =
  components["schemas"]["VisitPlaceSuggestion"];
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
/** A person of the company, with an account or without one (ADR-058 §1). */
export type Person = components["schemas"]["Person"];
export type PersonDetail = components["schemas"]["PersonDetail"];
export type PersonCreateInput = components["schemas"]["PersonCreate"];
export type PersonUpdateInput = components["schemas"]["PatchedPersonUpdate"];
export type PersonHoursRule = components["schemas"]["HoursRuleInput"];
export type PersonInvitation = components["schemas"]["PersonInvitation"];
export type PersonInvitationInput =
  components["schemas"]["PersonInvitationInput"];
export type TimeOffInput = components["schemas"]["TimeOffInput"];
export type TimeOffCreated = components["schemas"]["TimeOffCreated"];
/** Who works, is away and is busy on one day (ADR-058 §9). */
export type PeopleDay = components["schemas"]["PeopleDay"];
export type StaffFacts = components["schemas"]["StaffFacts"];
export type StaffMetric = components["schemas"]["StaffMetric"];
export type StaffHistory = components["schemas"]["StaffHistory"];
export type StaffEvent = components["schemas"]["StaffEvent"];
export type TeamPerformance = components["schemas"]["Performance"];
export type SeatUsage = components["schemas"]["SeatUsage"];
/** A standing group of people, e.g. a crew (ADR-058 §2). */
export type StaffTeam = components["schemas"]["Team"];
export type StaffTeamInput = components["schemas"]["TeamInput"];
export type StaffTeamUpdate = components["schemas"]["PatchedTeamUpdate"];
/** Ustawienia › Usługi i grafik: switched-off items included (team phase 3c). */
export type BookingSetup = components["schemas"]["Setup"];
export type ServiceSetup = components["schemas"]["ServiceSetup"];
export type PlaceSetup = components["schemas"]["PlaceSetup"];
export type ResourceSetup = components["schemas"]["ResourceSetup"];
export type ServiceSetupInput = components["schemas"]["ServiceInput"];
export type ServiceSetupUpdate = components["schemas"]["ServiceUpdate"];
export type PlaceSetupInput = components["schemas"]["PlaceInput"];
export type PlaceSetupUpdate = components["schemas"]["PlaceUpdate"];
export type ResourceSetupInput = components["schemas"]["ResourceInput"];
export type ResourceSetupUpdate = components["schemas"]["ResourceUpdate"];
/** A pool of identical units, e.g. „Domek 6-os.” (ADR-072 §3). */
export type GroupSetup = components["schemas"]["GroupSetup"];
export type GroupSetupInput = components["schemas"]["GroupInput"];
export type GroupSetupUpdate = components["schemas"]["GroupUpdate"];
/** Days the company or one of its places is closed (B11). */
export type BookingClosure = components["schemas"]["BookingClosure"];
export type BookingClosureInput = components["schemas"]["BookingClosureInput"];
export type BookingRule = components["schemas"]["BookingRule"];
export type BookingRuleInput = components["schemas"]["BookingRuleInput"];
export type BookingRuleUpdate =
  components["schemas"]["PatchedBookingRuleUpdate"];
export type BookingClosureUpdate =
  components["schemas"]["BookingClosureUpdate"];
/** What can be set on a service, in the settings registry's shape (ADR-078). */
export type SetupOption = components["schemas"]["SetupOption"];
/** A visit in „Do przydzielenia”, with the customer's contact. */
export type QueueItem = components["schemas"]["QueueItem"];
export type BookingOverview = components["schemas"]["Overview"];
export type BookingOccupancy = components["schemas"]["Occupancy"];
export type OccupancyHeld = components["schemas"]["OccupancyHeld"];
export type OccupancyUnit = components["schemas"]["OccupancyUnit"];
export type StayInput = components["schemas"]["StayInput"];
export type StayPlan = components["schemas"]["StayPlan"];
export type UnitBlock = components["schemas"]["UnitBlock"];
/** One person for one visit: free, or why not (ADR-058 §9). */
export type CrewCandidate = components["schemas"]["Candidate"];
export type CrewInput = components["schemas"]["CrewInput"];
export type CrewMember = components["schemas"]["CrewMember"];

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

/** Signs out on every other device; this session stays. How many ended. */
export async function revokeOtherSessions(): Promise<number> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/auth/sessions/others/revoke/",
    {
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok || !data) throwProblem(error, response);
  return data.ended;
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

/** The currencies and panel languages a company may choose, with defaults. */
export async function getOrganizationOptions(): Promise<SettingOptions> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/options/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/**
 * Confirms the second factor once more (a code from the authenticator app):
 * billing changes and legal documents ask for it, then the request is repeated.
 */
export async function confirmStepUp(code: string): Promise<void> {
  const { error, response } = await client.POST("/api/v1/auth/step-up/", {
    body: { code },
    credentials: "same-origin",
    headers: { "X-CSRFToken": await getCsrfToken() },
  });
  if (error || !response.ok) throwProblem(error, response);
}

/** Every settings group of the company, its keys, variants and labels. */
export async function getSettingsSchema(): Promise<SettingsSchema> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/settings/schema/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export function getSettingsGroup(
  group: SettingsGroupKey,
): Promise<SettingsGroupState> {
  return settingsRequest(group, "", { method: "GET" });
}

/** What a change would do, saving nothing (`x-dry-run`). */
export async function previewSettingsGroup(
  group: SettingsGroupKey,
  change: SettingsGroupChange,
): Promise<SettingsGroupPreview> {
  return settingsRequest(group, "preview/", {
    method: "POST",
    body: JSON.stringify(change),
    headers: { "X-CSRFToken": await getCsrfToken() },
  });
}

export async function updateSettingsGroup(
  group: SettingsGroupKey,
  change: SettingsGroupChange,
  idempotencyKey: string,
): Promise<SettingsGroupState> {
  return settingsRequest(group, "", {
    method: "PATCH",
    body: JSON.stringify(change),
    headers: {
      "X-CSRFToken": await getCsrfToken(),
      "Idempotency-Key": idempotencyKey,
    },
  });
}

/**
 * A settings group's operations differ only in their path, which the group
 * names; their types come from the contract above (`SettingsGroupState`).
 */
async function settingsRequest<T>(
  group: SettingsGroupKey,
  suffix: string,
  init: RequestInit,
): Promise<T> {
  const response = await fetch(
    `/api/v1/organizations/current/settings/${group}/${suffix}`,
    {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...init.headers },
    },
  );
  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throwProblem(body, response);
  return body as T;
}

/** Every key the platform sets, for an operator signed in through MFA. */
export async function getPlatformSettings(): Promise<PlatformSchema> {
  const { data, error, response } = await client.GET(
    "/api/v1/platform/settings/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What a platform value's change would do, saving nothing (`x-dry-run`). */
export async function previewPlatformSetting(
  key: string,
  change: PlatformChange,
): Promise<PlatformPreview> {
  const { data, error, response } = await client.POST(
    "/api/v1/platform/settings/{key}/preview/",
    {
      params: { path: { key } },
      body: change,
      credentials: "same-origin",
      headers: { "X-CSRFToken": await getCsrfToken() },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** A new platform value, or `null` back to the deployment's or the code's. */
export async function changePlatformSetting(
  key: string,
  change: PlatformChange,
): Promise<PlatformValue> {
  const { data, error, response } = await client.POST(
    "/api/v1/platform/settings/{key}/",
    {
      params: { path: { key } },
      body: change,
      credentials: "same-origin",
      headers: { "X-CSRFToken": await getCsrfToken() },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getPlatformSettingHistory(
  key: string,
): Promise<PlatformHistoryItem[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/platform/settings/{key}/history/",
    {
      params: { path: { key } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
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

/** Current members; `includeFormer` adds former ones (management only). */
export async function listMemberships(
  query: { includeFormer?: boolean } = {},
): Promise<MembershipSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/members/",
    {
      params: query.includeFormer
        ? { query: { include_former: true } }
        : undefined,
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Accounts in use against the plan's limit (owner's answer 5). */
export async function getSeatUsage(): Promise<SeatUsage> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/seats/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type PublicLocales = components["schemas"]["PublicLocales"];
export type PublicLocalesPlan = components["schemas"]["PublicLocalesPlan"];
export type PublicLocalesChangeInput =
  components["schemas"]["PublicLocalesChange"];

/** The company's content languages in order, the languages it may add and
 *  the plan's limit (ADR-071 pkt 5). */
export async function getPublicLocales(): Promise<PublicLocales> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/public-locales/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What a change of the company's languages would do; nothing is saved. */
export async function previewPublicLocales(
  input: PublicLocalesChangeInput,
): Promise<PublicLocalesPlan> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/organizations/current/public-locales/preview/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function changePublicLocales(
  input: PublicLocalesChangeInput,
  idempotencyKey: string,
): Promise<PublicLocalesPlan> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/organizations/current/public-locales/",
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

export type HistoryPage = components["schemas"]["HistoryPage"];
export type HistoryEntry = components["schemas"]["HistoryEntry"];

/** The organization's history of changes, newest first (owner and admin). */
export async function readOrganizationHistory(
  query: {
    page?: number;
    pageSize?: number;
    action?: string;
    group?: string;
  } = {},
): Promise<HistoryPage> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/history/",
    {
      params: {
        query: {
          page: query.page,
          page_size: query.pageSize,
          action: query.action || undefined,
          group: query.group || undefined,
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

export async function listSitePages(
  siteId: string,
  state: "live" | "deleted" = "live",
): Promise<PageList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/pages/",
    {
      params: { path: { site_id: siteId }, query: { limit: 100, state } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Deletes a page (decision 7): hidden, off the public site at once, its
 *  addresses redirected to `redirectToPageId` or the home page. */
export async function deleteSitePage(
  pageId: string,
  input: { expected_version: number; redirect_to_page_id?: string | null },
  idempotencyKey: string,
): Promise<PageDeletion> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/delete/",
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

/** Brings a deleted page back as a draft; `slugs` when its old address is taken. */
export async function restoreSitePage(
  pageId: string,
  idempotencyKey: string,
  slugs?: Record<string, string>,
): Promise<PageListItem> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/restore/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId },
      },
      body: slugs ? { slugs } : {},
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The other pages whose drafts link to this one. */
export async function listPageIncomingLinks(
  pageId: string,
): Promise<PageIncomingLink[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/incoming-links/",
    {
      params: { path: { page_id: pageId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
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
  cursor?: string,
): Promise<SitePublicationList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/publications/",
    {
      params: {
        path: { site_id: siteId },
        query: { limit: 100, ...(cursor ? { cursor } : {}) },
      },
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

/** The organization's own templates (F4-B) with their newest version, and
 *  the plan's limit of active ones (null: none). */
export async function listSiteTemplates(
  kind?: "section" | "page",
): Promise<SiteTemplateList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/templates/",
    {
      params: { query: kind ? { kind } : {} },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createSiteTemplate(
  input: SiteTemplateCreateInput,
  idempotencyKey: string,
): Promise<SiteTemplate> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/templates/",
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

export async function saveSiteTemplateVersion(
  templateId: string,
  input: SiteTemplateVersionCreateInput,
  idempotencyKey: string,
): Promise<SiteTemplate> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/templates/{template_id}/versions/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { template_id: templateId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateSiteTemplate(
  templateId: string,
  input: { name: string; description: string },
): Promise<SiteTemplate> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/sites/templates/{template_id}/",
    {
      params: { path: { template_id: templateId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function archiveSiteTemplate(templateId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/sites/templates/{template_id}/archive/",
    {
      params: { path: { template_id: templateId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function importOwnPageTemplate(
  pageId: string,
  input: OwnTemplateImportInput,
  idempotencyKey: string,
): Promise<PageDraft> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/own-template-import/",
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

/** The page's versions, newest first; `cursor` continues after the last. */
export async function listPageVersions(
  pageId: string,
  cursor?: string,
): Promise<PageVersionList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/versions/",
    {
      params: {
        path: { page_id: pageId },
        query: { limit: 20, ...(cursor ? { cursor } : {}) },
      },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** A new draft version with an earlier version's content; nothing else changes. */
export async function restorePageVersion(
  pageId: string,
  versionId: string,
  input: { expected_version: number },
  idempotencyKey: string,
): Promise<PageDraft> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/versions/{version_id}/restore/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, version_id: versionId },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
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

/** The page's text in `locale`, unit by unit beside the source (TL15). */
export async function getLocaleBody(
  pageId: string,
  locale: string,
): Promise<LocaleBody> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/",
    {
      params: { path: { page_id: pageId, locale } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Saves the units named; the others keep their text. 409 when somebody
 *  saved this language meanwhile (`locale_body_version_conflict`). */
export async function saveLocaleBody(
  pageId: string,
  locale: string,
  input: LocaleBodySaveInput,
  idempotencyKey: string,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What saving would do, saving nothing (`x-dry-run`). */
export async function previewLocaleBody(
  pageId: string,
  locale: string,
  input: LocaleBodySaveInput,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/preview/",
    {
      params: { path: { page_id: pageId, locale } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listLocaleBodyVersions(
  pageId: string,
  locale: string,
): Promise<LocaleBodyVersionList> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/versions/",
    {
      params: { path: { page_id: pageId, locale } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** One version of this language as blocks, for its read-only preview. */
export async function getLocaleBodyVersion(
  pageId: string,
  locale: string,
  versionId: string,
): Promise<LocaleBodyVersionPreview> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/versions/{version_id}/",
    {
      params: { path: { page_id: pageId, locale, version_id: versionId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function restoreLocaleBodyVersion(
  pageId: string,
  locale: string,
  versionId: string,
  expectedBodyVersion: number,
  idempotencyKey: string,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/versions/{version_id}/restore/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale, version_id: versionId },
      },
      body: { expected_body_version: expectedBodyVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The source's text copied in as this language's starting point. */
export async function copySourceIntoLocaleBody(
  pageId: string,
  locale: string,
  input: { source_version_id: string; expected_body_version: number },
  idempotencyKey: string,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/copy/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Moves this language onto the source's current version, keeping what
 *  still matches. */
export async function rebaseLocaleBody(
  pageId: string,
  locale: string,
  expectedBodyVersion: number,
  idempotencyKey: string,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/rebase/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      body: { expected_body_version: expectedBodyVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What moving onto the current source would keep and drop (`x-dry-run`). */
export async function previewRebaseLocaleBody(
  pageId: string,
  locale: string,
  expectedBodyVersion: number,
): Promise<LocaleBody> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/rebase/preview/",
    {
      params: {
        path: { page_id: pageId, locale },
      },
      body: { expected_body_version: expectedBodyVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Accepts the translation waiting for a decision and publishes it. */
export async function acceptLocaleBody(
  pageId: string,
  locale: string,
  expectedBodyVersion: number,
  idempotencyKey: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/accept/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      body: { expected_body_version: expectedBodyVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Drops the translation waiting for a decision; nothing is published. */
export async function rejectLocaleBody(
  pageId: string,
  locale: string,
  expectedBodyVersion: number,
  idempotencyKey: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/reject/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      body: { expected_body_version: expectedBodyVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Publishes this language version alone. */
export async function publishLocaleBody(
  pageId: string,
  locale: string,
  idempotencyKey: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/publish/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Whether this language version would go out, and if not why. */
export async function previewPublishLocaleBody(
  pageId: string,
  locale: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/publish/preview/",
    {
      params: {
        path: { page_id: pageId, locale },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Takes this language version off the site; its address answers 308 to
 *  the source until somebody publishes it again. */
export async function withdrawLocaleBody(
  pageId: string,
  locale: string,
  idempotencyKey: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/withdraw/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { page_id: pageId, locale },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What taking this language off would do. */
export async function previewWithdrawLocaleBody(
  pageId: string,
  locale: string,
): Promise<LanguageDecision> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/pages/{page_id}/translations/{locale}/body/withdraw/preview/",
    {
      params: {
        path: { page_id: pageId, locale },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What publishing the site would carry in each other language — the
 *  publication's own verdict, read without saving anything (TL15). */
export async function previewSitePublication(
  siteId: string,
): Promise<PublicationPlan> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/publications/preview/",
    {
      params: { path: { site_id: siteId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Every page or article of a site against every other language. */
export async function getSiteTranslationOverview(
  siteId: string,
  query: TranslationOverviewQuery = {},
): Promise<TranslationOverview> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/translations/",
    {
      params: { path: { site_id: siteId }, query },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What accepting these waiting translations would publish, and the
 *  `digest` the acceptance must send back (`x-dry-run`). */
export async function previewAcceptSiteTranslations(
  siteId: string,
  input: LocaleBatchAcceptInput,
): Promise<LocaleBatchResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/translations/accept/preview/",
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

/** Accepts waiting translations in one publication, against the previewed
 *  list (`locale_batch_stale` when it changed). */
export async function acceptSiteTranslations(
  siteId: string,
  input: LocaleBatchAcceptInput,
  idempotencyKey: string,
): Promise<LocaleBatchResult> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/translations/accept/",
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

/** The site's own texts (tagline, footer, blog and tag names) in `locale`. */
export async function getSiteTexts(
  siteId: string,
  locale: string,
): Promise<SiteTexts> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/{site_id}/texts/{locale}/",
    {
      params: { path: { site_id: siteId, locale } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function saveSiteTexts(
  siteId: string,
  locale: string,
  input: SiteTextsSaveInput,
): Promise<SiteTexts> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/sites/{site_id}/texts/{locale}/",
    {
      params: { path: { site_id: siteId, locale } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function publishSiteTexts(
  siteId: string,
  locale: string,
  idempotencyKey: string,
): Promise<SiteTextsPublication> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/sites/{site_id}/texts/{locale}/publish/",
    {
      params: {
        header: { "Idempotency-Key": idempotencyKey },
        path: { site_id: siteId, locale },
      },
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
  filters: {
    mine?: boolean;
    /** A date (the organization's midnight) or an ISO instant, inclusive. */
    from?: string;
    /** As `from`, exclusive. */
    to?: string;
    staffId?: string;
    /** At most this many, earliest first; 1 answers "is there any". */
    limit?: number;
  } = {},
): Promise<BookingAppointment[]> {
  const query = {
    ...(filters.mine ? { mine: true } : {}),
    ...(filters.from ? { from: filters.from } : {}),
    ...(filters.to ? { to: filters.to } : {}),
    ...(filters.staffId ? { staff_id: filters.staffId } : {}),
    ...(filters.limit ? { limit: filters.limit } : {}),
  };
  const { data, error, response } = await client.GET(
    "/api/v1/booking/appointments/",
    {
      params: Object.keys(query).length ? { query } : undefined,
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

/** The company's people; without the team screen, one's own entry only. */
export async function listPeople(
  query: { mine?: boolean } = {},
): Promise<Person[]> {
  const { data, error, response } = await client.GET("/api/v1/booking/staff/", {
    params: query.mine ? { query: { mine: true } } : undefined,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function getPerson(staffId: string): Promise<PersonDetail> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/staff/{staff_id}/",
    {
      params: { path: { staff_id: staffId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** "Add employee": entry, invitation, services and hours — all or nothing. */
export async function addPerson(
  input: PersonCreateInput,
): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/staff/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Name and phone (a person their own phone), or the account it stands for. */
export async function updatePerson(
  staffId: string,
  input: PersonUpdateInput,
): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/staff/{staff_id}/",
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

export async function setPersonServices(
  staffId: string,
  serviceIds: string[],
): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/staff/{staff_id}/services/",
    {
      params: { path: { staff_id: staffId } },
      body: { service_ids: serviceIds },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/**
 * Replaces the person's week; an empty list clears it. `expectedVersion` is
 * the week's `hours_version` as last read (409 `booking_version_conflict`).
 */
export async function setPersonHours(
  staffId: string,
  rules: PersonHoursRule[],
  expectedVersion: number,
  idempotencyKey: string,
): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/staff/{staff_id}/hours/",
    {
      params: {
        path: { staff_id: staffId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: { rules, expected_version: expectedVersion },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function addTimeOff(
  staffId: string,
  input: TimeOffInput,
): Promise<TimeOffCreated> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/staff/{staff_id}/time-off/",
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

export async function removeTimeOff(timeOffId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/booking/time-off/{time_off_id}/",
    {
      params: { path: { time_off_id: timeOffId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function listTeams(): Promise<StaffTeam[]> {
  const { data, error, response } = await client.GET("/api/v1/booking/teams/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createTeam(input: StaffTeamInput): Promise<StaffTeam> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/teams/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateTeam(
  teamId: string,
  input: StaffTeamUpdate,
): Promise<StaffTeam> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/teams/{team_id}/",
    {
      params: { path: { team_id: teamId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getBookingSetup(): Promise<BookingSetup> {
  const { data, error, response } = await client.GET("/api/v1/booking/setup/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function listBookingClosures(): Promise<BookingClosure[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/setup/closures/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createBookingClosure(
  input: BookingClosureInput,
  idempotencyKey: string,
): Promise<BookingClosure> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/closures/",
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

export async function updateBookingClosure(
  closureId: string,
  input: BookingClosureUpdate,
  idempotencyKey: string,
): Promise<BookingClosure> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/closures/{closure_id}/",
    {
      params: {
        path: { closure_id: closureId },
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

export async function deleteBookingClosure(
  closureId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/booking/setup/closures/{closure_id}/",
    {
      params: {
        path: { closure_id: closureId },
        query: { expected_version: expectedVersion },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

/** Every closure starting in `year` again a year later; answers how many. */
export async function copyBookingClosuresToNextYear(
  year: number,
  idempotencyKey: string,
): Promise<number> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/closures/copy-year/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: { year },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.count;
}

/** Seasons (ADR-072 §5): dated rules of an offer, a group or a unit. */
export async function listBookingRules(): Promise<BookingRule[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/setup/rules/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function createBookingRule(
  input: BookingRuleInput,
  idempotencyKey: string,
): Promise<BookingRule> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/rules/",
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

export async function updateBookingRule(
  ruleId: string,
  input: BookingRuleUpdate,
  idempotencyKey: string,
): Promise<BookingRule> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/rules/{rule_id}/",
    {
      params: {
        path: { rule_id: ruleId },
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

export async function deleteBookingRule(
  ruleId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/booking/setup/rules/{rule_id}/",
    {
      params: {
        path: { rule_id: ruleId },
        query: { expected_version: expectedVersion },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

/** Every season starting in `year` again a year later; answers how many. */
export async function copyBookingRulesToNextYear(
  year: number,
  idempotencyKey: string,
): Promise<number> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/rules/copy-year/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: { year },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.count;
}

export async function createSetupGroup(
  input: GroupSetupInput,
  idempotencyKey: string,
): Promise<GroupSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/groups/",
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

/** Only the fields sent change; `expected_version` names the version read. */
export async function updateSetupGroup(
  groupId: string,
  input: GroupSetupUpdate,
  idempotencyKey: string,
): Promise<GroupSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/groups/{group_id}/",
    {
      params: {
        path: { group_id: groupId },
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

export async function createSetupService(
  input: ServiceSetupInput,
  idempotencyKey: string,
): Promise<ServiceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/services/",
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

/** Only the fields sent change; `expected_version` names the version read. */
export async function updateSetupService(
  serviceId: string,
  input: ServiceSetupUpdate,
  idempotencyKey: string,
): Promise<ServiceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/services/{service_id}/",
    {
      params: {
        path: { service_id: serviceId },
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

export async function createSetupLocation(
  input: PlaceSetupInput,
  idempotencyKey: string,
): Promise<PlaceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/locations/",
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

/** Only the fields sent change; `expected_version` names the version read. */
export async function updateSetupLocation(
  locationId: string,
  input: PlaceSetupUpdate,
  idempotencyKey: string,
): Promise<PlaceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/locations/{location_id}/",
    {
      params: {
        path: { location_id: locationId },
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

export async function createSetupResource(
  input: ResourceSetupInput,
  idempotencyKey: string,
): Promise<ResourceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/resources/",
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

/** Only the fields sent change; `expected_version` names the version read. */
export async function updateSetupResource(
  resourceId: string,
  input: ResourceSetupUpdate,
  idempotencyKey: string,
): Promise<ResourceSetup> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/booking/setup/resources/{resource_id}/",
    {
      params: {
        path: { resource_id: resourceId },
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

export async function deleteTeam(teamId: string): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/booking/teams/{team_id}/",
    {
      params: { path: { team_id: teamId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

/** Vacancies and the system's picks the office looks at (ADR-058 §3). */
export async function getBookingQueue(): Promise<QueueItem[]> {
  const { data, error, response } = await client.GET("/api/v1/booking/queue/", {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function getBookingOverview(): Promise<BookingOverview> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/overview/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Obłożenie: units against days, `from`–`to` local days (≤ 62). */
export async function getBookingOccupancy(query: {
  from: string;
  to: string;
  group_id?: string;
}): Promise<BookingOccupancy> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/occupancy/",
    { params: { query }, credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What a stay would take — the unit, the hours, its length; nothing saved. */
export async function previewStay(input: StayInput): Promise<StayPlan> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/stays/preview/",
    {
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createStay(
  input: StayInput,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/stays/",
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

/** A stay moves by its dates; the unit may change within its group. */
export async function moveStay(
  appointmentId: string,
  input: { start_date: string; end_date: string },
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/stay/",
    {
      params: {
        path: { appointment_id: appointmentId },
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

/** What moving a stay would take; nothing saved. */
export async function previewStayMove(
  appointmentId: string,
  input: { start_date: string; end_date: string },
): Promise<StayPlan> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/stay/preview/",
    {
      params: { path: { appointment_id: appointmentId } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The company keeps a unit for itself (a renovation, own use). */
export async function addUnitBlock(
  resourceId: string,
  input: { starts_at: string; ends_at: string; reason: string },
  idempotencyKey: string,
): Promise<UnitBlock> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/resources/{resource_id}/blocks/",
    {
      params: {
        path: { resource_id: resourceId },
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

export async function removeUnitBlock(
  blockId: string,
  idempotencyKey: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.DELETE(
    "/api/v1/booking/setup/blocks/{block_id}/",
    {
      params: {
        path: { block_id: blockId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

export async function getCrewCandidates(
  appointmentId: string,
  query: { everyone?: boolean } = {},
): Promise<CrewCandidate[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/appointments/{appointment_id}/candidates/",
    {
      params: {
        path: { appointment_id: appointmentId },
        ...(query.everyone ? { query: { everyone: true } } : {}),
      },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

/** Exactly these people on the visit; the same ones again is „Zostaw”. */
export async function assignCrew(
  appointmentId: string,
  input: CrewInput,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/crew/",
    {
      params: {
        path: { appointment_id: appointmentId },
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

/** An account for a person added without one; accepting links it. */
export async function invitePerson(
  staffId: string,
  input: PersonInvitationInput,
): Promise<PersonInvitation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/staff/{staff_id}/invitation/",
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

/** "Remove from the company"; 409 while the person leads planned visits. */
export async function endPerson(staffId: string): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/staff/{staff_id}/end/",
    {
      params: { path: { staff_id: staffId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function restorePerson(staffId: string): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/staff/{staff_id}/restore/",
    {
      params: { path: { staff_id: staffId } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** „Pokazuj klientom”: the person's name on the booking form, or not. */
export async function setPersonPublic(
  staffId: string,
  input: { shown: boolean; name?: string },
): Promise<PersonDetail> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/staff/{staff_id}/public/",
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

type Period = { from?: string; to?: string };

/** A person's numbers for a period, each beside the period before (phase 5). */
export async function getStaffFacts(
  staffId: string,
  period: Period = {},
): Promise<StaffFacts> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/staff/{staff_id}/facts/",
    {
      params: { path: { staff_id: staffId }, query: period },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What happened to a person, newest first; `before` pages further back. */
export async function getStaffHistory(
  staffId: string,
  query: Period & { kind?: string; before?: string } = {},
): Promise<StaffHistory> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/staff/{staff_id}/history/",
    {
      params: { path: { staff_id: staffId }, query },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Everybody's numbers side by side: the owner's and administrator's view. */
export async function getTeamPerformance(
  query: Period & { team?: string } = {},
): Promise<TeamPerformance> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/performance/",
    { params: { query }, credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Who works, is away and is busy on a day; today without `date`. */
export async function getPeopleDay(date?: string): Promise<PeopleDay> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/staff-availability/",
    {
      params: date ? { query: { date } } : undefined,
      credentials: "same-origin",
      cache: "no-store",
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

/**
 * The customer did not come (UX-031): a confirmed visit that has begun closes
 * as `no_show`. Before its start: 409 `visit_not_started_yet`.
 */
export async function markBookingAppointmentNoShow(
  appointmentId: string,
  idempotencyKey: string,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/appointments/{appointment_id}/no-show/",
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

/** „Miejsce wizyty” (ADR-066): its town and, optionally, the address. */
export async function setBookingAppointmentPlace(
  appointmentId: string,
  place: BookingVisitPlace,
): Promise<BookingAppointment> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/appointments/{appointment_id}/place/",
    {
      params: { path: { appointment_id: appointmentId } },
      body: place,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The company's places a module keeps (a farm, say), for the visit form. */
export async function listBookingPlaces(
  search = "",
): Promise<BookingPlaceSuggestion[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/places/",
    {
      params: { query: search ? { q: search } : {} },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
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
/** A customer's „Do kogo?”: the team or the person shown to customers. */
export type BookingPublicChoice = { team_id?: string; person_id?: string };

export async function getPublicBookingDays(
  publicSlug: string,
  query: {
    service_id: string;
    location_id: string;
    from: string;
    to: string;
  } & BookingPublicChoice,
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
  query: {
    service_id: string;
    location_id: string;
    date: string;
  } & BookingPublicChoice,
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
  cursor?: string,
): Promise<{ items: ContentEntry[]; next_cursor: string | null }> {
  const { data, error, response } = await client.GET(
    "/api/v1/sites/collections/{collection_id}/entries/",
    {
      params: {
        path: { collection_id: collectionId },
        query: { limit: 100, ...(cursor ? { cursor } : {}) },
      },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function createContentEntry(
  collectionId: string,
  input: { slug: string; locale: string; title: string },
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
  input: { slug: string; locale: string; title: string },
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

/** Title, excerpt, author and indexing; a field left out keeps its value. */
export async function updateContentEntryMetadata(
  entryId: string,
  body: ContentEntryMetadataInput,
): Promise<ContentEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PATCH(
    "/api/v1/sites/entries/{entry_id}/metadata/",
    {
      params: { path: { entry_id: entryId } },
      body,
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
export type FarmAnimalHealthCorrection =
  components["schemas"]["AnimalHealthCorrectionInput"];

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

/** A hand-written entry corrected or withdrawn by its author: the next
 * revision, never a rewrite (ADR-062). */
export async function correctFarmAnimalHealth(
  animalId: string,
  entryId: string,
  input: FarmAnimalHealthCorrection,
): Promise<FarmAnimalHealthEntry> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/farms/animals/{animal_id}/health/{entry_id}/corrections/",
    {
      params: { path: { animal_id: animalId, entry_id: entryId } },
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
export type InventoryLotStock = components["schemas"]["InventoryLotStock"];
export type InventoryCategory = components["schemas"]["InventoryCategory"];
export type InventoryLowStockRow = components["schemas"]["LowStockRow"];
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
  method: "POST" | "PATCH" | "PUT" | "DELETE",
  path: keyof paths,
  pathParams: Record<string, string>,
  body?: unknown,
  idempotencyKey?: string,
): Promise<T> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await (client[method] as Fetch)(
    path as never,
    {
      params: {
        path: pathParams,
        ...(idempotencyKey
          ? { header: { "Idempotency-Key": idempotencyKey } }
          : {}),
      },
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

/** Only the fields sent change; `expiring_days: null` returns to the company's number. */
export function updateInventoryCategory(
  categoryId: string,
  input: components["schemas"]["PatchedInventoryCategoryUpdate"],
): Promise<InventoryCategory> {
  return inventoryWrite(
    "PATCH",
    "/api/v1/inventory/categories/{category_id}/",
    { category_id: categoryId },
    input,
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

/** Partie, których coś leży — od najkrótszej ważności. */
/** What is at or below its minimum, the biggest shortfall first (M4). */
export function listInventoryLowStock(
  places?: "main" | "warehouses" | "all",
): Promise<InventoryLowStockRow[]> {
  return inventoryRead("/api/v1/inventory/low-stock/", { places });
}

/** An item's minimum in one place; `null` returns to the item's own. */
export function setInventoryPlaceMinimum(
  input: components["schemas"]["PlaceMinimumInput"],
): Promise<InventoryBalance> {
  return inventoryWrite("PUT", "/api/v1/inventory/minimums/", {}, input);
}

export type InventoryImportResult = components["schemas"]["ImportResult"];
export type InventoryImportTemplate = components["schemas"]["ImportTemplate"];
export type InventoryImportInput = components["schemas"]["ImportInput"];

/** The CSV import's columns, limits and a file to start from. */
export function getInventoryImportTemplate(): Promise<InventoryImportTemplate> {
  return inventoryRead("/api/v1/inventory/imports/template/");
}

/** What a CSV would do to the catalogue; nothing is saved. */
export function previewInventoryImport(
  input: InventoryImportInput,
): Promise<InventoryImportResult> {
  return inventoryWrite(
    "POST",
    "/api/v1/inventory/imports/preview/",
    {},
    input,
  );
}

/** Saves the CSV: every row or none. One key per file chosen. */
export function applyInventoryImport(
  input: InventoryImportInput,
  idempotencyKey: string,
): Promise<InventoryImportResult> {
  return inventoryWrite(
    "POST",
    "/api/v1/inventory/imports/",
    {},
    input,
    idempotencyKey,
  );
}

export type InventoryStockValueReport =
  components["schemas"]["StockValueReport"];
export type InventoryUsageReport = components["schemas"]["UsageReport"];
export type InventoryStockValueGroup =
  components["schemas"]["StockValueReportGroupEnum"];
export type InventoryUsageGroup = components["schemas"]["UsageReportGroupEnum"];

/** What the stock is worth now: quantity × average cost (inventory.manage). */
export function getInventoryStockValue(query: {
  group: InventoryStockValueGroup;
  locationId?: string;
}): Promise<InventoryStockValueReport> {
  return inventoryRead("/api/v1/inventory/reports/stock-value/", {
    group: query.group,
    location_id: query.locationId,
  });
}

/** What went out in a period, and what a visit cost (inventory.manage). */
export function getInventoryUsage(query: {
  group: InventoryUsageGroup;
  from: string;
  to: string;
  page?: number;
  pageSize?: number;
}): Promise<InventoryUsageReport> {
  return inventoryRead("/api/v1/inventory/reports/usage/", {
    group: query.group,
    from: query.from,
    to: query.to,
    page: query.page ? String(query.page) : undefined,
    page_size: query.pageSize ? String(query.pageSize) : undefined,
  });
}

export function listInventoryLots(
  filters: { itemId?: string; locationId?: string } = {},
): Promise<InventoryLotStock[]> {
  return inventoryRead("/api/v1/inventory/lots/", {
    item_id: filters.itemId,
    location_id: filters.locationId,
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

/** The companies' visits to all of the keeper's farms (UX-078), soonest first. */
export type RegisterVisit = components["schemas"]["FarmRegisterVisit"];

export async function listRegisterVisits(
  query: {
    from?: string;
    to?: string;
    status?: "planned" | "done" | "canceled";
  } = {},
): Promise<RegisterVisit[]> {
  const { data, error, response } = await client.GET("/api/v1/farms/visits/", {
    params: { query },
    credentials: "same-origin",
    cache: "no-store",
  });
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Controls due on the keeper's animals (ADR-052, addendum 2026-10-03). */
export type FollowUp = components["schemas"]["FollowUp"];

export async function listFollowUps(
  query: { from?: string; to?: string } = {},
): Promise<FollowUp[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/farms/follow-ups/",
    { params: { query }, credentials: "same-origin", cache: "no-store" },
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
/** City, category, words, page, and a radius around the town or a point. */
export type CatalogSearch = NonNullable<
  paths["/api/v1/public/catalog/"]["get"]["parameters"]["query"]
>;

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

// --- Translations of the card and the booking catalogue (TL12) ---------------

/** One unit of a translation form: the source, the text, its state, its author. */
export type TranslationUnitState =
  components["schemas"]["ProfileTranslationUnit"];
export type ProfileTranslationList =
  components["schemas"]["ProfileTranslationList"];
export type ProfileTranslation =
  components["schemas"]["ProfileTranslationSummary"];
export type ProfileTranslationInput =
  components["schemas"]["ProfileTranslation"];
export type BookingItemKind =
  "service" | "location" | "resource" | "group" | "team";
export type BookingItemTranslationList =
  components["schemas"]["ItemTranslationList"];
export type BookingItemTranslation = components["schemas"]["ItemTranslation"];
export type BookingItemTranslationInput =
  components["schemas"]["ItemTranslationInput"];
export type TranslationOffer = components["schemas"]["TranslationOffer"];
export type TranslationQuote = components["schemas"]["Quote"];
export type TranslationTarget = components["schemas"]["Target"];
export type TranslationJob = components["schemas"]["Job"];

export async function getProfileTranslations(
  profileId: string,
): Promise<ProfileTranslationList> {
  const { data, error, response } = await client.GET(
    "/api/v1/profiles/{profile_id}/translations/",
    {
      params: { path: { profile_id: profileId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateProfileTranslation(
  profileId: string,
  locale: string,
  input: ProfileTranslationInput,
): Promise<ProfileTranslation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/profiles/{profile_id}/translations/{locale}/",
    {
      params: { path: { profile_id: profileId, locale } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function getBookingItemTranslations(
  kind: BookingItemKind,
  itemId: string,
): Promise<BookingItemTranslationList> {
  const { data, error, response } = await client.GET(
    "/api/v1/booking/setup/translations/{kind}/{item_id}/",
    {
      params: { path: { kind, item_id: itemId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function updateBookingItemTranslation(
  kind: BookingItemKind,
  itemId: string,
  locale: string,
  input: BookingItemTranslationInput,
  idempotencyKey: string,
): Promise<BookingItemTranslation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.PUT(
    "/api/v1/booking/setup/translations/{kind}/{item_id}/{locale}/",
    {
      params: {
        path: { kind, item_id: itemId, locale },
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

export async function previewBookingItemTranslation(
  kind: BookingItemKind,
  itemId: string,
  locale: string,
  input: BookingItemTranslationInput,
): Promise<BookingItemTranslation> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/booking/setup/translations/{kind}/{item_id}/{locale}/preview/",
    {
      params: { path: { kind, item_id: itemId, locale } },
      body: input,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Whether the company can order a translation now, and why not. */
export async function getTranslationOffer(): Promise<TranslationOffer> {
  const { data, error, response } = await client.GET(
    "/api/v1/translation/offer/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** What a person's or an integration's text gets: left alone, a proposal
 *  that waits for a person (the default), or overwritten — a person's choice. */
export type TranslationProtected = "skip" | "propose" | "overwrite";

export async function quoteTranslation(
  targets: TranslationTarget[],
  protectedTexts: TranslationProtected = "propose",
): Promise<TranslationQuote> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/translation/quotes/",
    {
      body: { targets, protected: protectedTexts, include_unverified: false },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export async function orderTranslation(
  targets: TranslationTarget[],
  quote: Pick<TranslationQuote, "digest" | "credits">,
  idempotencyKey: string,
  protectedTexts: TranslationProtected = "propose",
): Promise<TranslationJob> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/translation/jobs/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: {
        targets,
        protected: protectedTexts,
        include_unverified: false,
        digest: quote.digest,
        expected_credits: quote.credits,
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** One translation order with its parts and items, to follow its progress. */
export async function getTranslationJob(jobId: string): Promise<TranslationJob> {
  const { data, error, response } = await client.GET(
    "/api/v1/translation/jobs/{job_id}/",
    {
      params: { path: { job_id: jobId } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

export type AssistantOffer = components["schemas"]["AssistantOffer"];
export type AssistantConversationSummary =
  components["schemas"]["AssistantConversationSummary"];
export type AssistantConversation =
  components["schemas"]["AssistantConversation"];
export type AssistantTurn = components["schemas"]["AssistantTurn"];
export type AssistantTurnItem = components["schemas"]["AssistantTurnItem"];
export type AssistantConsentGroup =
  components["schemas"]["AssistantConsentGroup"];
export type CommandConsent = components["schemas"]["CommandConsent"];
export type CommandConsentCall = components["schemas"]["CommandConsentCall"];

/** Whether the assistant takes a message now, and why not. */
export async function getAssistantOffer(): Promise<AssistantOffer> {
  const { data, error, response } = await client.GET(
    "/api/v1/assistant/offer/",
    { credentials: "same-origin", cache: "no-store" },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The signed-in person's own conversations, newest first. */
export async function listAssistantConversations(
  limit = 20,
): Promise<AssistantConversationSummary[]> {
  const { data, error, response } = await client.GET(
    "/api/v1/assistant/conversations/",
    {
      params: { query: { limit } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.items;
}

export async function startAssistantConversation(
  language: "pl" | "en",
  idempotencyKey: string,
): Promise<AssistantConversationSummary> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/assistant/conversations/",
    {
      params: { header: { "Idempotency-Key": idempotencyKey } },
      body: { language },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The conversation with every turn: read again until the last one settles. */
export async function getAssistantConversation(
  conversationId: string,
  signal?: AbortSignal,
): Promise<AssistantConversation> {
  const { data, error, response } = await client.GET(
    "/api/v1/assistant/conversations/{conversation_id}/",
    {
      params: { path: { conversation_id: conversationId } },
      credentials: "same-origin",
      cache: "no-store",
      signal,
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** Queues the assistant's turn; its answer arrives in the conversation. */
export async function sendAssistantMessage(
  conversationId: string,
  text: string,
  idempotencyKey: string,
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/assistant/conversations/{conversation_id}/turns/",
    {
      params: {
        path: { conversation_id: conversationId },
        header: { "Idempotency-Key": idempotencyKey },
      },
      body: { text },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

/**
 * Answers the plan a turn waits with: the tokens of the groups the person
 * agreed to (group id → token), or `declined` for the whole plan.
 */
export async function answerAssistantConsent(
  conversationId: string,
  turnId: string,
  answer: { consents?: Record<string, string>; declined?: boolean },
): Promise<void> {
  const csrfToken = await getCsrfToken();
  const { error, response } = await client.POST(
    "/api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/consents/",
    {
      params: { path: { conversation_id: conversationId, turn_id: turnId } },
      body: {
        consents: answer.consents ?? {},
        declined: answer.declined ?? false,
      },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !response.ok) throwProblem(error, response);
}

/** The plan a person is asked to agree to, exactly as the server previewed it. */
export async function getCommandConsent(
  digest: string,
): Promise<CommandConsent> {
  const { data, error, response } = await client.GET(
    "/api/v1/organizations/current/command-consents/{digest}/",
    {
      params: { path: { digest } },
      credentials: "same-origin",
      cache: "no-store",
    },
  );
  if (error || !data) throwProblem(error, response);
  return data;
}

/** The person's click: mints the short-lived token that lets the plan run. */
export async function grantCommandConsent(digest: string): Promise<string> {
  const csrfToken = await getCsrfToken();
  const { data, error, response } = await client.POST(
    "/api/v1/organizations/current/command-consents/{digest}/",
    {
      params: { path: { digest } },
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    },
  );
  if (error || !data) throwProblem(error, response);
  return data.consent_token;
}
