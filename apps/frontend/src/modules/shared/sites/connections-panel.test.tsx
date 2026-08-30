import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { AutomationConnectionsPanel } from "./connections-panel";

const { listAutomationConnections, revokeAutomationGrant } = vi.hoisted(() => ({
  listAutomationConnections: vi.fn(),
  revokeAutomationGrant: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  listAutomationConnections,
  revokeAutomationGrant,
}));

const live = {
  grant_id: "019ff20d-c000-7000-8000-000000000001",
  credential_id: "019ff20d-c000-7000-8000-000000000002",
  mode: "draft_write",
  scope: {
    kind: "site",
    id: "019ff20d-c000-7000-8000-000000000003",
    name: "kkk",
  },
  expires_at: "2026-09-30T10:00:00Z",
  revoked_at: null,
  active: true,
  max_changes_per_day: 25,
  max_payload_bytes: 100000,
  window_start: "07:00:00",
  window_end: "18:00:00",
  last_activity_at: "2026-08-29T21:15:00Z",
};
const revoked = {
  ...live,
  grant_id: "019ff20d-c000-7000-8000-000000000004",
  credential_id: "019ff20d-c000-7000-8000-000000000005",
  mode: "autonomous",
  scope: {
    kind: "collection",
    id: "019ff20d-c000-7000-8000-000000000006",
    name: "aktualnosci",
  },
  revoked_at: "2026-08-20T08:00:00Z",
  active: false,
  last_activity_at: null,
};
const expired = {
  ...live,
  grant_id: "019ff20d-c000-7000-8000-000000000007",
  credential_id: "019ff20d-c000-7000-8000-000000000008",
  mode: "suggest_only",
  scope: {
    kind: "collection",
    id: "019ff20d-c000-7000-8000-000000000009",
    name: "poradnik",
  },
  expires_at: "2026-08-01T10:00:00Z",
  revoked_at: null,
  active: false,
  last_activity_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  listAutomationConnections.mockResolvedValue([live, revoked, expired]);
  revokeAutomationGrant.mockResolvedValue([
    { ...live, revoked_at: "2026-08-30T09:00:00Z", active: false },
    revoked,
    expired,
  ]);
});

afterEach(cleanup);

function renderPanel() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <AutomationConnectionsPanel />
    </NextIntlClientProvider>,
  );
}

test("pokazuje zakres, granice i ostatnią aktywność każdego połączenia", async () => {
  const rendered = renderPanel();

  expect(await screen.findByText(live.credential_id)).not.toBeNull();
  expect(screen.getByText("Zapisywanie szkiców")).not.toBeNull();
  expect(screen.getByText("kkk")).not.toBeNull();
  // A revoked grant stays on the list: "who had access last month" is a
  // question the panel has to answer.
  expect(screen.getByText(revoked.credential_id)).not.toBeNull();
  expect(screen.getByText("Odwołane")).not.toBeNull();
  expect(screen.getByText(expired.credential_id)).not.toBeNull();
  expect(screen.getByText("Wygasłe")).not.toBeNull();
  expect(screen.getByText("aktualnosci")).not.toBeNull();
  expect(screen.getByText("poradnik")).not.toBeNull();
  expect(screen.getAllByText("Brak aktywności")).toHaveLength(2);
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("nie proponuje odwołania grantu, który już nie działa", async () => {
  renderPanel();
  await screen.findByText(live.credential_id);

  // One button, for the one live connection — offering it on a revoked grant
  // would suggest there is something left to stop.
  expect(
    screen.getAllByRole("button", { name: /Awaryjnie odwołaj dostęp/ }),
  ).toHaveLength(1);
});

test("odcina połączenie dopiero po podaniu powodu", async () => {
  const rendered = renderPanel();
  await screen.findByText(live.credential_id);
  fireEvent.click(
    screen.getByRole("button", { name: /Awaryjnie odwołaj dostęp/ }),
  );

  const submit = await screen.findByRole("button", {
    name: /Odwołaj dostęp natychmiast/,
  });
  const reason = screen.getByLabelText("Powód awaryjnego odwołania");
  await waitFor(() => expect(reason).toHaveFocus());
  expect(
    screen.getByText(/natychmiast i nieodwracalnie zatrzyma/),
  ).not.toBeNull();
  expect((await axe.run(document.body)).violations).toHaveLength(0);
  // An emergency stop nobody wrote a reason for is one nobody can explain a
  // week later, so the action stays out of reach until there is one.
  expect(submit.hasAttribute("disabled")).toBe(true);
  fireEvent.submit(reason.closest("form")!);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Wpisz powód odwołania dostępu.",
  );
  expect(revokeAutomationGrant).not.toHaveBeenCalled();

  fireEvent.change(reason, {
    target: { value: "Klucz zaczął pisać w nocy poza oknem." },
  });
  // The form watches the field, so the button becomes reachable a render later
  // rather than in the same tick as the keystroke.
  await waitFor(() => expect(submit.hasAttribute("disabled")).toBe(false));
  fireEvent.click(submit);

  await waitFor(() => expect(revokeAutomationGrant).toHaveBeenCalledOnce());
  expect(revokeAutomationGrant.mock.calls[0]?.[0]).toBe(live.grant_id);
  expect(revokeAutomationGrant.mock.calls[0]?.[1]).toBe(
    "Klucz zaczął pisać w nocy poza oknem.",
  );
  // The whole list comes back, so the screen cannot show a stale row beside
  // the one it just changed.
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /Awaryjnie odwołaj dostęp/ }),
    ).toBeNull(),
  );
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("ogłasza błąd odwołania i pozostawia dialog otwarty do ponowienia", async () => {
  listAutomationConnections.mockResolvedValueOnce([live]);
  revokeAutomationGrant.mockRejectedValueOnce(new Error("offline"));
  renderPanel();

  fireEvent.click(
    await screen.findByRole("button", {
      name: /Awaryjnie odwołaj dostęp/,
    }),
  );
  fireEvent.change(await screen.findByLabelText("Powód awaryjnego odwołania"), {
    target: { value: "Podejrzenie incydentu." },
  });
  const submit = screen.getByRole("button", {
    name: /Odwołaj dostęp natychmiast/,
  });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);

  // A failed emergency stop must remain visible; otherwise the operator could
  // reasonably believe the credential was already blocked.
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /Nie udało się wykonać operacji/,
  );
  expect(screen.getByRole("dialog")).not.toBeNull();
});

test("po Escape przywraca fokus na przycisku awaryjnego odwołania", async () => {
  listAutomationConnections.mockResolvedValueOnce([live]);
  renderPanel();

  const trigger = await screen.findByRole("button", {
    name: /Awaryjnie odwołaj dostęp/,
  });
  trigger.focus();
  fireEvent.click(trigger);
  await screen.findByRole("dialog");

  // Returning focus preserves the operator's place after abandoning a
  // destructive action with the keyboard.
  fireEvent.keyDown(document, { key: "Escape" });
  await waitFor(() => expect(trigger).toHaveFocus());
  expect(screen.queryByRole("dialog")).toBeNull();
});
