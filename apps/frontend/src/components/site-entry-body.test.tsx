import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SiteEntryBody } from "./site-entry-body";

const picture = "019ff20d-d000-7000-8000-000000000002";
const generated = "019ff20d-d000-7000-8000-000000000003";

const blocks = [
  {
    block_type: "core.rich_text",
    schema_version: 1,
    data: { text: "Szczeniak je cztery razy dziennie." },
  },
  {
    block_type: "core.hero",
    schema_version: 3,
    data: {
      title: "Miska i woda",
      image: { asset_id: picture, alt: "Szczeniak przy misce" },
    },
  },
  {
    block_type: "core.hero",
    schema_version: 3,
    data: {
      title: "Spacer",
      image: { asset_id: generated, alt: "Pies na spacerze" },
    },
  },
  // A form posts to the site its page was published on, and a block of live
  // records shows what the server answers for that site: a product's page
  // has neither behind it.
  {
    block_type: "core.contact_form",
    schema_version: 2,
    data: { title: "Napisz do nas" },
  },
  { block_type: "core.stay_units", schema_version: 1, data: {} },
];

const entry = {
  blocks,
  locale: "pl",
  image_sizes: { [picture]: { width: 1600, height: 900 } },
  ai_media_ids: [generated],
  machine_text: null,
};

describe("an entry's body inside a product's own page (ADR-079)", () => {
  it("draws the blocks with the core's components and nothing around them", () => {
    const { container } = render(
      <SiteEntryBody entry={entry} className="guide-body" />,
    );

    const body = container.firstElementChild!;
    expect(container.children).toHaveLength(1);
    // The theme the blocks' styles are written under, marked as standing
    // inside somebody else's page.
    expect(body.className).toBe(
      "site-theme site-theme--neutral site-theme--sans site-theme--radius-medium " +
        "site-theme--comfortable site-theme--embedded guide-body",
    );
    expect(
      screen.getByText("Szczeniak je cztery razy dziennie."),
    ).toBeInTheDocument();
    expect(screen.getByText("Miska i woda")).toBeInTheDocument();
    // The page around the body is the product's: no document landmarks, no
    // menu, no site header or footer come with it.
    for (const tag of ["main", "header", "footer", "nav", "html", "body"]) {
      expect(body.querySelector(tag), tag).toBeNull();
    }
  });

  it("loads pictures from /media on the page's own host, with their size and the AI badge", () => {
    const { container } = render(<SiteEntryBody entry={entry} />);

    const stored = screen.getByAltText("Szczeniak przy misce");
    expect(stored).toHaveAttribute("src", `/media/${picture}`);
    expect(stored.getAttribute("srcset")).toBe(
      `/media/${picture}/thumbnail 320w, /media/${picture}/preview 1280w, /media/${picture} 2560w`,
    );
    expect(stored).toHaveAttribute("width", "1600");
    expect(stored).toHaveAttribute("height", "900");
    // The first pictures of a body load with the page.
    expect(stored).toHaveAttribute("loading", "eager");
    const made = container.querySelector(`img[src="/media/${generated}"]`)!;
    expect(made.getAttribute("alt")).toContain("Pies na spacerze");
    expect(made.getAttribute("alt")).not.toBe("Pies na spacerze");
    expect(container.querySelectorAll(".site-ai-badge")).toHaveLength(1);
  });

  it("leaves out a form and blocks of a company's live records", () => {
    const { container } = render(<SiteEntryBody entry={entry} />);

    expect(screen.queryByText("Napisz do nas")).toBeNull();
    for (const tag of ["form", "fieldset", "input", "button"]) {
      expect(container.querySelector(tag), tag).toBeNull();
    }
    expect(container.querySelectorAll(".site-block")).toHaveLength(3);
  });

  it("says above the text that a machine translated it, on the server's word", () => {
    const { rerender } = render(<SiteEntryBody entry={entry} />);
    expect(screen.queryByRole("note")).toBeNull();

    rerender(
      <SiteEntryBody
        entry={{
          ...entry,
          locale: "en",
          machine_text: { source_type: "x", reviewed: false, notice: true },
        }}
      />,
    );

    expect(screen.getByRole("note")).toBeInTheDocument();
    rerender(
      <SiteEntryBody
        entry={{
          ...entry,
          machine_text: { source_type: "x", reviewed: true, notice: false },
        }}
      />,
    );
    expect(screen.queryByRole("note")).toBeNull();
  });
});
