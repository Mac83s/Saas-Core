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
import { ProposalsQueue } from "./proposals-queue";

const { discardContentProposal, listContentProposals, readContentProposal } =
  vi.hoisted(() => ({
    discardContentProposal: vi.fn(),
    listContentProposals: vi.fn(),
    readContentProposal: vi.fn(),
  }));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
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
});

afterEach(cleanup);

function renderQueue() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
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

test("mówi, gdzie przyjąć propozycję, zamiast udawać drugi przycisk publikacji", async () => {
  renderQueue();

  // Publishing lives where publishing lives; a second button here would be a
  // second path past the checks that guard it.
  expect(
    await screen.findByText(/Aby przyjąć: opublikuj wpis na zakładce Blog/),
  ).not.toBeNull();
});
