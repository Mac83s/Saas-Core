import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { InlineText } from "./inline-text";

const props = {
  value: "Original",
  label: "Edit heading",
  instructions: "Enter saves; Escape cancels",
};
test("buffers text, commits once on Enter, preserves literal markup and restores focus", async () => {
  const commit = vi.fn();
  render(<InlineText {...props} onCommit={commit} />);
  fireEvent.click(screen.getByRole("button"));
  const input = screen.getByRole("textbox") as HTMLInputElement;
  expect(document.activeElement).toBe(input);
  fireEvent.change(input, { target: { value: "<script>alert(1)</script>" } });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(commit.mock.calls).toEqual([["<script>alert(1)</script>"]]);
  expect(document.querySelector("script")).toBeNull();
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button")),
  );
});
test("Escape cancels while multiline Enter and IME Enter do not submit", () => {
  const commit = vi.fn();
  const view = render(<InlineText {...props} multiline onCommit={commit} />);
  fireEvent.click(screen.getByRole("button"));
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "First\nSecond" } });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Escape" });
  expect(commit).not.toHaveBeenCalled();
  view.rerender(<InlineText {...props} onCommit={commit} />);
  fireEvent.click(screen.getByRole("button"));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "入力" } });
  fireEvent.keyDown(screen.getByRole("textbox"), {
    key: "Enter",
    isComposing: true,
  });
  expect(commit).not.toHaveBeenCalled();
  fireEvent.blur(screen.getByRole("textbox"));
  expect(commit.mock.calls).toEqual([["入力"]]);
});
test("the canvas button looks like the published text: case and underline carry over", () => {
  render(<InlineText {...props} onCommit={vi.fn()} />);
  const button = screen.getByRole("button");
  // Neither is inherited by a button (an inline-block) on its own.
  expect(button.style.textTransform).toBe("inherit");
  expect(button.style.textDecoration).toBe("inherit");
});
