import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  DataTable,
  DataTableFilter,
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

test("steps back to the last page when a filter leaves fewer rows", () => {
  const view = (data: Person[]) => (
    <DataTable
      caption="People"
      columns={columns}
      data={data}
      labels={labels}
      pageSize={2}
    />
  );
  const { rerender } = render(view(people));
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(names()).toEqual(["Kasia"]);

  rerender(view(people.filter((person) => person.visits > 5)));
  expect(names()).toEqual(["Zenon", "Kasia"]);
  expect(screen.queryByText(/Page 2/)).toBeNull();
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

test("inline row actions are buttons of their own; on a phone the main one stays beside „…”", async () => {
  const open = vi.fn();
  const remove = vi.fn();
  render(
    <RowActions
      items={[
        { label: "Call", onSelect: vi.fn(), inline: true, icon: <svg /> },
        {
          label: "Edit",
          onSelect: open,
          inline: true,
          main: true,
          icon: <svg />,
        },
        { label: "Remove", onSelect: remove, destructive: true },
      ]}
      label="Actions for Kasia"
    />,
  );
  const button = screen.getByRole("button", { name: "Edit" });
  fireEvent.click(button);
  expect(open).toHaveBeenCalledWith(button);
  // The main action („Edytuj”) is a button on a phone too (answer 41a);
  // another inline one goes into the phone's menu.
  expect(button.className).not.toContain("max-md:hidden");
  expect(screen.getByRole("button", { name: "Call" }).className).toContain(
    "max-md:hidden",
  );
  fireEvent.click(screen.getByRole("button", { name: "Actions for Kasia" }));
  const copy = await screen.findByRole("menuitem", { name: "Call" });
  expect(copy.className).toContain("md:hidden");
  expect(screen.queryByRole("menuitem", { name: "Edit" })).toBeNull();
  expect(
    screen.getByRole("menuitem", { name: "Remove" }).className,
  ).not.toContain("md:hidden");
});

test("a row whose only action is inline shows that button alone", () => {
  render(
    <RowActions
      items={[
        {
          label: "Edit",
          link: <a href="/farms/1" />,
          inline: true,
          icon: <svg />,
        },
      ]}
      label="Actions for Kasia"
    />,
  );
  const edit = screen.getByRole("link", { name: "Edit" });
  expect(edit.getAttribute("href")).toBe("/farms/1");
  expect(edit.className).not.toContain("max-md:hidden");
  expect(
    screen.queryByRole("button", { name: "Actions for Kasia" }),
  ).toBeNull();
});

test("a labelled inline action says its words beside the icon on a wide screen, and keeps one name", () => {
  render(
    <RowActions
      items={[
        {
          label: "Use the preset",
          onSelect: vi.fn(),
          inline: true,
          labelled: true,
          icon: <svg />,
        },
      ]}
      label="Actions: Stay"
    />,
  );
  // One button, named once: the visible words are for the eye only.
  const button = screen.getByRole("button", { name: "Use the preset" });
  const words = button.querySelector("span");
  expect(words?.textContent).toBe("Use the preset");
  expect(words?.getAttribute("aria-hidden")).toBe("true");
  // A phone's card has room for the icon alone.
  expect(words?.className).toContain("max-md:hidden");
  expect(button.getAttribute("title")).toBeNull();
});

test("two inline actions: „…” only on a phone, for the one that does not fit", () => {
  render(
    <RowActions
      items={[
        { label: "Open", onSelect: vi.fn(), inline: true, icon: <svg /> },
        { label: "Edit", onSelect: vi.fn(), inline: true, icon: <svg /> },
      ]}
      label="Actions for Kasia"
    />,
  );
  expect(
    screen.getByRole("button", { name: "Actions for Kasia" }).className,
  ).toContain("md:hidden");
});

test("a filter names its select on the same line", () => {
  render(
    <DataTableFilter id="kind" label="Kind" onChange={() => undefined} value="">
      <option value="">All kinds</option>
    </DataTableFilter>,
  );
  expect(screen.getByRole("combobox", { name: "Kind" })).toBeTruthy();
});

test("on a phone the filters wait under one button; one copy at a time", async () => {
  function Filtered() {
    return (
      <DataTable
        activeFilters={1}
        caption="People"
        columns={columns}
        data={people}
        filters={
          <DataTableFilter
            id="city"
            label="City"
            onChange={() => undefined}
            value="lodz"
          >
            <option value="">All cities</option>
            <option value="lodz">Łódź</option>
          </DataTableFilter>
        }
        labels={{
          ...labels,
          filters: (count) => (count ? `Filters (${count})` : "Filters"),
          showResults: "Show results",
          close: "Close",
        }}
        searchable
      />
    );
  }
  render(<Filtered />);
  // A wide screen's row: the search and the filter itself.
  expect(screen.getAllByRole("combobox", { name: "City" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Filters (1)" }));

  const sheet = await screen.findByRole("dialog", { name: "Filters" });
  expect(screen.getAllByRole("combobox", { name: "City" })).toHaveLength(1);
  within(sheet).getByRole("combobox", { name: "City" });
  fireEvent.click(within(sheet).getByRole("button", { name: "Show results" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getAllByRole("combobox", { name: "City" })).toHaveLength(1);
});

test("an empty list with nothing narrowing it shows its empty state, not a toolbar over nothing", () => {
  const { rerender } = render(
    <DataTable
      caption="People"
      columns={columns}
      data={[]}
      emptyAction={<button type="button">Add the first person</button>}
      labels={labels}
      searchable
      toolbar={<span>Period</span>}
    />,
  );
  expect(screen.queryByRole("searchbox")).toBeNull();
  // The page's scope stays: another period may have rows.
  screen.getByText("Period");
  // The column names stay for a screen reader only.
  expect(screen.getAllByRole("rowgroup")[0].className).toContain("sr-only");
  screen.getByText("Nothing here");
  screen.getByRole("button", { name: "Add the first person" });

  // A filter that leaves nothing keeps the bar, so it can be undone.
  rerender(
    <DataTable
      activeFilters={1}
      caption="People"
      columns={columns}
      data={[]}
      filters={<span>City filter</span>}
      labels={labels}
      searchable
    />,
  );
  screen.getByRole("searchbox", { name: "Search" });
});
