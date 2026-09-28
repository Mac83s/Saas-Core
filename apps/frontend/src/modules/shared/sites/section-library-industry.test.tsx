import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import pl from "../../../../messages/pl.json";
import { SectionLibraryContent } from "./section-library";

// A product sets its trade in the product slot (decision 4a, 24.09).
vi.mock("../../../product", () => ({
  product: { siteIndustry: "agriculture" },
}));

afterEach(() => cleanup());

test("the library opens on the product's trade, its sections first, and the person may pick all", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={pl}>
      <SectionLibraryContent onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  expect(screen.getByLabelText("Branża")).toHaveValue("agriculture");
  const added = screen
    .getAllByRole("button", { name: /^Dodaj: / })
    .map((button) => button.getAttribute("aria-label"));
  // The six agriculture sections lead; universal ones follow, no medicine.
  expect(added.slice(0, 6)).toEqual(
    expect.arrayContaining([
      "Dodaj: Przebieg wizyty w gospodarstwie",
      "Dodaj: Przygotuj stanowisko (gospodarstwo)",
    ]),
  );
  expect(
    screen.queryByRole("button", { name: "Dodaj: Rodzaje wizyt (gabinet)" }),
  ).toBeNull();
  expect(
    screen.getByRole("option", { name: pl.Sites.sectionLibrary.allIndustries }),
  ).toBeDefined();
});
