import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderPublishedPage,
  type DesignTokensV1,
  type JsonObject,
  type PublishedPageDocument,
  type SiteBlock,
} from "./index";

const [FIRST, SECOND, THIRD, UNKNOWN] = [1, 2, 3, 4].map(
  (n) => `01a0d300-0000-7000-8000-00000000000${n}`,
) as [string, string, string, string];
const UNIT = "22222222-2222-4222-8222-222222222222";

const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};
const registry = createSiteBlockRegistry([coreSiteBlockManifest]);

/** A block without a picture, before the ones that show some. */
const text: SiteBlock = {
  block_type: "core.hero",
  schema_version: 6,
  data: { title: "Domki nad jeziorem" },
};
const figures = (...ids: string[]): SiteBlock => ({
  block_type: "core.rich_text",
  schema_version: 2,
  data: {
    content: ids.map((asset_id) => ({
      type: "figure",
      image: { asset_id, alt: `Zdjęcie ${asset_id.slice(-1)}` },
    })),
  },
});
const stay = (kind: string, data: JsonObject = {}): SiteBlock => ({
  block_type: `core.stay_${kind}`,
  schema_version: 1,
  data: { title: "Nasze domki", ...data },
});
/** What booking answers for a list of units and for one unit's card. */
const shown = (photos: string[]): JsonObject => ({
  slug: "domki",
  form_url: "https://app.example.test/book/domki",
  timezone: "Europe/Warsaw",
  last_day: "2028-04-04",
  paused: false,
  offers: [
    {
      id: "11111111-1111-4111-8111-111111111111",
      name: "Pobyt",
      range_unit: "night",
      choices: photos.map((photo, index) => ({
        kind: "unit",
        id: UNIT.replace(/2$/, String(index)),
        name: `Domek ${index + 1}`,
        capacity: 4,
        description: "",
        photos: [photo],
        amenities: [],
        town: null,
        from_price: null,
      })),
    },
  ],
  unit: {
    name: "Domek nad jeziorem",
    capacity: 4,
    description: "",
    photos,
    amenities: [],
    town: null,
  },
});

function page(
  blocks: SiteBlock[],
  extra: Partial<PublishedPageDocument> = {},
): string {
  return renderToStaticMarkup(
    renderPublishedPage(
      {
        kind: "publication",
        locale: "pl",
        publicationId: "publication-images",
        snapshotHash: "c".repeat(64),
        designTokens: tokens,
        blocks,
        ...extra,
      },
      registry,
    ),
  );
}

const images = (html: string) => html.match(/<img[^>]*>/g) ?? [];
const loading = (html: string) =>
  images(html).map((img) => /loading="(\w+)"/.exec(img)?.[1]);

describe("pictures of a published page", () => {
  it("states each picture's stored size, and nothing for one it does not know", () => {
    const html = page([figures(FIRST, UNKNOWN)], {
      imageSizes: { [FIRST]: { width: 2400, height: 1600 } },
    });

    const [known, unknown] = images(html);
    expect(known).toContain('width="2400" height="1600"');
    expect(unknown).not.toMatch(/width=|height=/);
  });

  it("loads the first two pictures of the first block that shows any with the page", () => {
    const html = page([text, figures(FIRST, SECOND, THIRD), figures(UNKNOWN)]);

    expect(loading(html)).toEqual(["eager", "eager", "lazy", "lazy"]);
  });

  it("goes on to the next block's pictures where the first one names fewer than a first screen holds", () => {
    expect(
      loading(page([text, figures(FIRST), text, figures(SECOND, THIRD)])),
    ).toEqual(["eager", "eager", "lazy"]);

    // A unit with one photo: the first of the other units' covers, under its
    // map, is the page's second picture (the audit of 07.10).
    const sizes = Object.fromEntries(
      [FIRST, SECOND, THIRD].map((id) => [id, { width: 1536, height: 1024 }]),
    );
    const other = (photo: string, slug: string): JsonObject => ({
      kind: "unit",
      id: UNIT.replace(/2$/, slug),
      name: `Domek ${slug}`,
      capacity: 4,
      town: null,
      from_price: null,
      page_path: `/stay/domek-${slug}/`,
      photos: [photo],
    });
    const place = {
      name: "Domek nad jeziorem",
      town: { slug: "mragowo", name: "Mrągowo" },
      exact: false,
      latitude: 53.8645,
      longitude: 21.305,
    };
    const own = page(
      [
        {
          block_type: "core.stay_unit",
          schema_version: 1,
          data: { unit: UNIT, main: true },
        },
        {
          block_type: "core.stay_map",
          schema_version: 1,
          data: { unit: UNIT },
        },
      ],
      {
        live: {
          "0": shown([FIRST]),
          "1": { place, others: [other(SECOND, "3"), other(THIRD, "4")] },
        },
        imageSizes: sizes,
      },
    );
    expect(loading(own)).toEqual(["eager", "eager", "lazy"]);
  });

  it("treats a unit's photos as any block's pictures: size, first ones eager, the AI marking", () => {
    const sizes = Object.fromEntries(
      [FIRST, SECOND, THIRD].map((id) => [id, { width: 1536, height: 1024 }]),
    );
    const unit: SiteBlock = {
      block_type: "core.stay_unit",
      schema_version: 1,
      data: { unit: UNIT, main: true },
    };
    const card = page([unit], {
      live: { "0": shown([FIRST, SECOND, THIRD]) },
      imageSizes: sizes,
      aiMediaIds: [FIRST],
    });

    expect(loading(card)).toEqual(["eager", "eager", "lazy"]);
    expect(
      images(card).every((img) => img.includes('width="1536" height="1024"')),
    ).toBe(true);
    // The badge sits inside the photo's link, over the photo (ADR-059 pkt 7).
    expect(card).toMatch(
      /<a class="site-stay-card__photo"[^>]*><span class="site-ai-media"><img [^>]*alt="Domek nad jeziorem — zdjęcie 1 — obraz wygenerowany przez AI"[^>]*\/><span class="site-ai-badge" aria-hidden="true">AI<\/span><\/span><\/a>/,
    );
    expect(card.match(/class="site-ai-badge"/g)).toHaveLength(1);

    // The list of units under a hero without a picture: its covers lead.
    const list = page([text, stay("units")], {
      live: { "1": shown([FIRST, SECOND, THIRD]) },
      imageSizes: sizes,
      aiMediaIds: [SECOND],
    });
    expect(loading(list)).toEqual(["eager", "eager", "lazy"]);
    expect(list).toMatch(
      /<div class="site-stay-unit__cover"><span class="site-ai-media"><img [^>]*alt="Domek 2 — obraz wygenerowany przez AI"/,
    );
  });
});
