import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";

import polishMessages from "../../../../messages/pl.json";
import { NavigationEditor } from "./navigation-editor";

const { getSiteNavigation, saveSiteNavigation } = vi.hoisted(() => ({
  getSiteNavigation: vi.fn(),
  saveSiteNavigation: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  getSiteNavigation,
  saveSiteNavigation,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const pages = [
  { id: "page-start", name: "Start", key: "home" },
  { id: "page-offer", name: "Oferta", key: "oferta" },
  { id: "page-contact", name: "Kontakt", key: "kontakt" },
] as never[];

function renderEditor() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <NavigationEditor pages={pages} siteId={siteId} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getSiteNavigation.mockResolvedValue({
    site_id: siteId,
    version: 3,
    items: [
      { page_id: "page-start", parent_page_id: null, visible: true },
      { page_id: "page-offer", parent_page_id: null, visible: true },
    ],
  });
  saveSiteNavigation.mockImplementation(
    async (_id: string, input: { expected_version: number }) => ({
      site_id: siteId,
      version: input.expected_version + 1,
      items: [],
    }),
  );
});

test("reorders and nests entries from the keyboard, then saves the whole menu", async () => {
  renderEditor();

  expect(await screen.findByText("Start")).not.toBeNull();
  // Every move is a button, so the whole editor is reachable without a pointer
  // — the acceptance gate ADR-031 sets for this screen.
  fireEvent.click(
    screen.getByRole("button", { name: "Przenieś Oferta wyżej" }),
  );
  fireEvent.click(
    screen.getByRole("button", {
      name: "Zagnieźdź Start pod pozycją wyżej",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zapisz menu" }));

  await waitFor(() => expect(saveSiteNavigation).toHaveBeenCalledOnce());
  expect(saveSiteNavigation.mock.calls[0]?.[1]).toEqual({
    expected_version: 3,
    items: [
      { page_id: "page-offer", parent_page_id: null, visible: true },
      { page_id: "page-start", parent_page_id: "page-offer", visible: true },
    ],
  });
  expect(await screen.findByRole("status")).not.toBeNull();
});

test("removing a parent takes its children with it", async () => {
  renderEditor();

  expect(await screen.findByText("Start")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Zagnieźdź Oferta pod pozycją wyżej" }),
  );
  fireEvent.click(screen.getAllByRole("button", { name: "Usuń z menu" })[0]);

  // Leaving the child behind would publish an entry whose parent is gone. Both
  // return to the "add to menu" list, so the check is on the menu itself.
  expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  expect(screen.getByText(/Menu jest puste/)).not.toBeNull();
});

test("keeps the operator's arrangement when the server version moved on", async () => {
  saveSiteNavigation.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "navigation_version_conflict",
      detail: "Navigation changed",
      correlation_id: null,
    }),
  );
  renderEditor();

  expect(await screen.findByText("Start")).not.toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Przenieś Oferta wyżej" }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Zapisz menu" }));

  expect(await screen.findByRole("alert")).not.toBeNull();
  // The menu is saved as a whole, so there is nothing to merge — the work stays
  // on screen until the operator chooses to discard it.
  const names = screen.getAllByRole("listitem").map((item) => item.textContent);
  expect(names[0]).toContain("Oferta");
  expect(
    screen.getByRole("button", { name: "Wczytaj wersję serwera" }),
  ).not.toBeNull();
});

test("offers pages that are not in the menu yet and stays accessible", async () => {
  const rendered = renderEditor();

  expect(await screen.findByText("Start")).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Kontakt" }));

  expect(screen.getAllByRole("listitem")).toHaveLength(3);
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);
});
