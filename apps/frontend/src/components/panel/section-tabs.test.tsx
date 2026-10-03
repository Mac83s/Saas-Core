import { cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import polishMessages from "../../../messages/pl.json";
import { SectionTabs } from "./section-tabs";

const navigation = vi.hoisted(() => ({ pathname: "/panel/team/roles" }));
vi.mock("#i18n/navigation", () => ({
  Link: "a",
  usePathname: () => navigation.pathname,
}));

afterEach(cleanup);

test("on a phone the current tab scrolls into view and a long name is short for the eye", () => {
  const scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  render(
    <NextIntlClientProvider locale="pl" messages={polishMessages}>
      <SectionTabs
        access={{
          modules: ["core.organizations", "shared.booking"],
          permissions: [
            "organization.members.read",
            "booking.appointment.read",
          ],
          isOwner: true,
          limited: false,
        }}
      />
    </NextIntlClientProvider>,
  );
  // UX-001: „Role i uprawnienia” is „Role” on the tab, whole for a screen reader.
  const current = screen.getByRole("link", { name: "Role i uprawnienia" });
  expect(current).toHaveAttribute("aria-current", "page");
  expect(current).toHaveTextContent("Role");
  // The whole name is out of the flow: its tab holds it, or the name of a tab
  // scrolled out of sight makes a phone's page scroll sideways (TL16, 390 px).
  expect(current).toHaveClass("relative");
  expect(scrollIntoView).toHaveBeenCalledWith({
    inline: "center",
    block: "nearest",
  });
});
