import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderDraftPreview,
  renderPublishedPage,
  stayFormHref,
  type DesignTokensV1,
  type JsonObject,
  type PublishedPageDocument,
  type SiteBlock,
  type StayLive,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};
const STAY = "11111111-1111-4111-8111-111111111111";
const COTTAGE = "22222222-2222-4222-8222-222222222222";
const FLAT = "33333333-3333-4333-8333-333333333333";
const PHOTO = "44444444-4444-4444-8444-444444444444";
const FORM = "https://app.example.test/book/domki";

const live: StayLive = {
  slug: "domki",
  form_url: FORM,
  timezone: "Europe/Warsaw",
  last_day: "2028-04-04",
  paused: false,
  offers: [
    {
      id: STAY,
      name: "Pobyt nad jeziorem",
      range_unit: "night",
      choices: [
        {
          kind: "group",
          id: COTTAGE,
          name: "Domek 6-os.",
          capacity: 6,
          description: "Dwie sypialnie i taras.",
          photos: [PHOTO],
          amenities: [
            "Wi-Fi",
            "Parking",
            "Kuchnia",
            "Sauna",
            "Kominek",
            "Grill",
            "Pomost",
            "Rowery",
          ].map((label) => ({ key: label, label })),
          town: { slug: "mragowo", name: "Mrągowo" },
          from_price: { gross_minor: 30000, currency: "PLN", per: "night" },
        },
        {
          kind: "unit",
          id: FLAT,
          name: "Apartament",
          capacity: null,
          description: "",
          photos: [],
          amenities: [],
          town: null,
          from_price: null,
        },
      ],
    },
  ],
};

const hero: SiteBlock = {
  block_type: "core.hero",
  schema_version: 6,
  data: { title: "Domki nad jeziorem" },
};
const stay = (kind: string, data: JsonObject = {}): SiteBlock => ({
  block_type: `core.stay_${kind}`,
  schema_version: 1,
  data: { title: "Nasze domki", ...data },
});

function published(
  blocks: SiteBlock[],
  answers: Record<string, unknown>,
  locale = "pl",
): PublishedPageDocument {
  return {
    kind: "publication",
    locale,
    publicationId: "publication-1",
    snapshotHash: "a".repeat(64),
    blocks,
    designTokens: tokens,
    live: answers as Record<string, JsonObject>,
  };
}

describe("stay blocks", () => {
  it("lists the units the server names, each leading to the form with itself chosen", () => {
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published([hero, stay("units", { text: "Wybierz swój." })], {
          "1": live,
        }),
        registry,
      ),
    );

    expect(html).toContain('data-block-type="core.stay_units"');
    expect(html).toContain("<h2>Nasze domki</h2>");
    // One offer: its name is the form's business, the units are the list.
    expect(html).not.toContain("Pobyt nad jeziorem");
    expect(html).toContain('<h3 class="site-stay-unit__name">Domek 6-os.</h3>');
    expect(html).toContain("Mrągowo · do 6 osób");
    // Our copies of the picture at the site's own host, never the original.
    expect(html).toContain(
      `src="/media/${PHOTO}/preview" srcSet="/media/${PHOTO}/thumbnail 320w, /media/${PHOTO}/preview 1280w"`,
    );
    expect(html).not.toContain(`/media/${PHOTO} `);
    expect(html).toMatch(/od 300\szł \/ noc/);
    // Six amenities and how many more.
    expect(html).toContain("<li>Grill</li><li>+2</li>");
    expect(html).not.toContain("Pomost");
    expect(html).toContain(
      `href="${FORM}?offer=${STAY}&amp;group=${COTTAGE}" rel="nofollow" aria-label="Zarezerwuj: Domek 6-os."`,
    );
    // A unit the company shows nothing of is still a way to book it.
    expect(html).toContain(`href="${FORM}?offer=${STAY}&amp;unit=${FLAT}"`);
  });

  it("names the offers when there are several, and speaks the page's language", () => {
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published(
          [stay("units", { layout: "rows", action_label: "Zum Termin" })],
          {
            "0": {
              ...live,
              offers: [
                live.offers[0],
                { ...live.offers[0], id: FLAT, name: "Bootsverleih" },
              ],
            },
          },
          "de",
        ),
        registry,
      ),
    );

    expect(html).toContain("site-stay-units--rows");
    expect(html).toContain("<h3>Bootsverleih</h3>");
    expect(html).toContain('<h4 class="site-stay-unit__name">Domek 6-os.</h4>');
    // The amount as the page's language writes a foreign currency.
    expect(html).toMatch(/ab 300\s(zł|PLN) \/ Nacht/);
    expect(html).toContain("bis 6 Personen");
    expect(html).toContain('aria-label="Zum Termin: Domek 6-os."');
  });

  it("draws no section for a block the server has no answer for", () => {
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published([stay("units"), stay("search"), stay("calendar"), hero], {}),
        registry,
      ),
    );

    expect(html).not.toContain("core.stay_");
    expect(html).not.toContain("Nasze domki");
    expect(html).toContain("Domki nad jeziorem");
  });

  it("hands the widget and the calendar to the application, with the block's choice and the answer", () => {
    const seen: unknown[] = [];
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published([stay("search", { offer: STAY }), stay("calendar")], {
          "0": live,
          "1": live,
        }),
        registry,
        undefined,
        (blockType, data, answer) => {
          seen.push([blockType, data.offer, (answer as StayLive).slug]);
          return createElement("div", { "data-live": blockType });
        },
      ),
    );

    expect(seen).toEqual([
      ["core.stay_search", STAY, "domki"],
      ["core.stay_calendar", undefined, "domki"],
    ]);
    expect(html).toContain('<div data-live="core.stay_search"></div>');
    expect(html).toContain('data-block-type="core.stay_calendar"');
    // Without the application's part the way to the form is still there.
    const plain = renderToStaticMarkup(
      renderPublishedPage(
        published([stay("search", { offer: STAY })], { "0": live }),
        registry,
      ),
    );
    expect(plain).toContain(
      `<a class="site-section__action" href="${FORM}?offer=${STAY}" rel="nofollow">Sprawdź cenę i zarezerwuj</a>`,
    );
  });

  it("answers a block by the position it was published at, whatever was left out before it", () => {
    // The testimonial is all slots: the cleaning leaves it out of the page.
    const slots: SiteBlock = {
      block_type: "core.testimonials",
      schema_version: 1,
      data: {
        items: [{ quote: "[Uzupełnij: opinia]", author: "[Uzupełnij: kto]" }],
      },
    };
    const positions: number[] = [];
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published(
          [
            slots,
            stay("units"),
            {
              block_type: "core.contact_form",
              schema_version: 2,
              data: { title: "Napisz" },
            },
          ],
          { "1": live },
        ),
        registry,
        (_form, position) => {
          positions.push(position);
          return null;
        },
      ),
    );

    expect(html).not.toContain("core.testimonials");
    expect(html).toContain("Domek 6-os.");
    // The form's message names the block the publication has at 2.
    expect(positions).toEqual([2]);
  });

  it("shows in the editor where the live part will be, never a unit", () => {
    const html = renderToStaticMarkup(
      renderDraftPreview(
        {
          kind: "draft-preview",
          versionId: "draft-1",
          blocks: [
            stay("units"),
            stay("search"),
            stay("calendar"),
            {
              block_type: "core.stay_unit",
              schema_version: 1,
              data: { unit: FLAT },
            },
          ],
          designTokens: tokens,
        },
        registry,
      ),
    );

    expect(html).toContain(
      "Na opublikowanej stronie pojawią się tu Twoje jednostki",
    );
    expect(html).toContain("gość wybierze tu termin i liczbę osób");
    expect(html).toContain("kalendarz wolnych terminów z Twojego grafiku");
    expect(html).toContain("pojawi się tu karta jednostki");
    expect(html).not.toContain("<a ");
  });

  it("draws a unit's card from the server's answer: pictures, all it has, and the application's calendar", () => {
    const [group] = live.offers[0]!.choices;
    const answer = {
      ...live,
      unit: group,
      offers: [
        {
          ...live.offers[0]!,
          choices: [
            { kind: "group", id: COTTAGE, name: "Domek 6-os.", capacity: 6 },
          ],
        },
      ],
    };
    const card = (data: JsonObject): SiteBlock => ({
      block_type: "core.stay_unit",
      schema_version: 1,
      data: { unit: FLAT, ...data },
    });
    const seen: string[] = [];
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published([card({ main: true }), card({}), card({})], {
          "0": answer,
          "1": answer,
        }),
        registry,
        undefined,
        (blockType) => {
          seen.push(blockType);
          return createElement("div", { "data-live": blockType });
        },
      ),
    );

    // On the unit's own page the name is the page's heading; in a page of
    // the company's it is a section's. A card without an answer is not drawn.
    expect(html.match(/<h1>Domek 6-os\.<\/h1>/g)).toHaveLength(1);
    expect(html.match(/<h2>Domek 6-os\.<\/h2>/g)).toHaveLength(1);
    expect(html.match(/data-block-type="core.stay_unit"/g)).toHaveLength(2);
    expect(seen).toEqual(["core.stay_unit", "core.stay_unit"]);
    // Each picture opens in our large copy; all eight amenities are named.
    expect(html).toContain(
      `<a class="site-stay-card__photo" href="/media/${PHOTO}/preview" target="_blank" rel="noopener"><img src="/media/${PHOTO}/preview"`,
    );
    expect(html).toContain('alt="Domek 6-os. — zdjęcie 1"');
    expect(html).toContain("<li>Pomost</li><li>Rowery</li>");
    expect(html).toMatch(/od 300\szł \/ noc/);
    expect(html).toContain("Mrągowo · do 6 osób");
  });

  it("leads from the list to a unit's own page where the site has one", () => {
    const [group, flat] = live.offers[0]!.choices;
    const html = renderToStaticMarkup(
      renderPublishedPage(
        published([stay("units")], {
          "0": {
            ...live,
            offers: [
              {
                ...live.offers[0]!,
                choices: [{ ...group, page_path: "/stay/domek-1/" }, flat],
              },
            ],
          },
        }),
        registry,
      ),
    );

    expect(html).toContain(
      '<h3 class="site-stay-unit__name"><a href="/stay/domek-1/">Domek 6-os.</a></h3>',
    );
    expect(html).toContain('<h3 class="site-stay-unit__name">Apartament</h3>');
  });

  it("builds the form's address from what was chosen", () => {
    expect(stayFormHref(FORM)).toBe(FORM);
    expect(
      stayFormHref(FORM, {
        offer: STAY,
        choice: { kind: "unit", id: FLAT },
        from: "2027-07-03",
        to: "2027-07-10",
        people: 4,
      }),
    ).toBe(
      `${FORM}?offer=${STAY}&unit=${FLAT}&from=2027-07-03&to=2027-07-10&people=4`,
    );
  });
});
