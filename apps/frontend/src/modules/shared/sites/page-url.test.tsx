import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { PageUrlDialog, SiteRedirectsCard } from "./page-url";

const { changePageUrl, deleteSiteRedirect, listSiteRedirects } = vi.hoisted(
  () => ({
    changePageUrl: vi.fn(),
    deleteSiteRedirect: vi.fn(),
    listSiteRedirects: vi.fn(),
  }),
);

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  changePageUrl,
  deleteSiteRedirect,
  listSiteRedirects,
}));

const siteId = "019ff20d-b000-7000-8000-000000000001";
const pageId = "019ff20d-b000-7000-8000-000000000002";
const redirect = {
  id: "019ff20d-b000-7000-8000-000000000003",
  locale: "pl",
  from_path: "/oferta/",
  to_path: "/nasze-uslugi/",
  reason: "Nowa nazwa działu.",
};

beforeEach(() => {
  vi.clearAllMocks();
  changePageUrl.mockResolvedValue(redirect);
  deleteSiteRedirect.mockResolvedValue(undefined);
  listSiteRedirects.mockResolvedValue([redirect]);
});

afterEach(cleanup);

function renderDialog(onChanged = vi.fn().mockResolvedValue(undefined)) {
  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PageUrlDialog
        locale="pl"
        onChanged={onChanged}
        pageId={pageId}
        slug="oferta"
      />
    </NextIntlClientProvider>,
  );
  return { onChanged, rendered };
}

test("zmienia adres dopiero po podaniu uzasadnienia", async () => {
  const { onChanged } = renderDialog();
  fireEvent.click(screen.getByRole("button", { name: "Zmień adres" }));

  const slug = await screen.findByLabelText("Slug");
  fireEvent.change(slug, { target: { value: "nasze-uslugi" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Zmień adres i zostaw przekierowanie" }),
  );

  // The reason is not decoration: without it there is nothing left six months
  // later explaining why a ranking address moved.
  expect(await screen.findByText("Podaj powód zmiany adresu.")).not.toBeNull();
  expect(changePageUrl).not.toHaveBeenCalled();

  fireEvent.change(screen.getByLabelText("Dlaczego zmieniasz adres?"), {
    target: { value: "Nowa nazwa działu." },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Zmień adres i zostaw przekierowanie" }),
  );

  await waitFor(() => expect(changePageUrl).toHaveBeenCalledOnce());
  expect(changePageUrl.mock.calls[0]?.[0]).toBe(pageId);
  expect(changePageUrl.mock.calls[0]?.[1]).toEqual({
    locale: "pl",
    slug: "nasze-uslugi",
    reason: "Nowa nazwa działu.",
  });
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce());
});

test("wypisuje przekierowania i przechodzi axe", async () => {
  const rendered = render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SiteRedirectsCard siteId={siteId} />
    </NextIntlClientProvider>,
  );

  expect(await screen.findByText("/oferta/")).not.toBeNull();
  expect(screen.getByText("/nasze-uslugi/")).not.toBeNull();
  expect(screen.getByText("Nowa nazwa działu.")).not.toBeNull();
  expect(listSiteRedirects.mock.calls[0]?.[0]).toBe(siteId);

  const result = await axe.run(rendered.container);
  expect(result.violations).toHaveLength(0);
});

test("usuwa przekierowanie, którego nikt już nie potrzebuje", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SiteRedirectsCard siteId={siteId} />
    </NextIntlClientProvider>,
  );

  fireEvent.click(
    await screen.findByRole("button", {
      name: "Usuń przekierowanie z /oferta/",
    }),
  );

  await waitFor(() => expect(deleteSiteRedirect).toHaveBeenCalledOnce());
  expect(deleteSiteRedirect.mock.calls[0]?.[0]).toBe(redirect.id);
  // Gone from the list without a reload: a row that answers is a lie.
  await waitFor(() =>
    expect(
      screen.getByText("Żaden adres nie był jeszcze zmieniany."),
    ).not.toBeNull(),
  );
});
