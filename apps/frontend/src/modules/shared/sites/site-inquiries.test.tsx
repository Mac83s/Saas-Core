import axe from "axe-core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SiteInquiries } from "./site-inquiries";

const { listSites, listSiteInquiries, markSiteInquiryRead } = vi.hoisted(
  () => ({
    listSites: vi.fn(),
    listSiteInquiries: vi.fn(),
    markSiteInquiryRead: vi.fn(),
  }),
);
vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  listSites,
  listSiteInquiries,
  markSiteInquiryRead,
}));
const first = {
  id: "10000000-0000-4000-8000-000000000001",
  site_id: "site-1",
  page_path: "/contact/",
  name: "Example Visitor",
  email: "visitor@example.test",
  phone: "+48 000 000 000",
  message: "First private inquiry",
  created_at: "2026-09-21T12:00:00Z",
  read_at: null,
  email_status: "queued",
};
const second = {
  ...first,
  id: "10000000-0000-4000-8000-000000000002",
  name: "Second Visitor",
  message: "Second private inquiry",
  read_at: "2026-09-21T12:02:00Z",
  email_status: "delivered",
};

beforeEach(() => {
  vi.resetAllMocks();
  listSites.mockResolvedValue({
    items: [
      { id: "site-1", name: "Example Website" },
      { id: "site-2", name: "Second Website" },
    ],
    next_cursor: null,
  });
  listSiteInquiries.mockResolvedValue({
    items: [first, second],
    next_cursor: null,
  });
  markSiteInquiryRead.mockImplementation(async (id) => ({
    ...(id === first.id ? first : second),
    read_at: "2026-09-21T13:00:00Z",
  }));
});
afterEach(cleanup);
function renderInbox(locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <SiteInquiries />
    </NextIntlClientProvider>,
  );
}
function problem(code: string, status = 403) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Denied",
    status,
    code,
    detail: "Private server detail",
    correlation_id: null,
  });
}

test.each(["pl", "en"] as const)(
  "skrzynka %s pokazuje treść tylko wybranego zapytania i umożliwia ręczną odpowiedź",
  async (locale) => {
    const result = renderInbox(locale);
    const firstButton = await screen.findByRole("button", {
      name: /Example Visitor/,
    });
    expect(screen.queryByText(first.message)).toBeNull();
    expect(screen.queryByText(second.message)).toBeNull();
    expect((await axe.run(result.container)).violations).toHaveLength(0);
    fireEvent.click(firstButton);
    expect(await screen.findByText(first.message)).not.toBeNull();
    expect(
      screen.getByRole("heading", { name: "Example Visitor" }),
    ).toHaveFocus();
    expect(screen.queryByText(second.message)).toBeNull();
    await waitFor(() =>
      expect(markSiteInquiryRead).toHaveBeenCalledWith(
        first.id,
        expect.any(String),
      ),
    );
    expect(
      screen.getByRole("link", {
        name: locale === "pl" ? "Odpowiedz e-mailem" : "Reply by email",
      }),
    ).toHaveAttribute("href", "mailto:visitor%40example.test");
    expect(
      screen.getByText(locale === "pl" ? "W kolejce" : "Queued"),
    ).not.toBeNull();
    expect((await axe.run(result.container)).violations).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /Second Visitor/ }));
    expect(await screen.findByText(second.message)).not.toBeNull();
    expect(screen.queryByText(first.message)).toBeNull();
    expect(markSiteInquiryRead).toHaveBeenCalledTimes(1);
  },
);

test("ponawia oznaczenie odczytu tym samym kluczem i pozostawia czytelną wiadomość po błędzie", async () => {
  markSiteInquiryRead.mockRejectedValueOnce(new Error("offline"));
  renderInbox();
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "nie udało się oznaczyć",
  );
  expect(screen.getByText(first.message)).not.toBeNull();
  const key = markSiteInquiryRead.mock.calls[0][1];
  fireEvent.click(
    screen.getByRole("button", { name: "Oznacz jako przeczytaną" }),
  );
  await waitFor(() => expect(markSiteInquiryRead).toHaveBeenCalledTimes(2));
  expect(markSiteInquiryRead.mock.calls[1][1]).toBe(key);
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Oznacz jako przeczytaną" }),
    ).toBeNull(),
  );
});

test("dodaje starsze zapytania bez powielania wpisów i zachowuje wybór", async () => {
  listSiteInquiries
    .mockResolvedValueOnce({ items: [first], next_cursor: "cursor-1" })
    .mockResolvedValueOnce({ items: [first, second], next_cursor: null });
  renderInbox();
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  await screen.findByText(first.message);
  fireEvent.click(
    screen.getByRole("button", { name: "Wczytaj starsze zapytania" }),
  );
  expect(
    await screen.findByRole("button", { name: /Second Visitor/ }),
  ).not.toBeNull();
  expect(
    screen.getAllByRole("button", { name: /Example Visitor/ }),
  ).toHaveLength(1);
  expect(listSiteInquiries).toHaveBeenLastCalledWith("site-1", {
    cursor: "cursor-1",
  });
  expect(screen.getByText(first.message)).not.toBeNull();
  expect(
    screen.queryByRole("button", { name: "Wczytaj starsze zapytania" }),
  ).toBeNull();
});

test("zmiana witryny usuwa poprzednią treść i ignoruje spóźniony odczyt", async () => {
  let finishRead!: (
    value: Omit<typeof first, "read_at"> & { read_at: string },
  ) => void;
  markSiteInquiryRead.mockImplementation(
    () =>
      new Promise((resolve) => {
        finishRead = resolve;
      }),
  );
  listSiteInquiries
    .mockResolvedValueOnce({ items: [first], next_cursor: null })
    .mockResolvedValueOnce({ items: [], next_cursor: null });
  renderInbox();
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  await screen.findByText(first.message);
  fireEvent.change(screen.getByRole("combobox", { name: "Witryna" }), {
    target: { value: "site-2" },
  });
  await screen.findByText("Nie ma jeszcze zapytań z tej witryny.");
  finishRead({ ...first, read_at: "2026-09-21T13:00:00Z" });
  expect(screen.queryByText(first.message)).toBeNull();
  expect(listSiteInquiries).toHaveBeenLastCalledWith("site-2", undefined);
});

test.each([
  ["permission_denied", "Nie masz dostępu"],
  ["entitlement_required", "nie są dostępne w obecnym planie"],
])("ukrywa dane i pokazuje przyczynę %s", async (code, message) => {
  listSiteInquiries.mockRejectedValue(problem(code));
  renderInbox();
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByRole("list", { name: "Lista zapytań" })).toBeNull();
  expect(screen.queryByText(/Private server detail/)).toBeNull();
});

test("po odświeżeniu odmawiającym dostępu usuwa wcześniej widoczną wiadomość", async () => {
  renderInbox();
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  await screen.findByText(first.message);
  listSiteInquiries.mockRejectedValueOnce(problem("permission_denied"));
  fireEvent.click(screen.getByRole("button", { name: "Odśwież" }));
  await screen.findByRole("alert");
  expect(screen.queryByText(first.message)).toBeNull();
  expect(screen.queryByRole("list", { name: "Lista zapytań" })).toBeNull();
});

test("ponawia błąd listy, a przy pustej organizacji nie odpytuje zapytań", async () => {
  listSites
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ items: [], next_cursor: null });
  renderInbox();
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(await screen.findByText(/Nie masz jeszcze witryny/)).not.toBeNull();
  expect(listSiteInquiries).not.toHaveBeenCalled();
});

test("status niedostępnego e-maila nie sugeruje utraty wiadomości", async () => {
  listSiteInquiries.mockResolvedValue({
    items: [
      {
        ...first,
        email_status: "unavailable",
        read_at: "2026-09-21T13:00:00Z",
      },
    ],
    next_cursor: null,
  });
  renderInbox("en");
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  const article = screen.getByRole("article", { name: "Example Visitor" });
  expect(
    within(article).getByText(
      "Notification unavailable — the message is saved in the panel",
    ),
  ).not.toBeNull();
  expect(within(article).getByText(first.message)).not.toBeNull();
});

test("ponawia właściwą stronę paginacji po błędzie i nie gubi wcześniejszych wpisów", async () => {
  listSiteInquiries
    .mockResolvedValueOnce({ items: [first], next_cursor: "cursor-1" })
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ items: [second], next_cursor: null });
  renderInbox();
  await screen.findByRole("button", { name: /Example Visitor/ });
  fireEvent.click(
    screen.getByRole("button", { name: "Wczytaj starsze zapytania" }),
  );
  await screen.findByRole("alert");
  expect(
    screen.getByRole("button", { name: /Example Visitor/ }),
  ).not.toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  await screen.findByRole("button", { name: /Second Visitor/ });
  expect(listSiteInquiries).toHaveBeenLastCalledWith("site-1", {
    cursor: "cursor-1",
  });
  expect(
    screen.getByRole("button", { name: /Example Visitor/ }),
  ).not.toBeNull();
});

test("cofnięcie uprawnień podczas odczytu usuwa treść z widoku", async () => {
  markSiteInquiryRead.mockRejectedValue(problem("permission_denied"));
  renderInbox();
  fireEvent.click(
    await screen.findByRole("button", { name: /Example Visitor/ }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Nie masz dostępu",
  );
  expect(screen.queryByText(first.message)).toBeNull();
  expect(screen.queryByRole("list", { name: "Lista zapytań" })).toBeNull();
});
