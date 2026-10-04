import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { TranslationTabs } from "./translation-tabs";

const { api } = vi.hoisted(() => ({
  api: { listTranslationReview: vi.fn() },
}));
// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("./testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel/sites/translations",
}));

function view(waiting?: number, website?: boolean) {
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslationTabs waiting={waiting} website={website} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("asks the queue how much waits and marks the view one is on", async () => {
  api.listTranslationReview.mockResolvedValue({
    items: [],
    count: 4,
    next_cursor: null,
  });
  view();
  expect(
    await screen.findByRole("link", { name: "Do akceptacji (4)" }),
  ).toBeTruthy();
  expect(
    screen.getByRole("link", { name: "Przegląd" }).getAttribute("aria-current"),
  ).toBe("page");
  expect(api.listTranslationReview).toHaveBeenCalledWith({ limit: 1 });
});

test("no engine or no right to decide: no second view, so no tabs", async () => {
  api.listTranslationReview.mockRejectedValue(new Error("404"));
  const { container } = view();
  await waitFor(() => expect(api.listTranslationReview).toHaveBeenCalled());
  await waitFor(() => expect(container.querySelector("nav")).toBeNull());
});

test("a page that knows the number does not ask again", () => {
  view(0);
  expect(screen.getByRole("link", { name: "Do akceptacji" })).toBeTruthy();
  expect(api.listTranslationReview).not.toHaveBeenCalled();
});

test("an organization without websites gets no overview of pages", () => {
  view(2, false);
  expect(screen.getByRole("link", { name: "Do akceptacji (2)" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Zadania" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Przegląd" })).toBeNull();
});
