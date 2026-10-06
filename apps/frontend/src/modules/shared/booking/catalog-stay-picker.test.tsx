import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { CatalogUnitPage } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { CatalogStayPicker } from "./catalog-stay-picker";

const { api } = vi.hoisted(() => ({
  api: { getPublicStayEnds: vi.fn(), getPublicStayStarts: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const NIGHTS = "11111111-1111-4111-8111-111111111111";
const COTTAGES = "22222222-2222-4222-8222-222222222222";
const WEEKEND = "33333333-3333-4333-8333-333333333333";

const booking: CatalogUnitPage["booking"] = {
  form_url: "https://platforma.example/book/domki",
  form_slug: "domki",
  timezone: "Europe/Warsaw",
  last_day: "2027-10-04",
  paused: false,
  origin: "ey:token",
};

const offers: CatalogUnitPage["offers"] = [
  {
    id: NIGHTS,
    name: "Nocleg w domku",
    range_unit: "night",
    choice: { kind: "group", id: COTTAGES },
  },
];

function show(
  props: Partial<Parameters<typeof CatalogStayPicker>[0]> = {},
): ReturnType<typeof render> {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <CatalogStayPicker
        booking={booking}
        capacity={6}
        locale="pl"
        offers={offers}
        {...props}
      />
    </NextIntlClientProvider>,
  );
}

/** The address a link leads to, as its parts. */
function target(name: string): URL {
  return new URL(screen.getByRole("link", { name }).getAttribute("href")!);
}

beforeEach(() => {
  vi.clearAllMocks();
  // The calendar opens on the company's today.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-04T10:00:00Z"));
  api.getPublicStayStarts.mockResolvedValue(["2026-11-07", "2026-11-14"]);
  api.getPublicStayEnds.mockResolvedValue(["2026-11-09", "2026-11-10"]);
});

afterEach(() => {
  vi.useRealTimers();
});

test("the days are the form's own, and the link carries the choice and the catalogue's origin", async () => {
  const { container } = show();

  // Before any day is picked the link still says where the guest comes from.
  const plain = target("Zarezerwuj online");
  expect(plain.origin + plain.pathname).toBe(
    "https://platforma.example/book/domki",
  );
  expect(Object.fromEntries(plain.searchParams)).toEqual({
    offer: NIGHTS,
    group: COTTAGES,
    people: "2",
    origin: "ey:token",
  });

  // The free days are read from the company's form, for what books the unit.
  await waitFor(() =>
    expect(api.getPublicStayStarts).toHaveBeenCalledWith("domki", {
      service_id: NIGHTS,
      group_id: COTTAGES,
      from: "2026-10-04",
      to: "2026-11-30",
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: / 7 listopada 2026, wolny termin/,
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: / 10 listopada 2026, Wyjazd, 3 noce/,
    }),
  );
  fireEvent.change(screen.getByLabelText("Osoby"), { target: { value: "4" } });

  expect(
    Object.fromEntries(target("Zarezerwuj ten termin").searchParams),
  ).toEqual({
    offer: NIGHTS,
    group: COTTAGES,
    from: "2026-11-07",
    to: "2026-11-10",
    people: "4",
    origin: "ey:token",
  });
  expect((await axe.run(container)).violations).toEqual([]);
});

test("a search's days and guests open the page already chosen; what cannot be a stay is dropped", () => {
  const first = show({
    preset: { from: "2026-11-07", to: "2026-11-10", people: "3" },
  });
  expect(
    Object.fromEntries(target("Zarezerwuj ten termin").searchParams),
  ).toEqual({
    offer: NIGHTS,
    group: COTTAGES,
    from: "2026-11-07",
    to: "2026-11-10",
    people: "3",
    origin: "ey:token",
  });
  first.unmount();

  // A day behind us, an end before its start, a number that is no party.
  show({ preset: { from: "2026-09-01", to: "2026-08-01", people: "wielu" } });
  expect(Object.fromEntries(target("Zarezerwuj online").searchParams)).toEqual({
    offer: NIGHTS,
    group: COTTAGES,
    people: "2",
    origin: "ey:token",
  });
});

test("a unit booked through two offers lets the guest choose; a paused form shows no days", async () => {
  show({
    booking: { ...booking, paused: true },
    offers: [
      ...offers,
      {
        id: WEEKEND,
        name: "Weekend w domku",
        range_unit: "night",
        choice: { kind: "unit", id: COTTAGES },
      },
    ],
  });

  fireEvent.change(screen.getByLabelText("Oferta"), {
    target: { value: WEEKEND },
  });

  expect(target("Zarezerwuj online").searchParams.get("unit")).toBe(COTTAGES);
  expect(
    screen.getByText(/Rezerwacje online są chwilowo wstrzymane/),
  ).toBeInTheDocument();
  expect(api.getPublicStayStarts).not.toHaveBeenCalled();
});
