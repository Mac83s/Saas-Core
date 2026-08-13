import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  Sidebar,
  SidebarContent,
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "./sidebar";

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("mobilne menu obsługuje Escape i przywraca focus", async () => {
  render(
    <SidebarProvider>
      <SidebarTrigger
        aria-controls="test-sidebar"
        aria-label="Toggle navigation"
      />
      <Sidebar aria-label="Main navigation" id="test-sidebar">
        <SidebarContent>
          <a href="/start">Start</a>
          <button type="button">Close</button>
        </SidebarContent>
      </Sidebar>
      <SidebarInset>
        <button type="button">Background action</button>
      </SidebarInset>
    </SidebarProvider>,
  );
  const trigger = screen.getByRole("button", { name: "Toggle navigation" });
  trigger.focus();
  fireEvent.click(trigger);

  expect(
    screen.getByRole("dialog", { name: "Main navigation" }),
  ).not.toBeNull();
  expect(document.activeElement).toBe(
    screen.getByRole("link", { name: "Start" }),
  );
  expect(
    screen
      .getByRole("button", { name: "Background action", hidden: true })
      .parentElement?.hasAttribute("inert"),
  ).toBe(true);
  expect(document.body.style.overflow).toBe("hidden");
  fireEvent.keyDown(document, { key: "Escape" });

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.activeElement).toBe(trigger);
  expect(document.body.style.overflow).toBe("");
});

test("zamyka modalny tryb sidebara po poszerzeniu viewportu", async () => {
  const listeners = new Set<() => void>();
  let matches = true;
  const mediaQuery = {
    get matches() {
      return matches;
    },
    addEventListener: (_event: string, listener: () => void) =>
      listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) =>
      listeners.delete(listener),
  };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mediaQuery),
  );
  render(
    <SidebarProvider>
      <SidebarTrigger aria-label="Toggle navigation" />
      <Sidebar aria-label="Main navigation">
        <SidebarContent>
          <a href="/start">Start</a>
        </SidebarContent>
      </Sidebar>
      <SidebarInset>Content</SidebarInset>
    </SidebarProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Toggle navigation" }));
  expect(
    screen.getByRole("dialog", { name: "Main navigation" }),
  ).not.toBeNull();

  matches = false;
  act(() => listeners.forEach((listener) => listener()));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(document.body.style.overflow).toBe("");
});
