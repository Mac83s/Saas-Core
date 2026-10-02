import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import polishMessages from "../../../messages/pl.json";
import { PanelPage } from "./panel-page";

vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const path = {
  set current(value: string) {
    window.history.replaceState(null, "", value);
  },
};

function page(props: Parameters<typeof PanelPage>[0]) {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PanelPage {...props} />
    </NextIntlClientProvider>,
  );
}

test("a subtitle of data stays on a phone; an explanation gives way (UX-005)", () => {
  page({
    description: "Kto jest w firmie i co może.",
    subtitle: "Pracownik · w firmie od 10 marca 2025",
    title: "Paweł Pracownik",
  });
  expect(
    screen.getByText("Pracownik · w firmie od 10 marca 2025"),
  ).not.toHaveClass("max-sm:hidden");
  expect(screen.getByText("Kto jest w firmie i co może.")).toHaveClass(
    "max-sm:hidden",
  );
});

test("the eyebrow is the menu entry the page stands under, never the title twice (UX-003)", () => {
  path.current = "/panel/calendar/queue";
  const { unmount } = page({
    eyebrow: "Wizyty i rezerwacje",
    title: "Do przydzielenia",
  });
  expect(screen.getByText("Kalendarz")).toBeInTheDocument();
  expect(screen.queryByText("Wizyty i rezerwacje")).toBeNull();
  unmount();
  // On the entry's own page: its group.
  path.current = "/en/panel/calendar";
  page({ title: "Kalendarz" });
  expect(screen.getByText("Praca")).toBeInTheDocument();
});
