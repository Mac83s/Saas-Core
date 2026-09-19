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
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { TeamPanel } from "./team-panel";

const { api, router } = vi.hoisted(() => ({
  api: {
    listMemberships: vi.fn(),
    listInvitations: vi.fn(),
    listRoles: vi.fn(),
    createInvitation: vi.fn(),
    revokeInvitation: vi.fn(),
    updateMembership: vi.fn(),
    transferOwnership: vi.fn(),
  },
  router: { replace: vi.fn(), refresh: vi.fn() },
}));
vi.mock("#i18n/navigation", () => ({ useRouter: () => router }));
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
const staff = [...viewer, "organization.members.read"];
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
  role: string,
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
    role,
    status: "active",
    joined_at: "2026-08-10T12:00:00Z",
  };
}

function organization(
  role: string,
  permissions: string[],
): OrganizationSummary {
  return {
    id: "019c5f87-fce8-739b-b960-b7a195bfc298",
    name: "Acme",
    slug: "acme",
    workspace_kind: "business",
    organization_type: "business",
    status: "active",
    default_locale: "pl",
    timezone: "Europe/Warsaw",
    currency: "PLN",
    version: 1,
    membership_status: "active",
    role,
    permissions,
    active: true,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listMemberships.mockResolvedValue([
    member("owner", "owner", "ola@example.com", "Ola", "Kowalska"),
    member("anna", "admin", "anna@example.com", "Anna", "Nowak"),
    member("piotr", "staff", "piotr@example.com"),
  ]);
  api.listInvitations.mockResolvedValue([
    {
      id: "invitation-pending",
      email: "nowy@example.com",
      role: "staff",
      status: "pending",
      expires_at: "2026-09-26T10:00:00Z",
      created_at: "2026-09-19T10:00:00Z",
    },
    {
      id: "invitation-expired",
      email: "stary@example.com",
      role: "viewer",
      status: "expired",
      expires_at: "2026-09-01T10:00:00Z",
      created_at: "2026-08-25T10:00:00Z",
    },
    {
      // Accepted: the person is a member already, not an invitation.
      id: "invitation-accepted",
      email: "anna@example.com",
      role: "admin",
      status: "accepted",
      expires_at: "2026-08-17T10:00:00Z",
      created_at: "2026-08-10T10:00:00Z",
    },
  ]);
  api.listRoles.mockResolvedValue({
    roles: [
      role("admin", admin),
      role("manager", manager),
      role("owner", owner),
      role("staff", staff, true),
      role("viewer", viewer, true),
      {
        ...role("custom-1a2b", [
          "organization.read",
          "booking.appointment.read",
          "booking.appointment.manage",
        ]),
        name: "Biuro",
        scope: "organization" as const,
      },
    ],
    grantable_permissions: manager,
  });
  api.createInvitation.mockResolvedValue({});
  api.revokeInvitation.mockResolvedValue(undefined);
  api.updateMembership.mockResolvedValue({});
  api.transferOwnership.mockResolvedValue(undefined);
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
      <TeamPanel organization={current} userId={userId} />
    </NextIntlClientProvider>,
  );
}

async function openRowAction(person: string, action: string) {
  const trigger = await screen.findByRole("button", {
    name: `Działania: ${person}`,
  });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("menuitem", { name: action }));
  return trigger;
}

test("pokazuje członków, zaproszenia i opis każdej roli", async () => {
  const { container } = renderPanel();

  const table = await screen.findByRole("table", {
    name: "Członkowie zespołu i zaproszenia",
  });
  const rows = within(table).getAllByRole("row");
  // Header, three members, two open invitations; the accepted one is a member.
  expect(rows).toHaveLength(6);
  expect(within(rows[1]).getByText("Ola Kowalska")).toBeInTheDocument();
  expect(within(rows[1]).getByText("(Ty)")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Właściciel")).toBeInTheDocument();
  // Nobody changes their own membership, so the owner's row has no menu.
  expect(within(rows[1]).queryByRole("button")).toBeNull();
  expect(within(rows[2]).getByText("anna@example.com")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Aktywny")).toBeInTheDocument();
  expect(within(rows[4]).getByText("Zaproszony")).toBeInTheDocument();
  expect(within(rows[5]).getByText("Wygasło")).toBeInTheDocument();

  // Descriptions come from permissions, own roles included.
  expect(screen.getByText("Pełny dostęp do wszystkiego.")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Podgląd: kalendarz i wizyty, zespół. Bez dostępu: ustawienia organizacji, abonament i płatności.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Biuro")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Edycja: kalendarz i wizyty. Bez dostępu: zespół, ustawienia organizacji, abonament i płatności.",
    ),
  ).toBeInTheDocument();

  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});

test("zaprasza osobę z rolą roboczą jako domyślną", async () => {
  renderPanel();

  fireEvent.click(await screen.findByRole("button", { name: "Zaproś osobę" }));
  const dialog = await screen.findByRole("dialog", { name: "Zaproś osobę" });
  const select = within(dialog).getByLabelText("Rola") as HTMLSelectElement;
  expect(select.value).toBe("staff");
  expect(select).toHaveAccessibleDescription(
    "Podgląd: kalendarz i wizyty, zespół. Bez dostępu: ustawienia organizacji, abonament i płatności.",
  );
  expect(
    within(select)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Administrator", "Menedżer", "Pracownik", "Podgląd", "Biuro"]);
  const results = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);

  api.createInvitation.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "invitation_conflict",
      detail:
        "Dla tego adresu istnieje już aktywne zaproszenie lub membership.",
      correlation_id: null,
    }),
  );
  fireEvent.change(within(dialog).getByLabelText("E-mail"), {
    target: { value: "ewa@example.com" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Wyślij zaproszenie" }),
  );
  expect(
    await within(dialog).findByText(
      "Ta osoba jest już w zespole albo ma ważne zaproszenie.",
    ),
  ).toBeInTheDocument();

  fireEvent.click(
    within(dialog).getByRole("button", { name: "Wyślij zaproszenie" }),
  );
  await waitFor(() =>
    expect(api.createInvitation).toHaveBeenLastCalledWith({
      email: "ewa@example.com",
      role: "staff",
    }),
  );
  expect(
    await screen.findByText("Wysłano zaproszenie: ewa@example.com."),
  ).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(api.listMemberships).toHaveBeenCalledTimes(2);
});

test("zmienia rolę i usuwa z zespołu po potwierdzeniu", async () => {
  renderPanel();

  const trigger = await openRowAction("Anna Nowak", "Zmień rolę");
  let dialog = await screen.findByRole("dialog", {
    name: "Zmień rolę: Anna Nowak",
  });
  const submit = within(dialog).getByRole("button", { name: "Zmień rolę" });
  expect(submit).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText("Nowa rola"), {
    target: { value: "manager" },
  });
  fireEvent.click(submit);
  await waitFor(() =>
    expect(api.updateMembership).toHaveBeenCalledWith("anna", {
      role: "manager",
    }),
  );
  expect(
    await screen.findByText("Zmieniono rolę: Anna Nowak."),
  ).toBeInTheDocument();
  await waitFor(() => expect(trigger).toHaveFocus());

  await openRowAction("piotr@example.com", "Usuń z zespołu");
  dialog = await screen.findByRole("dialog", {
    name: "Usunąć z zespołu: piotr@example.com?",
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Usuń z zespołu" }),
  );
  await waitFor(() =>
    expect(api.updateMembership).toHaveBeenCalledWith("piotr", {
      status: "revoked",
    }),
  );
});

test("przekazanie organizacji to osobna akcja z ostrzeżeniem", async () => {
  renderPanel();

  await openRowAction("Anna Nowak", "Przekaż organizację");
  const dialog = await screen.findByRole("dialog", {
    name: "Przekazać organizację?",
  });
  expect(dialog).toHaveTextContent(
    "Anna Nowak przejmie rolę „Właściciel” i pełną kontrolę nad organizacją Acme.",
  );
  expect(dialog).toHaveTextContent("Twoja rola zmieni się na „Administrator”.");
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

  await openRowAction("stary@example.com", "Wyślij ponownie");
  await waitFor(() =>
    expect(api.createInvitation).toHaveBeenCalledWith({
      email: "stary@example.com",
      role: "viewer",
    }),
  );
  await openRowAction("nowy@example.com", "Cofnij zaproszenie");
  await waitFor(() =>
    expect(api.revokeInvitation).toHaveBeenCalledWith("invitation-pending"),
  );
  // A pending invitation cannot be sent twice (one per address); the API
  // has no resend, so only revoking is offered.
  fireEvent.click(
    screen.getByRole("button", { name: "Działania: nowy@example.com" }),
  );
  expect(await screen.findAllByRole("menuitem")).toHaveLength(1);
});

test("menedżer zarządza tylko rolami ograniczonymi, bez przekazania (EN)", async () => {
  api.listMemberships.mockResolvedValue([
    member("owner", "owner", "ola@example.com", "Ola", "Kowalska"),
    member("anna", "admin", "anna@example.com", "Anna", "Nowak"),
    member("piotr", "staff", "piotr@example.com"),
    member("marek", "manager", "marek@example.com", "Marek", "Lis"),
  ]);
  renderPanel(organization("manager", manager), "user-marek", "en");

  expect(await screen.findByText("People in the team")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Actions: Anna Nowak" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "New role" })).toBeNull();

  fireEvent.click(
    screen.getByRole("button", { name: "Actions: piotr@example.com" }),
  );
  expect(
    (await screen.findAllByRole("menuitem")).map((item) => item.textContent),
  ).toEqual(["Change role", "Remove from team"]);
  fireEvent.keyDown(document.activeElement ?? document.body, {
    key: "Escape",
  });

  fireEvent.click(screen.getByRole("button", { name: "Invite person" }));
  const dialog = await screen.findByRole("dialog", { name: "Invite person" });
  expect(
    within(within(dialog).getByLabelText("Role"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Staff", "Viewer"]);
});

test("bez podglądu zespołu mówi o braku dostępu i nic nie pobiera", () => {
  renderPanel(organization("viewer", viewer), "user-viewer");

  expect(screen.getByText("Brak dostępu do zespołu")).toBeInTheDocument();
  expect(api.listMemberships).not.toHaveBeenCalled();
});
