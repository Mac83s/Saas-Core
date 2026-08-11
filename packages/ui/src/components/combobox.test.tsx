import { useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "./combobox";

function Fixture({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<string | null>(null);
  const items = ["Alpha", "Beta", "Gamma"];
  return (
    <div>
      <label htmlFor="test-combobox">Choose item</label>
      <Combobox
        disabled={disabled}
        items={items}
        onValueChange={setValue}
        value={value}
      >
        <ComboboxInput
          disabled={disabled}
          id="test-combobox"
          triggerLabel="Show choices"
        />
        <ComboboxContent>
          <ComboboxEmpty>No matches</ComboboxEmpty>
          <ComboboxList>
            {items.map((item) => (
              <ComboboxItem key={item} value={item}>
                {item}
              </ComboboxItem>
            ))}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
      <output aria-label="Selected item">{value}</output>
    </div>
  );
}

afterEach(cleanup);

test("Combobox supports arrows, Enter, filtering, Escape, and focus", async () => {
  render(<Fixture />);
  const input = screen.getByRole("combobox", { name: "Choose item" });

  input.focus();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(await screen.findByRole("option", { name: "Alpha" })).not.toBeNull();
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(
    screen.getByRole("status", { name: "Selected item" }).textContent,
  ).toContain("Beta");

  fireEvent.change(input, { target: { value: "missing" } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(await screen.findByText("No matches")).not.toBeNull();
  fireEvent.keyDown(input, { key: "Escape" });
  await waitFor(() => expect(document.activeElement).toBe(input));
  expect(screen.queryByText("No matches")).toBeNull();
});

test("Combobox exposes a disabled input", () => {
  render(<Fixture disabled />);
  expect(
    (screen.getByRole("combobox", { name: "Choose item" }) as HTMLInputElement)
      .disabled,
  ).toBe(true);
  expect(
    (screen.getByRole("button", { name: "Show choices" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
