import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { Checkbox } from "#components/checkbox";
import { RadioGroup, RadioGroupItem } from "#components/radio-group";

test("a radio group is named, keeps one choice and reports the new one", () => {
  let chosen = "";
  render(
    <>
      <span id="mode">Publikacja</span>
      <RadioGroup
        aria-labelledby="mode"
        defaultValue="automatic"
        onValueChange={(value) => {
          chosen = String(value);
        }}
      >
        <label>
          <RadioGroupItem value="automatic" />
          Automatycznie
        </label>
        <label>
          <RadioGroupItem value="review" />
          Po akceptacji
        </label>
      </RadioGroup>
    </>,
  );
  expect(screen.getByRole("radiogroup", { name: "Publikacja" })).toBeTruthy();
  const review = screen.getByRole("radio", { name: "Po akceptacji" });
  expect(review.getAttribute("aria-checked")).toBe("false");
  fireEvent.click(review);
  expect(chosen).toBe("review");
  expect(review.getAttribute("aria-checked")).toBe("true");
  expect(
    screen
      .getByRole("radio", { name: "Automatycznie" })
      .getAttribute("aria-checked"),
  ).toBe("false");
});

test("a disabled radio group takes no choice", () => {
  let chosen = "";
  render(
    <RadioGroup
      aria-label="Publikacja"
      disabled
      onValueChange={(value) => {
        chosen = String(value);
      }}
      value="automatic"
    >
      <label>
        <RadioGroupItem value="review" />
        Po akceptacji
      </label>
    </RadioGroup>,
  );
  fireEvent.click(screen.getByRole("radio", { name: "Po akceptacji" }));
  expect(chosen).toBe("");
});

test("a checkbox is named by its label and reports the tick", () => {
  let ticked = false;
  render(
    <label>
      <Checkbox
        onCheckedChange={(value) => {
          ticked = value;
        }}
      />
      Potwierdzam
    </label>,
  );
  const box = screen.getByRole("checkbox", { name: "Potwierdzam" });
  expect(box.getAttribute("aria-checked")).toBe("false");
  fireEvent.click(box);
  expect(ticked).toBe(true);
  expect(box.getAttribute("aria-checked")).toBe("true");
});
