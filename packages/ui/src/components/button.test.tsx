import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { Button } from "./button";

test("Button zachowuje nazwę dostępną i natywną semantykę", () => {
  render(<Button>Zapisz</Button>);

  const button = screen.getByRole("button", { name: "Zapisz" });
  expect(button.tagName).toBe("BUTTON");
  expect(button.getAttribute("data-slot")).toBe("button");
});
