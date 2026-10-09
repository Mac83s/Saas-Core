import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, expect, test, vi } from "vitest";

import type { ContentCollection } from "@saas-core/api-client";
import polishMessages from "../../../../messages/pl.json";
import { PanelAccessProvider } from "#components/panel/panel-access";
import { ContentTypeSettings } from "./content-type-settings";

/**
 * A content type's settings in the platform's own workspace (ADR-079 pkt
 * 29): what the type is to search engines stays; the two switches that only
 * a builder site reads — its RSS feed and its menu, which waits for a
 * publication the publisher's panel has not — are not drawn. A company's
 * screen is in `content-types-panel.test.tsx`, unchanged.
 */
vi.mock("#i18n/navigation", () => ({ Link: "a" }));
const api = vi.hoisted(() => ({
  getPublicLocales: vi.fn(),
  listContentTypes: vi.fn(),
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const siteId = "019ff20d-a000-7000-8000-000000000010";
const guide: ContentCollection = {
  id: "019ff20d-a000-7000-8000-000000000020",
  site_id: siteId,
  key: "poradnik",
  name: "Poradnik",
  kind: "blog",
  base_path: "poradnik",
  locale_paths: {},
  paths: { pl: "/poradnik/" },
  automation_policy: "manual",
  show_in_navigation: false,
  schema_type: "BlogPosting",
  in_site_feed: true,
  archived: false,
  archived_at: null,
};

function view(wrap: (panel: ReactNode) => ReactNode = (panel) => panel) {
  return render(
    <NextIntlClientProvider
      locale="pl"
      messages={polishMessages}
      timeZone="Europe/Warsaw"
    >
      {wrap(
        <ContentTypeSettings
          onSwitchedOff={vi.fn()}
          siteId={siteId}
          typeId={guide.id}
        />,
      )}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getPublicLocales.mockRejectedValue(new Error("offline"));
  api.listContentTypes.mockResolvedValue({
    types: [{ collection: guide, entries: 2, published: 2, locales: ["pl"] }],
    limit: { allowed: true, reason: "" },
    schema_types: [
      {
        schema_type: "BlogPosting",
        title: { pl: "Wpisy bloga", en: "Blog posts" },
        hint: { pl: "Artykuły i porady.", en: "Articles." },
        in_site_feed: true,
      },
    ],
  });
});

test("wydawca: nazwa, rodzaj dla wyszukiwarek i integracje — bez kanału RSS i menu strony", async () => {
  const { container } = view((panel) => (
    <PanelAccessProvider
      access={{
        modules: ["shared.sites"],
        permissions: null,
        isOwner: true,
        limited: false,
        publisher: true,
      }}
    >
      {panel}
    </PanelAccessProvider>
  ));

  expect(await screen.findByLabelText("Nazwa")).toHaveValue("Poradnik");
  expect(screen.getByLabelText("Czym są wpisy")).toHaveValue("BlogPosting");
  expect(screen.getByLabelText("Kto redaguje tę treść")).toBeTruthy();
  expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0);
  for (const word of [
    "RSS",
    "menu strony",
    "Menu strony",
    "publikacji strony",
    "znika ze strony ",
  ])
    expect(container, word).not.toHaveTextContent(word);
  expect(
    screen.getByText(
      "Nazwa typu i to, czym jego wpisy są dla wyszukiwarek. Zmiany działają od razu.",
    ),
  ).toBeTruthy();
});

test("firma: kanał RSS i menu strony są tam, gdzie były", async () => {
  const { container } = view();

  expect(await screen.findByLabelText("Nazwa")).toHaveValue("Poradnik");
  expect(
    screen.getByLabelText(/Pokazuj wpisy w kanale RSS strony/),
  ).toBeChecked();
  expect(
    screen.getByLabelText(/Pokaż ten typ treści w menu strony/),
  ).not.toBeChecked();
  expect(container).toHaveTextContent("Menu strony");
});
