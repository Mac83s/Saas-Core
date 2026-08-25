import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsPanel,
  TabsTab,
} from "#components/tabs";

function Fixture() {
  return (
    <Tabs defaultValue="structure">
      <TabsList>
        <TabsTab value="structure">Struktura</TabsTab>
        <TabsTab value="content">Treść</TabsTab>
        <TabsIndicator />
      </TabsList>
      <TabsPanel value="structure">Drzewo podstron</TabsPanel>
      <TabsPanel value="content">Sekcje strony</TabsPanel>
    </Tabs>
  );
}

test("Tabs exposes the ARIA tab pattern and switches panels", () => {
  render(<Fixture />);

  expect(screen.getByRole("tablist")).not.toBeNull();
  const structure = screen.getByRole("tab", { name: "Struktura" });
  const content = screen.getByRole("tab", { name: "Treść" });

  expect(structure.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tabpanel").textContent).toBe("Drzewo podstron");

  fireEvent.click(content);
  expect(content.getAttribute("aria-selected")).toBe("true");
  expect(structure.getAttribute("aria-selected")).toBe("false");
  expect(screen.getByRole("tabpanel").textContent).toBe("Sekcje strony");
});

test("Tabs uses roving tabindex so the strip is one tab stop", () => {
  render(<Fixture />);

  // Only the selected tab is reachable with Tab; the rest are entered with the
  // arrow keys. Base UI drives that navigation through a composite focus
  // manager which jsdom's synthetic events do not trigger, so the arrow keys
  // themselves are covered by the Playwright suite rather than here.
  expect(screen.getByRole("tab", { name: "Struktura" }).tabIndex).toBe(0);
  expect(screen.getByRole("tab", { name: "Treść" }).tabIndex).toBe(-1);
});
