import { beforeEach, expect, test, vi } from "vitest";

/** „Do akceptacji”, „Zadania” and a job's page entered straight from the
 *  address bar: in a deployment without the translation engine (HoofCare,
 *  MedPlano) they are a 404 decided on the server, so no screen is drawn
 *  and nothing asks the translation API. */

const { api, composed } = vi.hoisted(() => ({
  api: {
    getTranslationOffer: vi.fn(),
    getTranslationJob: vi.fn(),
    listTranslationJobs: vi.fn(),
    listTranslationReview: vi.fn(),
    listTranslationDemand: vi.fn(),
  },
  composed: { translation: false },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("../../../generated/deployment", async (original) => {
  const { deployment } =
    await original<typeof import("../../../generated/deployment")>();
  const others = (deployment.modules as readonly string[]).filter(
    (module) => module !== "shared.translation",
  );
  const withEngine = (modules: readonly string[]) => [
    ...modules.filter((module) => module !== "shared.translation"),
    ...(composed.translation ? ["shared.translation"] : []),
  ];
  return {
    deployment: {
      ...deployment,
      get modules() {
        return withEngine(others);
      },
      get organizationTypes() {
        return deployment.organizationTypes.map((type) => ({
          ...type,
          modules: withEngine(type.modules),
        }));
      },
    },
  };
});
vi.mock("#lib/server-auth", () => ({
  getServerCurrentOrganization: async () => ({
    id: "0199f0a0-0000-7000-8000-000000000001",
    organization_type: undefined,
  }),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/sites/translations",
}));

const JOB = "0199f0a0-0000-7000-8000-0000000000d1";

async function pages() {
  vi.resetModules();
  const [review, jobs, job] = await Promise.all([
    import("../../../app/[locale]/panel/sites/translations/review/page"),
    import("../../../app/[locale]/panel/sites/translations/jobs/page"),
    import("../../../app/[locale]/panel/sites/translations/jobs/[jobId]/page"),
  ]);
  return [
    () => review.default(),
    () => jobs.default({ searchParams: Promise.resolve({ state: "held" }) }),
    () => job.default({ params: Promise.resolve({ jobId: JOB }) }),
  ];
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("without the engine each page is a 404 and the translation API is asked nothing", async () => {
  composed.translation = false;
  for (const page of await pages())
    await expect(page()).rejects.toThrow("NEXT_NOT_FOUND");
  for (const call of Object.values(api)) expect(call).not.toHaveBeenCalled();
});

test("with the engine each page hands over to its screen", async () => {
  composed.translation = true;
  for (const page of await pages()) {
    const element = await page();
    expect(element.props).toBeTruthy();
  }
});
