import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { PanelPage } from "./panel-page";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

test("a subtitle of data stays on a phone; an explanation gives way (UX-005)", () => {
  render(
    <PanelPage
      description="Kto jest w firmie i co może."
      subtitle="Pracownik · w firmie od 10 marca 2025"
      title="Paweł Pracownik"
    />,
  );
  expect(
    screen.getByText("Pracownik · w firmie od 10 marca 2025"),
  ).not.toHaveClass("max-sm:hidden");
  expect(screen.getByText("Kto jest w firmie i co może.")).toHaveClass(
    "max-sm:hidden",
  );
});
