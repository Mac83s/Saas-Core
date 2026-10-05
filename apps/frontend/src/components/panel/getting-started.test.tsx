import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import englishMessages from "../../../messages/en.json";
import polishMessages from "../../../messages/pl.json";
import type { PanelAccess } from "#lib/panel-navigation";
import { ApiProblemError } from "@saas-core/api-client";
import { GettingStarted } from "./getting-started";

const { api } = vi.hoisted(() => ({
  api: {
    getBookingSetup: vi.fn(),
    getCustomerBillingOverview: vi.fn(),
    listBookingAppointments: vi.fn(),
    listFarms: vi.fn(),
    listInvitations: vi.fn(),
    listMemberships: vi.fn(),
    listSites: vi.fn(),
    readOrganizationProfile: vi.fn(),
  },
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
// The organization type's own ready-made services (ADR-050); none in core.
const types = vi.hoisted(() => ({ templates: [] as unknown[] }));
vi.mock("#lib/organization-types", async (original) => {
  const actual = await original<typeof import("#lib/organization-types")>();
  return {
    ...actual,
    organizationType: (key?: string | null) => ({
      ...actual.organizationType(key),
      serviceTemplates: types.templates,
    }),
  };
});
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

// Core's global roles (saas_core.modules.core.organizations.permissions).
const viewer = ["organization.read", "booking.appointment.read", "farms.read"];
const owner = [
  ...viewer,
  "organization.members.read",
  "organization.members.manage",
  "organization.members.manage_limited",
  "organization.settings.manage",
  "organization.billing.manage",
  "booking.appointment.manage",
  "farms.manage",
  "site.content.edit",
  "profiles.manage",
];

function access(overrides: Partial<PanelAccess> = {}): PanelAccess {
  return {
    modules: [
      "core.identity",
      "core.organizations",
      "shared.billing",
      "shared.booking",
      "shared.farms",
      "shared.profiles",
      "shared.sites",
    ],
    permissions: owner,
    isOwner: true,
    limited: false,
    organizationType: "business",
    ...overrides,
  };
}

function renderList(
  current = access(),
  messages: Record<string, unknown> = polishMessages,
  locale = "pl",
) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <GettingStarted access={current} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  types.templates = [];
  api.getBookingSetup.mockResolvedValue({ services: [] });
  api.getCustomerBillingOverview.mockResolvedValue({ subscription: null });
  api.listBookingAppointments.mockResolvedValue([]);
  api.listFarms.mockResolvedValue([]);
  api.listInvitations.mockResolvedValue([]);
  api.listMemberships.mockResolvedValue([{ id: "only-me" }]);
  api.listSites.mockResolvedValue({ items: [] });
  api.readOrganizationProfile.mockResolvedValue({
    profile: { id: "profile-one" },
    catalog: { published: false },
  });
});

test("pokazuje kroki typu organizacji z postępem liczonym z danych", async () => {
  api.getCustomerBillingOverview.mockResolvedValue({
    subscription: { state: "trialing" },
  });
  api.listFarms.mockResolvedValue([{ id: "farm-one" }]);
  const { container } = renderList();

  expect(
    await screen.findByRole("heading", { level: 2, name: "Na start" }),
  ).toBeInTheDocument();
  expect(screen.getByText("Gotowe 2 z 7")).toBeInTheDocument();
  expect(
    screen.getAllByRole("listitem").map((item) => item.textContent),
  ).toEqual([
    expect.stringContaining("Wybierz planZrobione"),
    expect.stringContaining("Dodaj pierwsze gospodarstwoZrobione"),
    // What customers book comes before the first visit: an offer started
    // from a preset (ADR-072 §10, slice 5g).
    expect.stringContaining("Ustaw pierwszą ofertęDo zrobienia"),
    expect.stringContaining("Zaplanuj pierwszą wizytęDo zrobienia"),
    expect.stringContaining("Zaproś kogoś do zespołuDo zrobienia"),
    // The business card sits before the website: it is what puts the company
    // in the directory, and every organization has it (ADR-053).
    expect.stringContaining("Uzupełnij wizytówkęDo zrobienia"),
    expect.stringContaining("Uruchom stronę internetowąDo zrobienia"),
  ]);
  // A step that is done offers no action; the first open one leads on.
  expect(screen.queryByRole("link", { name: /Wybierz plan/ })).toBeNull();
  expect(screen.getByRole("link", { name: /Wybierz wzorzec/ })).toHaveAttribute(
    "href",
    "/panel/settings/services/presets",
  );

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("a type without a module is never asked for it, in English too", async () => {
  const { container } = renderList(
    access({
      modules: ["core.organizations", "shared.billing", "shared.booking"],
    }),
    englishMessages,
    "en",
  );

  expect(await screen.findByText("0 of 4 done")).toBeInTheDocument();
  expect(
    screen.getAllByRole("listitem").map((item) => item.textContent),
  ).toEqual([
    expect.stringContaining("Choose a plan"),
    expect.stringContaining("Set up your first offer"),
    expect.stringContaining("Plan your first appointment"),
    expect.stringContaining("Invite someone to the team"),
  ]);
  expect(screen.queryByText(/farm/i)).toBeNull();
  // Nothing may ask the API about a module this organization does not have.
  expect(api.listFarms).not.toHaveBeenCalled();
  expect(api.listSites).not.toHaveBeenCalled();

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("członkostwo bez uprawnień do żadnego kroku nie widzi listy", () => {
  const { container } = renderList(
    access({ permissions: viewer, isOwner: false, limited: true }),
  );

  expect(container).toBeEmptyDOMElement();
  expect(api.getCustomerBillingOverview).not.toHaveBeenCalled();
  expect(api.listMemberships).not.toHaveBeenCalled();
});

test("zaproszenie bez odpowiedzi zamyka krok zespołu", async () => {
  api.listInvitations.mockResolvedValue([
    { id: "invitation", status: "pending" },
    { id: "revoked", status: "revoked" },
  ]);
  renderList();

  expect(await screen.findByText("Gotowe 1 z 7")).toBeInTheDocument();
  expect(
    screen.getByText("Zaproś kogoś do zespołu").closest("li"),
  ).toHaveTextContent("Zrobione");
});

test("błąd odczytu daje ponowienie zamiast zmyślonego postępu", async () => {
  api.listFarms.mockRejectedValueOnce(new Error("offline"));
  renderList();

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie udało się sprawdzić, co jest już zrobione.",
  );
  expect(screen.queryByText(/Gotowe 0 z/)).toBeNull();

  api.listFarms.mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(await screen.findByText("Gotowe 0 z 7")).toBeInTheDocument();
});

test("firma bez planu widzi listę z krokiem „Wybierz plan”, a nie błąd", async () => {
  // What the modules answer before a plan is picked.
  const refused = new ApiProblemError({
    type: "about:blank",
    title: "Żądanie nie może zostać obsłużone",
    status: 403,
    code: "entitlement_required",
    detail: "Plan organizacji nie pozwala na tę operację.",
  } as ConstructorParameters<typeof ApiProblemError>[0]);
  api.getBookingSetup.mockRejectedValue(refused);
  api.listBookingAppointments.mockRejectedValue(refused);
  api.listSites.mockRejectedValue(refused);
  renderList();

  expect(await screen.findByText("Gotowe 0 z 7")).toBeInTheDocument();
  expect(screen.getAllByText("Wybierz plan").length).toBeGreaterThan(0);
  expect(screen.queryByRole("alert")).toBeNull();
});

test("ukrycie listy zapamiętuje się lokalnie i przeżywa brak storage", async () => {
  renderList();
  fireEvent.click(await screen.findByRole("button", { name: "Ukryj listę" }));

  await waitFor(() => expect(screen.queryByText("Na start")).toBeNull());
  expect(localStorage.getItem("saas-core.getting-started.hidden")).toBe("1");

  // A browser that refuses storage still renders the list, it just forgets.
  const failing = vi
    .spyOn(Storage.prototype, "getItem")
    .mockImplementation(() => {
      throw new Error("storage disabled");
    });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage disabled");
  });
  renderList();
  expect(await screen.findByText("Gotowe 0 z 7")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ukryj listę" }));
  await waitFor(() => expect(screen.queryByText("Na start")).toBeNull());
  failing.mockRestore();
});

test("a list already done folds to one line on any device and opens on demand", async () => {
  api.getCustomerBillingOverview.mockResolvedValue({ subscription: {} });
  api.getBookingSetup.mockResolvedValue({ services: [{ id: "offer" }] });
  api.listBookingAppointments.mockResolvedValue([{ id: "visit" }]);
  api.listMemberships.mockResolvedValue([{ id: "me" }, { id: "you" }]);
  renderList(
    access({
      modules: ["core.organizations", "shared.billing", "shared.booking"],
    }),
    englishMessages,
    "en",
  );
  // Derived from data, so a new browser folds it too (UX-022).
  expect(
    await screen.findByText("Getting started: 4 of 4 done"),
  ).toBeInTheDocument();
  expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "Show" }));
  expect(screen.getAllByRole("listitem")).toHaveLength(4);
});

test("an organization type with ready-made services of its own is not sent to the presets", async () => {
  types.templates = [
    { key: "trim", label: { pl: "Korekcja", en: "Trimming" } },
  ];
  renderList(
    access({
      modules: ["core.organizations", "shared.billing", "shared.booking"],
    }),
  );

  expect(await screen.findByText("Gotowe 0 z 3")).toBeInTheDocument();
  expect(screen.queryByText("Ustaw pierwszą ofertę")).toBeNull();
  expect(api.getBookingSetup).not.toHaveBeenCalled();
});
