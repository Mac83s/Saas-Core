import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import messages from "../../messages/pl.json";
import { HealthPanel } from "./health-panel";

vi.mock("@saas-core/api-client", () => ({
  getHealth: vi.fn(async () => ({
    status: "ok",
    deployment: "core-only",
    version: "0.1.0",
    correlation_id: "019c5f88-66c1-7b45-9ab4-3df6a5a6d7f0",
  })),
}));

beforeEach(() => vi.clearAllMocks());

test("pokazuje profil zwrócony przez health API", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <HealthPanel />
    </NextIntlClientProvider>,
  );
  expect(
    await screen.findByText("API ok; profil: core-only"),
  ).toBeInTheDocument();
});
