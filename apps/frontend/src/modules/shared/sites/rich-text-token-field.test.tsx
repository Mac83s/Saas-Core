import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { Editor } from "@tiptap/core";

import {
  TokenText,
  TokenTextField,
  tokenFieldExtensions,
} from "./rich-text-token-field";
import { docToTokens, runsToDoc, tokenRuns } from "./rich-text-tokens";

const SOURCE = "Przeczytaj ⟦1⟧naszą ofertę⟦/1⟧ albo ⟦2⟧partnera⟦/2⟧.";
const MARKS = [{ bold: true, href: "/oferta/" }, { italic: true }];

test("a translated run shows the source's formatting, the link with its target", async () => {
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <span id="label">Treść</span>
      <TokenTextField
        id="field"
        value="Lies ⟦1⟧unser Angebot⟦/1⟧ oder ⟦2⟧den Partner⟦/2⟧."
        onChange={vi.fn()}
        source={SOURCE}
        marks={MARKS}
        labelledBy="label"
        onRefused={vi.fn()}
      />
    </NextIntlClientProvider>,
  );

  const field = await screen.findByRole("textbox", { name: "Treść" });
  await waitFor(() =>
    expect(field.querySelector('[data-token="1"]')?.textContent).toBe(
      "unser Angebot",
    ),
  );
  const link = field.querySelector('[data-token="1"]');
  expect(link?.getAttribute("title")).toBe("link do /oferta/");
  expect(link?.className).toContain("font-semibold");
  expect(field.querySelector('[data-token="2"]')?.className).toContain(
    "italic",
  );
});

test("the source run reads as the page shows it", () => {
  const { container } = render(<TokenText text={SOURCE} marks={MARKS} />);
  expect(container.textContent).toBe("Przeczytaj naszą ofertę albo partnera.");
  expect(container.querySelector(".font-semibold")?.textContent).toBe(
    "naszą ofertę",
  );
});

test("a token can be moved and reworded, never removed or split, and says why", () => {
  const refused = vi.fn();
  const editor = new Editor({
    extensions: tokenFieldExtensions((href) => href, [1, 2], refused),
    content: runsToDoc(tokenRuns(SOURCE), MARKS),
  });
  // "naszą ofertę" spans positions 12–24 (the paragraph opens at 1).
  editor.commands.insertContentAt({ from: 12, to: 17 }, "unsere");
  expect(docToTokens(editor.getJSON())).toBe(
    "Przeczytaj ⟦1⟧unsere ofertę⟦/1⟧ albo ⟦2⟧partnera⟦/2⟧.",
  );
  expect(refused).not.toHaveBeenCalled();

  const before = docToTokens(editor.getJSON());
  editor.commands.deleteRange({ from: 12, to: 25 });
  expect(docToTokens(editor.getJSON())).toBe(before);
  expect(refused).toHaveBeenLastCalledWith("token_removed");

  // Plain words in the middle of a token would make it two.
  editor.view.dispatch(
    editor.state.tr.insertText(" X ", 15).removeMark(15, 18),
  );
  expect(docToTokens(editor.getJSON())).toBe(before);
  expect(refused).toHaveBeenLastCalledWith("token_split");
  editor.destroy();
});
