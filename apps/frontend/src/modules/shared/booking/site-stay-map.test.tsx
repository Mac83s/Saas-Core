import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import type { StayPlace } from "@saas-core/site-blocks";

import { SiteStayMap } from "./site-stay-map";

const point: StayPlace = {
  name: "Domek nad jeziorem",
  town: { slug: "mragowo", name: "Mrągowo" },
  exact: true,
  latitude: 53.8712,
  longitude: 21.3184,
};
const town: StayPlace = {
  ...point,
  exact: false,
  latitude: 53.8645,
  longitude: 21.305,
};

test("asks OpenStreetMap for nothing until the visitor says „Pokaż mapę”", async () => {
  const { container } = render(<SiteStayMap locale="pl" place={point} />);

  // Before the click: a button, whose map it is, and the plain way out —
  // nothing that would make the browser talk to anybody else.
  expect(container.querySelector("iframe, img, script, link")).toBeNull();
  expect(
    screen.getByText(
      /Mapę wyświetla OpenStreetMap\. Po kliknięciu „Pokaż mapę”/,
    ),
  ).toBeInTheDocument();
  const out = screen.getByRole("link", { name: "Otwórz w mapach" });
  expect(out).toHaveAttribute(
    "href",
    "https://www.openstreetmap.org/?mlat=53.8712&mlon=21.3184#map=16/53.8712/21.3184",
  );
  expect(out).toHaveAttribute("rel", "noopener noreferrer");
  expect(out).toHaveAttribute("target", "_blank");
  expect((await axe.run(container)).violations).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "Pokaż mapę" }));

  // After it: OpenStreetMap's own frame with the pin, named for whoever does
  // not see it, told nothing of the page it sits on and kept in a sandbox.
  const frame = screen.getByTitle("Mapa: Domek nad jeziorem, Mrągowo");
  expect(frame.tagName).toBe("IFRAME");
  const address = new URL(frame.getAttribute("src")!);
  expect(address.origin).toBe("https://www.openstreetmap.org");
  expect(address.pathname).toBe("/export/embed.html");
  expect(address.searchParams.get("marker")).toBe("53.8712,21.3184");
  expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
  expect(frame.getAttribute("sandbox")).toContain("allow-scripts");
  expect(frame.getAttribute("sandbox")).not.toContain("allow-top-navigation");
  expect(frame).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Pokaż mapę" })).toBeNull();
  expect(screen.getByRole("link", { name: "Otwórz w mapach" })).toBe(out);
  // The frame's inside is OpenStreetMap's; the page around it is ours.
  expect((await axe.run(container, { iframes: false })).violations).toEqual([]);
});

test("shows a town without a pin, in the page's language", () => {
  render(<SiteStayMap locale="en" place={town} />);

  expect(screen.getByRole("link", { name: "Open in maps" })).toHaveAttribute(
    "href",
    "https://www.openstreetmap.org/#map=12/53.8645/21.305",
  );
  fireEvent.click(screen.getByRole("button", { name: "Show map" }));
  const frame = screen.getByTitle("Map: Domek nad jeziorem, Mrągowo");
  expect(new URL(frame.getAttribute("src")!).searchParams.has("marker")).toBe(
    false,
  );
});
