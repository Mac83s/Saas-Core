/** A module's blocks where the deployment does not compose the module
 *  (ADR-077): the product's slot lists the set, the profile does not name
 *  the module — the studio and the published page do not know the type. */

import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import { UnknownBlockTypeError } from "@saas-core/site-blocks";

import pl from "../../../../messages/pl.json";
import { deployment } from "../../../generated/deployment";
import { blockOption, registry } from "./block-form";
import { SectionLibraryContent } from "./section-library";
import { sectionTemplates } from "./site-block-registry";
import { RECORD_LIST, SAMPLE_MODULE } from "./testing/sample-module-blocks";

vi.mock("../../../product", () => ({ product: {} }));
vi.mock("../../../product/site-blocks", async () => ({
  siteBlocks: [
    (await import("./testing/sample-module-blocks")).sampleModuleBlocks,
  ],
}));

test("a set whose module the profile does not name brings nothing", () => {
  expect(deployment.modules).not.toContain(SAMPLE_MODULE);

  expect(
    [...registry.definitions.keys()].filter(
      (type) => !type.startsWith("core."),
    ),
  ).toEqual([]);
  expect(blockOption(RECORD_LIST)).toBeUndefined();
  expect(
    sectionTemplates.filter((section) => !section.id.startsWith("core.")),
  ).toEqual([]);
  expect(() =>
    registry.validate({
      block_type: RECORD_LIST,
      schema_version: 2,
      data: { heading: "Rekordy" },
    }),
  ).toThrow(UnknownBlockTypeError);

  render(
    <NextIntlClientProvider locale="pl" messages={pl}>
      <SectionLibraryContent compact onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  const chips = within(screen.getByRole("group", { name: "Kategoria" }))
    .getAllByRole("button")
    .map((chip) => chip.textContent?.replace(/\d+$/, ""));
  expect(chips.at(-1)).toBe("Tabela");
  expect(screen.queryByText("Lista rekordów")).toBeNull();
});
