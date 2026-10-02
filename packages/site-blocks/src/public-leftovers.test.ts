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
