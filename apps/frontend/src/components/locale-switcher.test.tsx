import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import messages from "../../messages/pl.json";
import { LocaleSwitcher } from "./locale-switcher";

vi.mock("#i18n/navigation", () => ({
  usePathname: () => "/panel",
  useRouter: () => ({ replace: vi.fn() }),
}));

test("the panel's language reads as its name before the list is ever opened", () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <LocaleSwitcher />
    </NextIntlClientProvider>,
  );

  // „Polski”, never the raw „pl”.
  expect(
    screen.getByRole("combobox", { name: "Język interfejsu" }),
  ).toHaveTextContent("Polski");
});
