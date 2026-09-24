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
    /** Titles the row's card on a phone; shown without a label. */
    primary?: boolean;
    /** Row actions: a narrow right cell, the card's top-right corner on a phone. */
    actions?: boolean;
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
  const rows = table.getRowModel().rows;
  const width = table.getVisibleLeafColumns().length;

  return (
    <div className={cn("space-y-3", className)}>
      {searchable || toolbar ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          {searchable ? (
            <DataTableSearch
              label={labels.search}
              onChange={search}
              value={term}
            />
          ) : null}
          {toolbar}
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
          role="table"
        >
          <TableCaption className="sr-only">{caption}</TableCaption>
          <TableHeader className="max-md:sr-only" role="rowgroup">
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id} role="row">
                {group.headers.map((header) => {
                  const meta = header.column.columnDef.meta;
                  const sorted = header.column.getIsSorted();
                  const content = header.isPlaceholder
                    ? null
                    : renderSlot(
                        header.column.columnDef.header,
                        header.getContext(),
                      );
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
                        meta?.className,
                      )}
                      key={header.id}
                      role="columnheader"
                      scope="col"
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
                  className="max-md:relative max-md:block max-md:rounded-lg max-md:border! max-md:p-3 max-md:hover:bg-transparent"
                  key={row.id}
                  role="row"
                >
                  {row.getVisibleCells().map((cell) => {
                    const meta = cell.column.columnDef.meta;
                    const header = cell.column.columnDef.header;
                    const label =
                      meta?.label ??
                      (typeof header === "string" ? header : cell.column.id);
                    return (
                      <TableCell
                        className={cn(
                          "py-3 align-top whitespace-normal",
                          meta?.actions
                            ? "py-1.5 text-right whitespace-nowrap max-md:absolute max-md:top-1.5 max-md:right-1.5 max-md:p-0"
                            : meta?.primary
                              ? "max-md:block max-md:px-0 max-md:pt-0 max-md:pr-12 max-md:pb-1 max-md:text-base"
                              : "max-md:flex max-md:justify-between max-md:gap-3 max-md:px-0 max-md:py-1",
                          meta?.className,
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
                            "min-w-0",
                            !meta?.actions &&
                              !meta?.primary &&
                              "max-md:text-right",
                          )}
                        >
                          {renderSlot(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
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
  id,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** What can be searched for, e.g. "Ear tag, name or number". */
  placeholder?: string;
  id?: string;
}) {
  return (
    <div className="relative w-full sm:w-72">
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
      <div className="min-w-0 flex-1 sm:w-48 sm:flex-none">{children}</div>
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
  icon?: ReactNode;
  destructive?: boolean;
  /** Draws a separator above this item. */
  separated?: boolean;
};

/**
 * A row's actions: the few that are used all the time as buttons, the rest
 * behind one "…" (ADR-057). On a phone the card has room for one button, so
 * everything is in the menu there.
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
  const phoneOnly = (item: RowAction) =>
    shown(item) ? "md:hidden" : undefined;
  return (
    <div className="flex items-center justify-end gap-0.5">
      {items.filter(shown).map((item) =>
        // A link stays a link: Base UI's Button would give it role="button".
        item.link ? (
          cloneElement(item.link as ReactElement<Record<string, unknown>>, {
            "aria-label": item.label,
            className: cn(
              buttonVariants({ size: "icon", variant: "ghost" }),
              "max-md:hidden md:size-9",
            ),
            key: item.label,
            title: item.label,
            children: item.icon,
          })
        ) : (
          <Button
            aria-label={item.label}
            className="max-md:hidden md:size-9"
            key={item.label}
            onClick={(event) => item.onSelect?.(event.currentTarget)}
            size="icon"
            title={item.label}
            variant="ghost"
          >
            {item.icon}
          </Button>
        ),
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          ref={trigger}
          render={
            <Button
              aria-label={label}
              // 44 px on a phone's card, row height on a wide table.
              className={items.every(shown) ? "md:hidden" : "md:size-9"}
              size="icon"
              variant="ghost"
            />
          }
        >
          <EllipsisIcon aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {items.flatMap((item) => [
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
    </div>
  );
}
