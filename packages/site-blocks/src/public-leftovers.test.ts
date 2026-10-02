import { renderToStaticMarkup } from "react-dom/server";
import { expect, test } from "vitest";

import {
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderDraftPreview,
  renderPublishedPage,
} from "./index";
import {
  isTemplateContact,
  withoutSlots,
  withoutTemplateLeftovers,
} from "./public-leftovers";

test("a sentence with a slot is left out, the rest stays", () => {
  expect(
    withoutSlots(
      "Przyjeżdżamy z poskromem. Dojeżdżamy do gospodarstw: [Uzupełnij: powiaty]. Po wizycie zostawiamy zapis.",
    ),
  ).toBe("Przyjeżdżamy z poskromem. Po wizycie zostawiamy zapis.");
  expect(withoutSlots("[Uzupełnij: nazwa projektu]")).toBe("");
  // A slot's own full stop („np.”) does not cut it in two.
  expect(withoutSlots("[Uzupełnij: np. czy przyjść na czczo]")).toBe("");
  expect(
    withoutSlots("Przyjdź wcześniej. [Uzupełnij: np. 10 min. przed wizytą]"),
  ).toBe("Przyjdź wcześniej.");
  expect(withoutSlots("Bez miejsc do uzupełnienia.")).toBe(
    "Bez miejsc do uzupełnienia.",
  );
});

test("the template's sample phone and e-mail are told from a real contact", () => {
  expect(isTemplateContact("tel:+48000000000")).toBe(true);
  expect(isTemplateContact("tel:+48 000 000 000")).toBe(true);
  expect(isTemplateContact("mailto:kontakt@example.com")).toBe(true);
  expect(isTemplateContact("tel:+48600100200")).toBe(false);
  expect(isTemplateContact("mailto:biuro@salon.pl")).toBe(false);
  expect(isTemplateContact("#kontakt")).toBe(false);
});

test("a link to the sample contact goes with its label; the rest of the block stays", () => {
  const [hero] = withoutTemplateLeftovers([
    {
      block_type: "core.hero",
      data: {
        title: "Korekcja racic",
        text: "Pracujemy na miejscu. Dojazd: [Uzupełnij: powiaty].",
        action: { label: "Zadzwoń", href: "tel:+48000000000" },
        secondaryAction: { label: "Napisz", href: "#kontakt" },
        rows: [
          { key: "phone", value: "+48 000 000 000", href: "tel:+48000000000" },
          {
            key: "email",
            value: "biuro@salon.pl",
            href: "mailto:biuro@salon.pl",
          },
        ],
      },
    },
  ]);
  expect(hero!.data).toEqual({
    title: "Korekcja racic",
    text: "Pracujemy na miejscu.",
    secondaryAction: { label: "Napisz", href: "#kontakt" },
    rows: [
      { key: "email", value: "biuro@salon.pl", href: "mailto:biuro@salon.pl" },
    ],
  });
});

test("a published page leaves them out; the owner's preview keeps them", () => {
  const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
  const designTokens = {
    schemaVersion: 1 as const,
    palette: "blue" as const,
    typography: "sans" as const,
    radius: "medium" as const,
    spacing: "comfortable" as const,
  };
  const blocks = [
    {
      block_type: "core.hero",
      schema_version: 6,
      data: {
        title: "Korekcja racic",
        text: "Pracujemy na miejscu. Dojazd: [Uzupełnij: powiaty].",
        action: { label: "Zadzwoń", href: "tel:+48000000000" },
        layout: "split",
      },
    },
  ];
  const published = renderToStaticMarkup(
    renderPublishedPage(
      {
        kind: "publication",
        publicationId: "publication-1",
        snapshotHash: "c".repeat(64),
        designTokens,
        blocks,
      },
      registry,
    ),
  );
  expect(published).toContain("Pracujemy na miejscu.");
  expect(published).not.toContain("Uzupełnij");
  expect(published).not.toContain("tel:+48000000000");
  const preview = renderToStaticMarkup(
    renderDraftPreview(
      { kind: "draft-preview", versionId: "draft-1", designTokens, blocks },
      registry,
    ),
  );
  expect(preview).toContain("[Uzupełnij: powiaty]");
});

const ASSET = "01a0d300-0000-7000-8000-000000000001";

test("a gallery of slots stays a valid block: optional words go, a photo stays, else as it was", () => {
  const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
  const valid = (block: {
    block_type: string;
    schema_version: number;
    data: unknown;
  }) => {
    try {
      registry.validate(block as never);
      return true;
    } catch {
      return false;
    }
  };
  const gallery = (items: unknown[]) => ({
    block_type: "core.gallery",
    schema_version: 1,
    data: { title: "Realizacje", items },
  });
  // Photos with slot titles and captions: the words go, the photos stay.
  const [photos] = withoutTemplateLeftovers(
    [
      gallery([
        {
          image: { asset_id: ASSET, alt: "Obora" },
          title: "[Uzupełnij: nazwa projektu]",
          caption: "[Uzupełnij: co zrobiliście]",
        },
        { image: { asset_id: ASSET, alt: "Racica" }, title: "Po korekcji" },
      ]),
    ],
    valid,
  );
  expect(photos!.data).toEqual({
    title: "Realizacje",
    items: [
      { image: { asset_id: ASSET, alt: "Obora" } },
      { image: { asset_id: ASSET, alt: "Racica" }, title: "Po korekcji" },
    ],
  });
  expect(valid(photos!)).toBe(true);
  // An item that was only slots goes; the others stay, without their slots.
  const [mixed] = withoutTemplateLeftovers(
    [
      gallery([
        { title: "[Uzupełnij: nazwa]", caption: "[Uzupełnij: opis]" },
        { title: "Obora wolnostanowiskowa", caption: "[Uzupełnij: efekt]" },
      ]),
    ],
    valid,
  );
  expect(mixed!.data).toEqual({
    title: "Realizacje",
    items: [{ title: "Obora wolnostanowiskowa" }],
  });
  expect(valid(mixed!)).toBe(true);
  // Nothing but slots: no cleaning keeps it valid, so the page goes without it.
  const onlySlots = gallery([{ title: "[Uzupełnij: nazwa]" }]);
  expect(withoutTemplateLeftovers([onlySlots], valid)).toEqual([]);
  // A block without leftovers is passed through untouched, even if odd.
  const plain = gallery([{ title: "Obora" }]);
  expect(withoutTemplateLeftovers([plain], () => false)).toEqual([plain]);
});

test("a published page with such a gallery renders instead of failing", () => {
  const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
  const markup = renderToStaticMarkup(
    renderPublishedPage(
      {
        kind: "publication",
        publicationId: "publication-2",
        snapshotHash: "d".repeat(64),
        designTokens: {
          schemaVersion: 1,
          palette: "blue",
          typography: "sans",
          radius: "medium",
          spacing: "comfortable",
        },
        blocks: [
          {
            block_type: "core.gallery",
            schema_version: 1,
            data: {
              items: [
                {
                  image: { asset_id: ASSET, alt: "Obora" },
                  title: "[Uzupełnij: nazwa projektu]",
                  caption: "[Uzupełnij: co zrobiliście]",
                },
                { title: "[Uzupełnij: nazwa]", caption: "[Uzupełnij: opis]" },
                { title: "Po korekcji", caption: "[Uzupełnij: efekt]" },
              ],
            },
          },
        ],
      },
      registry,
    ),
  );
  expect(markup).toContain("Po korekcji");
  expect(markup).not.toContain("Uzupełnij");
});
