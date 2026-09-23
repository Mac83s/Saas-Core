import { useState } from "react";
import axe from "axe-core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import {
  coreSiteBlockManifest,
  type PagePresentationV1,
  type SectionPresentationV1,
} from "@saas-core/site-blocks";
import polishMessages from "../../../../messages/pl.json";
import englishMessages from "../../../../messages/en.json";
import { PagePresentationFields } from "./page-presentation-fields";
import { SectionPresentationFields } from "./section-presentation-fields";

afterEach(cleanup);

const messages = { pl: polishMessages, en: englishMessages } as const;

function Section({ onChange }: { onChange: (value: unknown) => void }) {
  const [value, setValue] = useState<SectionPresentationV1 | undefined>();
  return (
    <SectionPresentationFields
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

function Page({ onChange }: { onChange: (value: unknown) => void }) {
  const [value, setValue] = useState<PagePresentationV1 | null>(null);
  return (
    <PagePresentationFields
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

test.each(["pl", "en"] as const)(
  "section width and surface write closed values and reset clears them (%s)",
  async (locale) => {
    const onChange = vi.fn();
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <Section onChange={onChange} />
      </NextIntlClientProvider>,
    );
    const t = messages[locale].Sites.sectionPresentation;
    fireEvent.change(screen.getByLabelText(t.fields.inner), {
      target: { value: "wide" },
    });
    fireEvent.change(screen.getByLabelText(t.fields.surface), {
      target: { value: "muted" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 1,
      inner: "wide",
      surface: "muted",
    });
    expect(screen.getByText(t.hints.surface.muted)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: t.reset }));
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect((await axe.run(container)).violations).toEqual([]);
  },
);

test.each(["pl", "en"] as const)(
  "this page's look says it is page-only, writes fonts and returns to the site look (%s)",
  async (locale) => {
    const onChange = vi.fn();
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <Page onChange={onChange} />
      </NextIntlClientProvider>,
    );
    const t = messages[locale].Sites.pagePresentation;
    expect(screen.getByText(t.description)).toBeDefined();
    fireEvent.change(screen.getByLabelText(t.fields.width), {
      target: { value: "full" },
    });
    fireEvent.change(screen.getByLabelText(t.fields.bodyFont), {
      target: { value: "playfair-display" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 1,
      width: "full",
      bodyFont: "playfair-display",
    });
    // Back to "as the site" on every field is no own look at all.
    fireEvent.change(screen.getByLabelText(t.fields.width), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText(t.fields.bodyFont), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect((await axe.run(container)).violations).toEqual([]);
  },
);

test("every catalogue label the editor shows exists in both languages", () => {
  const keys = new Set<string>();
  const collect = (
    fields: readonly { labelKey: string; item?: readonly unknown[] }[],
  ) => {
    for (const field of fields) {
      keys.add(field.labelKey);
      if (field.item) collect(field.item as typeof fields);
    }
  };
  for (const block of coreSiteBlockManifest.blocks) {
    if (!block.catalog) continue;
    keys.add(block.catalog.labelKey);
    collect(block.catalog.fields);
  }
  for (const locale of ["pl", "en"] as const) {
    const sites = messages[locale].Sites as Record<string, unknown>;
    const missing = [...keys].filter((key) => typeof sites[key] !== "string");
    expect(missing, locale).toEqual([]);
  }
});
