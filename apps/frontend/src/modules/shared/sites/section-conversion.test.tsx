import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import type { SiteBlock } from "@saas-core/site-blocks";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { SectionTypeChooser } from "./section-conversion";

afterEach(cleanup);

const list: SiteBlock = {
  block_type: "core.feature_list",
  schema_version: 5,
  data: {
    layout: "cards",
    title: "Co warto wiedzieć",
    lead: "Krótko o zasadach",
    items: [
      { title: "Ile to trwa?", text: "Około godziny." },
      { title: "Czy trzeba się przygotować?" },
    ],
  },
};

function show(
  block: SiteBlock,
  locale: "pl" | "en" = "pl",
  onConvert = vi.fn(),
) {
  render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
    >
      <SectionTypeChooser block={block} locale={locale} onConvert={onConvert} />
    </NextIntlClientProvider>,
  );
  return onConvert;
}

test.each([
  ["pl", polishMessages],
  ["en", englishMessages],
] as const)(
  "a list becomes questions and answers after the choice, saying what stays behind (%s)",
  async (locale, messages) => {
    const onConvert = show(list, locale);
    const text = messages.Sites.sectionConversion;
    fireEvent.click(screen.getByRole("button", { name: text.open }));
    const dialog = screen.getByRole("dialog", { name: text.title });
    const faqName = messages.Sites.faqBlock;
    const option = within(dialog)
      .getByRole("heading", { name: faqName })
      .closest("li")!;
    expect(option).toHaveTextContent(messages.Sites.lead);
    expect(onConvert).not.toHaveBeenCalled();
    expect((await axe.run(dialog)).violations).toHaveLength(0);
    fireEvent.click(
      within(option).getByRole("button", {
        name: text.useNamed.replace("{name}", faqName),
      }),
    );
    expect(onConvert).toHaveBeenCalledOnce();
    expect(onConvert.mock.calls[0]![0]).toMatchObject({
      block_type: "core.faq",
      data: {
        title: "Co warto wiedzieć",
        items: [
          { question: "Ile to trwa?", answer: "Około godziny." },
          {
            question: "Czy trzeba się przygotować?",
            answer:
              locale === "pl" ? "[Uzupełnij: odpowiedź]" : "[Fill in: answer]",
          },
        ],
      },
    });
  },
);

test("a question too long for a list stops that change and says which", () => {
  const onConvert = show({
    block_type: "core.faq",
    schema_version: 3,
    data: {
      layout: "accordion",
      items: [
        { question: "Krótko?", answer: "Tak." },
        { question: "P".repeat(150), answer: "Za długie pytanie." },
      ],
    },
  });
  const text = polishMessages.Sites.sectionConversion;
  fireEvent.click(screen.getByRole("button", { name: text.open }));
  const listName = polishMessages.Sites.featureListBlock;
  const option = within(screen.getByRole("dialog"))
    .getByRole("heading", { name: listName })
    .closest("li")!;
  expect(option).toHaveTextContent(
    text.tooLong.replace("{item}", "2").replace("{max}", "120"),
  );
  expect(
    within(option).getByRole("button", {
      name: text.useNamed.replace("{name}", listName),
    }),
  ).toBeDisabled();
  expect(onConvert).not.toHaveBeenCalled();
});

test("a section type with no conversion offers none", () => {
  show({
    block_type: "core.hero",
    schema_version: 6,
    data: { title: "Start", layout: "classic" },
  });
  expect(
    screen.queryByRole("button", {
      name: polishMessages.Sites.sectionConversion.open,
    }),
  ).toBeNull();
});
