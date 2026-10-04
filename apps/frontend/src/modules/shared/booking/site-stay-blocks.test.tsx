import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { StayLive } from "@saas-core/site-blocks";

import { SiteStayBlock } from "./site-stay-blocks";

const { api } = vi.hoisted(() => ({
  api: { getPublicStayEnds: vi.fn(), getPublicStayStarts: vi.fn() },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const STAY = "11111111-1111-4111-8111-111111111111";
const RENTAL = "22222222-2222-4222-8222-222222222222";
const COTTAGES = "33333333-3333-4333-8333-333333333333";
const FLAT = "44444444-4444-4444-8444-444444444444";
const KAYAK = "55555555-5555-4555-8555-555555555555";

const live: StayLive = {
  slug: "domki-demo",
  form_url: "http://business.localhost:8080/book/domki-demo",
  timezone: "Europe/Warsaw",
  last_day: "2028-04-04",
  paused: false,
  offers: [
    {
      id: STAY,
      name: "Pobyt nad jeziorem",
      range_unit: "night",
      choices: [
        { kind: "group", id: COTTAGES, name: "Domek 6-os.", capacity: 6 },
        { kind: "unit", id: FLAT, name: "Apartament", capacity: 2 },
      ],
    },
    {
      id: RENTAL,
      name: "Kajaki",
      range_unit: "day",
      choices: [{ kind: "unit", id: KAYAK, name: "Kajak", capacity: null }],
    },
  ],
};

const day = (name: RegExp) => screen.findByRole("button", { name });
const action = () => screen.getByRole("link", { name: /zarezerwuj/i });

beforeEach(() => {
  vi.clearAllMocks();
  // Only the clock: the calendar opens on the company's today.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-04T10:00:00Z"));
  api.getPublicStayStarts.mockResolvedValue(["2026-10-10", "2026-10-17"]);
  api.getPublicStayEnds.mockResolvedValue(["2026-10-12", "2026-10-13"]);
});
afterEach(() => {
  vi.useRealTimers();
});

test("the calendar reads free days at the form's address and leads to the form with them", async () => {
  const { container } = render(
    <SiteStayBlock
      data={{ title: "Wolne terminy" }}
      kind="calendar"
      live={live}
      locale="pl"
    />,
  );

  // Before anything is picked the way to the form names the first choice.
  expect(action()).toHaveAttribute(
    "href",
    `${live.form_url}?offer=${STAY}&group=${COTTAGES}`,
  );
  fireEvent.click(await day(/ 10 października 2026, wolny termin/));
  expect(api.getPublicStayStarts).toHaveBeenCalledWith("domki-demo", {
    service_id: STAY,
    group_id: COTTAGES,
    from: "2026-10-04",
    to: "2026-11-30",
  });
  fireEvent.click(await day(/ 12 października 2026, Wyjazd, 2 noce/));
  expect(api.getPublicStayEnds).toHaveBeenCalledWith("domki-demo", {
    service_id: STAY,
    group_id: COTTAGES,
    start: "2026-10-10",
  });
  expect(action()).toHaveAttribute(
    "href",
    `${live.form_url}?offer=${STAY}&group=${COTTAGES}&from=2026-10-10&to=2026-10-12`,
  );
  expect(
    screen.getByText("10 października – 12 października · 2 noce"),
  ).toBeVisible();
  const results = await axe.run(container);
  expect(results.violations).toEqual([]);

  // Another thing booked: its own days are asked for, the chosen ones go.
  fireEvent.change(screen.getByLabelText("Co rezerwujesz"), {
    target: { value: `unit:${FLAT}` },
  });
  await waitFor(() =>
    expect(api.getPublicStayStarts).toHaveBeenCalledWith(
      "domki-demo",
      expect.objectContaining({ resource_id: FLAT }),
    ),
  );
  expect(action()).toHaveAttribute(
    "href",
    `${live.form_url}?offer=${STAY}&unit=${FLAT}`,
  );
  // A rental counts days, and says so.
  fireEvent.change(screen.getByLabelText("Oferta"), {
    target: { value: RENTAL },
  });
  expect(await screen.findByText("Wybierz pierwszy dzień")).toBeVisible();
  expect(screen.queryByLabelText("Co rezerwujesz")).toBeNull();
});

test("the widget asks for the days and the people, and opens its calendar when asked", async () => {
  const { container } = render(
    <SiteStayBlock
      data={{ title: "Rezerwacja", action_label: "Sprawdź cenę" }}
      kind="search"
      live={{ ...live, offers: live.offers.slice(0, 1) }}
      locale="pl"
    />,
  );

  // No calendar and no question to the server until a date is asked for.
  expect(api.getPublicStayStarts).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Oferta")).toBeNull();
  fireEvent.change(screen.getByLabelText("Liczba osób"), {
    target: { value: "4" },
  });
  expect(screen.getByRole("link", { name: "Sprawdź cenę" })).toHaveAttribute(
    "href",
    `${live.form_url}?offer=${STAY}&group=${COTTAGES}&people=4`,
  );
  fireEvent.click(screen.getByRole("button", { name: /Przyjazd/ }));
  fireEvent.click(await day(/ 17 października 2026, wolny termin/));
  expect(
    screen.getByRole("button", { name: /Przyjazd.*17 października/ }),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: "Sprawdź cenę" })).toHaveAttribute(
    "href",
    `${live.form_url}?offer=${STAY}&group=${COTTAGES}&from=2026-10-17&people=4`,
  );
  const results = await axe.run(container);
  expect(results.violations).toEqual([]);
});

test("a paused form shows no calendar, only the way to the form", () => {
  render(
    <SiteStayBlock
      data={{ title: "Wolne terminy" }}
      kind="calendar"
      live={{ ...live, paused: true }}
      locale="de"
    />,
  );

  expect(
    screen.getByText("Die Online-Buchung ist vorübergehend ausgesetzt."),
  ).toBeVisible();
  expect(api.getPublicStayStarts).not.toHaveBeenCalled();
  expect(
    screen.getByRole("link", { name: "Preis prüfen und buchen" }),
  ).toHaveAttribute("href", `${live.form_url}?offer=${STAY}&group=${COTTAGES}`);
});
