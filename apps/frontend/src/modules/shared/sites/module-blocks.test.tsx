/** A module's blocks in the studio and on a published page (ADR-077,
 *  docs/architecture/site-block-types.md), proven on the test-only vertical
 *  `vertical.sample`: the product's slot lists its set and the deployment
 *  composes the module. One block a person places (`record_list`, filled
 *  live) and one the module builds for a record's own page
 *  (`record_profile`). `module-blocks-absent.test.tsx` is the other half. */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { FormProvider, useForm, type FieldValues } from "react-hook-form";
import { afterEach, expect, test, vi } from "vitest";

import type { PublicSitePage } from "@saas-core/api-client";
import { renderDraftPreview } from "@saas-core/site-blocks";

import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { mergeMessages } from "../../../i18n/merge-messages";
import {
  BlockFields,
  blockFormSchema,
  blockOption,
  blockOptions,
  blockPayload,
  emptyBlock,
  registry,
} from "./block-form";
import { PageEditorContext } from "./page-editor-context";
import { PublicSiteRenderer } from "./public-site";
import { SectionLibraryContent } from "./section-library";
import {
  RECORD_LIST,
  RECORD_PROFILE,
  sampleModuleMessages,
} from "./testing/sample-module-blocks";

vi.mock("../../../product", () => ({ product: {} }));
// The product's slot lists the module's set…
vi.mock("../../../product/site-blocks", async () => ({
  siteBlocks: [
    (await import("./testing/sample-module-blocks")).sampleModuleBlocks,
  ],
}));
// …and the deployment's profile composes the module.
vi.mock("../../../generated/deployment", async (original) => {
  const { deployment } =
    await original<typeof import("../../../generated/deployment")>();
  return {
    deployment: {
      ...deployment,
      modules: [...deployment.modules, "vertical.sample"],
    },
  };
});

afterEach(cleanup);

// jsdom draws nothing: contrast is checked in a browser.
const quiet = { rules: { "color-contrast": { enabled: false } } };

// What the product brings in `product.messages`, merged as the app merges it.
const messages = {
  pl: mergeMessages(pl, sampleModuleMessages.pl),
  en: mergeMessages(en, sampleModuleMessages.en),
};
const tokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

test("the registry holds the module's types beside the core's", () => {
  expect(registry.definitions.has("core.hero")).toBe(true);
  expect(registry.definitions.get(RECORD_LIST)?.latestVersion).toBe(2);
  expect(registry.definitions.has(RECORD_PROFILE)).toBe(true);
  // „Dodaj pustą sekcję” offers what a person places, never what only the
  // server builds.
  expect(blockOptions.map((option) => option.type)).toContain(RECORD_LIST);
  expect(blockOption(RECORD_PROFILE)).toBeUndefined();
});

test.each(["pl", "en"] as const)(
  "the library has the module's family and adds its section (%s)",
  (locale) => {
    const onAdd = vi.fn();
    render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <SectionLibraryContent compact onAdd={onAdd} />
      </NextIntlClientProvider>,
    );
    const name = locale === "pl" ? "Lista rekordów" : "List of records";
    const chips = within(
      screen.getByRole("group", {
        name: (locale === "pl" ? pl : en).Sites.sectionLibrary.category,
      }),
    ).getAllByRole("button");
    // After the core's families, under the name the outline uses.
    expect(chips.at(-1)?.textContent).toBe(`${name}1`);
    fireEvent.click(chips.at(-1)!);
    expect(screen.getByRole("heading", { name })).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", {
        name: `${locale === "pl" ? "Dodaj" : "Add"}: ${name}`,
      }),
    );
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        block_type: RECORD_LIST,
        data: expect.objectContaining({
          heading: locale === "pl" ? "Nasze rekordy" : "Our records",
          order: "name",
        }),
      }),
    );
  },
);

function Form({ onValues }: { onValues: (values: FieldValues) => void }) {
  const form = useForm<FieldValues>({
    defaultValues: { blocks: [emptyBlock(RECORD_LIST)] },
  });
  return (
    <NextIntlClientProvider locale="pl" messages={messages.pl}>
      <FormProvider {...form}>
        <PageEditorContext
          value={{
            undo: vi.fn(),
            redo: vi.fn(),
            look: "",
            imageGeneration: null,
          }}
        >
          <BlockFields
            form={form}
            index={0}
            isFirst
            isLast
            moveDown={vi.fn()}
            moveUp={vi.fn()}
            onRemove={vi.fn()}
            type={RECORD_LIST}
          />
          <button type="button" onClick={() => onValues(form.getValues())}>
            read
          </button>
        </PageEditorContext>
      </FormProvider>
    </NextIntlClientProvider>
  );
}

test("the inspector draws the block's form from its catalogue fields", async () => {
  const onValues = vi.fn();
  const { container } = render(<Form onValues={onValues} />);

  fireEvent.change(screen.getByLabelText("Nagłówek"), {
    target: { value: "Rasy psów" },
  });
  fireEvent.change(screen.getByLabelText("Wprowadzenie"), {
    target: { value: "Wszystkie rasy w jednym miejscu." },
  });
  const order = screen.getByLabelText("Kolejność");
  expect(
    within(order)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Według nazwy", "Od najnowszych"]);
  fireEvent.change(order, { target: { value: "newest" } });
  expect(screen.getByLabelText("Opiekun listy")).toBeVisible();
  expect((await axe.run(container, quiet)).violations).toEqual([]);

  // What a save would send is a block its schema accepts, at the latest
  // version; the blank optional fields are not sent.
  fireEvent.click(screen.getByRole("button", { name: "read" }));
  const block = onValues.mock.calls[0]![0].blocks[0];
  expect(blockFormSchema.safeParse(block).success).toBe(true);
  expect(blockPayload(block)).toEqual({
    block_type: RECORD_LIST,
    schema_version: 2,
    data: {
      heading: "Rasy psów",
      intro: "Wszystkie rasy w jednym miejscu.",
      order: "newest",
    },
  });
});

test("the studio draws a placed block of live records as a sketch", async () => {
  const { container } = render(
    renderDraftPreview(
      {
        kind: "draft-preview",
        versionId: "preview",
        blocks: [
          {
            block_type: RECORD_LIST,
            // Stored as v1: drawn as the latest version.
            schema_version: 1,
            data: { heading: "Nasze rekordy", order: "name" },
          },
        ],
        designTokens: tokens,
      },
      registry,
    ),
  );

  expect(screen.getByRole("heading", { name: "Nasze rekordy" })).toBeVisible();
  expect(
    container.querySelector(".site-sample-records__sketch"),
  ).not.toBeNull();
  expect(screen.queryByRole("link")).toBeNull();
  expect((await axe.run(container, quiet)).violations).toEqual([]);
});

const published = {
  publication_id: "019ff20d-a000-7000-8000-000000000020",
  snapshot_hash: "a".repeat(64),
  locale: "pl",
  canonical_url: "https://rasy.example.test/",
  hreflang: { pl: "https://rasy.example.test/" },
  x_default: "https://rasy.example.test/",
  breadcrumbs: [{ title: "Start", path: "/" }],
  title: "Rasy",
  description: "Opis",
  social_title: "Rasy",
  social_description: "Opis",
  design_tokens: tokens,
  blocks: [],
  navigation: [],
  live: {},
  pagination: null,
  article: null,
  ai_media_ids: [],
  noindex: false,
  language_links: [],
  feeds: { rss: "", atom: "" },
  social: {
    site_name: "Rasy",
    locale: "pl_PL",
    alternate_locales: [],
    image: null,
  },
} as unknown as PublicSitePage;

const placed = {
  block_type: RECORD_LIST,
  schema_version: 2,
  data: {
    heading: "Nasze rekordy",
    intro: "Wstęp do listy",
    order: "name",
    curator: "Anna Nowak",
    curator_role: "Opiekunka zbioru",
    action: { label: "Zobacz wszystkie", href: "/samples/" },
  },
};

test("a published page draws the placed block with the module's answer", async () => {
  const { container } = render(
    <PublicSiteRenderer
      page={{
        ...published,
        blocks: [placed],
        live: {
          "0": {
            records: [
              { name: "Rekord drugi", href: "/samples/second/" },
              { name: "Rekord pierwszy", href: "/samples/first/" },
            ],
          },
        },
      }}
    />,
  );

  expect(
    container.querySelector(`[data-block-type='${RECORD_LIST}']`),
  ).not.toBeNull();
  expect(
    screen
      .getAllByRole("link")
      .map((link) => [link.textContent, link.getAttribute("href")]),
  ).toEqual([
    ["Rekord drugi", "/samples/second/"],
    ["Rekord pierwszy", "/samples/first/"],
    ["Zobacz wszystkie", "/samples/"],
  ]);
  expect(screen.getByText(/Anna Nowak — Opiekunka zbioru/)).toBeVisible();
  expect(container.querySelector(".site-sample-records__sketch")).toBeNull();
  expect((await axe.run(container, quiet)).violations).toEqual([]);
});

test("without the module's answer the placed block is no section at all", () => {
  const { container } = render(
    <PublicSiteRenderer page={{ ...published, blocks: [placed], live: {} }} />,
  );

  expect(
    container.querySelector(`[data-block-type='${RECORD_LIST}']`),
  ).toBeNull();
  expect(screen.queryByText("Nasze rekordy")).toBeNull();
});

test("a record's own page is the block the module built", async () => {
  const { container } = render(
    <PublicSiteRenderer
      page={{
        ...published,
        canonical_url: "https://rasy.example.test/samples/first/",
        title: "Rekord pierwszy",
        blocks: [
          {
            block_type: RECORD_PROFILE,
            schema_version: 1,
            data: {
              name: "Rekord pierwszy",
              summary: "Krótko o rekordzie.",
              facts: [{ label: "Pochodzenie", value: "Polska" }],
              ratings: [{ label: "Energia", value: 4 }],
              sections: [{ heading: "Charakter", text: "Spokojny i uważny." }],
              related: [{ name: "Rekord drugi", href: "/samples/second/" }],
            },
          },
        ],
      }}
    />,
  );

  expect(
    screen.getByRole("heading", { level: 2, name: "Rekord pierwszy" }),
  ).toBeVisible();
  expect(screen.getByText("Polska")).toBeVisible();
  expect(screen.getByRole("meter", { name: "Energia" })).toHaveAttribute(
    "value",
    "4",
  );
  expect(screen.getByRole("heading", { name: "Charakter" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Rekord drugi" })).toHaveAttribute(
    "href",
    "/samples/second/",
  );
  expect((await axe.run(container, quiet)).violations).toEqual([]);
});
