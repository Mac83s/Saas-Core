import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiProblemError, type SiteTexts } from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SiteTextsSheet } from "./site-texts-sheet";

const { api } = vi.hoisted(() => ({
  api: {
    getSiteTexts: vi.fn(),
    saveSiteTexts: vi.fn(),
    publishSiteTexts: vi.fn(),
  },
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const SITE = "0199f0a0-0000-7000-8000-000000000001";
const LINK = "footer/link/3f2a9c1d0b7e";

const item = (
  key: string,
  role: SiteTexts["items"][number]["role"],
  source_text: string,
  extra: Partial<SiteTexts["items"][number]> = {},
): SiteTexts["items"][number] => ({
  key,
  role,
  source_text,
  text: "",
  origin: "",
  state: "missing",
  pending_text: "",
  pending_reason: "",
  ...extra,
});

const TEXTS: SiteTexts = {
  site_id: SITE,
  locale: "en",
  version: "v1",
  items: [
    item("header/tagline", "tagline", "Fryzjer w centrum", {
      text: "Hairdresser downtown",
      origin: "human",
      state: "fresh",
    }),
    item("footer/text", "footer", "Zapraszamy od poniedziałku do soboty", {
      pending_text: "Open Monday to Saturday",
      pending_reason: "review_mode",
    }),
    item(LINK, "footer_link", "Kontakt", {
      text: "Contact us",
      origin: "ai",
      state: "stale",
    }),
    item("collection/0199f0a0", "collection", "Porady"),
  ],
};

const onChanged = vi.fn();
const onClose = vi.fn();

function view(locale: "pl" | "en" = "pl", language: string | null = "en") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <SiteTextsSheet
        locale={language ?? undefined}
        onChanged={onChanged}
        onClose={onClose}
        siteId={SITE}
      />
    </NextIntlClientProvider>,
  );
}

async function expectNoAxeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(
    results.violations.map((violation) => violation.id),
    JSON.stringify(results.violations, null, 2),
  ).toEqual([]);
}

const problem = (status: number, code: string, errors?: unknown) =>
  new ApiProblemError({
    type: "about:blank",
    title: "",
    status,
    code,
    detail: "",
    ...(errors ? { errors } : {}),
  } as ConstructorParameters<typeof ApiProblemError>[0]);

beforeEach(() => {
  vi.clearAllMocks();
  api.getSiteTexts.mockResolvedValue(TEXTS);
});

test("each text stands beside its source, with its state and what waits", async () => {
  view();
  const sheet = await screen.findByRole("dialog", {
    name: "Nagłówek i stopka — English",
  });
  expect(api.getSiteTexts).toHaveBeenCalledWith(SITE, "en");
  const tagline = (await within(sheet).findByLabelText(
    "Hasło w nagłówku",
  )) as HTMLInputElement;
  expect(tagline.value).toBe("Hairdresser downtown");
  expect(sheet.textContent).toContain("Fryzjer w centrum");
  // Each link, blog and tag is named by its own text.
  expect(
    (
      within(sheet).getByLabelText(
        "Odnośnik w stopce: Kontakt",
      ) as HTMLInputElement
    ).value,
  ).toBe("Contact us");
  expect(within(sheet).getByLabelText("Nazwa bloga: Porady")).toBeTruthy();
  // The footer's sentence gets room; a text an automatic translation left
  // for a person is shown where it would go.
  expect(within(sheet).getByLabelText("Tekst stopki").tagName).toBe("TEXTAREA");
  expect(sheet.textContent).toContain(
    "Czeka na Twoją decyzję w „Do akceptacji”: „Open Monday to Saturday”",
  );
  expect(within(sheet).getByText("Do odświeżenia")).toBeTruthy();
  expect(sheet.textContent).toContain("Tłumaczenie AI");
  // Nothing changed yet: nothing to save; what is saved can go out.
  expect(
    (within(sheet).getByRole("button", { name: "Zapisz" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(
    (
      within(sheet).getByRole("button", {
        name: "Opublikuj teraz",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
  await expectNoAxeViolations(document.body);
});

test("a save sends only what changed, at the version read; publishing follows", async () => {
  const saved: SiteTexts = {
    ...TEXTS,
    version: "v2",
    items: TEXTS.items.map((entry) =>
      entry.key === "collection/0199f0a0"
        ? { ...entry, text: "Tips", origin: "human", state: "fresh" }
        : entry,
    ),
  };
  api.saveSiteTexts.mockResolvedValue(saved);
  api.publishSiteTexts.mockResolvedValue({
    site_id: SITE,
    locale: "en",
    publication_id: "0199f0a0-0000-7000-8000-0000000000b1",
  });
  view();
  const sheet = await screen.findByRole("dialog");
  fireEvent.change(await within(sheet).findByLabelText("Nazwa bloga: Porady"), {
    target: { value: "Tips" },
  });
  const publish = within(sheet).getByRole("button", {
    name: "Opublikuj teraz",
  }) as HTMLButtonElement;
  // What is not saved cannot go out.
  expect(publish.disabled).toBe(true);
  fireEvent.click(within(sheet).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.saveSiteTexts).toHaveBeenCalledWith(SITE, "en", {
      expected_version: "v1",
      texts: { "collection/0199f0a0": "Tips" },
    }),
  );
  expect((await within(sheet).findByRole("status")).textContent).toBe(
    "Zapisano. Odwiedzający zobaczą te teksty po publikacji.",
  );
  expect(onChanged).toHaveBeenCalledTimes(1);

  await waitFor(() => expect(publish.disabled).toBe(false));
  fireEvent.click(publish);
  await waitFor(() =>
    expect(api.publishSiteTexts).toHaveBeenCalledWith(
      SITE,
      "en",
      expect.any(String),
    ),
  );
  expect((await within(sheet).findByRole("status")).textContent).toBe(
    "Opublikowano — odwiedzający widzą już te teksty.",
  );
  expect(onChanged).toHaveBeenCalledTimes(2);
});

test("somebody else's save in between brings their texts back; a refused text is named", async () => {
  api.saveSiteTexts
    .mockRejectedValueOnce(problem(409, "site_texts_version_conflict"))
    .mockRejectedValueOnce(
      problem(400, "validation_error", [
        {
          field: `texts.${LINK}`,
          code: "invalid",
          message: "Najwyżej 60 znaków.",
        },
      ]),
    );
  view();
  const sheet = await screen.findByRole("dialog");
  const link = () =>
    within(sheet).findByLabelText("Odnośnik w stopce: Kontakt");
  fireEvent.change(await link(), { target: { value: "Get in touch" } });
  fireEvent.click(within(sheet).getByRole("button", { name: "Zapisz" }));
  expect((await within(sheet).findByRole("alert")).textContent).toContain(
    "Ktoś zmienił te teksty w międzyczasie.",
  );
  // Read again: the field shows what is saved now.
  expect(api.getSiteTexts).toHaveBeenCalledTimes(2);
  expect(((await link()) as HTMLInputElement).value).toBe("Contact us");

  fireEvent.change(await link(), { target: { value: "x".repeat(80) } });
  fireEvent.click(within(sheet).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(within(sheet).getByRole("alert").textContent).toBe(
      "Odnośnik w stopce: Kontakt: Najwyżej 60 znaków.",
    ),
  );
});

test("publishing is a person's with the right to publish; English words and axe", async () => {
  api.publishSiteTexts.mockRejectedValue(problem(403, "permission_denied"));
  view("en");
  const sheet = await screen.findByRole("dialog", {
    name: "Header and footer — English",
  });
  fireEvent.click(
    await within(sheet).findByRole("button", { name: "Publish now" }),
  );
  expect((await within(sheet).findByRole("alert")).textContent).toContain(
    "a person with the right to publish the site",
  );
  await expectNoAxeViolations(document.body);
});

test("a site that shows no texts of its own says so; a failed read too", async () => {
  api.getSiteTexts.mockResolvedValueOnce({ ...TEXTS, items: [] });
  const empty = view();
  expect(
    await screen.findByText(/nie pokazuje jeszcze własnych tekstów/),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Zapisz" })).toBeNull();
  empty.unmount();

  api.getSiteTexts.mockRejectedValueOnce(new Error("network"));
  const failed = view();
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Nie udało się wczytać tekstów strony.",
  );
  failed.unmount();
});

test("closed, the sheet asks nothing", () => {
  const { container } = view("pl", null);
  expect(container.textContent).toBe("");
  expect(api.getSiteTexts).not.toHaveBeenCalled();
});
