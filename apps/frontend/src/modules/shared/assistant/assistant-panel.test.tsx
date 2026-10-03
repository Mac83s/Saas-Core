import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type {
  AssistantConversation,
  AssistantOffer,
  AssistantTurn,
  CommandConsent,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { AssistantPanel } from "./assistant-panel";

const api = vi.hoisted(() => ({
  getAssistantOffer: vi.fn(),
  listAssistantConversations: vi.fn(),
  getAssistantConversation: vi.fn(),
  startAssistantConversation: vi.fn(),
  sendAssistantMessage: vi.fn(),
  answerAssistantConsent: vi.fn(),
  getCommandConsent: vi.fn(),
  grantCommandConsent: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const OFFER: AssistantOffer = {
  available: true,
  reasons: [],
  in_plan: true,
  credits_per_message: 1,
  max_message_characters: 4000,
};

function turn(extra: Partial<AssistantTurn>): AssistantTurn {
  return {
    id: "t1",
    state: "done",
    failure_code: "",
    created_at: "2026-10-03T10:00:00Z",
    text: "Jak nazywa się firma?",
    items: [],
    consents: [],
    ...extra,
  };
}

function conversation(...turns: AssistantTurn[]): AssistantConversation {
  return {
    id: "c1",
    title: "",
    language: "pl",
    created_at: "2026-10-03T10:00:00Z",
    updated_at: "2026-10-03T10:00:00Z",
    turns,
  };
}

const RENAME = turn({
  state: "awaiting_consent",
  text: "Zmień nazwę",
  items: [
    {
      kind: "action",
      step_id: "s1",
      title: { pl: "Zmień dane firmy", en: "Change company details" },
      risk: "apply",
      status: "pending",
      code: "",
    },
  ],
  consents: [{ id: "s1", digest: "d1", steps: ["s1"] }],
});
const PLAN: CommandConsent = {
  digest: "d1",
  risk: "apply",
  step_up_required: false,
  expires_at: "2026-10-03T10:30:00Z",
  calls: [
    {
      step_id: "s1",
      command: "organization.update@1",
      title: { pl: "Zmień dane firmy", en: "Change company details" },
      summary: { pl: "Dane firmy.", en: "Company details." },
      risk: "apply",
      effects: [
        {
          kind: "updated",
          resource: "organization",
          resource_id: "o1",
          summary: {
            pl: "Nazwa: Studio → Studio Plus",
            en: "Name: Studio → Studio Plus",
          },
        },
      ],
      quote: null,
      person_gates: [],
    },
  ],
};

function view(locale: "pl" | "en" = "pl", canManageBilling = false) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <AssistantPanel canManageBilling={canManageBilling} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getAssistantOffer.mockResolvedValue(OFFER);
  api.listAssistantConversations.mockResolvedValue([]);
  api.startAssistantConversation.mockResolvedValue({ id: "c1" });
  api.sendAssistantMessage.mockResolvedValue(undefined);
  api.answerAssistantConsent.mockResolvedValue(undefined);
});

test("a message starts a conversation and its answer appears, with what was checked", async () => {
  api.getAssistantConversation.mockResolvedValue(
    conversation(
      turn({
        items: [
          {
            kind: "action",
            step_id: "s1",
            title: { pl: "Odczytaj dane firmy", en: "Read the company" },
            risk: "read",
            status: "done",
            code: "",
          },
          { kind: "text", text: "Firma nazywa się Studio Testowe." },
        ],
      }),
    ),
  );
  const { container } = view();

  fireEvent.change(await screen.findByLabelText("Wiadomość do asystenta"), {
    target: { value: "Jak nazywa się firma?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));

  expect(
    await screen.findByText("Firma nazywa się Studio Testowe."),
  ).toBeInTheDocument();
  expect(api.startAssistantConversation).toHaveBeenCalledWith(
    "pl",
    expect.any(String),
  );
  expect(api.sendAssistantMessage).toHaveBeenCalledWith(
    "c1",
    "Jak nazywa się firma?",
    expect.any(String),
  );
  // A read is a quiet line with the command's title — never its key.
  expect(screen.getByText("Odczytaj dane firmy")).toBeInTheDocument();
  expect(container.textContent).not.toContain("organization.");
  expect(screen.getByRole("log")).toBeInTheDocument();
  expect((await axe.run(container)).violations).toEqual([]);
});

test("a proposed change is shown as the server previewed it and runs on the click", async () => {
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation.mockResolvedValue(conversation(RENAME));
  api.getCommandConsent.mockResolvedValue(PLAN);
  api.grantCommandConsent.mockResolvedValue("token-1");
  view();

  // The dialog opens by itself when the plan starts waiting.
  expect(
    await screen.findByRole("heading", { name: "Zgoda na zmiany" }),
  ).toBeInTheDocument();
  expect(
    await screen.findByText("Nazwa: Studio → Studio Plus"),
  ).toBeInTheDocument();
  expect(api.getCommandConsent).toHaveBeenCalledWith("d1");
  // While a plan waits, no new message is taken (the page is behind the dialog).
  expect(
    screen.getByRole("button", { name: "Wyślij", hidden: true }),
  ).toBeDisabled();

  fireEvent.click(
    screen.getByRole("button", { name: "Zgadzam się i wykonaj" }),
  );

  await waitFor(() =>
    expect(api.answerAssistantConsent).toHaveBeenCalledWith("c1", "t1", {
      consents: { s1: "token-1" },
      declined: false,
    }),
  );
  expect(api.grantCommandConsent).toHaveBeenCalledWith("d1");
});

test("„Anuluj” declines the plan and nothing is granted", async () => {
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation.mockResolvedValue(conversation(RENAME));
  api.getCommandConsent.mockResolvedValue(PLAN);
  view();

  await screen.findByText("Nazwa: Studio → Studio Plus");
  fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));

  await waitFor(() =>
    expect(api.answerAssistantConsent).toHaveBeenCalledWith("c1", "t1", {
      consents: {},
      declined: true,
    }),
  );
  expect(api.grantCommandConsent).not.toHaveBeenCalled();
});

test("a failed turn says what to do next, and a step shows how it ended", async () => {
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation.mockResolvedValue(
    conversation(
      turn({
        id: "t0",
        items: [
          {
            kind: "action",
            step_id: "s0",
            title: { pl: "Zmień dane firmy", en: "Change company details" },
            risk: "apply",
            status: "declined",
            code: "consent_declined",
          },
        ],
      }),
      turn({ state: "failed", failure_code: "conversation_budget" }),
    ),
  );
  view();

  expect(await screen.findByText("Bez zgody")).toBeInTheDocument();
  expect(
    screen.getByText("Ta rozmowa osiągnęła swój limit. Zacznij nową rozmowę."),
  ).toBeInTheDocument();
});

test("outside the plan the page says so, with the way to the plans for the owner only", async () => {
  api.getAssistantOffer.mockResolvedValue({
    ...OFFER,
    available: false,
    in_plan: false,
    reasons: ["feature_disabled"],
  });
  const member = view("pl");
  expect(
    await screen.findByText("Asystent nie jest w Twoim planie"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Poproś właściciela firmy/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Porównaj plany" })).toBeNull();
  member.unmount();

  view("en", true);
  expect(
    await screen.findByText("The assistant is not in your plan"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Compare plans" }),
  ).toBeInTheDocument();
});

test("a closed chat takes no message and says where to go instead", async () => {
  api.getAssistantOffer.mockResolvedValue({
    ...OFFER,
    available: false,
    reasons: ["model_not_selected"],
  });
  view("en");

  expect(
    await screen.findByText(
      "The assistant is not available now. You can do the same in the panel.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Message to the assistant")).toBeDisabled();
});
