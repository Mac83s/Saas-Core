import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, test } from "vitest";

import {
  Toolbar,
  ToolbarButton,
  ToolbarSeparator,
  ToolbarToggle,
} from "#components/toolbar";

function Fixture() {
  const [bold, setBold] = useState(false);
  return (
    <Toolbar aria-label="Formatowanie">
      <ToolbarToggle
        aria-label="Pogrubienie"
        pressed={bold}
        onPressedChange={setBold}
      >
        B
      </ToolbarToggle>
      <ToolbarSeparator />
      <ToolbarButton aria-label="Link">L</ToolbarButton>
    </Toolbar>
  );
}

test("Toolbar is one tab stop and a toggle announces its state", () => {
  render(<Fixture />);
  const bold = screen.getByRole("button", { name: "Pogrubienie" });
  const link = screen.getByRole("button", { name: "Link" });

  expect(screen.getByRole("toolbar", { name: "Formatowanie" })).not.toBeNull();
  // Roving tab index: only the active item is reachable with Tab; arrow keys
  // (Base UI, needs layout) are checked in the browser.
  expect(bold.getAttribute("tabindex")).toBe("0");
  expect(link.getAttribute("tabindex")).toBe("-1");

  expect(bold.getAttribute("aria-pressed")).toBe("false");
  fireEvent.click(bold);
  expect(bold.getAttribute("aria-pressed")).toBe("true");
});
