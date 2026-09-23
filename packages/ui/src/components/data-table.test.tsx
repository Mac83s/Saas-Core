import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  DataTable,
  RowActions,
  type ColumnDef,
  type DataTableLabels,
  type DataTableQuery,
} from "./data-table";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

type Person = { id: string; name: string; city: string; visits: number };

const people: Person[] = [
  { id: "z", name: "Zenon", city: "Poznań", visits: 10 },
  { id: "l", name: "Łukasz", city: "Łódź", visits: 2 },
  { id: "k", name: "Kasia", city: "Kraków", visits: 9 },
];

const columns: ColumnDef<Person, unknown>[] = [
  { accessorKey: "name", header: "Name", meta: { primary: true } },
  { accessorKey: "city", header: "City" },
  { accessorKey: "visits", header: "Visits" },
];

const labels: DataTableLabels = {
  search: "Search",
  empty: "Nothing here",
  loading: "Loading",
  pagination: "Pages",
  previousPage: "Previous page",
  nextPage: "Next page",
  pageOf: (page, pages) => `Page ${page} of ${pages}`,
};

function names() {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent);
}

test("renders a captioned table whose cells carry their label for phone cards", () => {
  render(
    <DataTable
      caption="People"
      columns={columns}
      data={people}
      getRowId={(row) => row.id}
      labels={labels}
    />,
  );
  const table = screen.getByRole("table", { name: "People" });
  const [, first] = within(table).getAllByRole("row");
  const [name, city] = within(first).getAllByRole("cell");
  // The card title needs no label; the other values do, hidden from readers
  // because the column header already names them.
  expect(name.textContent).toBe("Zenon");
  expect(within(city).getByText("City").getAttribute("aria-hidden")).toBe(
    "true",
  );
  expect(names()).toEqual(["Zenon", "Łukasz", "Kasia"]);
});

test("sorts with the locale's alphabet and says so on the header", () => {
  render(
    <DataTable
      caption="People"
      columns={columns}
      data={people}
      labels={labels}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Name" }));
  expect(names()).toEqual(["Kasia", "Łukasz", "Zenon"]);
  expect(
    screen
      .getByRole("columnheader", { name: "Name" })
      .getAttribute("aria-sort"),
  ).toBe("ascending");
  fireEvent.click(screen.getByRole("button", { name: "Name" }));
  expect(names()).toEqual(["Zenon", "Łukasz", "Kasia"]);
  fireEvent.click(screen.getByRole("button", { name: "Visits" }));
  expect(names()).toEqual(["Łukasz", "Kasia", "Zenon"]);
});

test("search ignores case, accents and ł, and can look past the columns", () => {
  const { rerender } = render(
    <DataTable
      caption="People"
      columns={columns}
      data={people}
      labels={labels}
      searchable
    />,
  );
  fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
    target: { value: "LODZ" },
  });
  expect(names()).toEqual(["Łukasz"]);
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "warszawa" },
  });
  expect(screen.getByText("Nothing here")).toBeTruthy();

  rerender(
    <DataTable
      caption="People"
      columns={columns}
      data={people}
      labels={labels}
      searchText={(row) => `${row.name} ${row.id}-secret`}
      searchable
    />,
  );
  fireEvent.change(screen.getByRole("searchbox"), {
    target: { value: "k-secret" },
  });
  expect(names()).toEqual(["Kasia"]);
});

test("pages its own rows", () => {
  render(
    <DataTable
      caption="People"
      columns={columns}
      data={people}
      labels={labels}
      pageSize={2}
    />,
  );
  expect(names()).toEqual(["Zenon", "Łukasz"]);
  expect(screen.getByText("Page 1 of 2")).toBeTruthy();
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Previous page" })
      .disabled,
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(names()).toEqual(["Kasia"]);
  expect(screen.getByText("Page 2 of 2")).toBeTruthy();
});

test("shows a busy placeholder until the first rows arrive", () => {
  render(
    <DataTable
      caption="People"
      columns={columns}
      data={[]}
      labels={labels}
      loading
    />,
  );
  expect(screen.queryByRole("table")).toBeNull();
  expect(
    screen.getByText("Loading").parentElement?.getAttribute("aria-busy"),
  ).toBe("true");
});

test("in server mode it only asks: sorting, paging and a debounced search", () => {
  vi.useFakeTimers();
  const onQueryChange = vi.fn<(query: DataTableQuery) => void>();
  const query: DataTableQuery = {
    pageIndex: 0,
    pageSize: 2,
    sorting: [],
    search: "",
  };
  render(
    <DataTable
      caption="People"
      columns={columns}
      data={people.slice(0, 2)}
      labels={labels}
      onQueryChange={onQueryChange}
      query={query}
      rowCount={5}
      searchable
    />,
  );
  // The API already sorted and paged: the table shows the page as given.
  expect(screen.getByText("Page 1 of 3")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Name" }));
  expect(names()).toEqual(["Zenon", "Łukasz"]);
  expect(onQueryChange).toHaveBeenLastCalledWith({
    ...query,
    sorting: [{ id: "name", desc: false }],
  });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(onQueryChange).toHaveBeenLastCalledWith({ ...query, pageIndex: 1 });

  onQueryChange.mockClear();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "ka" } });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "kas" } });
  expect(onQueryChange).not.toHaveBeenCalled();
  act(() => vi.advanceTimersByTime(300));
  expect(onQueryChange).toHaveBeenCalledTimes(1);
  expect(onQueryChange).toHaveBeenCalledWith({ ...query, search: "kas" });
});

test("row actions hide without items and hand the trigger to the chosen one", async () => {
  const onSelect = vi.fn();
  const { container, rerender } = render(
    <RowActions items={[]} label="Actions for Kasia" />,
  );
  expect(container.innerHTML).toBe("");
  rerender(
    <RowActions
      items={[{ label: "Remove", onSelect, destructive: true }]}
      label="Actions for Kasia"
    />,
  );
  const trigger = screen.getByRole("button", { name: "Actions for Kasia" });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Remove" }));
  expect(onSelect).toHaveBeenCalledWith(trigger);
});
