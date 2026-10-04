import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
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

// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("../translation/testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  getSiteAppearance: vi.fn(),
  getSiteNavigation: vi.fn().mockResolvedValue({ items: [] }),
  getSiteLocalizationReport: vi
    .fn()
    .mockResolvedValue({ pages: [], default_locale: "en" }),
  saveSiteAppearance: vi.fn(),
  getPublicLocales: vi.fn().mockRejectedValue(new Error("offline")),
  // No translation engine composed, unless a test says otherwise.
  getTranslationOffer: vi.fn().mockRejectedValue(new Error("not found")),
}));

vi.mock("./page-language-editor", () => ({
  PageLanguageEditor: ({
    locale,
    leading,
    languageSwitch,
    onSwitchToSource,
  }: {
    locale: string;
    leading: ReactNode;
    languageSwitch: ReactNode;
    onSwitchToSource: () => void;
  }) => (
    <>
      {leading}
      {languageSwitch}
      <p>Translating into {locale}</p>
      <button onClick={onSwitchToSource}>Back to the source</button>
    </>
  ),
}));

vi.mock("./page-editor", () => ({
  PageEditor: ({
    onExitStateChange,
    appearanceControls,
    pagesPanel,
    leading,
    page,
    previewOnOpen,
    afterSaveNotice,
  }: {
    afterSaveNotice?: string;
    appearanceControls?: ReactNode;
    pagesPanel?: ReactNode;
    leading?: ReactNode;
    page: PageSummary;
    previewOnOpen?: boolean;
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
        {leading}
        <p>Editing {page.name}</p>
        {previewOnOpen ? <p>Preview first</p> : null}
        {afterSaveNotice ? <p>After a save: {afterSaveNotice}</p> : null}
        {pagesPanel}
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

test("the page list opens it with the preview and gets control back on close", async () => {
  const onClose = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <PageStudio
        page={{ id: "page", name: "Home" } as PageSummary}
        onChanged={vi.fn()}
        onClose={onClose}
        previewOnOpen
      />
    </NextIntlClientProvider>,
  );
  expect(await screen.findByText("Preview first")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Back to pages" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
});

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

test("the studio switches pages without closing, and asks first about unsaved changes", async () => {
  const pages = [
    { id: "home", name: "Home", key: "home", site_id: "site" },
    { id: "offer", name: "Offer", key: "offer", site_id: "site" },
  ] as PageSummary[];
  function Harness() {
    const [current, setCurrent] = useState("home");
    return (
      <NextIntlClientProvider locale="en" messages={englishMessages}>
        <PageStudio
          page={pages.find((item) => item.id === current)!}
          pages={pages}
          onSelectPage={setCurrent}
          onChanged={vi.fn()}
        />
      </NextIntlClientProvider>
    );
  }
  render(<Harness />);
  expect(await screen.findByText("Editing Home")).toBeDefined();
  expect(screen.getByRole("button", { name: /^Home/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(screen.getByRole("button", { name: /^Offer/ }));
  expect(await screen.findByText("Editing Offer")).toBeDefined();
  // A dirty page asks; keeping it stays on the page.
  fireEvent.click(screen.getByRole("button", { name: "Change draft" }));
  fireEvent.click(screen.getByRole("button", { name: /^Home/ }));
  expect(
    await screen.findByText(
      englishMessages.Sites.studio.unsavedSwitchDescription,
    ),
  ).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
  expect(screen.getByText("Editing Offer")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: /^Home/ }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: englishMessages.Sites.studio.discardAndSwitch,
    }),
  );
  expect(await screen.findByText("Editing Home")).toBeDefined();
  // The studio itself never closed.
  expect(screen.getByTestId("fullscreen-studio")).toBeDefined();
});

test("the studio edits another language of the page and keeps it in the address", async () => {
  const { getSiteLocalizationReport } = await import("@saas-core/api-client");
  vi.mocked(getSiteLocalizationReport).mockResolvedValueOnce({
    default_locale: "pl",
    languages: [
      { locale: "pl", is_source: true, live: true },
      { locale: "de", is_source: false, live: true },
    ],
    pages: [
      {
        page_id: "page",
        locales: [
          { locale: "pl", state: "complete" },
          { locale: "de", state: "untranslated" },
        ],
      },
    ],
  } as never);
  window.history.replaceState(null, "", "/panel/sites/pages/page?language=de");
  setup("pl", "site");

  expect(await screen.findByText("Translating into de")).not.toBeNull();
  // No row of the studio's own over the language mode: the way back and the
  // dialog's title go into that editor's top bar, as with the source.
  const dialog = screen.getByRole("dialog");
  expect(dialog.querySelector("header")).toBeNull();
  expect(dialog).toHaveAccessibleName(/Home/);
  expect(
    screen.getByRole("button", { name: "Wróć do podstron" }),
  ).toBeDefined();
  expect(
    screen.getByRole("combobox", { name: "Wersja językowa" }).textContent,
  ).toContain("Niepełna");
  fireEvent.click(screen.getByRole("button", { name: "Back to the source" }));
  expect(await screen.findByText("Editing Home")).not.toBeNull();
  expect(window.location.search).toBe("");
});

test("a saved source says what follows for its live languages, only with the automation on", async () => {
  const { getSiteLocalizationReport, getTranslationOffer } =
    await import("@saas-core/api-client");
  const report = {
    default_locale: "pl",
    languages: [
      { locale: "pl", is_source: true, live: true },
      { locale: "en", is_source: false, live: true },
      { locale: "de", is_source: false, live: false },
    ],
    pages: [
      {
        page_id: "page",
        locales: [
          { locale: "pl", state: "complete" },
          { locale: "en", state: "published" },
          // Not on the site yet: the automation does not follow it.
          { locale: "de", state: "complete" },
        ],
      },
    ],
  } as never;
  const offer = (enabled: boolean, mode: string) =>
    ({
      available: true,
      reasons: [],
      mode: { effective: mode },
      automation: { enabled },
      billing: { mode: "credits" },
    }) as never;
  window.history.replaceState(null, "", "/panel/sites/pages/page");

  vi.mocked(getSiteLocalizationReport).mockResolvedValue(report);
  vi.mocked(getTranslationOffer).mockResolvedValueOnce(offer(true, "review"));
  const first = setup("pl", "site");
  expect(
    await screen.findByText(
      "After a save: Zapisano. Po publikacji tej strony nowe tłumaczenia (English) poczekają na Twoją akceptację.",
    ),
  ).not.toBeNull();
  first.unmount();

  vi.mocked(getTranslationOffer).mockClear();
  vi.mocked(getTranslationOffer).mockResolvedValueOnce(
    offer(false, "automatic"),
  );
  setup("pl", "site");
  expect(await screen.findByText("Editing Home")).not.toBeNull();
  await waitFor(() => expect(getTranslationOffer).toHaveBeenCalledTimes(1));
  // The answer has landed: nothing is promised without the automation.
  await act(async () => {
    await Promise.resolve();
  });
  expect(screen.queryByText(/After a save/)).toBeNull();
});
