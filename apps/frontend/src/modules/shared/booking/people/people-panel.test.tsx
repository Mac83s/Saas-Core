import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type OrganizationSummary,
} from "@saas-core/api-client";

import englishMessages from "../../../../../messages/en.json";
import polishMessages from "../../../../../messages/pl.json";
import type { PanelAccess } from "#lib/panel-navigation";
import { PeoplePanel } from "./people-panel";

const { api, router } = vi.hoisted(() => ({
  api: {
    addPerson: vi.fn(),
    addTimeOff: vi.fn(),
    createInvitation: vi.fn(),
    endPerson: vi.fn(),
    getBookingCatalog: vi.fn(),
    getPeopleDay: vi.fn(),
    getSeatUsage: vi.fn(),
    invitePerson: vi.fn(),
    listInvitations: vi.fn(),
    listMemberships: vi.fn(),
    listPeople: vi.fn(),
    listRoles: vi.fn(),
    restorePerson: vi.fn(),
    revokeInvitation: vi.fn(),
    transferOwnership: vi.fn(),
    updateMembership: vi.fn(),
    updatePerson: vi.fn(),
    setPersonServices: vi.fn(),
  },
  router: { replace: vi.fn(), refresh: vi.fn() },
}));
vi.mock("#i18n/navigation", () => ({ Link: "a", useRouter: () => router }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

// Core's global roles (saas_core.modules.core.organizations.permissions).
const viewer = [
  "organization.read",
  "notifications.preferences",
  "booking.appointment.read",
];
const staff = [...viewer, "organization.members.read", "booking.schedule.own"];
const manager = [
  ...staff,
  "organization.members.manage_limited",
  "booking.appointment.manage",
];
const admin = [
  ...manager,
  "organization.members.manage",
  "organization.settings.manage",
];
const owner = [
  ...admin,
  "organization.billing.manage",
  "organization.ownership.transfer",
  "organization.archive",
];

const SERVICE = "0199c5f8-0000-7000-8000-000000000001";
const PLACE = "0199c5f8-0000-7000-8000-000000000002";

function role(key: string, permissions: string[], limited = false) {
  return {
    key,
    name: key,
    scope: "system" as const,
    permissions,
    limited,
    version: 1,
  };
}

function member(
  id: string,
  roleKey: string,
  email: string,
  first_name = "",
  last_name = "",
) {
  return {
    id,
    user_id: `user-${id}`,
    email,
    first_name,
    last_name,
    role: roleKey,
    status: "active",
    joined_at: "2025-03-10T12:00:00Z",
    revoked_at: null,
  };
}

function person(id: string, name: string, over: Record<string, unknown> = {}) {
  return {
    id,
    name,
    public_slug: id,
    membership_id: null,
    invitation_id: null,
    phone: null,
    active: true,
    service_ids: [SERVICE],
    has_hours: true,
    created_at: "2025-03-10T12:00:00Z",
    ...over,
  };
}

function organization(
  roleKey: string,
  permissions: string[],
): OrganizationSummary {
  return {
    id: "019c5f87-fce8-739b-b960-b7a195bfc298",
    name: "Korekcja Racic Wójcik",
    slug: "wojcik",
    workspace_kind: "business",
    organization_type: "business",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role: roleKey,
    permissions,
    active: true,
  };
}

function accessOf(current: OrganizationSummary): PanelAccess {
  return {
    modules: ["shared.booking"],
    permissions: current.permissions,
    isOwner: current.role === "owner",
    limited: false,
    organizationType: current.organization_type,
  };
}

const problem = (status: number, code: string, detail = "Nie.") =>
  new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail,
    correlation_id: null,
  });

beforeEach(() => {
  vi.clearAllMocks();
  // 10:30 in Warsaw: Marcin is on a visit, Krzysztof starts at 13:00.
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-09-24T08:30:00Z"));
  api.listMemberships.mockResolvedValue([
    member("owner", "owner", "jan@example.com", "Jan", "Wójcik"),
    member("anna", "admin", "anna@example.com", "Anna", "Lewandowska"),
    member("marcin", "staff", "marcin@example.com", "Marcin", "Kowalski"),
  ]);
  api.listInvitations.mockResolvedValue([
    {
      id: "invitation-kamil",
      email: "kamil@example.com",
      role: "staff",
      status: "pending",
      expires_at: "2026-10-01T10:00:00Z",
      created_at: "2026-09-24T07:00:00Z",
    },
    {
      id: "invitation-old",
      email: "stary@example.com",
      role: "viewer",
      status: "expired",
      expires_at: "2026-09-01T10:00:00Z",
      created_at: "2026-08-25T10:00:00Z",
    },
  ]);
  api.listRoles.mockResolvedValue({
    roles: [
      role("owner", owner),
      role("admin", admin),
      role("manager", manager),
      role("staff", staff, true),
      role("viewer", viewer, true),
      {
        ...role("custom-brygadzista", [
          "organization.read",
          "booking.appointment.read",
          "booking.appointment.manage",
        ]),
        name: "Brygadzista",
        scope: "organization" as const,
      },
    ],
    grantable_permissions: manager,
  });
  api.getSeatUsage.mockResolvedValue({ used: 4, limit: 25 });
  api.getBookingCatalog.mockResolvedValue({
    locations: [{ id: PLACE, name: "Baza", public_slug: "baza" }],
    staff: [],
    services: [
      {
        id: SERVICE,
        name: "Korekcja stada",
        public_slug: "korekcja",
        duration_minutes: 120,
        appointment_kind: "",
      },
    ],
    resources: [],
  });
  api.listPeople.mockResolvedValue([
    person("s-marcin", "Marcin Kowalski", {
      membership_id: "marcin",
      phone: "601 234 567",
    }),
    person("s-kamil", "Kamil Duda", {
      invitation_id: "invitation-kamil",
      has_hours: false,
      service_ids: [],
    }),
    person("s-krzysztof", "Krzysztof Nowak", { phone: "604 567 890" }),
  ]);
  api.getPeopleDay.mockResolvedValue({
    date: "2026-09-24",
    timezone: "Europe/Warsaw",
    items: [
      {
        staff_id: "s-marcin",
        works: [
          {
            starts_at: "2026-09-24T04:00:00Z",
            ends_at: "2026-09-24T14:00:00Z",
          },
        ],
        time_off: [],
        busy: [
          {
            starts_at: "2026-09-24T06:00:00Z",
            ends_at: "2026-09-24T10:00:00Z",
          },
        ],
      },
      {
        staff_id: "s-krzysztof",
        works: [
          {
            starts_at: "2026-09-24T11:00:00Z",
            ends_at: "2026-09-24T16:00:00Z",
          },
        ],
        time_off: [],
        busy: [],
      },
    ],
  });
  api.addPerson.mockResolvedValue({});
  api.createInvitation.mockResolvedValue({});
  api.updateMembership.mockResolvedValue({});
  api.endPerson.mockResolvedValue({});
  api.revokeInvitation.mockResolvedValue(undefined);
  api.transferOwnership.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function renderPanel(
  current = organization("owner", owner),
  userId = "user-owner",
  locale: "pl" | "en" = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <PeoplePanel
        access={accessOf(current)}
        organization={current}
        userId={userId}
      />
    </NextIntlClientProvider>,
  );
}

async function openRowAction(name: string, action: string) {
  const trigger = await screen.findByRole("button", {
    name: `Więcej akcji: ${name}`,
  });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("menuitem", { name: action }));
  return trigger;
}

async function expectAccessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

test("jedna lista ludzi: z kontem i bez, rola, konto i to, co robią dziś", async () => {
  const { container } = renderPanel();
  const table = await screen.findByRole("table", { name: "Pracownicy firmy" });
  const rows = within(table).getAllByRole("row").slice(1);
  // You first, then the office, the people with an account, without one, and
  // those still invited — the order of the plan's board 1.
  expect(rows.map((row) => row.querySelector("td")?.textContent)).toEqual([
    "Jan Wójcik (Ty)jan@example.com",
    "Anna Lewandowskaanna@example.com",
    "Marcin Kowalski601 234 567",
    "Krzysztof Nowak604 567 890",
    "Kamil Dudakamil@example.com",
    "stary@example.com",
  ]);
  // Management roles say so; an account without a calendar entry has a card too.
  expect(within(rows[0]).getByText("Zarządza")).toBeInTheDocument();
  expect(
    within(rows[0]).getByRole("link", { name: "Jan Wójcik" }),
  ).toHaveAttribute("href", "/panel/team/owner");
  const marcin = within(rows[2]);
  expect(marcin.getByRole("link", { name: "Marcin Kowalski" })).toHaveAttribute(
    "href",
    "/panel/team/s-marcin",
  );
  expect(marcin.getByText("Konto aktywne")).toBeInTheDocument();
  expect(marcin.getByText("Na wizycie do 12:00")).toBeInTheDocument();
  expect(
    marcin.getByRole("link", { name: "Zadzwoń: Marcin Kowalski" }),
  ).toHaveAttribute("href", "tel:601234567");
  expect(within(rows[3]).getByText("Bez konta")).toBeInTheDocument();
  expect(within(rows[3]).getByText("Wolne od 13:00")).toBeInTheDocument();
  expect(
    within(rows[4]).getByText(/Zaproszenie · ważne do/),
  ).toBeInTheDocument();
  expect(within(rows[4]).getByText("Nie przyjmuje wizyt")).toBeInTheDocument();
  expect(within(rows[5]).getByText("Zaproszenie wygasło")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Konta w planie: 4 z 25 · pracownicy bez konta nie wliczają się do limitu",
    ),
  ).toBeInTheDocument();
  await expectAccessible(container);
});

test("filtry: byli pracownicy osobno od stanu konta", async () => {
  api.listMemberships.mockResolvedValue([
    member("owner", "owner", "jan@example.com", "Jan", "Wójcik"),
    member("marcin", "staff", "marcin@example.com", "Marcin", "Kowalski"),
    {
      ...member("gone", "staff", "byly@example.com", "Piotr", "Były"),
      status: "revoked",
      revoked_at: "2026-06-30T10:00:00Z",
    },
  ]);
  renderPanel();
  await screen.findByRole("table", { name: "Pracownicy firmy" });
  expect(screen.queryByText("Piotr Były")).toBeNull();
  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "former" },
  });
  expect(await screen.findByText("Piotr Były")).toBeInTheDocument();
  expect(screen.getByText(/W firmie do 30 cze 2026/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Pokaż"), {
    target: { value: "current" },
  });
  fireEvent.change(screen.getByLabelText("Konto"), {
    target: { value: "none" },
  });
  const table = screen.getByRole("table", { name: "Pracownicy firmy" });
  expect(
    within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.querySelector("td")?.textContent),
  ).toEqual(["Krzysztof Nowak604 567 890"]);
  // Former management data is asked for: management may see it (ADR-058 §9).
  expect(api.listMemberships).toHaveBeenCalledWith({ includeFormer: true });
});

test("dodaje podwykonawcę bez konta z usługami i godzinami w jednym kroku", async () => {
  renderPanel();
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj pracownika" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Dodaj pracownika",
  });
  fireEvent.click(within(dialog).getByLabelText(/Bez konta/));
  fireEvent.change(within(dialog).getByLabelText("Imię i nazwisko"), {
    target: { value: "Krzysztof Nowak" },
  });
  fireEvent.change(within(dialog).getByLabelText("Telefon"), {
    target: { value: "604 567 890" },
  });
  // One service: already chosen; Monday to Friday, 8 to 16 by default.
  expect(within(dialog).getByLabelText("Korekcja stada")).toBeChecked();
  fireEvent.click(within(dialog).getByRole("button", { name: "Piątek" }));
  fireEvent.change(within(dialog).getByLabelText("Od"), {
    target: { value: "06:00" },
  });
  await expectAccessible(dialog);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj pracownika" }),
  );
  await waitFor(() =>
    expect(api.addPerson).toHaveBeenCalledWith({
      name: "Krzysztof Nowak",
      phone: "604 567 890",
      invitation: null,
      service_ids: [SERVICE],
      hours: {
        weekdays: [0, 1, 2, 3],
        local_start: "06:00",
        local_end: "16:00",
        location_id: PLACE,
      },
      copy_hours_from: null,
    }),
  );
  expect(
    await screen.findByText("Dodano do zespołu: Krzysztof Nowak."),
  ).toBeInTheDocument();
});

test("z kontem: rola robocza domyślnie, zaproszenie i czytelny konflikt", async () => {
  renderPanel();
  fireEvent.click(
    await screen.findByRole("button", { name: "Dodaj pracownika" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Dodaj pracownika",
  });
  const select = within(dialog).getByLabelText("Rola") as HTMLSelectElement;
  expect(select.value).toBe("staff");
  // Management first, own roles by what they do: Brygadzista assigns visits.
  expect(
    within(select)
      .getAllByRole("group")
      .map((group) => group.getAttribute("label")),
  ).toEqual(["Zarządzanie", "Praca"]);
  expect(
    within(select)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual([
    "Administrator",
    "Menedżer",
    "Brygadzista",
    "Pracownik",
    "Podgląd",
  ]);
  expect(
    within(dialog).getByText("Konta w planie: 5 z 25 po wysłaniu zaproszenia."),
  ).toBeInTheDocument();

  api.addPerson.mockRejectedValueOnce(problem(409, "invitation_conflict"));
  fireEvent.change(within(dialog).getByLabelText("Imię i nazwisko"), {
    target: { value: "Kamil Duda" },
  });
  fireEvent.change(within(dialog).getByLabelText("E-mail"), {
    target: { value: "kamil@example.com" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj i wyślij zaproszenie" }),
  );
  expect(
    await within(dialog).findByText(
      "Ta osoba jest już w zespole albo ma ważne zaproszenie.",
    ),
  ).toBeInTheDocument();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj i wyślij zaproszenie" }),
  );
  await waitFor(() =>
    expect(api.addPerson).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Kamil Duda",
        invitation: { email: "kamil@example.com", role: "staff" },
        service_ids: [SERVICE],
      }),
    ),
  );
  expect(
    await screen.findByText("Wysłano zaproszenie: kamil@example.com."),
  ).toBeInTheDocument();
});

test("zmiana roli w grupach Zarządzanie i Praca działa od razu", async () => {
  renderPanel();
  const trigger = await openRowAction("Anna Lewandowska", "Zmień rolę…");
  const dialog = await screen.findByRole("dialog", {
    name: "Zmień rolę: Anna Lewandowska",
  });
  expect(
    within(dialog)
      .getAllByRole("group")
      .map((group) => group.querySelector("legend")?.textContent),
  ).toEqual(["Zarządzanie", "Praca"]);
  expect(
    within(dialog).getByText(
      "Zmiana działa od razu — nowe pozycje w menu pojawią się po odświeżeniu.",
    ),
  ).toBeInTheDocument();
  const submit = within(dialog).getByRole("button", { name: "Zmień rolę" });
  expect(submit).toBeDisabled();
  fireEvent.click(within(dialog).getByLabelText(/Menedżer/));
  fireEvent.click(submit);
  await waitFor(() =>
    expect(api.updateMembership).toHaveBeenCalledWith("anna", {
      role: "manager",
    }),
  );
  expect(
    await screen.findByText("Zmieniono rolę: Anna Lewandowska."),
  ).toBeInTheDocument();
  await waitFor(() => expect(trigger).toHaveFocus());
});

test("usunięcie z firmy czeka na przeniesienie wizyt", async () => {
  renderPanel();
  await openRowAction("Marcin Kowalski", "Usuń z firmy…");
  const dialog = await screen.findByRole("dialog", {
    name: "Usunąć z firmy: Marcin Kowalski?",
  });
  expect(
    within(dialog).getByRole("link", { name: "Pokaż jej wizyty w kalendarzu" }),
  ).toHaveAttribute("href", "/panel/calendar?view=list&staff=s-marcin");
  api.endPerson.mockRejectedValueOnce(
    problem(
      409,
      "staff_has_upcoming_appointments",
      "Marcin Kowalski prowadzi zaplanowane wizyty (2). Przenieś je w kalendarzu, zanim zakończysz współpracę.",
    ),
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń z firmy" }));
  expect(
    await within(dialog).findByText(/prowadzi zaplanowane wizyty \(2\)/),
  ).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button", { name: "Usuń z firmy" }));
  await waitFor(() => expect(api.endPerson).toHaveBeenCalledTimes(2));
  expect(
    await screen.findByText("Marcin Kowalski nie pracuje już w firmie."),
  ).toBeInTheDocument();
});

test("przekazanie organizacji to osobna akcja z ostrzeżeniem", async () => {
  renderPanel();
  await openRowAction("Anna Lewandowska", "Przekaż organizację");
  const dialog = await screen.findByRole("dialog", {
    name: "Przekazać organizację?",
  });
  expect(dialog).toHaveTextContent(
    "Po przekazaniu oboje zostaniecie wylogowani.",
  );
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Tak, przekaż organizację" }),
  );
  await waitFor(() =>
    expect(api.transferOwnership).toHaveBeenCalledWith("anna"),
  );
  expect(router.replace).toHaveBeenCalledWith("/login");
});

test("zaproszenie wygasłe wysyła się ponownie, oczekujące cofa", async () => {
  renderPanel();
  await openRowAction("stary@example.com", "Wyślij zaproszenie ponownie");
  await waitFor(() =>
    expect(api.createInvitation).toHaveBeenCalledWith({
      email: "stary@example.com",
      role: "viewer",
    }),
  );
  await openRowAction("Kamil Duda", "Cofnij zaproszenie");
  await waitFor(() =>
    expect(api.revokeInvitation).toHaveBeenCalledWith("invitation-kamil"),
  );
});

test("menedżer zarządza tylko rolami ograniczonymi, bez przekazania (EN)", async () => {
  api.listMemberships.mockResolvedValue([
    member("owner", "owner", "jan@example.com", "Jan", "Wójcik"),
    member("anna", "admin", "anna@example.com", "Anna", "Lewandowska"),
    member("marcin", "staff", "marcin@example.com", "Marcin", "Kowalski"),
    member("marek", "manager", "marek@example.com", "Marek", "Lis"),
  ]);
  renderPanel(organization("manager", manager), "user-marek", "en");
  fireEvent.click(
    await screen.findByRole("button", {
      name: "More actions: Anna Lewandowska",
    }),
  );
  const items = (await screen.findAllByRole("menuitem")).map(
    (item) => item.textContent,
  );
  expect(items).not.toContain("Change role…");
  expect(items).not.toContain("Remove from the company…");
  expect(items).not.toContain("Transfer the organization");
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

  fireEvent.click(screen.getByRole("button", { name: "Add a person" }));
  const dialog = await screen.findByRole("dialog", { name: "Add a person" });
  expect(
    within(within(dialog).getByLabelText("Role"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Staff", "Viewer"]);
});

test("bez kalendarza w planie: lista kont i samo zaproszenie", async () => {
  api.getBookingCatalog.mockRejectedValue(problem(403, "entitlement_required"));
  renderPanel();
  const table = await screen.findByRole("table", { name: "Pracownicy firmy" });
  expect(
    within(table).queryByRole("columnheader", { name: "Dziś" }),
  ).toBeNull();
  expect(within(table).getByText("Marcin Kowalski")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Dodaj pracownika" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Dodaj pracownika",
  });
  expect(within(dialog).queryByLabelText("Imię i nazwisko")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("E-mail"), {
    target: { value: "ewa@example.com" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj i wyślij zaproszenie" }),
  );
  await waitFor(() =>
    expect(api.createInvitation).toHaveBeenCalledWith({
      email: "ewa@example.com",
      role: "staff",
    }),
  );
  expect(api.addPerson).not.toHaveBeenCalled();
});

test("bez podglądu zespołu mówi o braku dostępu i nic nie pobiera", () => {
  renderPanel(organization("viewer", viewer), "user-viewer");
  expect(
    screen.getByText(/Listę osób i ich role widzą tylko osoby z dostępem/),
  ).toBeInTheDocument();
  expect(api.listMemberships).not.toHaveBeenCalled();
});

test("the list is accessible in English too", async () => {
  const { container } = renderPanel(
    organization("owner", owner),
    "user-owner",
    "en",
  );
  await screen.findByRole("table", { name: "The company's people" });
  expect(screen.getByText("On a visit until 12:00")).toBeInTheDocument();
  await expectAccessible(container);
});
