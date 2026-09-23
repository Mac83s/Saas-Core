import { useState, type ReactNode } from "react";
import axe from "axe-core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { FormProvider, useForm } from "react-hook-form";
import { afterEach, expect, test, vi } from "vitest";

import {
  coreSiteBlockManifest,
  type SectionPresentationV2,
} from "@saas-core/site-blocks";
import polishMessages from "../../../../messages/pl.json";
import englishMessages from "../../../../messages/en.json";
import {
  PagePresentationFields,
  PagePresentationSummary,
  type PagePresentation,
} from "./page-presentation-fields";
import { SectionPresentationFields } from "./section-presentation-fields";

afterEach(cleanup);

const messages = { pl: polishMessages, en: englishMessages } as const;

function Section({
  onChange,
  blockIndex,
}: {
  onChange: (value: unknown) => void;
  blockIndex?: number;
}) {
  const [value, setValue] = useState<SectionPresentationV2 | undefined>();
  return (
    <SectionPresentationFields
      blockIndex={blockIndex}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

/** The page form the section fields read other anchors from. */
function PageForm({
  blocks,
  children,
}: {
  blocks: unknown[];
  children: ReactNode;
}) {
  const form = useForm({ defaultValues: { blocks } });
  return <FormProvider {...form}>{children}</FormProvider>;
}

function Page({ onChange }: { onChange: (value: unknown) => void }) {
  const [value, setValue] = useState<PagePresentation | null>(null);
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
      schemaVersion: 2,
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

test.each(["pl", "en"] as const)(
  "a section anchor is written as v2, shows its link and an invalid one is not written (%s)",
  async (locale) => {
    const onChange = vi.fn();
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <Section onChange={onChange} />
      </NextIntlClientProvider>,
    );
    const t = messages[locale].Sites;
    const anchor = screen.getByLabelText(t.sectionPresentation.fields.anchor);
    fireEvent.change(anchor, { target: { value: "kontakt" } });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 2,
      anchor: "kontakt",
    });
    expect(screen.getByText("#kontakt")).toBeDefined();
    expect(anchor).toHaveAccessibleDescription(
      `${t.sectionPresentation.hints.anchor} ${t.sectionPresentation.anchorLink} #kontakt`,
    );

    onChange.mockClear();
    fireEvent.change(anchor, { target: { value: "Kontakt teraz" } });
    expect(onChange).not.toHaveBeenCalled();
    expect(anchor).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(t.richText.anchorInvalid)).toBeDefined();
    expect((await axe.run(container)).violations).toEqual([]);

    // Cleared, and nothing else set: no presentation at all.
    fireEvent.change(anchor, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith(undefined);
    expect(screen.queryByText(t.richText.anchorInvalid)).toBeNull();
  },
);

test.each(["pl", "en"] as const)(
  "a section anchor already used on the page by a heading or a section is flagged (%s)",
  (locale) => {
    const onChange = vi.fn();
    render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <PageForm
          blocks={[
            {
              block_type: "core.rich_text",
              data: {
                content: [
                  { type: "heading", level: 2, anchor: "oferta", text: "O" },
                ],
              },
            },
            {
              block_type: "core.hero",
              data: { title: "Start" },
              presentation: { schemaVersion: 2, anchor: "kontakt" },
            },
            // This section: its own stored anchor never counts as taken.
            {
              block_type: "core.contact_form",
              data: {},
              presentation: { schemaVersion: 2, anchor: "formularz" },
            },
          ]}
        >
          <Section blockIndex={2} onChange={onChange} />
        </PageForm>
      </NextIntlClientProvider>,
    );
    const t = messages[locale].Sites;
    const anchor = screen.getByLabelText(t.sectionPresentation.fields.anchor);
    for (const taken of ["oferta", "kontakt"]) {
      fireEvent.change(anchor, { target: { value: taken } });
      expect(screen.getByText(t.richText.anchorTaken)).toBeDefined();
      expect(anchor).toHaveAttribute("aria-invalid", "true");
    }
    fireEvent.change(anchor, { target: { value: "formularz" } });
    expect(screen.queryByText(t.richText.anchorTaken)).toBeNull();
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 2,
      anchor: "formularz",
    });
  },
);

test.each(["pl", "en"] as const)(
  "a page style is written as v2 with its description, fonts alone stay v1 (%s)",
  async (locale) => {
    const onChange = vi.fn();
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <Page onChange={onChange} />
      </NextIntlClientProvider>,
    );
    const t = messages[locale].Sites.pagePresentation;
    const style = screen.getByLabelText(t.fields.style);
    expect(style).toHaveAccessibleDescription(t.hints.style);
    expect(
      [...style.querySelectorAll("option")].map((option) => option.value),
    ).toEqual(["", ...Object.keys(t.styles)]);
    fireEvent.change(style, { target: { value: "editorial" } });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 2,
      style: "editorial",
    });
    expect(style).toHaveAccessibleDescription(t.styles.editorial.description);
    fireEvent.change(screen.getByLabelText(t.fields.headingFont), {
      target: { value: "lora" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 2,
      style: "editorial",
      headingFont: "lora",
    });
    expect((await axe.run(container)).violations).toEqual([]);

    fireEvent.change(style, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({
      schemaVersion: 1,
      headingFont: "lora",
    });
    fireEvent.change(style, { target: { value: "technical" } });
    fireEvent.click(screen.getByRole("button", { name: t.reset }));
    expect(onChange).toHaveBeenLastCalledWith(null);
  },
);

test.each(["pl", "en"] as const)(
  "the review summary names the page style (%s)",
  (locale) => {
    const t = messages[locale].Sites.pagePresentation;
    const { container } = render(
      <NextIntlClientProvider locale={locale} messages={messages[locale]}>
        <PagePresentationSummary
          value={{ schemaVersion: 2, style: "premium", width: "full" }}
        />
      </NextIntlClientProvider>,
    );
    expect(container).toHaveTextContent(
      `${t.summaryStyle.replace("{style}", t.styles.premium.name)} · ${t.fullWidth}`,
    );
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
