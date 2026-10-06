import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import en from "../../../../messages/en.json";
import pl from "../../../../messages/pl.json";
import { mergeMessages } from "#i18n/merge-messages";
import { AuthShell } from "./auth-shell";

// The profile is generated per product; each test names the one it stands on.
const profile = vi.hoisted(() => ({
  product: { name: "", platformDomain: "" },
}));
vi.mock("../../../generated/deployment", () => ({ deployment: profile }));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

function renderShell(
  product: { name: string; platformDomain: string },
  messages: Record<string, unknown> = pl,
) {
  profile.product = product;
  return render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <AuthShell title="Zaloguj się" description="Opis ekranu">
        <p>formularz</p>
      </AuthShell>
    </NextIntlClientProvider>,
  );
}

test("core's default: the profile's name, plain words for an owner, the note on a local address", () => {
  const { container } = renderShell({
    name: "Firma Testowa",
    platformDomain: "business.localhost",
  });

  // Beside the card on a wide screen and above it on a phone.
  expect(screen.getAllByRole("link", { name: "Firma Testowa" })).toHaveLength(
    2,
  );
  expect(screen.getByText(pl.Identity.heroEyebrow)).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 1, name: pl.Identity.heroTitle }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Firma Testowa · lokalne środowisko"),
  ).toBeInTheDocument();
  expect(container.textContent).not.toContain("SaaS Core");
});

test("a product's profile: its name and its own side panel, no environment note on a public address", () => {
  const { container } = renderShell(
    { name: "MedPlano", platformDomain: "medplano.test.example.com" },
    mergeMessages(pl, {
      Identity: {
        heroEyebrow: "Panel gabinetu",
        heroTitle: "Wizyty i pacjenci w jednym kalendarzu.",
        heroDescription: "Tekst produktu.",
      },
    }),
  );

  expect(screen.getAllByRole("link", { name: "MedPlano" })).toHaveLength(2);
  expect(screen.getByText("Panel gabinetu")).toBeInTheDocument();
  expect(
    screen.getByRole("heading", {
      level: 1,
      name: "Wizyty i pacjenci w jednym kalendarzu.",
    }),
  ).toBeInTheDocument();
  expect(screen.queryByText(pl.Identity.heroTitle)).not.toBeInTheDocument();
  expect(container.textContent).not.toContain("SaaS Core");
  expect(container.textContent).not.toContain(pl.Identity.localEnvironment);
});

test.each([
  ["localhost", true],
  ["hoofcare.localhost", true],
  ["notlocalhost", false],
  ["hoofcare.localhost.example.com", false],
])("the environment note on %s: %s", (platformDomain, shown) => {
  const { container } = renderShell({ name: "HoofCare", platformDomain });
  expect(container.textContent?.includes(pl.Identity.localEnvironment)).toBe(
    shown,
  );
});

test.each([
  ["pl", pl.Identity],
  ["en", en.Identity],
])(
  "the %s texts of the screens before the panel name no product and boast of no mechanism",
  (_locale, identity) => {
    for (const [key, text] of Object.entries(identity)) {
      expect(text, key).not.toMatch(/SaaS Core|same-origin|CSRF/i);
    }
  },
);
