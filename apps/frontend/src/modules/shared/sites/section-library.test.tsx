import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";
import { materializeTemplatePhoto } from "@saas-core/api-client";
import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { SectionLibraryContent } from "./section-library";

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  materializeTemplatePhoto: vi.fn(),
}));
beforeEach(() => vi.clearAllMocks());

test.each(["pl", "en"] as const)(
  "copies a photo before inserting and reuses the retry key (%s)",
  async (locale) => {
    const onAdd = vi.fn();
    const onBusyChange = vi.fn();
    vi.mocked(materializeTemplatePhoto).mockRejectedValueOnce(
      new Error("Unavailable"),
    );
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent onAdd={onAdd} onBusyChange={onBusyChange} />
      </NextIntlClientProvider>,
    );
    const label =
      locale === "pl"
        ? "Dodaj: Klasyczne wprowadzenie"
        : "Add: Classic introduction";
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(onAdd).not.toHaveBeenCalled();
    vi.mocked(materializeTemplatePhoto).mockResolvedValueOnce({
      asset_id: "019ff20d-a000-7000-8000-000000000099",
    });
    fireEvent.click(screen.getByRole("button", { name: label }));
    await waitFor(() => expect(onAdd).toHaveBeenCalledOnce());
    const calls = vi.mocked(materializeTemplatePhoto).mock.calls;
    expect(calls[0]).toEqual(calls[1]);
    expect(onAdd.mock.calls[0][0].data.image.asset_id).toBe(
      "019ff20d-a000-7000-8000-000000000099",
    );
    expect(onAdd.mock.calls[0][0].data.image.alt).toContain(
      locale === "pl" ? "pracownia" : "studio",
    );
    expect(onBusyChange.mock.calls.at(-1)).toEqual([false]);
  },
);

test("limits initial thumbnail rendering and exposes the remaining catalogue", () => {
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent onAdd={vi.fn()} />
    </NextIntlClientProvider>,
  );
  expect(screen.getAllByRole("article")).toHaveLength(12);
  fireEvent.click(
    screen.getByRole("button", { name: "Show more layouts (60 remaining)" }),
  );
  expect(screen.getAllByRole("article")).toHaveLength(24);
  fireEvent.change(screen.getByLabelText("Category"), {
    target: { value: "core.faq" },
  });
  expect(screen.getAllByRole("article")).toHaveLength(12);
  expect(
    screen.getByRole("button", { name: "Show more layouts (8 remaining)" }),
  ).toBeDefined();
});

test.each(["pl", "en"] as const)(
  "searches the catalogue together with category and industry filters (%s)",
  (locale) => {
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent compact onAdd={vi.fn()} />
      </NextIntlClientProvider>,
    );
    fireEvent.change(
      screen.getByLabelText(locale === "pl" ? "Branża" : "Industry"),
      {
        target: { value: "medicine" },
      },
    );
    fireEvent.change(
      screen.getByLabelText(locale === "pl" ? "Kategoria" : "Category"),
      {
        target: { value: "core.feature_list" },
      },
    );
    const search = screen.getByRole("searchbox", {
      name: locale === "pl" ? "Szukaj układu" : "Find a layout",
    });
    fireEvent.change(search, {
      target: {
        value: locale === "pl" ? "  KONSULTACJI  " : "  CONSULTATION  ",
      },
    });
    expect(screen.getAllByRole("article")).toHaveLength(2);
    expect(
      screen.getByRole("button", {
        name:
          locale === "pl"
            ? "Dodaj: Ścieżka konsultacji"
            : "Add: Consultation pathway",
      }),
    ).toBeDefined();
    fireEvent.change(search, { target: { value: "missing layout" } });
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(screen.getByRole("status").textContent).toBe(
      locale === "pl"
        ? "Brak sekcji spełniających wybrane filtry."
        : "No sections match the selected filters.",
    );
    fireEvent.change(search, { target: { value: "" } });
    expect(screen.getAllByRole("article")).toHaveLength(12);
  },
);

test.each(["pl", "en"] as const)(
  "opens an accessible full preview from the compact rail and restores focus (%s)",
  async (locale) => {
    const onAdd = vi.fn();
    render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? pl : en}
      >
        <SectionLibraryContent compact onAdd={onAdd} />
      </NextIntlClientProvider>,
    );
    const trigger = screen.getByRole("button", {
      name:
        locale === "pl" ? "Podgląd: Rozwijane FAQ" : "Preview: Expandable FAQ",
    });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("region", {
        name: locale === "pl" ? "Podgląd sekcji" : "Section preview",
      }).textContent,
    ).toContain(locale === "pl" ? "Od czego zacząć?" : "How do I start?");
    const mobile = within(dialog).getByRole("button", {
      name: locale === "pl" ? "Widok telefonu" : "Phone view",
    });
    fireEvent.click(mobile);
    expect(mobile).toHaveAttribute("aria-pressed", "true");
    const result = await axe.run(dialog, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
    fireEvent.click(
      within(dialog).getByRole("button", {
        name: locale === "pl" ? "Zamknij" : "Close",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: locale === "pl" ? "Dodaj: Rozwijane FAQ" : "Add: Expandable FAQ",
      }),
    );
    expect(onAdd).toHaveBeenCalledOnce();
    expect(onAdd.mock.calls[0][0].block_type).toBe("core.faq");
    expect(materializeTemplatePhoto).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  },
);

test("keeps photo preparation and a retry error visible in the preview", async () => {
  let rejectPhoto!: (error: Error) => void;
  vi.mocked(materializeTemplatePhoto).mockImplementationOnce(
    () =>
      new Promise((_resolve, reject) => {
        rejectPhoto = reject;
      }),
  );
  const onAdd = vi.fn();
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <SectionLibraryContent compact onAdd={onAdd} />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Preview: Classic introduction" }),
  );
  const dialog = screen.getByRole("dialog");
  const add = within(dialog).getByRole("button", {
    name: "Add: Classic introduction",
  });
  fireEvent.click(add);
  expect(add).toBeDisabled();
  expect(within(dialog).getByRole("status")).toHaveTextContent(
    "Preparing the photo",
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.getByRole("dialog")).toBeDefined();
  rejectPhoto(new Error("Unavailable"));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Could not prepare the photo",
  );
  expect(add).not.toBeDisabled();
  expect(onAdd).not.toHaveBeenCalled();
});
