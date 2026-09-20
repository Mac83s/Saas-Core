import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
