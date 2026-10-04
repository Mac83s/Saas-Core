import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, test, vi } from "vitest";

import { StayDatePicker, type StayDateLabels } from "./stay-date-picker";

const labels: StayDateLabels = {
  previousMonth: "Poprzedni miesiąc",
  nextMonth: "Następny miesiąc",
  pickStart: "Wybierz dzień przyjazdu",
  pickEnd: "Wybierz dzień wyjazdu",
  start: "Przyjazd",
  end: "Wyjazd",
  free: "wolny termin",
  unavailable: "niedostępny",
  clear: "Wybierz inny termin",
  loading: "Sprawdzam…",
  loadError: "Nie udało się wczytać terminów.",
  noDays: "W tym miesiącu nie ma wolnych terminów.",
  length: (count) => `${count} n.`,
};

function Picker({
  lastDay = "2027-01-15",
  loadEnds,
  loadStarts,
  retryAfterMs,
  searchKey = "domek",
}: {
  lastDay?: string;
  loadEnds: (start: string) => Promise<string[]>;
  loadStarts: (from: string, to: string) => Promise<string[]>;
  retryAfterMs?: number;
  searchKey?: string;
}) {
  const [days, setDays] = useState({ start: "", end: "" });
  return (
    <StayDatePicker
      end={days.end}
      labels={labels}
      lastDay={lastDay}
      loadEnds={loadEnds}
      loadStarts={loadStarts}
      locale="pl"
      onChange={(start, end) => setDays({ start, end })}
      retryAfterMs={retryAfterMs}
      searchKey={searchKey}
      start={days.start}
      today="2026-11-20"
      unit="night"
    />
  );
}

const day = (name: RegExp) => screen.findByRole("button", { name });

test("a month is asked for from today to its end, and the next one when it is opened", async () => {
  const loadStarts = vi.fn(async (from: string) =>
    from.startsWith("2026-11") ? ["2026-11-28"] : ["2026-12-05"],
  );
  const loadEnds = vi.fn(async () => ["2026-11-30", "2026-12-02"]);
  render(<Picker loadEnds={loadEnds} loadStarts={loadStarts} />);

  expect(screen.getByRole("group", { name: "listopad 2026" })).toBeVisible();
  expect(await screen.findByText("Wybierz dzień przyjazdu")).toBeVisible();
  // Never a day behind us, never more than the month.
  expect(loadStarts.mock.calls).toEqual([["2026-11-20", "2026-11-30"]]);
  expect(
    screen.getByRole("button", { name: "Poprzedni miesiąc" }),
  ).toBeDisabled();
  expect(await day(/ 27 listopada 2026, niedostępny/)).toBeDisabled();

  fireEvent.click(await day(/ 28 listopada 2026, wolny termin/));
  expect(loadEnds).toHaveBeenCalledWith("2026-11-28");
  expect(
    await screen.findByText("28 listopada · Wybierz dzień wyjazdu"),
  ).toBeVisible();
  // A departure may lie in the next month: it is offered there.
  fireEvent.click(screen.getByRole("button", { name: "Następny miesiąc" }));
  expect(screen.getByRole("group", { name: "grudzień 2026" })).toBeVisible();
  await waitFor(() =>
    expect(loadStarts).toHaveBeenLastCalledWith("2026-12-01", "2026-12-31"),
  );
  fireEvent.click(await day(/ 2 grudnia 2026, Wyjazd, 4 n\./));
  expect(screen.getByText("28 listopada – 2 grudnia · 4 n.")).toBeVisible();
  // A day in between belongs to the stay and is nobody's to pick.
  expect(await day(/ 1 grudnia 2026/)).toHaveAttribute("data-state", "between");

  // Another arrival starts over; the chosen one again clears.
  fireEvent.click(await day(/ 5 grudnia 2026, wolny termin/));
  expect(loadEnds).toHaveBeenLastCalledWith("2026-12-05");
  fireEvent.click(screen.getByRole("button", { name: "Wybierz inny termin" }));
  expect(await screen.findByText("Wybierz dzień przyjazdu")).toBeVisible();
});

test("the last month is the one of the form's last day, and its days end there", async () => {
  const loadStarts = vi.fn(async () => []);
  render(
    <Picker
      lastDay="2026-12-10"
      loadEnds={vi.fn(async () => [])}
      loadStarts={loadStarts}
    />,
  );

  expect(
    await screen.findByText("W tym miesiącu nie ma wolnych terminów."),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Następny miesiąc" }));
  await waitFor(() =>
    expect(loadStarts).toHaveBeenLastCalledWith("2026-12-01", "2026-12-10"),
  );
  expect(
    screen.getByRole("button", { name: "Następny miesiąc" }),
  ).toBeDisabled();
});

test("a question the server did not answer is put again by itself, and said to have failed only after that", async () => {
  const loadStarts = vi
    .fn<(from: string, to: string) => Promise<string[]>>()
    .mockRejectedValueOnce(new Error("throttled"))
    .mockResolvedValue(["2026-11-28"]);
  const { unmount } = render(
    <Picker
      loadEnds={vi.fn(async () => [])}
      loadStarts={loadStarts}
      retryAfterMs={5}
    />,
  );

  // Asked twice; the guest was never told anything failed.
  expect(await day(/ 28 listopada 2026, wolny termin/)).toBeEnabled();
  expect(loadStarts).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("Nie udało się wczytać terminów.")).toBeNull();
  unmount();

  const never = vi.fn(async () => {
    throw new Error("offline");
  });
  const { rerender } = render(
    <Picker
      loadEnds={vi.fn(async () => [])}
      loadStarts={never}
      retryAfterMs={5}
    />,
  );
  expect(
    await screen.findByText("Nie udało się wczytać terminów."),
  ).toBeVisible();
  expect(never).toHaveBeenCalledTimes(4);
  // Another search starts over.
  rerender(
    <Picker
      loadEnds={vi.fn(async () => [])}
      loadStarts={loadStarts}
      retryAfterMs={5}
      searchKey="domek#1"
    />,
  );
  expect(await day(/ 28 listopada 2026, wolny termin/)).toBeEnabled();
});

test("two months side by side are one question", async () => {
  const loadStarts = vi.fn(async () => ["2026-11-28", "2026-12-05"]);
  render(
    <StayDatePicker
      end=""
      labels={labels}
      lastDay="2027-01-15"
      loadEnds={vi.fn(async () => [])}
      loadStarts={loadStarts}
      locale="pl"
      months={2}
      onChange={() => undefined}
      searchKey="domek"
      start=""
      today="2026-11-20"
      unit="night"
    />,
  );

  expect(await day(/ 5 grudnia 2026, wolny termin/)).toBeEnabled();
  expect(await day(/ 28 listopada 2026, wolny termin/)).toBeEnabled();
  expect(loadStarts.mock.calls).toEqual([["2026-11-20", "2026-12-31"]]);
  // The next pair shares a month with this one: only the new month is asked.
  fireEvent.click(screen.getByRole("button", { name: "Następny miesiąc" }));
  await waitFor(() =>
    expect(loadStarts).toHaveBeenLastCalledWith("2027-01-01", "2027-01-15"),
  );
});
