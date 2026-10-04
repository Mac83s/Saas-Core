import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { coreSiteBlockManifest } from "@saas-core/site-blocks";
import {
  availablePageTemplates,
  createSiteBlockRegistry,
} from "@saas-core/site-blocks";

import {
  isStayBlock,
  stayEntitlements,
  stayModules,
  useStayOffers,
} from "./stay-offers";

const { api, profile } = vi.hoisted(() => ({
  api: { getBookingSetup: vi.fn() },
  profile: { features: { publicBooking: true } },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("../../../generated/deployment", () => ({ deployment: profile }));

const service = (time_model: string, active = true) => ({ time_model, active });

beforeEach(() => {
  vi.clearAllMocks();
  profile.features.publicBooking = true;
});

test("a company with an active offer booked from–to has stays to show", async () => {
  api.getBookingSetup.mockResolvedValue({
    services: [service("slot"), service("range")],
  });
  const { result } = renderHook(() => useStayOffers());
  // Nothing is offered before the company's booking answers.
  expect(result.current).toBe(false);
  await waitFor(() => expect(result.current).toBe(true));
});

test("visits only, an offer switched off, or bookings the person does not see: no stays", async () => {
  for (const answer of [
    () => Promise.resolve({ services: [service("slot"), service("event")] }),
    () => Promise.resolve({ services: [service("range", false)] }),
    () => Promise.reject(new Error("403")),
  ]) {
    api.getBookingSetup.mockImplementationOnce(answer);
    const { result, unmount } = renderHook(() => useStayOffers());
    await waitFor(() => expect(api.getBookingSetup).toHaveBeenCalled());
    await Promise.resolve();
    expect(result.current).toBe(false);
    unmount();
    api.getBookingSetup.mockClear();
  }
});

test("a product without a public booking form asks nobody", () => {
  profile.features.publicBooking = false;
  const { result } = renderHook(() => useStayOffers());
  expect(result.current).toBe(false);
  expect(api.getBookingSetup).not.toHaveBeenCalled();
});

test("with stays the editor asks for the booking's sections and the „Noclegi” template", () => {
  expect(["core.stay_units", "core.stay_map"].every(isStayBlock)).toBe(true);
  expect(isStayBlock("core.booking")).toBe(false);
  expect(stayModules(true)).toEqual(["shared.sites", "shared.booking"]);
  expect(stayModules(false)).toEqual(["shared.sites"]);
  const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
  const offered = (stays: boolean) =>
    availablePageTemplates(registry, stayEntitlements(stays)).map(
      ({ id }) => id,
    );
  expect(offered(false)).not.toContain("core.lodging");
  expect(offered(true)).toEqual([...offered(false), "core.lodging"]);
});
