import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ApiProblemError,
  archiveSiteTemplate,
  listPageVersions,
  listSiteTemplates,
  saveSiteTemplateVersion,
  type SiteTemplate,
} from "@saas-core/api-client";

import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { emptyBlock, registry } from "./block-form";
import { SaveAsTemplate } from "./own-templates";
import { SectionLibraryContent } from "./section-library";
import { VersionHistory } from "./version-history";

vi.mock("../../../product", () => ({ product: {} }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  archiveSiteTemplate: vi.fn(),
  createSiteTemplate: vi.fn(),
  listPageVersions: vi.fn(),
  listSiteTemplates: vi.fn(),
  saveSiteTemplateVersion: vi.fn(),
  updateSiteTemplate: vi.fn(),
}));

const heroVersion = registry.definitions.get("core.hero")!.latestVersion;
const author = {
  id: "019ff20d-a000-7000-8000-0000000000f9",
  email: "ania@example.test",
  name: "",
};
const offer: SiteTemplate = {
  id: "019ff20d-a000-7000-8000-0000000000f1",
  kind: "section",
  name: "Oferta firmowa",
  description: "Na strony usług",
  created_by: author,
  created_at: "2026-09-28T12:00:00Z",
  updated_at: "2026-09-28T12:00:00Z",
  version: {
    number: 3,
    blocks: [
      {
        block_type: "core.hero",
        schema_version: heroVersion,
        data: { title: "Nasza oferta", text: "Trzy pakiety" },
      },
    ],
    page_presentation: null,
    media_asset_ids: [],
    created_by: author,
    created_at: "2026-09-28T12:00:00Z",
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSiteTemplates).mockResolvedValue({
    items: [offer],
    limit: null,
  });
});
afterEach(cleanup);

function withMessages(locale: "pl" | "en", children: React.ReactNode) {
  return (
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? pl : en}
    >
      {children}
    </NextIntlClientProvider>
  );
}

test("the library puts company templates first and adds a copy", async () => {
  const onAdd = vi.fn();
  render(withMessages("pl", <SectionLibraryContent onAdd={onAdd} />));
  const group = await screen.findByRole("region", { name: "Szablony firmy" });
  expect(within(group).getByText("Wersja 3 · ania@example.test")).toBeDefined();
  fireEvent.click(
    within(group).getByRole("button", {
      name: "Dodaj szablon firmy „Oferta firmowa”",
    }),
  );
  expect(onAdd).toHaveBeenCalledOnce();
  expect(onAdd.mock.calls[0][0]).toMatchObject({
    block_type: "core.hero",
    data: { title: "Nasza oferta", text: "Trzy pakiety" },
  });
  // A search the template does not match hides the group.
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "galeria" },
  });
  expect(screen.queryByRole("region", { name: "Szablony firmy" })).toBeNull();
});

test("archiving asks first and every open list reads the templates again", async () => {
  vi.mocked(archiveSiteTemplate).mockResolvedValue(undefined);
  render(withMessages("pl", <SectionLibraryContent onAdd={vi.fn()} />));
  const group = await screen.findByRole("region", { name: "Szablony firmy" });
  fireEvent.click(
    within(group).getByRole("button", {
      name: "Zarchiwizuj szablon „Oferta firmowa”",
    }),
  );
  const dialog = screen.getByRole("dialog", {
    name: "Zarchiwizować szablon „Oferta firmowa”?",
  });
  vi.mocked(listSiteTemplates).mockResolvedValue({ items: [], limit: null });
  fireEvent.click(within(dialog).getByRole("button", { name: "Zarchiwizuj" }));
  await waitFor(() =>
    expect(archiveSiteTemplate).toHaveBeenCalledWith(offer.id),
  );
  await waitFor(() =>
    expect(screen.queryByRole("region", { name: "Szablony firmy" })).toBeNull(),
  );
});

test.each(["pl", "en"] as const)(
  "saving over an existing template makes its next version (%s)",
  async (locale) => {
    const messages = (locale === "pl" ? pl : en).Sites.ownTemplates;
    vi.mocked(saveSiteTemplateVersion).mockResolvedValue({
      ...offer,
      version: { ...offer.version, number: 4 },
    });
    render(
      withMessages(
        locale,
        <SaveAsTemplate
          kind="section"
          triggerLabel={messages.saveSection}
          blocks={() => [emptyBlock("core.hero")]}
        />,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: messages.saveSection }));
    const dialog = await screen.findByRole("dialog");
    const target = await within(dialog).findByLabelText(messages.saveAs);
    const result = await axe.run(dialog, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
    fireEvent.change(target, { target: { value: offer.id } });
    expect(within(dialog).queryByLabelText(messages.name)).toBeNull();
    fireEvent.click(
      within(dialog).getByRole("button", { name: messages.saveVersion }),
    );
    await waitFor(() => expect(saveSiteTemplateVersion).toHaveBeenCalledOnce());
    expect(vi.mocked(saveSiteTemplateVersion).mock.calls[0][0]).toBe(offer.id);
    expect(vi.mocked(saveSiteTemplateVersion).mock.calls[0][1]).toMatchObject({
      expected_version: 3,
      page_presentation: null,
    });
    expect(
      await within(dialog).findByText(
        locale === "pl"
          ? "Zapisano wersję 4 szablonu „Oferta firmowa”."
          : "Saved version 4 of the template “Oferta firmowa”.",
      ),
    ).toBeDefined();
  },
);

test("a full plan blocks a new template but not a new version", async () => {
  vi.mocked(listSiteTemplates).mockResolvedValue({ items: [offer], limit: 1 });
  vi.mocked(saveSiteTemplateVersion).mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Conflict",
      status: 409,
      code: "site_template_version_conflict",
      detail: "Server detail",
      correlation_id: null,
    }),
  );
  const own = pl.Sites.ownTemplates;
  render(
    withMessages(
      "pl",
      <SaveAsTemplate
        kind="section"
        triggerLabel={own.saveSection}
        blocks={() => [emptyBlock("core.hero")]}
      />,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: own.saveSection }));
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByLabelText(own.saveAs);
  fireEvent.change(within(dialog).getByLabelText(own.name), {
    target: { value: "Druga" },
  });
  expect(
    within(dialog).getByText(/Twój plan pozwala na 1 szablon firmy/),
  ).toBeDefined();
  expect(within(dialog).getByRole("button", { name: own.save })).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText(own.saveAs), {
    target: { value: offer.id },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: own.saveVersion }),
  );
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    own.versionConflict,
  );
});

test("the page history names the company template and its version", async () => {
  vi.mocked(listPageVersions).mockResolvedValue({
    items: [
      {
        id: "019ff20d-a000-7000-8000-0000000000e0",
        number: 2,
        origin: "own_template",
        origin_ref: "Usługa @ firma@4",
        created_by: author,
        automation: false,
        block_count: 5,
        current: true,
        created_at: "2026-09-28T12:00:00Z",
      },
    ],
    next_cursor: null,
  });
  render(
    withMessages(
      "pl",
      <VersionHistory
        pageId="019ff20d-a000-7000-8000-000000000020"
        dirty={false}
        disabled={false}
        onPreview={vi.fn()}
        onRestore={vi.fn()}
      />,
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: pl.Sites.versions.open }));
  expect(
    await screen.findByText("Szablon firmy: Usługa @ firma (wersja 4)"),
  ).toBeDefined();
});
