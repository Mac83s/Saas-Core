import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "./dialog";

test("Dialog exposes accessible title and restores focus after Escape", async () => {
  render(
    <Dialog>
      <DialogTrigger>Open settings</DialogTrigger>
      <DialogContent>
        <DialogTitle>Organization settings</DialogTitle>
        <DialogDescription>Change organization defaults.</DialogDescription>
      </DialogContent>
    </Dialog>,
  );
  const trigger = screen.getByRole("button", { name: "Open settings" });

  trigger.focus();
  fireEvent.click(trigger);
  expect(
    await screen.findByRole("dialog", { name: "Organization settings" }),
  ).not.toBeNull();
  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });

  expect(screen.queryByRole("dialog")).toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});
