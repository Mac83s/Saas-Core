import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type {
  BookingPublicAppointment,
  BookingPublicQuote,
} from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { SelfServiceBooking } from "./self-service-booking";

const { api } = vi.hoisted(() => ({
  api: {
    getSelfServiceBooking: vi.fn(),
    moveSelfServiceStay: vi.fn(),
    previewSelfServiceStayMove: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const quote: BookingPublicQuote = {
  currency: "PLN",
  lines: [
    {
      kind: "price",
      name: "Pobyt nad jeziorem",
      quantity: 2,
      gross_minor: 80000,
    },
  ],
  gross_minor: 80000,
  security_deposit_minor: 0,
  payment_policy: "on_site",
  prepayment: null,
  cancellation: null,
  digest: "digest-new",
};

const stay = {
  id: "77777777-7777-4777-8777-777777777777",
  starts_at: "2026-11-07T14:00:00Z",
  ends_at: "2026-11-10T10:00:00Z",
  timezone: "Europe/Warsaw",
  service_name: "Pobyt nad jeziorem",
  location_name: "Nad jeziorem",
  time_model: "range",
  range_unit: "night",
  unit_name: "Domek 2",
  status: "confirmed",
  hold_expires_at: null,
  payment: null,
  settlement: null,
  team_name: null,
  person_name: null,
  self_service: {
    reschedule: true,
    cancel: true,
    until: "2026-11-06T14:00:00Z",
  },
  quote: { ...quote, gross_minor: 120000, digest: "digest-old" },
} as unknown as BookingPublicAppointment;

function show() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SelfServiceBooking token="bk_token" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getSelfServiceBooking.mockResolvedValue(stay);
  api.previewSelfServiceStayMove.mockResolvedValue({
    starts_at: "2026-11-14T14:00:00Z",
    ends_at: "2026-11-16T10:00:00Z",
    length: 2,
    range_unit: "night",
    quote,
  });
  api.moveSelfServiceStay.mockResolvedValue({
    ...stay,
    starts_at: "2026-11-14T14:00:00Z",
    ends_at: "2026-11-16T10:00:00Z",
    quote,
  });
});

test("a stay is told by its days and its unit", async () => {
  show();

  expect(
    await screen.findByText("7–10 listopada 2026 · 3 noce"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Zameldowanie od 15:00, wymeldowanie do 11:00"),
  ).toBeInTheDocument();
  expect(screen.getByText("Domek 2 · Nad jeziorem")).toBeInTheDocument();
  // A stay is moved by its dates, not by a time of day.
  expect(screen.getByLabelText("Przyjazd")).toHaveAttribute("type", "date");
  expect(screen.getByLabelText("Wyjazd")).toHaveAttribute("type", "date");
});

test("a stay moves only after its new dates and price were shown", async () => {
  show();
  fireEvent.change(await screen.findByLabelText("Przyjazd"), {
    target: { value: "2026-11-14" },
  });
  // Both days first: nothing is checked on a half-typed stay.
  expect(screen.getByRole("button", { name: "Sprawdź termin" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Wyjazd"), {
    target: { value: "2026-11-16" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź termin" }));

  expect(
    await screen.findByText("Nowy termin: 14–16 listopada 2026 · 2 noce."),
  ).toBeInTheDocument();
  expect(api.previewSelfServiceStayMove).toHaveBeenCalledWith("bk_token", {
    start_date: "2026-11-14",
    end_date: "2026-11-16",
  });
  expect(api.moveSelfServiceStay).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Przenieś rezerwację" }));
  await waitFor(() => expect(api.moveSelfServiceStay).toHaveBeenCalledTimes(1));
  // With the digest of the price just shown.
  expect(api.moveSelfServiceStay.mock.calls[0][0]).toBe("bk_token");
  expect(api.moveSelfServiceStay.mock.calls[0][1]).toEqual({
    start_date: "2026-11-14",
    end_date: "2026-11-16",
  });
  expect(api.moveSelfServiceStay.mock.calls[0][3]).toBe("digest-new");
  expect(
    await screen.findByText("14–16 listopada 2026 · 2 noce"),
  ).toBeInTheDocument();
});

test("a visit keeps its time of day", async () => {
  api.getSelfServiceBooking.mockResolvedValue({
    ...stay,
    time_model: "slot",
    range_unit: "",
    unit_name: null,
    ends_at: "2026-11-07T15:00:00Z",
  });
  show();

  expect(await screen.findByLabelText("Nowy termin")).toHaveAttribute(
    "type",
    "datetime-local",
  );
  expect(screen.queryByLabelText("Przyjazd")).not.toBeInTheDocument();
  expect(screen.getByText("Nad jeziorem")).toBeInTheDocument();
});
