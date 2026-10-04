import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ComponentProps, ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type BookingPreset,
  type ServiceSetup,
} from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { OfferPresets } from "./offer-presets";

const api = vi.hoisted(() => ({
  applyBookingPreset: vi.fn(),
  listBookingPresets: vi.fn(),
  readCatalogDictionary: vi.fn(),
  saveBookingPresetInterest: vi.fn(),
  withdrawBookingPresetInterest: vi.fn(),
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

const noContrast = { rules: { "color-contrast": { enabled: false } } };

const preset = (given: Partial<BookingPreset>): BookingPreset => ({
  id: "core.specialist_visit",
  version: 1,
  readiness: "ready",
  labels: {
    pl: { name: "Wizyta u specjalisty", description: "Fryzjer, lekarz." },
    en: { name: "Appointment with a specialist", description: "A barber." },
  },
  time_model: "slot",
  booked_subject: "staff",
  booked_staff: "required",
  place: "business",
  required_inputs: [],
  catalog_category: null,
  page_template: null,
  interest: null,
  online_booking: "ready",
  ...given,
});

const VISIT = preset({});
const AT_CUSTOMER = preset({
  id: "core.service_at_customer",
  version: 2,
  labels: {
    pl: { name: "Usługa u klienta", description: "Hydraulik, elektryk." },
    en: { name: "Service at the customer's", description: "A plumber." },
  },
  online_booking: "soon",
});
const STAY = preset({
  id: "core.lodging",
  version: 5,
  labels: {
    pl: { name: "Nocleg", description: "Domek, apartament, pokój." },
    en: { name: "Stay", description: "Cottage, apartment, room." },
  },
  time_model: "range",
  booked_subject: "unit_group",
  booked_staff: "none",
  catalog_category: "turystyka-i-noclegi",
  page_template: "core.lodging",
});
const HOURLY = preset({
  id: "core.hourly_space",
  readiness: "soon",
  labels: {
    pl: { name: "Wynajem przestrzeni na godziny", description: "Kort, sala." },
    en: { name: "Space by the hour", description: "A court, a hall." },
  },
  time_model: "range",
  booked_subject: "unit",
  booked_staff: "none",
  online_booking: "soon",
});

function renderPresets(
  props: Partial<ComponentProps<typeof OfferPresets>> = {},
  messages: Record<string, unknown> = polishMessages,
  locale = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={messages}
      timeZone="Europe/Warsaw"
    >
      <OfferPresets catalog website {...props} />
    </NextIntlClientProvider>,
  );
}

const row = (name: string) =>
  within(screen.getByText(name).closest("tr") as HTMLElement);

beforeEach(() => {
  vi.clearAllMocks();
  api.listBookingPresets.mockResolvedValue([VISIT, AT_CUSTOMER, STAY, HOURLY]);
  api.readCatalogDictionary.mockResolvedValue({
    cities: [],
    locales: ["pl"],
    categories: [
      {
        key: "turystyka-i-noclegi",
        labels: { pl: "Turystyka i noclegi", en: "Travel and lodging" },
      },
    ],
  });
});

test("ready presets are used, announced ones take a sign-up", async () => {
  const { container } = renderPresets();

  expect(await screen.findByText("Nocleg")).toBeInTheDocument();
  // How each is booked, and whether it can be started now.
  expect(row("Nocleg").getByText("Od–do: noce albo dni")).toBeInTheDocument();
  expect(row("Nocleg").getByText("Gotowy")).toBeInTheDocument();
  expect(
    row("Nocleg").getByRole("button", { name: "Użyj wzorca" }),
  ).toBeInTheDocument();
  expect(
    row("Wizyta u specjalisty").getByText("Termin z kalendarza"),
  ).toBeInTheDocument();
  // Ready, yet the team books it: the site comes later for this one.
  expect(
    row("Usługa u klienta").getByText(
      "Rezerwacje wpisuje zespół; rezerwacja przez stronę — wkrótce.",
    ),
  ).toBeInTheDocument();
  expect(
    row("Wynajem przestrzeni na godziny").getByText("Wkrótce"),
  ).toBeInTheDocument();
  expect(
    row("Wynajem przestrzeni na godziny").getByRole("button", {
      name: "Daj znać, gdy będzie gotowy",
    }),
  ).toBeInTheDocument();
  expect(
    row("Wynajem przestrzeni na godziny").queryByRole("button", {
      name: "Użyj wzorca",
    }),
  ).toBeNull();

  expect((await axe.run(container, noContrast)).violations).toEqual([]);
});

test("a stay preset makes a draft offer and says what it suggests besides", async () => {
  api.applyBookingPreset.mockResolvedValue({
    id: "offer-1",
    name: "Domek nad jeziorem",
  } as ServiceSetup);
  renderPresets();

  await screen.findByText("Nocleg");
  fireEvent.click(row("Nocleg").getByRole("button", { name: "Użyj wzorca" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Nowa oferta ze wzorca „Nocleg”",
  });
  // The preset's own name is offered; a stay asks for no length of a visit.
  const name = within(dialog).getByLabelText("Nazwa oferty");
  expect(name).toHaveValue("Nocleg");
  expect(within(dialog).queryByLabelText(/Ile trwa/)).toBeNull();
  fireEvent.change(name, { target: { value: " Domek nad jeziorem " } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Utwórz ofertę" }),
  );

  await waitFor(() => expect(api.applyBookingPreset).toHaveBeenCalledTimes(1));
  expect(api.applyBookingPreset.mock.calls[0]![0]).toEqual({
    preset_id: "core.lodging",
    version: 5,
    name: "Domek nad jeziorem",
  });
  expect(api.applyBookingPreset.mock.calls[0]![1]).toMatch(/[0-9a-f-]{36}/);

  // What comes next: units and prices, the catalogue's category by its
  // name, and the page template by the name the page editor shows.
  const next = await screen.findByRole("status");
  expect(
    within(next).getByText("Oferta „Domek nad jeziorem” czeka jako szkic"),
  ).toBeInTheDocument();
  expect(next).toHaveTextContent(
    "Dodaj jednostki (domki, pokoje, sprzęt) i ceny",
  );
  expect(next).toHaveTextContent("kategoria „Turystyka i noclegi”");
  expect(next).toHaveTextContent("szablon „Noclegi”");
  expect(
    within(next).getByRole("link", { name: "Usługi i grafik" }),
  ).toHaveAttribute("href", "/panel/settings/services");
  expect(
    within(next).getByRole("link", { name: "ustaw ją w wizytówce" }),
  ).toHaveAttribute("href", "/panel/profile");
  expect(
    within(next).getByRole("link", { name: "otwórz stronę internetową" }),
  ).toHaveAttribute("href", "/panel/sites");
});

test("a visit asks how long it takes, and a company without a card or a site gets no such hint", async () => {
  api.applyBookingPreset.mockResolvedValue({
    id: "offer-2",
    name: "Konsultacja",
  } as ServiceSetup);
  renderPresets({ catalog: false, website: false }, englishMessages, "en");

  await screen.findByText("Appointment with a specialist");
  expect(api.readCatalogDictionary).not.toHaveBeenCalled();
  fireEvent.click(
    row("Appointment with a specialist").getByRole("button", {
      name: "Use the preset",
    }),
  );
  const dialog = await screen.findByRole("dialog");
  const minutes = within(dialog).getByLabelText(
    "How long one visit takes (minutes)",
  );
  expect(minutes).toHaveValue("60");
  // Without a length nothing is sent.
  fireEvent.change(minutes, { target: { value: "" } });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Create the offer" }),
  );
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Say how many minutes a visit takes.",
  );
  expect(api.applyBookingPreset).not.toHaveBeenCalled();
  fireEvent.change(minutes, { target: { value: "45" } });
  fireEvent.change(within(dialog).getByLabelText("Offer name"), {
    target: { value: "Konsultacja" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Create the offer" }),
  );

  await waitFor(() =>
    expect(api.applyBookingPreset.mock.calls[0]?.[0]).toEqual({
      preset_id: "core.specialist_visit",
      version: 1,
      name: "Konsultacja",
      duration_minutes: 45,
    }),
  );
  const next = await screen.findByRole("status");
  expect(next).toHaveTextContent("Say who does it and where");
  expect(within(next).getAllByRole("link")).toHaveLength(1);
});

test("a refusal of the preset is said in the dialog and nothing is claimed", async () => {
  api.applyBookingPreset.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad request",
      status: 400,
      detail: "",
      code: "invalid",
      errors: [
        { field: "preset_id", code: "preset_not_ready", message: "Wkrótce." },
      ],
    } as ConstructorParameters<typeof ApiProblemError>[0]),
  );
  renderPresets();

  await screen.findByText("Nocleg");
  fireEvent.click(row("Nocleg").getByRole("button", { name: "Użyj wzorca" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Utwórz ofertę" }),
  );

  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Ten wzorzec nie jest jeszcze dostępny.",
  );
  expect(screen.queryByRole("status")).toBeNull();
});

test("a company signs up for an announced preset, says what it lacks and may withdraw", async () => {
  api.saveBookingPresetInterest.mockResolvedValue({});
  api.withdrawBookingPresetInterest.mockResolvedValue(undefined);
  renderPresets();

  await screen.findByText("Wynajem przestrzeni na godziny");
  fireEvent.click(
    row("Wynajem przestrzeni na godziny").getByRole("button", {
      name: "Daj znać, gdy będzie gotowy",
    }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "„Wynajem przestrzeni na godziny” — daj znać, gdy będzie gotowy",
  });
  fireEvent.change(within(dialog).getByLabelText("Czego Ci brakuje?"), {
    target: { value: "  Kort na godziny, z ceną w szczycie. " },
  });
  // After the sign-up the list is read again: it now says so on the row.
  api.listBookingPresets.mockResolvedValue([
    VISIT,
    AT_CUSTOMER,
    STAY,
    {
      ...HOURLY,
      interest: {
        preset_id: HOURLY.id,
        note: "Kort na godziny, z ceną w szczycie.",
        created_at: "2026-10-04T10:00:00Z",
        updated_at: "2026-10-04T10:00:00Z",
      },
    },
  ]);
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz mnie" }));

  await waitFor(() =>
    expect(api.saveBookingPresetInterest).toHaveBeenCalledWith(
      "core.hourly_space",
      "Kort na godziny, z ceną w szczycie.",
      expect.stringMatching(/[0-9a-f-]{36}/),
    ),
  );
  expect(
    await row("Wynajem przestrzeni na godziny").findByText(
      "Zapisano 4 paź 2026",
    ),
  ).toBeInTheDocument();

  // The same window changes the note or takes the company off the list.
  fireEvent.click(
    row("Wynajem przestrzeni na godziny").getByRole("button", {
      name: "Zmień zapis",
    }),
  );
  const again = await screen.findByRole("dialog");
  expect(within(again).getByLabelText("Czego Ci brakuje?")).toHaveValue(
    "Kort na godziny, z ceną w szczycie.",
  );
  fireEvent.click(within(again).getByRole("button", { name: "Wypisz mnie" }));
  await waitFor(() =>
    expect(api.withdrawBookingPresetInterest).toHaveBeenCalledWith(
      "core.hourly_space",
    ),
  );
});
