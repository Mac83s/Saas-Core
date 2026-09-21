import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useEffect, useState, type ReactNode } from "react";
import { expect, test, vi } from "vitest";
import {
  getSiteAppearance,
  saveSiteAppearance,
  type PageSummary,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PageStudio } from "./page-studio";

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  getSiteAppearance: vi.fn(),
  getSiteNavigation: vi.fn().mockResolvedValue({ items: [] }),
  getSiteLocalizationReport: vi
    .fn()
    .mockResolvedValue({ pages: [], default_locale: "en" }),
  saveSiteAppearance: vi.fn(),
}));

vi.mock("./page-editor", () => ({
  PageEditor: ({
    onExitStateChange,
    appearanceControls,
  }: {
    appearanceControls?: ReactNode;
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
        {appearanceControls}
        <button onClick={() => setDirty(true)}>Change draft</button>
        <button onClick={() => setDirty(false)}>Save draft</button>
        <button onClick={() => setBusy(true)}>Start saving</button>
      </>
    );
  },
}));
function setup(locale: "pl" | "en" = "en", siteId?: string) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <PageStudio
        page={{ id: "page", name: "Home", site_id: siteId } as PageSummary}
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

test("appearance changes save separately and failed saves retain the working value", async () => {
  const appearance = {
    schemaVersion: 1,
    designTokens: {
      schemaVersion: 1,
      palette: "blue",
      typography: "sans",
      radius: "medium",
      spacing: "comfortable",
    },
    font: "system",
    width: "standard",
    buttons: "solid",
    header: { layout: "none", brand: "Clinic", tagline: "" },
    footer: { layout: "none", text: "", links: [] },
    navigation: { mobile: "drawer", tablet: "drawer" },
  };
  vi.mocked(getSiteAppearance).mockResolvedValue({
    site_id: "site",
    version: 0,
    appearance,
  });
  vi.mocked(saveSiteAppearance).mockRejectedValueOnce(new Error("Conflict"));
  setup("en", "site");
  fireEvent.change(await screen.findByLabelText("Font"), {
    target: { value: "inter" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save appearance" }));
  expect(await screen.findByRole("alert")).toBeDefined();
  expect(screen.getByLabelText("Font")).toHaveValue("inter");
  vi.mocked(saveSiteAppearance).mockResolvedValueOnce({
    site_id: "site",
    version: 1,
    appearance: { ...appearance, schemaVersion: 2, font: "inter" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save appearance" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Save appearance" }),
    ).toBeDisabled(),
  );
  expect(
    vi.mocked(saveSiteAppearance).mock.calls.at(-1)?.[1].expected_version,
  ).toBe(0);
  fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
