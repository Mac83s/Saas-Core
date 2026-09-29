import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { PublicationHistory } from "./publication-history";

const author = {
  id: "019ff20d-e000-7000-8000-0000000000a0",
  email: "ania@example.test",
};
const live = {
  id: "019ff20d-e000-7000-8000-000000000002",
  site_id: "019ff20d-e000-7000-8000-000000000001",
  sequence: 2,
  snapshot_schema_version: 1,
  snapshot_hash: "b".repeat(64),
  source_publication_id: "019ff20d-e000-7000-8000-000000000003",
  created_by: author,
  created_at: "2026-09-28T12:00:00Z",
};
const older = {
  ...live,
  id: "019ff20d-e000-7000-8000-000000000003",
  sequence: 1,
  snapshot_hash: "a".repeat(64),
  source_publication_id: null,
  created_at: "2026-09-27T12:00:00Z",
};

afterEach(cleanup);

function renderHistory(
  onRollback = vi.fn(),
  { locale = "pl", loading = false } = {},
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <PublicationHistory
        currentPublicationId={live.id}
        loading={loading}
        onRollback={onRollback}
        publications={[live, older]}
      />
    </NextIntlClientProvider>,
  );
}

test("lists publications as a table and restores an older one", async () => {
  const onRollback = vi.fn();
  const rendered = renderHistory(onRollback);

  const table = screen.getByRole("table", { name: "Publikacje witryny" });
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(3);
  const current = within(table).getByText("Publikacja #2").closest("tr")!;
  expect(within(current).getByText("Bieżąca")).not.toBeNull();
  expect(within(current).getByText("ania@example.test")).not.toBeNull();
  // The live publication has nothing to go back to.
  expect(within(current).queryByRole("button")).toBeNull();
  expect((await axe.run(rendered.container)).violations).toHaveLength(0);

  const row = within(table).getByText("Publikacja #1").closest("tr")!;
  fireEvent.click(
    within(row).getByRole("button", { name: "Przywróć jako nową publikację" }),
  );
  expect(onRollback).toHaveBeenCalledWith(older);
});

test("does not start a second rollback while one is running (EN)", () => {
  const onRollback = vi.fn();
  renderHistory(onRollback, { locale: "en", loading: true });

  fireEvent.click(
    screen.getByRole("button", { name: "Restore as new publication" }),
  );
  expect(onRollback).not.toHaveBeenCalled();
});

test("offers older publications only while the API has them", () => {
  const onLoadOlder = vi.fn();
  const { rerender } = render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <PublicationHistory
        currentPublicationId={live.id}
        loading={false}
        onLoadOlder={onLoadOlder}
        onRollback={vi.fn()}
        publications={[live]}
      />
    </NextIntlClientProvider>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Wczytaj starsze publikacje" }),
  );
  expect(onLoadOlder).toHaveBeenCalledOnce();

  rerender(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      <PublicationHistory
        currentPublicationId={live.id}
        loading={false}
        onRollback={vi.fn()}
        publications={[live, older]}
      />
    </NextIntlClientProvider>,
  );
  expect(
    screen.queryByRole("button", { name: "Wczytaj starsze publikacje" }),
  ).toBeNull();
});
