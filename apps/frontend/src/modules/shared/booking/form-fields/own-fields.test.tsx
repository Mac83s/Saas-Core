import axe from "axe-core";
import {
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useState } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { BookingFormField } from "@saas-core/api-client";
import polishMessages from "../../../../../messages/pl.json";
import { OwnFields, type OwnField } from "../public-booking-parts";
import { useOfferFields } from "./use-offer-fields";

const { api } = vi.hoisted(() => ({ api: { listBookingFormFields: vi.fn() } }));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const OFFER = "0199a000-0000-7000-8000-0000000000a1";

function stored(overrides: Partial<BookingFormField>): BookingFormField {
  return {
    id: "0199a000-0000-7000-8000-0000000000f1",
    service_id: OFFER,
    name: "Liczba sztuk",
    kind: "text",
    options: [],
    mandatory: true,
    mandatory_for_staff: true,
    position: 1,
    active: true,
    version: 1,
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

test("a mandatory field binds the team only where the company says so", async () => {
  api.listBookingFormFields.mockResolvedValue({
    items: [
      stored({ id: "a", name: "Liczba sztuk", mandatory_for_staff: false }),
      stored({ id: "b", name: "Imię", position: 2 }),
      stored({
        id: "c",
        name: "Uwagi",
        kind: "long_text",
        mandatory: false,
        position: 3,
      }),
    ],
    limits: {},
  });
  const { result } = renderHook(() => useOfferFields(OFFER));
  await waitFor(() => expect(result.current).toHaveLength(3));
  expect(result.current.map((field) => [field.name, field.mandatory])).toEqual([
    ["Liczba sztuk", false],
    ["Imię", true],
    ["Uwagi", false],
  ]);
});

test("an older backend that sends no team flag still binds the team", async () => {
  const { mandatory_for_staff: _flag, ...older } = stored({ id: "a" });
  api.listBookingFormFields.mockResolvedValue({
    items: [older as unknown as BookingFormField],
    limits: {},
  });
  const { result } = renderHook(() => useOfferFields(OFFER));
  await waitFor(() => expect(result.current).toHaveLength(1));
  expect(result.current[0]?.mandatory).toBe(true);
});

function Harness({ fields }: { fields: OwnField[] }) {
  const [values, setValues] = useState<Record<string, string>>({});
  return (
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <OwnFields
        fields={fields}
        onChange={setValues}
        refused={{}}
        tried={false}
        values={values}
      />
    </NextIntlClientProvider>
  );
}

test("a long text is a labelled multi-line box of at most 500 characters", async () => {
  const note = {
    id: "0199a000-0000-7000-8000-0000000000f9",
    service_id: OFFER,
    name: "Uwagi do wizyty",
    kind: "long_text",
    mandatory: true,
    options: [],
  } as OwnField;
  render(<Harness fields={[note]} />);
  const box = screen.getByLabelText("Uwagi do wizyty");
  expect(box.tagName).toBe("TEXTAREA");
  expect(box).toHaveAttribute("maxlength", "500");
  expect(box).toHaveAttribute("rows", "3");
  fireEvent.change(box, { target: { value: "pierwsza\ndruga" } });
  expect(box).toHaveValue("pierwsza\ndruga");
  // A fragment of a form is not a page: no landmark is expected around it.
  const results = await axe.run(document.body, {
    rules: { region: { enabled: false } },
  });
  expect(results.violations).toEqual([]);
});
