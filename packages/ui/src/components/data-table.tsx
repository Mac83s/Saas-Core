"use client";

import {
  cloneElement,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  functionalUpdate,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type Row,
  type RowData,
  type SortingFn,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  ChevronsUpDownIcon,
  EllipsisIcon,
  ListFilterIcon,
  SearchIcon,
} from "lucide-react";

import { Button, buttonVariants } from "#components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLinkItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#components/dropdown-menu";
import { Input } from "#components/input";
import { NativeSelect } from "#components/native-select";
import {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "#components/sheet";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "#components/table";
import { cn } from "#lib/utils";

// Modules import table types from here, never from TanStack directly (AGENTS:
// modules use the public API of @saas-core/ui only).
export type { ColumnDef, SortingState };

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- declaration merging needs the same parameters
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Names the value on a phone card and a header that is not plain text. */
    label?: string;
    /**
     * Titles the row's card on a phone; shown without a label. A column that
     * is not the table's first one adds `max-md:order-first` to its className.
     */
    primary?: boolean;
    /** Row actions: a narrow right cell, the card's top-right corner on a phone. */
    actions?: boolean;
    /** A value longer than a line: under its label on a phone card, not beside it. */
    long?: boolean;
    /** Amounts and counts: right-aligned with even digits, so they stand under each other (UX-010). */
    numeric?: boolean;
    className?: string;
  }
}

export type DataTableLabels = {
  search: string;
  empty: string;
  loading: string;
  pagination: string;
  previousPage: string;
  nextPage: string;
  pageOf: (page: number, pages: number) => string;
  /** „Filtry”, „Filtry (2)”: the phone's button to the list's filters. */
  filters?: (active: number) => string;
  /** The sheet's way back to the list, e.g. „Pokaż wyniki”. */
  showResults?: string;
  close?: string;
};

/** What a server-side list is asked for; the table never pages or sorts it. */
export type DataTableQuery = {
  pageIndex: number;
  pageSize: number;
  sorting: SortingState;
  search: string;
};

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

// "Łukasz" sorts after "Zenon" with a plain `<` — a collator puts it with L.
const localeSort: SortingFn<unknown> = (a, b, id) => {
  const x = a.getValue(id);
  const y = b.getValue(id);
  if (typeof x === "number" && typeof y === "number") return x - y;
  if (x instanceof Date && y instanceof Date) return x.getTime() - y.getTime();
  return collator.compare(String(x ?? ""), String(y ?? ""));
};

/**
 * Which ends of a wide table are scrolled out of sight. A table wider than
 * the page keeps its first column and shows a shadow where more is (R6).
 */
function useHiddenEdges() {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState({ start: false, end: false });
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const rest = box.scrollWidth - box.clientWidth - box.scrollLeft;
      const next = { start: box.scrollLeft > 1, end: rest > 1 };
      setEdges((current) =>
        current.start === next.start && current.end === next.end
          ? current
          : next,
      );
    };
    // The observer measures once on its own when it starts.
    const observer = new ResizeObserver(measure);
    observer.observe(box);
    if (box.firstElementChild) observer.observe(box.firstElementChild);
    box.addEventListener("scroll", measure, { passive: true });
    return () => {
      observer.disconnect();
      box.removeEventListener("scroll", measure);
    };
  }, [box]);
  return [setBox, edges] as const;
}

/**
 * Calls a header or cell renderer as a plain function. TanStack's `flexRender`
 * mounts it as a component, so a page that rebuilds its columns on every
 * render (the usual case) remounts every cell — and a dialog can no longer
 * return focus to the row menu it came from. The price: renderers use no
 * hooks; anything stateful is its own component (like `RowActions`).
 */
function renderSlot<P extends object>(
  slot: ReactNode | ((props: P) => ReactNode) | undefined,
  props: P,
): ReactNode {
  return typeof slot === "function" ? slot(props) : slot;
}

/** "Łódź" is found by "lodz": case, accents and ł do not matter. */
export function foldText(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ł/g, "l");
}

/**
 * The one list of the client panel (ADR-054): a table on a wide screen, a
 * stack of cards on a phone — the same DOM, so each action exists once.
 *
 * Without `rowCount` it sorts, searches and pages `data` itself. With
 * `rowCount` the API does that: `data` is the current page and every change
 * arrives in `onQueryChange` (search is debounced).
 */
export function DataTable<TData, TValue>({
  columns,
  data,
  caption,
  labels,
  getRowId,
  loading = false,
  searchable = false,
  searchText,
  toolbar,
  filters,
  activeFilters = 0,
  emptyAction,
  pageSize = 20,
  rowCount,
  query,
  onQueryChange,
  className,
}: {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  /** Read by screen readers; the visible title belongs to the page. */
  caption: string;
  labels: DataTableLabels;
  getRowId?: (row: TData) => string;
  loading?: boolean;
  searchable?: boolean;
  /** What search looks at in a row; defaults to its text and number columns. */
  searchText?: (row: TData) => string;
  /**
   * Filters next to the search field, in one row: `DataTableFilter`, and
   * `DataTableSearch` when the API searches. The page's actions (add, receive)
   * belong in its header, not here.
   */
  toolbar?: ReactNode;
  /**
   * The list's filters (`DataTableFilter`): in the row on a wide screen, under
   * one „Filtry (n)” button and a sheet on a phone, so the list starts on the
   * first screen (UX-008). `activeFilters` is the n.
   */
  filters?: ReactNode;
  activeFilters?: number;
  /** A way out of an empty list, e.g. "Clear the search". */
  emptyAction?: ReactNode;
  pageSize?: number;
  rowCount?: number;
  query?: DataTableQuery;
  onQueryChange?: (query: DataTableQuery) => void;
  className?: string;
}) {
  const manual = rowCount !== undefined;
  const [local, setLocal] = useState<DataTableQuery>({
    pageIndex: 0,
    pageSize,
    sorting: [],
    search: "",
  });
  const current = manual && query ? query : local;
  const update = (patch: Partial<DataTableQuery>) => {
    const next = { ...current, ...patch };
    if (manual) onQueryChange?.(next);
    else setLocal(next);
  };

  // Typing asks the API once per pause, not once per key.
  const [term, setTerm] = useState(current.search);
  const pending = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(pending.current), []);
  function search(value: string) {
    setTerm(value);
    clearTimeout(pending.current);
    if (!manual) return update({ search: value, pageIndex: 0 });
    pending.current = setTimeout(
      () => update({ search: value, pageIndex: 0 }),
      300,
    );
  }

  const pagination = {
    pageIndex: current.pageIndex,
    pageSize: current.pageSize,
  };
  const table = useReactTable({
    data,
    columns,
    ...(getRowId ? { getRowId: (row: TData) => getRowId(row) } : {}),
    // First click sorts ascending for every column; TanStack starts numbers
    // descending, which reads as a random order.
    defaultColumn: {
      sortingFn: localeSort as SortingFn<TData>,
      sortDescFirst: false,
    },
    state: {
      sorting: current.sorting,
      globalFilter: current.search,
      pagination,
    },
    onSortingChange: (updater) =>
      update({
        sorting: functionalUpdate(updater, current.sorting),
        pageIndex: 0,
      }),
    onPaginationChange: (updater) =>
      update(functionalUpdate(updater, pagination)),
    globalFilterFn: (row: Row<TData>, columnId, value: string) =>
      foldText(
        searchText ? searchText(row.original) : row.getValue(columnId),
      ).includes(foldText(value)),
    ...(searchText ? { getColumnCanGlobalFilter: () => true } : {}),
    manualPagination: manual,
    manualSorting: manual,
    manualFiltering: manual,
    autoResetPageIndex: false,
    ...(manual ? { rowCount } : {}),
    getCoreRowModel: getCoreRowModel(),
    ...(manual
      ? {}
      : {
          getSortedRowModel: getSortedRowModel(),
          getFilteredRowModel: getFilteredRowModel(),
          getPaginationRowModel: getPaginationRowModel(),
        }),
  });

  const pages = table.getPageCount();
  // A filter the page applies to `data` can leave the table past its last
  // page: step back instead of showing an empty page with no way home.
  const lastPage = Math.max(0, pages - 1);
  useEffect(() => {
    if (!manual && current.pageIndex > lastPage) {
      setLocal((query) => ({ ...query, pageIndex: lastPage }));
    }
  }, [manual, current.pageIndex, lastPage]);
  const rows = table.getRowModel().rows;
  const width = table.getVisibleLeafColumns().length;
  const [frame, edges] = useHiddenEdges();
  // A table wider than the page keeps its first column, the row's name, in
  // sight while the rest scrolls under it (R6, UX-036).
  const first = table.getVisibleLeafColumns()[0];
  const pinned = (id: string) =>
    (edges.start || edges.end) &&
    id === first?.id &&
    Boolean(first.columnDef.meta?.primary);
  const pin = cn(
    "md:sticky md:left-0 md:z-10 md:bg-background",
    edges.start &&
      "md:shadow-[6px_0_8px_-4px_color-mix(in_oklab,var(--foreground)_22%,transparent)]",
  );
  // A list with nothing in it and nothing narrowing it shows no search, no
  // filters and no column names over nothing — only its empty state and the
  // way out (UX-021). `toolbar` stays: a period or a warehouse is the page's
  // scope, and another one may have rows.
  const bare =
    !loading && data.length === 0 && !current.search && activeFilters === 0;

  return (
    <div className={cn("space-y-3", className)}>
      {((searchable || filters) && !bare) || toolbar ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {searchable && !bare ? (
            <DataTableSearch
              label={labels.search}
              onChange={search}
              value={term}
            />
          ) : null}
          {toolbar}
          {filters && !bare ? (
            <FilterSheet active={activeFilters} labels={labels}>
              {filters}
            </FilterSheet>
          ) : null}
        </div>
      ) : null}

      {loading && data.length === 0 ? (
        <ListSkeleton label={labels.loading} />
      ) : (
        // Explicit roles: a phone lays rows out as cards, and a table styled
        // with `display: block` loses its semantics in some browsers.
        <Table
          aria-busy={loading || undefined}
          className="max-md:block"
          containerClassName={cn(
            edges.end &&
              "md:shadow-[inset_-14px_0_10px_-8px_color-mix(in_oklab,var(--foreground)_22%,transparent)]",
          )}
          containerRef={frame}
          role="table"
        >
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader
            className={bare ? "sr-only" : "max-md:sr-only"}
            role="rowgroup"
          >
            {table.getHeaderGroups().map((group, row, groups) => (
              <TableRow key={group.id} role="row">
                {group.headers.map((header) => {
                  // Columns under a group heading („Magazyn”): a column
                  // outside any group spans the rows, named in the first.
                  // TanStack's header depth counts from 1, a column's from 0.
                  if (header.depth - 1 !== header.column.depth) return null;
                  const meta = header.column.columnDef.meta;
                  const sorted = header.column.getIsSorted();
                  const content = renderSlot(
                    header.column.columnDef.header,
                    header.getContext(),
                  );
                  const rows = header.column.columns.length
                    ? 1
                    : groups.length - row;
                  return (
                    <TableHead
                      aria-sort={
                        sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : undefined
                      }
                      className={cn(
                        "text-xs text-muted-foreground",
                        meta?.actions && "w-px",
                        meta?.numeric && "text-right",
                        meta?.className,
                        pinned(header.column.id) && pin,
                      )}
                      colSpan={header.colSpan > 1 ? header.colSpan : undefined}
                      rowSpan={rows > 1 ? rows : undefined}
                      key={header.id}
                      role="columnheader"
                      scope={header.column.columns.length ? "colgroup" : "col"}
                    >
                      {meta?.actions ? (
                        <span className="sr-only">{meta.label ?? content}</span>
                      ) : header.column.getCanSort() ? (
                        <button
                          className="-mx-2 inline-flex h-10 items-center gap-1 rounded-md px-2 outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                          onClick={header.column.getToggleSortingHandler()}
                          type="button"
                        >
                          {content}
                          {sorted === "asc" ? (
                            <ArrowUpIcon
                              aria-hidden="true"
                              className="size-3.5"
                            />
                          ) : sorted === "desc" ? (
                            <ArrowDownIcon
                              aria-hidden="true"
                              className="size-3.5"
                            />
                          ) : (
                            <ChevronsUpDownIcon
                              aria-hidden="true"
                              className="size-3.5 opacity-50"
                            />
                          )}
                        </button>
                      ) : (
                        content
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody className="max-md:block max-md:space-y-3" role="rowgroup">
            {rows.length === 0 ? (
              <TableRow className="max-md:block max-md:border-0!" role="row">
                <TableCell
                  className="py-6 text-center whitespace-normal text-muted-foreground max-md:block"
                  colSpan={width}
                  role="cell"
                >
                  {labels.empty}
                  {emptyAction ? (
                    <div className="mt-3">{emptyAction}</div>
                  ) : null}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow
                  className="group/row max-md:relative max-md:flex max-md:flex-col max-md:rounded-lg max-md:border! max-md:p-3 max-md:hover:bg-transparent"
                  key={row.id}
                  role="row"
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta;
                    const header = cell.column.columnDef.header;
                    const label =
                      meta?.label ??
                      (typeof header === "string" ? header : cell.column.id);
                    const content = renderSlot(
                      cell.column.columnDef.cell,
                      cell.getContext(),
                    );
                    // A card leaves out a field with nothing in it rather
                    // than show its label alone (UX-009).
                    const blank =
                      content === null ||
                      content === undefined ||
                      content === false ||
                      content === "";
                    return (
                      <TableCell
                        className={cn(
                          "py-3 align-top whitespace-normal",
                          meta?.actions
                            ? "py-1.5 text-right whitespace-nowrap max-md:absolute max-md:top-1.5 max-md:right-1.5 max-md:p-0"
                            : meta?.primary
                              ? "max-md:block max-md:px-0 max-md:pt-0 max-md:pr-12 max-md:pb-1 max-md:text-base max-md:group-has-[[data-phone-actions='2']]/row:pr-24"
                              : meta?.long
                                ? "max-md:block max-md:px-0 max-md:py-1"
                                : "max-md:flex max-md:justify-between max-md:gap-3 max-md:px-0 max-md:py-1",
                          blank && !meta?.actions && "max-md:hidden",
                          meta?.numeric && "tabular-nums md:text-right",
                          meta?.className,
                          pinned(cell.column.id) &&
                            cn(
                              pin,
                              "md:group-hover/row:bg-[color-mix(in_oklab,var(--muted)_50%,var(--background))]",
                            ),
                        )}
                        key={cell.id}
                        role="cell"
                      >
                        {meta?.actions || meta?.primary ? null : (
                          <span
                            aria-hidden="true"
                            className="shrink-0 text-muted-foreground md:hidden"
                          >
                            {label}
                          </span>
                        )}
                        <div
                          className={cn(
                            // An e-mail or an address breaks inside a card
                            // instead of leaving it.
                            "min-w-0 max-md:wrap-anywhere",
                            !meta?.actions &&
                              !meta?.primary &&
                              !meta?.long &&
                              "max-md:text-right",
                          )}
                        >
                          {content}
                        </div>
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}

      {pages > 1 ? (
        <nav
          aria-label={labels.pagination}
          className="flex items-center justify-end gap-2"
        >
          <p aria-live="polite" className="text-sm text-muted-foreground">
            {labels.pageOf(current.pageIndex + 1, pages)}
          </p>
          <Button
            aria-label={labels.previousPage}
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
            size="icon"
            variant="outline"
          >
            <ChevronLeftIcon aria-hidden="true" />
          </Button>
          <Button
            aria-label={labels.nextPage}
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
            size="icon"
            variant="outline"
          >
            <ChevronRightIcon aria-hidden="true" />
          </Button>
        </nav>
      ) : null}
    </div>
  );
}

/**
 * The filters in the toolbar's row on a wide screen; on a phone one button
 * opens them in a sheet (UX-008). Only one copy is mounted at a time: the
 * row's copy is hidden on a phone and leaves while the sheet is open, so a
 * filter's id and label stay unique. `DataTable` uses it for `filters`; a
 * page with filters above something that is not a table (the calendar's
 * grids) uses it directly.
 */
export function FilterSheet({
  active,
  labels,
  children,
}: {
  active: number;
  labels: Pick<DataTableLabels, "filters" | "showResults" | "close">;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const name = (count: number) =>
    labels.filters?.(count) ?? (count ? `Filters (${count})` : "Filters");
  return (
    <>
      {open ? null : <div className="contents max-sm:hidden">{children}</div>}
      <Sheet onOpenChange={setOpen} open={open} side="bottom">
        <SheetTrigger
          render={<Button className="sm:hidden" variant="outline" />}
        >
          <ListFilterIcon aria-hidden="true" />
          {name(active)}
        </SheetTrigger>
        <SheetContent closeLabel={labels.close}>
          <SheetHeader>
            <SheetTitle>{name(0)}</SheetTitle>
          </SheetHeader>
          <SheetBody className="flex flex-col gap-3 py-3">{children}</SheetBody>
          <SheetFooter>
            <SheetClose render={<Button />}>
              {labels.showResults ?? "Show results"}
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}

/** Rows of a list before they arrive; a page loading its data shows the same. */
export function ListSkeleton({ label }: { label: string }) {
  return (
    <div aria-busy="true" className="space-y-2">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((row) => (
        <div className="h-14 animate-pulse rounded-lg bg-muted" key={row} />
      ))}
    </div>
  );
}

/** The list's search field; a page whose API searches puts it in `toolbar`. */
export function DataTableSearch({
  label,
  value,
  onChange,
  placeholder,
  hint,
  id,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** A short prompt that fits the field, e.g. "Ear tag or number". */
  placeholder?: string;
  /** All that can be searched for, as the field's tooltip (UX-007). */
  hint?: string;
  id?: string;
}) {
  return (
    <div className="relative min-w-0 flex-1 basis-40 sm:w-72 sm:flex-none">
      <SearchIcon
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        aria-label={label}
        className="pl-9"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder ?? label}
        title={hint}
        type="search"
        value={value}
      />
    </div>
  );
}

/**
 * A filter of the list: its name and the control on one line, as tall as the
 * search field, so the toolbar reads as one row. Takes any control (a
 * combobox for a long list); `DataTableFilter` is the usual native select.
 */
export function DataTableField({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 max-sm:w-full">
      <label
        className="shrink-0 text-sm text-muted-foreground max-sm:w-24"
        htmlFor={htmlFor}
      >
        {label}
      </label>
      {/* As wide as its longest option, so „Wszystkie gospodarstwa” is never
          cut while the row has room (UX-007). */}
      <div className="min-w-0 flex-1 sm:max-w-80 sm:min-w-40 sm:flex-none">
        {children}
      </div>
    </div>
  );
}

/** A select filter; its first option is the unfiltered state ("All kinds"). */
export function DataTableFilter({
  label,
  id,
  children,
  ...props
}: Omit<ComponentProps<"select">, "id"> & { label: string; id: string }) {
  return (
    <DataTableField htmlFor={id} label={label}>
      <NativeSelect id={id} {...props}>
        {children}
      </NativeSelect>
    </DataTableField>
  );
}

export type RowAction = {
  label: string;
  /** Gets the button or the menu's trigger, so a dialog can return focus to it. */
  onSelect?: (trigger: HTMLElement | null) => void;
  /** Navigates instead of `onSelect`: the anchor to render, e.g. `<Link href>`. */
  link?: ReactElement;
  /** Always in sight as its own button on a wide screen; needs `icon`. */
  inline?: boolean;
  /**
   * The row's main action, „Edytuj”: an inline button on a phone too, beside
   * „…” (answer 41a). A row's only inline action is a button there anyway.
   */
  main?: boolean;
  icon?: ReactNode;
  destructive?: boolean;
  /** Draws a separator above this item. */
  separated?: boolean;
};

/**
 * A row's actions: the few that are used all the time as buttons, the rest
 * behind one "…" (ADR-057 pkt 7). The buttons keep their places from the
 * right edge, so an action only some rows have goes first. On a phone the card
 * has room for two buttons: the main action and "…" (answer 41a, 03.10).
 */
export function RowActions({
  label,
  items,
}: {
  label: string;
  items: RowAction[];
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  if (items.length === 0) return null;
  const shown = (item: RowAction) => Boolean(item.inline && item.icon);
  const only = items.length === 1 ? items[0] : undefined;
  const main =
    items.find((item) => item.main && shown(item)) ??
    (only && shown(only) ? only : undefined);
  const wideMenu = items.filter((item) => !shown(item));
  const phoneMenu = items.filter((item) => item !== main);
  const phoneOnly = (item: RowAction) =>
    shown(item) ? "md:hidden" : undefined;
  return (
    <div
      className="flex items-center justify-end gap-0.5"
      data-phone-actions={(main ? 1 : 0) + (phoneMenu.length ? 1 : 0)}
    >
      {items.filter(shown).map((item) => {
        const phone = item === main ? undefined : "max-md:hidden";
        // A link stays a link: Base UI's Button would give it role="button".
        return item.link ? (
          cloneElement(item.link as ReactElement<Record<string, unknown>>, {
            "aria-label": item.label,
            className: cn(
              buttonVariants({ size: "icon", variant: "ghost" }),
              phone,
              "md:size-9",
            ),
            key: item.label,
            title: item.label,
            children: item.icon,
          })
        ) : (
          <Button
            aria-label={item.label}
            className={cn(phone, "md:size-9")}
            key={item.label}
            onClick={(event) => item.onSelect?.(event.currentTarget)}
            size="icon"
            title={item.label}
            variant="ghost"
          >
            {item.icon}
          </Button>
        );
      })}
      {phoneMenu.length ? (
        <DropdownMenu>
          <DropdownMenuTrigger
            ref={trigger}
            render={
              <Button
                aria-label={label}
                // 44 px on a phone's card, row height on a wide table.
                className={wideMenu.length ? "md:size-9" : "md:hidden"}
                size="icon"
                variant="ghost"
              />
            }
          >
            <EllipsisIcon aria-hidden="true" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {phoneMenu.flatMap((item) => [
              ...(item.separated
                ? [
                    <DropdownMenuSeparator
                      className={phoneOnly(item)}
                      key={`${item.label}-separator`}
                    />,
                  ]
                : []),
              item.link ? (
                <DropdownMenuLinkItem
                  className={cn(
                    item.destructive && "text-destructive",
                    phoneOnly(item),
                  )}
                  key={item.label}
                  render={item.link}
                >
                  {item.icon}
                  {item.label}
                </DropdownMenuLinkItem>
              ) : (
                <DropdownMenuItem
                  className={cn(
                    item.destructive && "text-destructive",
                    phoneOnly(item),
                  )}
                  key={item.label}
                  onClick={() => item.onSelect?.(trigger.current)}
                >
                  {item.icon}
                  {item.label}
                </DropdownMenuItem>
              ),
            ])}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}
