import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { StaffAccountsCard } from "./staff-accounts-card";

const api = vi.hoisted(() => ({
  getBookingCatalog: vi.fn(),
  listMemberships: vi.fn(),
  updateBookingStaff: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const PIOTR = "11111111-1111-4111-8111-111111111111";
const MEMBER = "22222222-2222-4222-8222-222222222222";

beforeEach(() => {
  vi.clearAllMocks();
  api.getBookingCatalog.mockResolvedValue({
    locations: [],
    resources: [],
    services: [],
    staff: [
      {
        id: PIOTR,
        name: "Piotr korektor",
        public_slug: "piotr",
        membership_id: null,
      },
    ],
  });
  api.listMemberships.mockResolvedValue([
    {
      id: MEMBER,
      user_id: "u1",
      email: "korektor@hoofcare.test",
      first_name: "Piotr",
      last_name: "Nowak",
      role: "trimmer",
      status: "active",
      joined_at: "2026-09-19T10:00:00Z",
    },
  ]);
  api.updateBookingStaff.mockImplementation(async (id, input) => ({
    id,
    name: "Piotr korektor",
    public_slug: "piotr",
    membership_id: input.membership_id,
  }));
});

test("łączy pracownika kalendarza z kontem członka zespołu", async () => {
  const { container } = render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <StaffAccountsCard />
    </NextIntlClientProvider>,
  );

  const select = await screen.findByLabelText("Piotr korektor");
  fireEvent.change(select, { target: { value: MEMBER } });

  await waitFor(() =>
    expect(api.updateBookingStaff).toHaveBeenCalledWith(PIOTR, {
      membership_id: MEMBER,
    }),
  );
  expect(
    await screen.findByText("Zapisano powiązanie: Piotr korektor."),
  ).not.toBeNull();
  expect((select as HTMLSelectElement).value).toBe(MEMBER);

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("odłączenie wysyła null", async () => {
  api.getBookingCatalog.mockResolvedValue({
    locations: [],
    resources: [],
    services: [],
    staff: [
      {
        id: PIOTR,
        name: "Piotr korektor",
        public_slug: "piotr",
        membership_id: MEMBER,
      },
    ],
  });
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <StaffAccountsCard />
    </NextIntlClientProvider>,
  );

  fireEvent.change(await screen.findByLabelText("Piotr korektor"), {
    target: { value: "" },
  });
  await waitFor(() =>
    expect(api.updateBookingStaff).toHaveBeenCalledWith(PIOTR, {
      membership_id: null,
    }),
  );
});
