import {
  act,
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
import englishMessages from "../../../../messages/en.json";
import { ProposalsQueue } from "./proposals-queue";

const {
  acceptContentProposal,
  discardContentProposal,
  listContentProposals,
  readContentProposal,
} = vi.hoisted(() => ({
  acceptContentProposal: vi.fn(),
  discardContentProposal: vi.fn(),
  listContentProposals: vi.fn(),
  readContentProposal: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  acceptContentProposal,
  discardContentProposal,
  listContentProposals,
  readContentProposal,
}));

const proposal = {
  proposal_id: "019ff20d-d000-7000-8000-000000000001",
  resource_type: "content_entry",
  resource_id: "019ff20d-d000-7000-8000-000000000002",
  version: 3,
  credential_id: "019ff20d-d000-7000-8000-000000000003",
  summary: "Wpis nie odpowiada na intencję frazy, po której ma ruch.",
  risk: "medium",
  expected_outcome: "Zgodność treści z intencją wyszukiwania.",
  sources: [
    {
      kind: "search_console",
      reference: "query=fizjoterapia;position=14.2",
      observed_at: "2026-08-29T22:00:00Z",
    },
  ],
  commands: ["block.replace"],
  created_at: "2026-08-30T08:00:00Z",
};

const detail = {
  ...proposal,
  review_token: "reviewed-diff-token",
  metadata_before: { title: "Stary tytuł", description: "Stary opis" },
  metadata_after: { title: "Nowy tytuł", description: "Nowy opis" },
  blocks_before: [
    {
      block_type: "core.rich_text",
      schema_version: 1,
      data: { text: "Stara treść." },
    },
  ],
  blocks_after: [
    {
      block_type: "core.rich_text",
      schema_version: 1,
      data: { text: "Nowa treść." },
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  listContentProposals.mockResolvedValue([proposal]);
  readContentProposal.mockResolvedValue(detail);
  discardContentProposal.mockResolvedValue(undefined);
  acceptContentProposal.mockResolvedValue({
    published: false,
    review_state: "accepted",
  });
});

afterEach(cleanup);

function renderQueue() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <ProposalsQueue />
    </NextIntlClientProvider>,
  );
}

test("przedstawia rekomendację jako twierdzenie integracji, nie jako fakt", async () => {
  const rendered = renderQueue();

  // The wording matters as much as the content: an operator who reads
  // recommendations as findings stops reading them.
  expect(await screen.findByText(/Integracja twierdzi:/)).not.toBeNull();
  expect(
    screen.getByText(/Spodziewany efekt według integracji/),
  ).not.toBeNull();
  expect(screen.getByText("Ryzyko średnie")).not.toBeNull();
  // And the sources it named, so the claim can be checked rather than trusted.
  expect(screen.getByText("Search Console:")).not.toBeNull();
  expect(screen.getByText("query=fizjoterapia;position=14.2")).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("pokazuje treść przed i po dopiero na żądanie", async () => {
  const rendered = renderQueue();
  const toggle = await screen.findByRole("button", { name: "Pokaż zmianę" });
  // Collapsed by default: the queue is a screen somebody scans, and the diff
  // is what they open once something looks worth deciding on.
  expect(readContentProposal).not.toHaveBeenCalled();
  expect(toggle.getAttribute("aria-expanded")).toBe("false");

  fireEvent.click(toggle);

  await waitFor(() => expect(readContentProposal).toHaveBeenCalledOnce());
  expect(await screen.findByText("Stara treść.")).not.toBeNull();
  expect(screen.getByText("Nowa treść.")).not.toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});

test("odrzuca propozycję i usuwa ją z kolejki", async () => {
  listContentProposals
    .mockResolvedValueOnce([proposal])
    .mockResolvedValueOnce([]);
  renderQueue();

  fireEvent.click(
    await screen.findByRole("button", { name: /Odrzuć i cofnij szkic/ }),
  );

  await waitFor(() => expect(discardContentProposal).toHaveBeenCalledOnce());
  expect(discardContentProposal.mock.calls[0]?.[0]).toBe(proposal.proposal_id);
  // The list is read again rather than patched locally: what is waiting now is
  // the server's answer, not this screen's memory of it.
  await waitFor(() =>
    expect(
      screen.getByText("Żadna integracja nie czeka na decyzję."),
    ).not.toBeNull(),
  );
});

test("oddziela przyjęcie do szkicu od publikacji", async () => {
  renderQueue();

  expect(
    await screen.findByText(/Wpis opublikujesz osobno na zakładce Blog/),
  ).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: "Przyjmij do szkicu" }),
  ).toBeNull();
});

test("przyjmuje dopiero obejrzaną zmianę z tokenem jej przeglądu", async () => {
  listContentProposals
    .mockResolvedValueOnce([proposal])
    .mockResolvedValueOnce([]);
  renderQueue();
  fireEvent.click(await screen.findByRole("button", { name: "Pokaż zmianę" }));
  expect(await screen.findByText("Stary opis")).not.toBeNull();
  expect(screen.getByText("Nowy opis")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Przyjmij do szkicu" }));
  await waitFor(() =>
    expect(acceptContentProposal).toHaveBeenCalledWith(
      proposal.proposal_id,
      "reviewed-diff-token",
    ),
  );
  expect(
    await screen.findByText("Żadna integracja nie czeka na decyzję."),
  ).not.toBeNull();
});

test("spóźniona odpowiedź innej propozycji nie podmienia przeglądu", async () => {
  const second = {
    ...proposal,
    proposal_id: "another-proposal",
    summary: "Druga propozycja",
  };
  listContentProposals.mockResolvedValue([proposal, second]);
  let finishFirst!: (value: typeof detail) => void;
  readContentProposal
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishFirst = resolve;
        }),
    )
    .mockResolvedValueOnce({
      ...detail,
      ...second,
      review_token: "second-token",
    });
  renderQueue();
  const buttons = await screen.findAllByRole("button", {
    name: "Pokaż zmianę",
  });
  fireEvent.click(buttons[0]!);
  fireEvent.click(buttons[1]!);
  await screen.findByRole("button", { name: "Przyjmij do szkicu" });
  await act(async () => {
    finishFirst(detail);
  });
  await waitFor(() =>
    expect(
      screen.getAllByRole("button", { name: "Przyjmij do szkicu" }),
    ).toHaveLength(1),
  );
  fireEvent.click(screen.getByRole("button", { name: "Przyjmij do szkicu" }));
  await waitFor(() =>
    expect(acceptContentProposal).toHaveBeenCalledWith(
      second.proposal_id,
      "second-token",
    ),
  );
});

test("angielski przegląd metadanych zachowuje dostępność", async () => {
  const rendered = render(
    <NextIntlClientProvider
      locale="en"
      messages={englishMessages}
      timeZone="Europe/Warsaw"
    >
      <ProposalsQueue />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Show the change" }),
  );
  expect(
    await screen.findByRole("button", { name: "Accept into draft" }),
  ).not.toBeNull();
  expect(screen.getAllByText("Search description")).toHaveLength(2);
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});
