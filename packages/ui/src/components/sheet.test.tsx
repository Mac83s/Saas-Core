import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  type SheetSide,
} from "./sheet";

afterEach(() => {
  vi.unstubAllGlobals();
});

function Filters({ side }: { side?: SheetSide }) {
  return (
    <Sheet side={side}>
      <SheetTrigger>Filtry (2)</SheetTrigger>
      <SheetContent closeLabel="Zamknij">
        <SheetHeader>
          <SheetTitle>Filtry</SheetTitle>
          <SheetDescription>Zawęź listę wizyt.</SheetDescription>
        </SheetHeader>
        <SheetBody>
          <label>
            Usługa <input />
          </label>
        </SheetBody>
        <SheetFooter>
          <SheetClose>Pokaż wyniki</SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function stubWidth(wide: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: wide,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
}

test("a sheet is a named modal dialog; Esc closes it and focus goes back", async () => {
  render(<Filters />);
  const trigger = screen.getByRole("button", { name: "Filtry (2)" });
  trigger.focus();
  fireEvent.click(trigger);

  const sheet = await screen.findByRole("dialog", { name: "Filtry" });
  expect(sheet.getAttribute("aria-modal")).toBe("true");
  expect(sheet.getAttribute("aria-describedby")).not.toBeNull();
  await waitFor(() =>
    expect(sheet.contains(document.activeElement)).toBe(true),
  );

  fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});

test("its own action closes it, and the close button has a name", async () => {
  render(<Filters />);
  fireEvent.click(screen.getByRole("button", { name: "Filtry (2)" }));
  await screen.findByRole("dialog", { name: "Filtry" });
  screen.getByRole("button", { name: "Zamknij" });

  fireEvent.click(screen.getByRole("button", { name: "Pokaż wyniki" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

test("from the bottom on a phone, from the right on a computer", async () => {
  stubWidth(false);
  const phone = render(<Filters />);
  fireEvent.click(screen.getByRole("button", { name: "Filtry (2)" }));
  expect((await screen.findByRole("dialog")).getAttribute("data-side")).toBe(
    "bottom",
  );
  phone.unmount();

  stubWidth(true);
  render(<Filters />);
  fireEvent.click(screen.getByRole("button", { name: "Filtry (2)" }));
  expect((await screen.findByRole("dialog")).getAttribute("data-side")).toBe(
    "right",
  );
});
