import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useEffect, useState } from "react";
import { expect, test, vi } from "vitest";
import type { PageSummary } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageStudio } from "./page-studio";

vi.mock("./page-editor", () => ({
  PageEditor: ({
    onExitStateChange,
  }: {
    onExitStateChange: (state: { dirty: boolean; busy: boolean }) => void;
  }) => {
    const [dirty, setDirty] = useState(false);
    const [busy, setBusy] = useState(false);
    useEffect(
      () => onExitStateChange({ dirty, busy }),
      [dirty, busy, onExitStateChange],
    );
    return (
      <>
        <button onClick={() => setDirty(true)}>Change draft</button>
        <button onClick={() => setDirty(false)}>Save draft</button>
        <button onClick={() => setBusy(true)}>Start saving</button>
      </>
    );
  },
}));
function setup(locale: "pl" | "en" = "en") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <PageStudio
        page={{ id: "page", name: "Home" } as PageSummary}
        onChanged={vi.fn()}
      />
    </NextIntlClientProvider>,
  );
}

test.each(["pl", "en"] as const)(
  "opens fullscreen, closes and reopens (%s)",
  async (locale) => {
    setup(locale);
    expect(await screen.findByRole("dialog")).toHaveClass(
      "h-dvh",
      "w-screen",
      "max-w-none",
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "pl" ? "Wróć do podstron" : "Back to pages",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "pl" ? "Otwórz edytor strony" : "Open page editor",
      }),
    );
    expect(await screen.findByRole("dialog")).toBeDefined();
  },
);

test("closing a dirty draft requires an explicit discard and cancel preserves it", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Change draft" }));
  fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
  expect(
    await screen.findByRole("dialog", { name: "You have unsaved changes" }),
  ).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: "You have unsaved changes" }),
    ).toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Discard and leave" }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("saved drafts close normally; active requests prevent closing", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Change draft" }));
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  fireEvent.click(screen.getByRole("button", { name: "Open page editor" }));
  fireEvent.click(await screen.findByRole("button", { name: "Start saving" }));
  expect(screen.getByRole("button", { name: "Back to pages" })).toBeDisabled();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  expect(screen.getByRole("dialog")).toBeDefined();
});
