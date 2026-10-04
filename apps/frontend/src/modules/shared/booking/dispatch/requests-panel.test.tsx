import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type OrganizationSummary,
  type QueueItem,
} from "@saas-core/api-client";

import polishMessages from "../../../../../messages/pl.json";
import { RequestsPanel } from "./requests-panel";

const { api, router } = vi.hoisted(() => ({
  api: {
    answerBookingRequest: vi.fn(),
    getBookingRequests: vi.fn(),
  },
  router: { refresh: vi.fn() },
}));
vi.mock("#i18n/navigation", () => ({ Link: "a", useRouter: () => router }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const request = {
  id: "55555555-5555-4555-8555-555555555555",
  starts_at: "2026-10-12T08:00:00Z",
  ends_at: "2026-10-12T09:00:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Konsultacja na prośbę",
  status: "pending_request",
  hold_expires_at: "2026-10-05T06:00:00Z",
  passed: false,
  closes_explicitly: false,
  customer_name: "Anna Kowalska",
  title: "",
  staff_id: null,
  staff_name: "",
  staff_membership_id: null,
  location_name: "Gabinet",
  place: null,
  place_town: "",
  place_address: "",
  appointment_kind: "",
  flags: [],
  resource_name: null,
  crew: [],
  staff_required: 1,
  needs_assignment: false,
  auto_assigned: false,
  crew_version: 1,
  queue_reason: "",
  queued_at: null,
  requested_team: null,
  requested_staff_id: null,
  customer_notes: "Proszę o termin rano",
  customer_phone: "+48 600 100 200",
  customer_email: "anna@example.test",
} as unknown as QueueItem;
const later = {
  ...request,
  id: "66666666-6666-4666-8666-666666666666",
  customer_name: "Ewa Nowak",
  customer_notes: "",
  hold_expires_at: "2026-10-05T18:00:00Z",
} as QueueItem;

const organization = (permissions: string[]): OrganizationSummary => ({
  id: "019c5f87-fce8-739b-b960-b7a195bfc298",
  name: "Dokumenty Demo",
  slug: "dokumenty-demo",
  workspace_kind: "business",
  organization_type: "business",
  status: "active",
  default_locale: "pl",
  timezone: "Europe/Warsaw",
  currency: "PLN",
  version: 1,
  membership_status: "active",
  role: "manager",
  permissions,
  active: true,
});
const office = organization([
  "booking.appointment.read",
  "booking.appointment.manage",
]);

function show(given = office) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <RequestsPanel organization={given} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getBookingRequests.mockResolvedValue([request, later]);
});

test("the requests that wait are listed with who asks, for what and until when the company answers", async () => {
  const { container } = show();
  const table = await screen.findByRole("table", {
    name: "Prośby czekające na odpowiedź",
  });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  const first = within(rows[0]!);
  expect(first.getByText("Anna Kowalska")).toBeInTheDocument();
  expect(
    first.getByText("+48 600 100 200 · anna@example.test"),
  ).toBeInTheDocument();
  expect(first.getByText("„Proszę o termin rano”")).toBeInTheDocument();
  expect(first.getByText("Konsultacja na prośbę")).toBeInTheDocument();
  // The company's clock: 06:00 UTC is 08:00 in Warsaw.
  expect(first.getByText(/5 paź 2026, 08:00/)).toBeInTheDocument();
  expect(
    first.getByRole("button", { name: "Przyjmij rezerwację: Anna Kowalska" }),
  ).toBeInTheDocument();
  expect((await axe.run(container)).violations).toEqual([]);
});

test("a request is accepted from the list, and the list and the menu's count follow", async () => {
  api.answerBookingRequest.mockResolvedValue({
    ...request,
    status: "confirmed",
  });
  show();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Przyjmij rezerwację: Anna Kowalska",
    }),
  );
  await waitFor(() =>
    expect(api.answerBookingRequest).toHaveBeenCalledWith(
      request.id,
      "accept",
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    ),
  );
  expect(
    await screen.findByText(/Rezerwacja przyjęta i potwierdzona/),
  ).toBeInTheDocument();
  await waitFor(() => expect(api.getBookingRequests).toHaveBeenCalledTimes(2));
  expect(router.refresh).toHaveBeenCalled();
});

test("declining asks first and takes the company's own words for the customer", async () => {
  api.answerBookingRequest
    .mockRejectedValueOnce(
      new ApiProblemError({
        type: "about:blank",
        title: "Validation",
        status: 400,
        code: "validation_error",
        detail: "",
        correlation_id: null,
        errors: [{ field: "reason", code: "links", message: "Bez linków." }],
      }),
    )
    .mockResolvedValue({ ...request, status: "canceled" });
  show();
  fireEvent.click(
    await screen.findByRole("button", { name: "Odmów: Anna Kowalska" }),
  );
  const question = await screen.findByRole("dialog", {
    name: "Odmówić tej rezerwacji?",
  });
  expect(
    within(question).getByText(/Klient zobaczy te słowa w e-mailu o odmowie/),
  ).toBeInTheDocument();
  expect((await axe.run(question)).violations).toEqual([]);
  const reason = within(question).getByLabelText(
    "Powód dla klienta (opcjonalnie)",
  );
  fireEvent.change(reason, { target: { value: "Zapisy na www.inna.example" } });
  fireEvent.click(
    within(question).getByRole("button", { name: "Odmów rezerwacji" }),
  );
  expect(
    await within(question).findByText(
      "Powód nie może zawierać linków ani adresów stron i e-maili.",
    ),
  ).toBeInTheDocument();
  fireEvent.change(reason, {
    target: { value: " W tym tygodniu nie przyjmujemy. " },
  });
  fireEvent.click(
    within(question).getByRole("button", { name: "Odmów rezerwacji" }),
  );
  await waitFor(() =>
    expect(api.answerBookingRequest).toHaveBeenLastCalledWith(
      request.id,
      "decline",
      expect.stringMatching(/^[0-9a-f-]{36}$/),
      "W tym tygodniu nie przyjmujemy.",
    ),
  );
  // Other words are another answer: the refused one's key is not reused.
  const [, , firstKey] = api.answerBookingRequest.mock.calls[0]!;
  const [, , secondKey] = api.answerBookingRequest.mock.calls[1]!;
  expect(firstKey).not.toBe(secondKey);
  expect(
    await screen.findByText(/Odmówiono rezerwacji\. Klient dostał wiadomość/),
  ).toBeInTheDocument();
});

test("a request somebody else answered says so, and whoever may not answer sees no list", async () => {
  api.answerBookingRequest.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "appointment_not_changeable",
      detail: "",
      correlation_id: null,
    }),
  );
  const first = show();
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Przyjmij rezerwację: Ewa Nowak",
    }),
  );
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  await waitFor(() => expect(api.getBookingRequests).toHaveBeenCalledTimes(2));
  first.unmount();

  api.getBookingRequests.mockClear();
  show(organization(["booking.appointment.read"]));
  expect(
    screen.getByText("Na prośby odpowiadają osoby zarządzające rezerwacjami."),
  ).toBeInTheDocument();
  expect(api.getBookingRequests).not.toHaveBeenCalled();
});
