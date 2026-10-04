import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { TranslationJobsBar } from "./jobs-bar";
import { TranslateMissing } from "./translate-missing";
import { TranslationSettingsSection } from "./translation-settings";
import { TranslationTabs } from "./translation-tabs";
import { useTranslationOffer } from "./use-translation";

const { api, composed } = vi.hoisted(() => ({
  api: {
    getTranslationOffer: vi.fn(),
    getTranslationSettings: vi.fn(),
    listTranslationJobs: vi.fn(),
    listTranslationReview: vi.fn(),
    listGlossaryTerms: vi.fn(),
  },
  // What the deployment's profile composes: a product without the engine
  // (HoofCare, MedPlano) by default.
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
  return {
    deployment: {
      ...deployment,
      get modules() {
        return composed.translation
          ? [...others, "shared.translation"]
          : others;
      },
    },
  };
});
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/sites/translations",
}));

function Offer() {
  return <p>offer: {useTranslationOffer().state}</p>;
}

function view(children: ReactNode) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      {children}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  composed.translation = false;
  // What the API of a deployment without the module would answer: 404.
  for (const call of Object.values(api))
    call.mockRejectedValue(new Error("404"));
});

test("a deployment without the translation module asks its API nothing", async () => {
  const { container } = view(
    <>
      <Offer />
      {/* Ustawienia › Usługi i grafik, the business card: „Przetłumacz brakujące”. */}
      <TranslateMissing
        targets={[
          {
            source_key: "booking.catalog",
            object_id: "0199f0a0-0000-7000-8000-0000000000a1",
            locale: "en",
            basis: "published",
          },
        ]}
      />
      {/* „Strona internetowa → Tłumaczenia”: the tabs and the bar of running jobs. */}
      <TranslationTabs />
      <TranslationJobsBar />
      {/* Ustawienia › Języki i tłumaczenia. */}
      <TranslationSettingsSection canManage />
    </>,
  );
  // Known at once, with no request behind it — and it stays so.
  expect(screen.getByText("offer: absent")).toBeTruthy();
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(container.textContent).toBe("offer: absent");
  for (const [name, call] of Object.entries(api))
    expect(call, name).not.toHaveBeenCalled();
});

test("with the module composed the offer is asked once and answered", async () => {
  composed.translation = true;
  api.getTranslationOffer.mockResolvedValue({ available: true, reasons: [] });
  view(<Offer />);
  expect(screen.getByText("offer: loading")).toBeTruthy();
  expect(await screen.findByText("offer: available")).toBeTruthy();
  expect(api.getTranslationOffer).toHaveBeenCalledTimes(1);
});

test("an engine that is composed but does not answer still reads as absent", async () => {
  composed.translation = true;
  view(<Offer />);
  await waitFor(() => expect(screen.getByText("offer: absent")).toBeTruthy());
  expect(api.getTranslationOffer).toHaveBeenCalledTimes(1);
});
