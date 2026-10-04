import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useForm } from "react-hook-form";
import { beforeEach, expect, test, vi } from "vitest";

import polishMessages from "../../../../messages/pl.json";
import { StayOfferSelect } from "./stay-offer-select";

const { api } = vi.hoisted(() => ({ api: { getBookingSetup: vi.fn() } }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const STAY = "11111111-1111-4111-8111-111111111111";
const HIDDEN = "22222222-2222-4222-8222-222222222222";
const GONE = "33333333-3333-4333-8333-333333333333";

function Select({ offer }: { offer: string }) {
  const form = useForm({ defaultValues: { offer } });
  return (
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <label htmlFor="offer">Oferta</label>
      <StayOfferSelect form={form} id="offer" invalid={false} name="offer" />
    </NextIntlClientProvider>
  );
}

const service = (id: string, name: string, extra: object = {}) => ({
  id,
  name,
  time_model: "range",
  online: true,
  active: true,
  ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
});

test("lists the company's offers booked from–to and keeps a choice that is gone", async () => {
  api.getBookingSetup.mockResolvedValue({
    services: [
      service(STAY, "Pobyt nad jeziorem"),
      service(HIDDEN, "Pobyt zimowy", { online: false }),
      service("44444444-4444-4444-8444-444444444444", "Konsultacja", {
        time_model: "slot",
      }),
      service("55555555-5555-4555-8555-555555555555", "Stara oferta", {
        active: false,
      }),
    ],
  });
  render(<Select offer={GONE} />);

  expect(
    await screen.findByRole("option", { name: "Pobyt nad jeziorem" }),
  ).toBeInTheDocument();
  expect(
    screen.getAllByRole("option").map((option) => option.textContent),
  ).toEqual([
    "Wszystkie oferty z rezerwacji online",
    // The id the block holds, whatever became of the offer: leaving the
    // field must not write another choice into the page.
    "Wybrana oferta",
    "Pobyt nad jeziorem",
    "Pobyt zimowy (poza rezerwacją online)",
  ]);
  expect(screen.getByLabelText("Oferta")).toHaveValue(GONE);
});

test("says what is missing when nothing is booked from–to, or the list cannot be read", async () => {
  api.getBookingSetup.mockRejectedValue(new Error("403"));
  render(<Select offer="" />);

  expect(
    await screen.findByText(/Nie masz jeszcze oferty rezerwowanej od–do/),
  ).toBeVisible();
  expect(screen.getByLabelText("Oferta")).toHaveValue("");
});
