import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { Slider } from "#components/slider";

test("the thumb is the named range input and moves with the keyboard", () => {
  let last = -1;
  render(
    <>
      <span id="distance">Odległość</span>
      <Slider
        aria-labelledby="distance"
        max={100}
        onValueChange={(value) => {
          last = Array.isArray(value) ? (value[0] ?? -1) : value;
        }}
        step={5}
        defaultValue={10}
      />
    </>,
  );
  // Base UI keeps the thumb hidden until it has measured the track and jsdom
  // never lays anything out, so the role query cannot name it here; the label
  // query finds the same input through aria-labelledby.
  const thumb = screen.getByLabelText("Odległość");
  expect(thumb.getAttribute("type")).toBe("range");
  fireEvent.keyDown(thumb, { key: "ArrowRight" });
  expect(last).toBe(15);
});
