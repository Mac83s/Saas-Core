import axe from "axe-core";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import messages from "../../../../messages/pl.json";
import { BookingSettings } from "./booking-settings";

const api = vi.hoisted(() => ({
  configureBookingSchedule: vi.fn(),
  createBookingCatalogItem: vi.fn(),
  getBookingCatalog: vi.fn(),
  listInventoryItems: vi.fn(),
  listInventoryBalances: vi.fn(),
}));

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

const SERVICE = "33333333-3333-4333-8333-333333333333";
const STAFF = "22222222-2222-4222-8222-222222222222";
const LOCATION = "11111111-1111-4111-8111-111111111111";

const CATALOG = {
  services: [
    {
      id: SERVICE,
      name: "Konsultacja",
      public_slug: "konsultacja",
      duration_minutes: 45,
      appointment_kind: "",
    },
  ],
  staff: [
    {
      id: STAFF,
      name: "Anna Nowak",
      public_slug: "anna-nowak",
      membership_id: null,
    },
  ],
  locations: [
    { id: LOCATION, name: "Poznań, ul. Półwiejska 12", public_slug: "poznan" },
  ],
  resources: [],
};

const problem = (status: number, code: string, detail: string) =>
  new ApiProblemError({
    type: "about:blank",
    title: code,
    status,
    code,
    detail,
    correlation_id: null,
  });

/** An entry of the overview (the forms' selects list the same names). */
const listed = (name: string) =>
  screen.findByText(name, { selector: "dd span" });
const noContrast = { rules: { "color-contrast": { enabled: false } } };

function renderSettings(canManageBilling = true, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? messages : englishMessages}
    >
      <BookingSettings canManageBilling={canManageBilling} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getBookingCatalog.mockResolvedValue(CATALOG);
  api.configureBookingSchedule.mockResolvedValue({ id: "x" });
});

test("pokazuje, co jest w kalendarzu, a obok formularze", async () => {
  const { container } = renderSettings();

  expect(await listed("Konsultacja")).toBeInTheDocument();
  expect(screen.getByText(/45 min/)).toBeInTheDocument();
  expect(await listed("Anna Nowak")).toBeInTheDocument();
  // No resources yet: said, not left blank.
  expect(screen.getByText("Jeszcze brak")).toBeInTheDocument();
  expect(screen.getByText("Katalog rezerwacji")).toBeInTheDocument();
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
});

test("grafik zapisuje się bez zasobu, który jest opcjonalny", async () => {
  renderSettings();
  await listed("Konsultacja");

  fireEvent.change(
    screen.getByLabelText("Usługa", { selector: "#schedule-service" }),
    {
      target: { value: SERVICE },
    },
  );
  fireEvent.change(
    screen.getByLabelText("Personel", { selector: "#schedule-staff" }),
    {
      target: { value: STAFF },
    },
  );
  fireEvent.change(
    screen.getByLabelText("Lokalizacja", { selector: "#schedule-location" }),
    {
      target: { value: LOCATION },
    },
  );
  fireEvent.click(screen.getByRole("button", { name: "Zapisz grafik" }));

  await waitFor(() =>
    expect(api.configureBookingSchedule).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "availability", staff_id: STAFF }),
    ),
  );
  expect(api.configureBookingSchedule).not.toHaveBeenCalledWith(
    expect.objectContaining({ kind: "service_resource" }),
  );
});

test("nieudane dodanie i niepełny formularz mówią, co poszło nie tak", async () => {
  api.createBookingCatalogItem.mockRejectedValue(
    problem(400, "validation_error", "Ten identyfikator jest już zajęty."),
  );
  renderSettings();
  await listed("Konsultacja");

  fireEvent.click(screen.getByRole("button", { name: "Zapisz grafik" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Uzupełnij wymagane pola formularza.",
  );

  fireEvent.change(screen.getByLabelText("Nazwa"), {
    target: { value: "Konsultacja" },
  });
  fireEvent.change(screen.getByLabelText("Publiczny identyfikator"), {
    target: { value: "konsultacja" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Dodaj" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ten identyfikator jest już zajęty.",
    ),
  );
});

test("pusty kalendarz mówi, od czego zacząć", async () => {
  api.getBookingCatalog.mockResolvedValue({
    services: [],
    staff: [],
    locations: [],
    resources: [],
  });
  renderSettings(true, "en");

  expect(
    await screen.findByText(/Nothing here yet. Add a service/),
  ).toBeInTheDocument();
  expect(screen.getAllByText("None yet")).toHaveLength(4);
});

test("bez rezerwacji w planie: właściciel idzie do planów, reszta pyta właściciela", async () => {
  api.getBookingCatalog.mockRejectedValue(
    problem(403, "entitlement_required", "Plan organizacji nie pozwala."),
  );
  const { container, unmount } = renderSettings(true);

  expect(
    await screen.findByRole("heading", {
      name: "Rezerwacje nie są w Twoim planie",
    }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Zobacz plany" })).toHaveAttribute(
    "href",
    "/panel/settings/billing",
  );
  expect((await axe.run(container, noContrast)).violations).toEqual([]);
  unmount();

  renderSettings(false);
  expect(
    await screen.findByText(/Poproś właściciela firmy o zmianę planu/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Zobacz plany" })).toBeNull();
});

test("błąd wczytywania daje ponowienie", async () => {
  api.getBookingCatalog
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(CATALOG);
  renderSettings();

  fireEvent.click(
    await screen.findByRole("button", { name: "Spróbuj ponownie" }),
  );

  expect(await listed("Konsultacja")).toBeInTheDocument();
  expect(api.getBookingCatalog).toHaveBeenCalledTimes(2);
});

test("usługa, której materiał rozlicza jej moduł, nie ma produktów z magazynu", async () => {
  api.listInventoryItems.mockResolvedValue([]);
  api.listInventoryBalances.mockResolvedValue([]);
  api.getBookingCatalog.mockResolvedValue({
    ...CATALOG,
    services: [
      // Like HoofCare's herd visit: material goes per cow, never from here.
      { ...CATALOG.services[0], takes_materials: false },
      {
        ...CATALOG.services[0],
        id: "33333333-3333-4333-8333-444444444444",
        name: "Masaż",
        public_slug: "masaz",
        takes_materials: true,
      },
    ],
  });
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <BookingSettings canManageBilling canUseInventory />
    </NextIntlClientProvider>,
  );
  const products = await screen.findByLabelText("Usługa", {
    selector: "#service-materials-service",
  });
  expect(
    Array.from((products as HTMLSelectElement).options).map((o) => o.text),
  ).toEqual(["Masaż"]);
});
