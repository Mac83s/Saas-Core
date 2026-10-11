import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { InputOTP, InputOTPGroup, InputOTPSlot } from "#components/input-otp";

function Field({ invalid = false }: { invalid?: boolean }) {
  const [value, setValue] = React.useState("");
  return (
    <>
      <label htmlFor="code">Kod</label>
      <InputOTP
        aria-invalid={invalid}
        id="code"
        onChange={setValue}
        value={value}
      >
        <InputOTPGroup>
          {[0, 1, 2, 3, 4, 5].map((index) => (
            <InputOTPSlot index={index} key={index} />
          ))}
        </InputOTPGroup>
      </InputOTP>
      <output data-testid="value">{value}</output>
    </>
  );
}

test("one labelled digits-only input, with the one-time-code hints", () => {
  render(<Field />);
  const input = screen.getByLabelText("Kod");
  expect(input.getAttribute("inputmode")).toBe("numeric");
  expect(input.getAttribute("autocomplete")).toBe("one-time-code");
  expect(input.getAttribute("maxlength")).toBe("6");
});

test("typed digits are kept and letters are refused", () => {
  render(<Field />);
  const input = screen.getByLabelText("Kod");
  fireEvent.change(input, { target: { value: "12a" } });
  expect(screen.getByTestId("value").textContent).toBe("");
  fireEvent.change(input, { target: { value: "123456" } });
  expect(screen.getByTestId("value").textContent).toBe("123456");
});

test("an invalid field marks the input", () => {
  render(<Field invalid />);
  expect(screen.getByLabelText("Kod").getAttribute("aria-invalid")).toBe(
    "true",
  );
});
