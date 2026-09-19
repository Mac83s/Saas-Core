import { useState } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { ReorderList } from "./reorder-list";

afterEach(cleanup);
function Fixture({ disabled = false }: { disabled?: boolean }) {
  const [items, setItems] = useState([{ id: "a" }, { id: "b" }, { id: "c" }]);
  return (
    <ReorderList
      items={items}
      label="Sections"
      instructions="Use arrow keys"
      disabled={disabled}
      handleLabel={(item) => `Move ${item.id}`}
      movedLabel={(item, position) => `${item.id}: ${position}`}
      onMove={(from, to) => {
        setItems((previous) => {
          const next = [...previous];
          next.splice(to, 0, ...next.splice(from, 1));
          return next;
        });
      }}
    >
      {(item, _index, handle) => (
        <>
          {handle}
          <span>{item.id}</span>
        </>
      )}
    </ReorderList>
  );
}
function transfer() {
  const values = new Map<string, string>();
  return {
    setData: (key: string, value: string) => values.set(key, value),
    getData: (key: string) => values.get(key) ?? "",
    effectAllowed: "",
    dropEffect: "",
  };
}
function order() {
  return screen
    .getAllByRole("listitem")
    .map((item) => item.getAttribute("data-reorder-id"));
}

test("keyboard moves the same item, keeps focus, announces and respects boundaries", async () => {
  render(<Fixture />);
  const handle = screen.getByRole("button", { name: "Move a" });
  handle.focus();
  fireEvent.keyDown(handle, { key: "ArrowDown" });
  expect(order()).toEqual(["b", "a", "c"]);
  expect(screen.getByRole("status").textContent).toBe("a: 2");
  await waitFor(() => expect(document.activeElement).toBe(handle));
  fireEvent.keyDown(handle, { key: "ArrowUp" });
  fireEvent.keyDown(handle, { key: "ArrowUp" });
  expect(order()).toEqual(["a", "b", "c"]);
});

test("drop moves rather than swaps items; external and cancelled drags cannot mutate", () => {
  render(<Fixture />);
  const dataTransfer = transfer();
  fireEvent.drop(screen.getAllByRole("listitem")[2], { dataTransfer });
  expect(order()).toEqual(["a", "b", "c"]);
  const handle = screen.getByRole("button", { name: "Move a" });
  fireEvent.dragStart(handle, { dataTransfer });
  fireEvent.dragOver(screen.getAllByRole("listitem")[2], { dataTransfer });
  expect(
    screen.getAllByRole("listitem")[2].getAttribute("data-drop-edge"),
  ).toBe("after");
  fireEvent.drop(screen.getAllByRole("listitem")[2], { dataTransfer });
  expect(order()).toEqual(["b", "c", "a"]);
  fireEvent.dragStart(handle, { dataTransfer });
  fireEvent.dragEnd(handle);
  fireEvent.drop(screen.getAllByRole("listitem")[0], { dataTransfer });
  expect(order()).toEqual(["b", "c", "a"]);
});

test("a disabled editor ignores a drag begun before saving", () => {
  const view = render(<Fixture />);
  const dataTransfer = transfer();
  fireEvent.dragStart(screen.getByRole("button", { name: "Move a" }), {
    dataTransfer,
  });
  view.rerender(<Fixture disabled />);
  fireEvent.drop(screen.getAllByRole("listitem")[2], { dataTransfer });
  expect(order()).toEqual(["a", "b", "c"]);
});
