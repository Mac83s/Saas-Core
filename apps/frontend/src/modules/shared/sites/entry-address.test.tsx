import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import axe from "axe-core";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type ContentCollection,
  type ContentEntry,
  type EntryAddress as Address,
} from "@saas-core/api-client";

import { PanelAccessProvider } from "#components/panel/panel-access";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { EntryAddress } from "./entry-address";

const {
  changeEntryAddress,
  getEntryAddress,
  getPublicLocales,
  previewEntryAddress,
} = vi.hoisted(() => ({
  changeEntryAddress: vi.fn(),
  getEntryAddress: vi.fn(),
  getPublicLocales: vi.fn(),
  previewEntryAddress: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@saas-core/api-client")>()),
  changeEntryAddress,
  getEntryAddress,
  getPublicLocales,
  previewEntryAddress,
}));

const entry = {
  id: "019ff20d-a000-7000-8000-000000000041",
  slug: "wpis-jeden",
  locale: "pl",
  title: "Wpis jeden",
} as ContentEntry;
const collection = { name: "Poradnik", key: "poradnik" } as ContentCollection;

const address = (extra: Partial<Address> = {}): Address => ({
  entry_id: entry.id,
  locale: "pl",
  previous_slug: "wpis-jeden",
  slug: "wpis-jeden",
  path: "/poradnik/wpis-jeden/",
  changed: false,
  published: true,
  moved: [],
  redirects: [],
  takes_over: [],
  unpublished_changes: false,
  ...extra,
});

const moved = (extra: Partial<Address> = {}) =>
  address({
    slug: "nowy",
    path: "/poradnik/nowy/",
    changed: true,
    moved: [{ from_path: "/poradnik/wpis-jeden/", to_path: "/poradnik/nowy/" }],
    redirects: [
      { from_path: "/poradnik/stary/", to_path: "/poradnik/nowy/" },
      { from_path: "/poradnik/wpis-jeden/", to_path: "/poradnik/nowy/" },
    ],
    ...extra,
  });

function renderCard({
  publisher = false,
  locale = "pl",
}: { publisher?: boolean; locale?: "pl" | "en" } = {}) {
  const onChanged = vi.fn().mockResolvedValue(undefined);
  const rendered = render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <PanelAccessProvider
        access={{
          modules: ["shared.sites"],
          permissions: null,
          isOwner: true,
          limited: false,
          ...(publisher ? { publisher: true as const } : {}),
        }}
      >
        <EntryAddress
          collection={collection}
          entry={entry}
          onChanged={onChanged}
        />
      </PanelAccessProvider>
    </NextIntlClientProvider>,
  );
  return { rendered, onChanged };
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  vi.clearAllMocks();
  getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en"],
    version: 1,
    offered: [
      { code: "pl", native_name: "Polski", english_name: "Polish" },
      { code: "en", native_name: "English", english_name: "English" },
    ],
    limit: { allowed: true, additional_max: null, reason: "" },
    protected: {},
  });
  getEntryAddress.mockResolvedValue(
    address({
      redirects: [
        { from_path: "/poradnik/stary/", to_path: "/poradnik/wpis-jeden/" },
      ],
    }),
  );
  previewEntryAddress.mockResolvedValue(moved());
  changeEntryAddress.mockResolvedValue(moved());
});

test("a company sees the address, what leads to it, and — before anything moves — what will", async () => {
  const { rendered, onChanged } = renderCard();

  expect(
    await screen.findByText(
      "Wpis odpowiada pod adresem /poradnik/wpis-jeden/.",
    ),
  ).not.toBeNull();
  expect(screen.getByText("/poradnik/stary/")).not.toBeNull();
  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);

  // A slug that is no slug is said at once, and nothing is asked.
  type("Nowa końcówka adresu", "Nowy Adres");
  expect(
    screen.getByText(
      "Adres to małe litery łacińskie, cyfry i pojedyncze łączniki, najwyżej 120 znaków.",
    ),
  ).not.toBeNull();
  expect(
    screen.getByRole<HTMLButtonElement>("button", { name: "Sprawdź zmianę" })
      .disabled,
  ).toBe(true);

  type("Nowa końcówka adresu", "nowy");
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź zmianę" }));
  expect(await screen.findByText("Nowy adres: /poradnik/nowy/")).not.toBeNull();
  expect(previewEntryAddress).toHaveBeenCalledWith(entry.id, {
    slug: "nowy",
    reason: "",
    take_over_former: false,
  });
  expect(
    screen.getByText(
      "Wpis jest opublikowany. Zostanie opublikowany ponownie pod nowym adresem — z tą treścią, którą goście widzą dziś.",
    ),
  ).not.toBeNull();
  expect(screen.getAllByText("/poradnik/wpis-jeden/").length).toBe(1);
  expect(screen.queryByText(/W szkicu są zmiany/)).toBeNull();
  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);

  // An address visitors know moves only with a reason.
  fireEvent.click(screen.getByRole("button", { name: "Zmień adres" }));
  expect(screen.getByText("Podaj powód zmiany adresu.")).not.toBeNull();
  expect(changeEntryAddress).not.toHaveBeenCalled();
  type("Powód zmiany adresu", "Lepszy adres");
  fireEvent.click(screen.getByRole("button", { name: "Zmień adres" }));
  await waitFor(() =>
    expect(changeEntryAddress).toHaveBeenCalledWith(entry.id, {
      slug: "nowy",
      reason: "Lepszy adres",
      take_over_former: false,
    }),
  );
  expect(
    await screen.findByText(
      "Adres zmieniony. Stary adres przekierowuje do nowego.",
    ),
  ).not.toBeNull();
  expect(onChanged).toHaveBeenCalled();
  expect(
    screen.getByText("Wpis odpowiada pod adresem /poradnik/nowy/."),
  ).not.toBeNull();
});

test("a draft's unpublished changes and another entry's redirect are said before the change", async () => {
  previewEntryAddress.mockResolvedValue(
    moved({
      unpublished_changes: true,
      takes_over: [
        {
          slug: "nowy",
          entry_id: "019ff20d-a000-7000-8000-000000000042",
          title: "Inny wpis",
        },
      ],
    }),
  );
  renderCard();
  await screen.findByText(/Wpis odpowiada pod adresem/);
  type("Nowa końcówka adresu", "nowy");
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź zmianę" }));

  expect(
    await screen.findByText(
      "W szkicu są zmiany, których jeszcze nie opublikowano. Zmiana adresu ich nie wyda: zostają w szkicu do Twojej publikacji.",
    ),
  ).not.toBeNull();
  expect(
    screen.getByText(
      "Ten adres dziś przekierowuje do wpisu „Inny wpis”. Po zmianie to przekierowanie przestanie działać.",
    ),
  ).not.toBeNull();
  const confirm = screen.getByRole<HTMLButtonElement>("button", {
    name: "Zmień adres",
  });
  // Not without saying so.
  expect(confirm.disabled).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Rozumiem — ten wpis przejmuje adres",
    }),
  );
  expect(confirm.disabled).toBe(false);
  type("Powód zmiany adresu", "Ten adres należy się temu wpisowi");
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(changeEntryAddress).toHaveBeenCalledWith(entry.id, {
      slug: "nowy",
      reason: "Ten adres należy się temu wpisowi",
      take_over_former: true,
    }),
  );

  // Typing another slug makes the answer not apply: it is asked again.
  type("Nowa końcówka adresu", "jeszcze-inny");
  expect(screen.queryByRole("button", { name: "Zmień adres" })).toBeNull();
  expect(screen.getByRole("button", { name: "Sprawdź zmianę" })).not.toBeNull();
});

test("a refusal is said in the panel's words, by the code on the field", async () => {
  previewEntryAddress.mockRejectedValue(
    new ApiProblemError({
      type: "about:blank",
      title: "Invalid",
      status: 400,
      detail: "x",
      code: "invalid",
      errors: [{ field: "slug", code: "entry_slug_taken", message: "x" }],
    } as never),
  );
  renderCard();
  await screen.findByText(/Wpis odpowiada pod adresem/);
  type("Nowa końcówka adresu", "zajety");
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź zmianę" }));
  expect(
    await screen.findByText(
      "Pod tym adresem odpowiada już inny wpis tego typu.",
    ),
  ).not.toBeNull();
});

test("an entry never published changes its address with no reason and no redirect", async () => {
  getEntryAddress.mockResolvedValue(address({ published: false }));
  const free = address({
    slug: "nowy",
    path: "/poradnik/nowy/",
    changed: true,
    published: false,
  });
  previewEntryAddress.mockResolvedValue(free);
  changeEntryAddress.mockResolvedValue(free);
  renderCard();
  expect(
    await screen.findByText(
      "Po publikacji wpis odpowie pod adresem /poradnik/wpis-jeden/.",
    ),
  ).not.toBeNull();
  type("Nowa końcówka adresu", "nowy");
  fireEvent.click(screen.getByRole("button", { name: "Sprawdź zmianę" }));
  expect(
    await screen.findByText(
      "Wpis nie był jeszcze opublikowany: adres zmieni się od razu i nic nie zostanie po starym.",
    ),
  ).not.toBeNull();
  expect(screen.queryByLabelText("Powód zmiany adresu")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Zmień adres" }));
  expect(await screen.findByText("Adres zmieniony.")).not.toBeNull();
});

test("the publisher is shown the parts of the address, never an address of a site", async () => {
  const { rendered } = renderCard({ publisher: true, locale: "en" });

  expect(
    await screen.findByText(
      "Type: Poradnik · language: Polski · last part of the address: wpis-jeden",
    ),
  ).not.toBeNull();
  expect(
    screen.getByText(
      "The site's own pages put this entry's full address together — here you change its last part.",
    ),
  ).not.toBeNull();
  // Former addresses as slugs, not as paths of a site nobody serves.
  expect(screen.getByText("stary")).not.toBeNull();
  type("New last part of the address", "nowy");
  fireEvent.click(screen.getByRole("button", { name: "Check the change" }));
  expect(
    await screen.findByText("New last part of the address: nowy"),
  ).not.toBeNull();
  expect(rendered.baseElement.textContent).not.toContain("/poradnik/");
  expect((await axe.run(rendered.baseElement)).violations).toHaveLength(0);
});
