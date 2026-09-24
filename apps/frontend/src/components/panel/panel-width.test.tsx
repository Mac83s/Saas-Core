import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test } from "vitest";

import messages from "../../../messages/pl.json";
import { PanelMain, PanelWidthProvider, WidthToggle } from "./panel-width";

afterEach(() => {
  cleanup();
  document.cookie = "panel-width=; max-age=0; path=/";
});

test("one box for every page: a reading width, or edge to edge on request", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <PanelWidthProvider initialWide={false}>
        <WidthToggle />
        <PanelMain>page</PanelMain>
      </PanelWidthProvider>
    </NextIntlClientProvider>,
  );
  const main = screen.getByRole("main");
  const toggle = screen.getByRole("button", {
    name: "Widok na całą szerokość",
  });
  expect(main.className).toContain("max-w-7xl");
  expect(toggle).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(toggle);
  expect(main.className).not.toContain("max-w-7xl");
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  // The server reads it on the next page, so it opens as wide as it was left.
  expect(document.cookie).toContain("panel-width=full");
});
