import { fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { SiteLocalizationReport } from "@saas-core/api-client";

import messages from "../../../../messages/pl.json";
import { PublishDialog } from "./publish-dialog";

const api = vi.hoisted(() => ({ previewSitePublication: vi.fn() }));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({
  Link: ({
    children,
    ...props
  }: ComponentProps<"a"> & { children: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));

const PLAN = {
  ready_to_publish: true,
  languages: [
    {
      locale: "en",
      live: true,
      live_after: true,
      pages: [
        { page_id: "p1", page_name: "Start", outcome: "unchanged", reason: "" },
        { page_id: "p2", page_name: "Oferta", outcome: "publish", reason: "" },
        {
          page_id: "p3",
          page_name: "Cennik",
          outcome: "withheld",
          reason: "source_outdated",
        },
      ],
    },
    {
      locale: "de",
      live: false,
      live_after: false,
      pages: [
        {
          page_id: "p1",
          page_name: "Start",
          outcome: "skipped",
          reason: "untranslated_units",
        },
        {
          page_id: "p2",
          page_name: "Oferta",
          outcome: "skipped",
          reason: "locale_home_missing",
        },
        { page_id: "p3", page_name: "Cennik", outcome: "missing", reason: "" },
      ],
    },
  ],
};

function show(onConfirm = vi.fn()) {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <PublishDialog
        open
        onOpenChange={vi.fn()}
        siteId="site"
        report={{ default_locale: "pl" } as SiteLocalizationReport}
        locales={[
          { code: "pl", name: "Polski" },
          { code: "en", name: "English" },
          { code: "de", name: "Deutsch" },
        ]}
        publishing={false}
        onConfirm={onConfirm}
      />
    </NextIntlClientProvider>,
  );
  return onConfirm;
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("each language says whether it will be on the site and which pages need a look", async () => {
  api.previewSitePublication.mockResolvedValue(PLAN);
  const confirm = show();

  expect(await screen.findByText("English")).not.toBeNull();
  expect(screen.getByText("Na stronie")).not.toBeNull();
  expect(screen.getByText("Jeszcze nie na stronie")).not.toBeNull();
  expect(
    screen.getByText("1 strona wychodzi · 1 bez zmian · 1 do sprawdzenia"),
  ).not.toBeNull();
  expect(
    screen.getByText(/wstrzymana — strona źródłowa zmieniła cenę/),
  ).not.toBeNull();
  expect(
    screen.getByText(
      /pominięta: najpierw musi wyjść strona główna w tym języku/,
    ),
  ).not.toBeNull();
  // Each page that needs a look leads to its editor in that language.
  expect(
    screen
      .getByRole("link", { name: "Otwórz stronę Start w języku Deutsch" })
      .getAttribute("href"),
  ).toBe("/panel/sites/pages/p1?language=de");

  fireEvent.click(screen.getByRole("button", { name: "Opublikuj zmiany" }));
  expect(confirm).toHaveBeenCalledOnce();
  expect((await axe.run(document.body)).violations).toEqual([]);
});

test("a failed check does not stop the publication", async () => {
  api.previewSitePublication.mockRejectedValue(new Error("offline"));
  const confirm = show();

  expect(
    await screen.findByText(/Nie udało się sprawdzić wersji językowych/),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Opublikuj zmiany" }));
  expect(confirm).toHaveBeenCalledOnce();
});
