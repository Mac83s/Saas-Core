import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import polishMessages from "../../../messages/pl.json";
import { PanelHeader } from "./panel-header";

vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => "/panel",
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("../../modules/shared/notifications", () => ({
  NotificationBell: () => null,
}));
vi.mock("./panel-width", () => ({ WidthToggle: () => null }));
vi.mock("@saas-core/ui/components/sidebar", () => ({
  SidebarTrigger: (props: object) => <button type="button" {...props} />,
}));

const access = {
  modules: ["core.organizations"],
  permissions: ["organization.read"],
  isOwner: true,
  limited: false,
};

function view() {
  return render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <PanelHeader
        access={access}
        user={{ email: "anna@saas.test", first_name: "Anna", last_name: "W" }}
      />
    </NextIntlClientProvider>,
  );
}

function phone(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("online the bar says nothing about the connection; offline it does", () => {
  phone(false);
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  view();
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
  cleanup();
  online.mockReturnValue(false);
  view();
  expect(screen.getByRole("status")).toHaveTextContent("Offline");
});

test("on a phone the theme and the language are in the account menu", async () => {
  phone(true);
  view();
  fireEvent.click(screen.getByRole("button", { name: /AW, / }));
  expect(
    await screen.findByRole("menuitemradio", { name: "Ciemny motyw" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("menuitemradio", { name: "Polski" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});
