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
  type AssistantConversation,
  type AssistantOffer,
  type AssistantSetup,
  type AssistantTurn,
  type CommandConsent,
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
  getAssistantSetup: vi.fn(),
  getCommandConsent: vi.fn(),
  grantCommandConsent: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
// The page's width: below 1280 px unless a test says otherwise.
const media = vi.hoisted(() => ({ wide: false }));
vi.mock("#lib/use-media", () => ({ useMedia: () => media.wide }));

const OFFER: AssistantOffer = {
  available: true,
  reasons: [],
  in_plan: true,
  credits_per_message: 1,
  max_message_characters: 4000,
  setup: { allowed: false, turns_left: 40, turns_left_today: 20 },
};
/** The same for a person who manages the company's settings. */
const SETUP_OFFER: AssistantOffer = {
  ...OFFER,
  setup: { ...OFFER.setup, allowed: true },
};
const NOTHING_NOTED: AssistantSetup = {
  version: 0,
  document: { schema: "company-profile.v1" },
  labels: { categories: {}, presets: {} },
  questions: [],
  ready: [],
  waiting: [],
  unsupported: [],
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
    kind: "operate",
    title: "",
    language: "pl",
    created_at: "2026-10-03T10:00:00Z",
    updated_at: "2026-10-03T10:00:00Z",
    turns,
  };
}

function setupConversation(...turns: AssistantTurn[]): AssistantConversation {
  return { ...conversation(...turns), kind: "setup" };
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
  media.wide = false;
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
    "operate",
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

test("setting the company up is offered only to who may do it", async () => {
  const member = view();
  expect(
    await screen.findByText("Napisz zwykłymi słowami, na przykład:"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Zacznij ustawianie firmy" }),
  ).toBeNull();
  member.unmount();

  api.getAssistantOffer.mockResolvedValue(SETUP_OFFER);
  view();
  expect(
    await screen.findByRole("heading", { name: "Ustaw firmę z asystentem" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Zacznij ustawianie firmy" }),
  ).toBeEnabled();
  // The examples of an ordinary conversation stay under it.
  expect(
    screen.getByText("Napisz zwykłymi słowami, na przykład:"),
  ).toBeInTheDocument();
});

test("the button starts a setup conversation with its first message: free, with the notes about the company", async () => {
  api.getAssistantOffer.mockResolvedValue(SETUP_OFFER);
  api.getAssistantConversation.mockResolvedValue(
    setupConversation(
      turn({
        text: "Chcę ustawić firmę z asystentem.",
        items: [{ kind: "text", text: "Czym zajmuje się Twoja firma?" }],
      }),
    ),
  );
  api.getAssistantSetup.mockResolvedValue({
    ...NOTHING_NOTED,
    questions: [
      {
        field: "company.activity",
        kind: "ask",
        reason: "what_company_does",
        proposal: null,
        options: [],
      },
    ],
  });
  const { container } = view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Zacznij ustawianie firmy" }),
  );

  expect(
    await screen.findByText("Czym zajmuje się Twoja firma?"),
  ).toBeInTheDocument();
  expect(api.startAssistantConversation).toHaveBeenCalledWith(
    "pl",
    expect.any(String),
    "setup",
  );
  expect(api.sendAssistantMessage).toHaveBeenCalledWith(
    "c1",
    "Chcę ustawić firmę z asystentem.",
    expect.any(String),
  );
  expect(screen.getByText("Ustawianie firmy")).toBeInTheDocument();
  expect(
    screen.getByText(/Ta rozmowa nie zużywa kredytów\./),
  ).toBeInTheDocument();
  expect(container.textContent).not.toContain("Każda odpowiedź to");
  expect(
    await screen.findByText("Asystent nie zanotował jeszcze nic o firmie."),
  ).toBeInTheDocument();
  expect(api.getAssistantSetup).toHaveBeenCalledWith("c1", expect.anything());
  // Below 1280 px the notes are under the conversation, closed, and their
  // line says what waits for the person.
  const notes = screen
    .getByText("Notatki o firmie · 1 pytanie")
    .closest("details");
  expect(notes).not.toHaveAttribute("open");
  expect(
    screen.getByRole("log").compareDocumentPosition(notes as HTMLElement) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.queryByRole("complementary")).toBeNull();
  // The offer to start is gone once the conversation is there.
  expect(
    screen.queryByRole("button", { name: "Zacznij ustawianie firmy" }),
  ).toBeNull();
  expect((await axe.run(container)).violations).toEqual([]);
});

test("the notes about the company are read again when the assistant's answer settles", async () => {
  const asked = turn({ state: "running", text: "Mam salon fryzjerski" });
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation
    .mockResolvedValueOnce(setupConversation(asked))
    .mockResolvedValue(
      setupConversation({
        ...asked,
        state: "done",
        items: [{ kind: "text", text: "Zanotowałem." }],
      }),
    );
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  view();

  expect(await screen.findByText("Asystent pisze…")).toBeInTheDocument();
  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(1));
  expect(
    await screen.findByText("Zanotowałem.", undefined, { timeout: 4000 }),
  ).toBeInTheDocument();
  await waitFor(() => expect(api.getAssistantSetup).toHaveBeenCalledTimes(2));
});

test("with the free setup messages used up there is no button, only where to go on", async () => {
  api.getAssistantOffer.mockResolvedValue({
    ...SETUP_OFFER,
    setup: { allowed: true, turns_left: 12, turns_left_today: 0 },
  });
  view();

  expect(
    await screen.findByText(
      "Bezpłatne wiadomości na ustawianie firmy są już wykorzystane. Resztę ustawisz w panelu.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "Ustaw firmę z asystentem" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Zacznij ustawianie firmy" }),
  ).toBeNull();
});

test("from 1280 px the notes stand beside the conversation, open, and are read once", async () => {
  media.wide = true;
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation.mockResolvedValue(setupConversation(turn({})));
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  const { container } = view();

  const beside = await screen.findByRole("complementary", {
    name: "Notatki o firmie — co już wiadomo i czego brakuje",
  });
  expect(
    await within(beside).findByText(
      "Asystent nie zanotował jeszcze nic o firmie.",
    ),
  ).toBeInTheDocument();
  expect(container.querySelector("details")).toBeNull();
  expect(beside.contains(screen.getByRole("log"))).toBe(false);
  expect(api.getAssistantSetup).toHaveBeenCalledTimes(1);
  expect((await axe.run(container)).violations).toEqual([]);
});

test("a setup message over the limit says what stays in the notes and where the rest is done", async () => {
  api.listAssistantConversations.mockResolvedValue([{ id: "c1" }]);
  api.getAssistantConversation.mockResolvedValue(setupConversation(turn({})));
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  api.sendAssistantMessage.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Limit",
      status: 429,
      code: "assistant_setup_daily_budget",
      detail: null,
      correlation_id: null,
    }),
  );
  view("en");

  fireEvent.change(await screen.findByLabelText("Message to the assistant"), {
    target: { value: "Add a service" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));

  expect(
    await screen.findByText(
      "Today's limit of free messages for setting the company up is used up. What was settled stays in the notes about the company. Come back tomorrow or do the rest in the panel: Business card, Team, Settings › Services and schedule.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByText("Setting the company up")).toBeInTheDocument();
  // A message typed under a setup conversation stays in it.
  expect(api.startAssistantConversation).not.toHaveBeenCalled();
});

test("an empty conversation that costs credits does not take the free setup message", async () => {
  api.getAssistantOffer.mockResolvedValue(SETUP_OFFER);
  api.listAssistantConversations.mockResolvedValue([{ id: "c0" }]);
  api.getAssistantConversation.mockImplementation(async (id: string) =>
    id === "c0"
      ? { ...conversation(), id: "c0" }
      : setupConversation(turn({ text: "Chcę ustawić firmę z asystentem." })),
  );
  api.getAssistantSetup.mockResolvedValue(NOTHING_NOTED);
  view();

  fireEvent.click(
    await screen.findByRole("button", { name: "Zacznij ustawianie firmy" }),
  );

  expect(await screen.findByText("Ustawianie firmy")).toBeInTheDocument();
  expect(api.startAssistantConversation).toHaveBeenCalledWith(
    "pl",
    expect.any(String),
    "setup",
  );
  expect(api.sendAssistantMessage).toHaveBeenCalledWith(
    "c1",
    "Chcę ustawić firmę z asystentem.",
    expect.any(String),
  );
});
