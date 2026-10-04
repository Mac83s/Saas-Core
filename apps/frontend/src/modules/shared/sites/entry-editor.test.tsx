import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import type { ContentEntry } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { blockOptions } from "./block-form";
import { EntryEditor } from "./entry-editor";

const { getBookingSetup, getContentEntryDraft, listMediaAssets } = vi.hoisted(
  () => ({
    getBookingSetup: vi.fn(),
    getContentEntryDraft: vi.fn(),
    listMediaAssets: vi.fn(),
  }),
);

vi.mock("../../../product", () => ({ product: {} }));
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getBookingSetup,
  getContentEntryDraft,
  listMediaAssets,
}));

const entry = {
  id: "019ff20d-a000-7000-8000-0000000000e1",
  version: 1,
} as ContentEntry;

function renderEditor() {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <EntryEditor
        entry={entry}
        locked={false}
        onSaved={() => undefined}
        proposal={false}
      />
    </NextIntlClientProvider>,
  );
}

/** The kinds of section the article's picker offers for what was typed. */
async function offered(search: string) {
  const picker = await screen.findByRole("combobox", { name: "Rodzaj sekcji" });
  picker.focus();
  fireEvent.change(picker, { target: { value: search } });
  fireEvent.keyDown(picker, { key: "ArrowDown" });
  return screen.queryAllByRole("option").map((item) => item.textContent);
}

beforeEach(() => {
  vi.clearAllMocks();
  getContentEntryDraft.mockResolvedValue({ version: 1, blocks: [] });
  listMediaAssets.mockResolvedValue({ items: [] });
});

test("an article's block list offers stay blocks to a company that has an offer booked from–to, and to no other", async () => {
  // Visits only: nothing of stays among the kinds of section.
  getBookingSetup.mockResolvedValue({
    services: [{ time_model: "slot", active: true }],
    resources: [],
  });
  const first = renderEditor();
  await waitFor(() => expect(getBookingSetup).toHaveBeenCalled());
  expect(await offered("Mapa")).not.toContain("Mapa położenia");
  first.unmount();

  getBookingSetup.mockResolvedValue({
    services: [{ time_model: "range", active: true }],
    resources: [],
  });
  renderEditor();
  await waitFor(async () =>
    expect(await offered("Mapa")).toContain("Mapa położenia"),
  );
});

test("a company's document is in no block list: only the server builds it", () => {
  expect(blockOptions.map((option) => option.type)).not.toContain(
    "core.document",
  );
  expect(blockOptions.length).toBeGreaterThan(10);
});
