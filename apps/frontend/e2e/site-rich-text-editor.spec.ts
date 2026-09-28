import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  expect as baseExpect,
  test,
  type Locator,
  type Page,
} from "@playwright/test";

// The Site Studio rich-text editor (TipTap on the `core.rich_text` contract,
// ADR-056) driven in the real panel on a running stack. jsdom cannot type
// into contentEditable, so typing, shortcuts, paste, full screen and the
// page's undo are proven only here. It writes to the stack through a
// synthetic w6-e2e-* account, removed afterwards; how to run it:
// e2e/site-catalog.md.

// Commits after 700 ms idle and remounts after undo take a moment on a
// loaded host.
const expect = baseExpect.configure({ timeout: 15_000 });
const env = process.env;
const here = path.dirname(fileURLToPath(import.meta.url));
const runId = randomUUID().replaceAll("-", "").slice(0, 10);
const slug = `w6-e2e-editor-${runId}`;
// The environment of site-catalog-run.sh, which owns the fixture.
const account = {
  SITE_CATALOG_SLUG: slug,
  SITE_CATALOG_EMAIL: `${slug}@example.test`,
  SITE_CATALOG_PASSWORD: `W6-E2E-${randomUUID()}-aA1!`,
};

const MARKER = "[Uzupełnij: kwota]";

// `core.rich_text` v4 node shapes (packages/contracts/site-blocks/
// core.rich_text.v4.schema.json): a new contract version changes the
// expected JSON below too.
const seededContent = [
  { type: "paragraph", content: [{ text: "Pierwszy akapit." }] },
  {
    type: "list",
    style: "bullet",
    items: [
      { content: [{ text: "Punkt pierwszy" }] },
      { content: [{ text: "Punkt drugi" }] },
    ],
  },
  { type: "paragraph", content: [{ text: `Cena: ${MARKER} zł.` }] },
];

// What Word puts on the clipboard, trimmed: a document with its own styles,
// list items as MsoListParagraph paragraphs behind a `mso-list:Ignore`
// bullet, a Google-Docs-style `<b>` that is not bold, a script link and an
// image. Only the contract's nodes and marks may come through.
const wordHtml = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word">
<head><meta charset="utf-8"><style>p.MsoNormal{margin:0cm;font-family:"Calibri",sans-serif}</style></head>
<body lang=PL style='tab-interval:35.4pt'>
<!--StartFragment-->
<p class=MsoNormal><b>Ważne</b> <span style='color:red;font-family:"Comic Sans MS"'>zdanie</span> <a href="javascript:alert(1)">z linkiem</a><o:p></o:p></p>
<p class=MsoListParagraphCxSpFirst style='text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol;mso-list:Ignore'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp;&nbsp; </span></span><![endif]>punkt z Worda<o:p></o:p></p>
<p class=MsoListParagraphCxSpLast style='text-indent:-18.0pt;mso-list:l0 level1 lfo1'><![if !supportLists]><span style='font-family:Symbol;mso-list:Ignore'>·<span style='font:7.0pt "Times New Roman"'>&nbsp;&nbsp;&nbsp;&nbsp; </span></span><![endif]><i>drugi</i> punkt<o:p></o:p></p>
<p class=MsoNormal><span style='font-weight:700'>To tak</span>, <b style="font-weight:normal">to nie</b><o:p></o:p></p>
<p class=MsoNormal><img width=10 height=10 src="file:///C:/Users/x/image001.png"><o:p></o:p></p>
<!--EndFragment-->
</body></html>`;
const wordText =
  "Ważne zdanie z linkiem\n\n· punkt z Worda\n· drugi punkt\n\nTo tak, to nie";

/** The rich-text block's `content` after the whole run, as stored. */
const expectedContent = [
  {
    type: "paragraph",
    content: [
      { text: "Pierwszy akapit. Dopisany tekst i " },
      { text: "pogrubienie", bold: true },
      { text: "." },
    ],
  },
  {
    type: "heading",
    level: 2,
    anchor: "nowy-rozdzial",
    text: "Nowy rozdział i plan",
  },
  {
    type: "list",
    style: "bullet",
    items: [
      {
        content: [{ text: "Punkt pierwszy" }],
        children: {
          style: "bullet",
          items: [
            { content: [{ text: "Punkt drugi" }] },
            { content: [{ text: "Punkt trzeci" }] },
          ],
        },
      },
    ],
  },
  {
    type: "paragraph",
    content: [
      { text: "Cena: 249 zł. " },
      { text: "Napisz do nas", href: "#kontakt" },
      { text: "." },
    ],
  },
  {
    type: "paragraph",
    content: [{ text: "Ważne", bold: true }, { text: " zdanie z linkiem" }],
  },
  {
    type: "list",
    style: "bullet",
    items: [
      { content: [{ text: "punkt z Worda" }] },
      { content: [{ text: "drugi", italic: true }, { text: " punkt" }] },
    ],
  },
  {
    type: "paragraph",
    content: [{ text: "To tak", bold: true }, { text: ", to nie" }],
  },
  {
    type: "paragraph",
    content: [{ text: "Tekst z pełnego ekranu. Do cofnięcia." }],
  },
];

interface Draft {
  version: number;
  blocks: {
    block_type: string;
    schema_version: number;
    data: Record<string, unknown>;
    presentation?: Record<string, unknown> | null;
  }[];
}

function fixture(action: "prepare" | "cleanup") {
  execFileSync("bash", [path.join(here, "site-catalog-run.sh"), action], {
    env: { ...env, ...account },
    stdio: "inherit",
  });
}

/** ProseMirror reads the DOM selection asynchronously: a key script faster
 *  than a person (End, then Enter at once) acts on the old selection on a
 *  loaded host. Human pace after cursor moves and before Enter. */
const settle = (page: Page) => page.waitForTimeout(200);

/** A paste from another application: ClipboardEvent with a DataTransfer
 *  holding HTML and plain text, dispatched at the focused editor. It reaches
 *  the editor's own paste handler (the normalizer), like Ctrl+V does. */
async function paste(page: Page, html: string, text: string) {
  await page.evaluate(
    ([html, text]) => {
      const target = document.activeElement;
      if (!(target instanceof HTMLElement) || !target.isContentEditable)
        throw new Error("paste: no focused editor");
      const data = new DataTransfer();
      data.setData("text/html", html);
      data.setData("text/plain", text);
      target.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData: data,
          bubbles: true,
          cancelable: true,
        }),
      );
    },
    [html, text] as const,
  );
}

test.describe("Site Studio rich-text editor on a live stack", () => {
  test.skip(
    env.SITE_EDITOR_E2E !== "1",
    "Creates a synthetic account and writes a page draft on a live stack; run it with SITE_EDITOR_E2E=1 (e2e/site-catalog.md).",
  );
  test.use({ viewport: { width: 1440, height: 900 } });
  test.beforeAll(() => fixture("prepare"));
  test.afterAll(() => fixture("cleanup"));

  test("writes, formats, links, pastes, undoes and saves the contract's JSON", async ({
    page,
  }, testInfo) => {
    test.setTimeout(240_000);
    page.setDefaultTimeout(30_000);
    const origin = new URL(String(testInfo.project.use.baseURL)).origin;
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));

    const api = async <T>(method: string, url: string, data?: unknown) => {
      const csrf = (await page.context().cookies()).find(
        (cookie) => cookie.name === "csrftoken",
      )?.value;
      const response = await page.request.fetch(url, {
        method,
        data,
        headers: {
          "X-CSRFToken": csrf ?? "",
          Origin: origin,
          Referer: `${origin}/panel/sites`,
          ...(method === "GET" ? {} : { "Idempotency-Key": randomUUID() }),
        },
      });
      if (!response.ok())
        throw new Error(
          `${method} ${url}: ${response.status()} ${(await response.text()).slice(0, 600)}`,
        );
      return (await response.json()) as T;
    };

    await page.goto("/login?next=/panel/sites");
    await page
      .getByLabel("E-mail", { exact: true })
      .fill(account.SITE_CATALOG_EMAIL);
    await page
      .getByLabel("Hasło", { exact: true })
      .fill(account.SITE_CATALOG_PASSWORD);
    await page
      .getByRole("button", { name: "Zaloguj się", exact: true })
      .click();
    await page.waitForURL((url) => url.pathname === "/panel/sites");

    // The page to edit: a rich-text section with a paragraph, a list and a
    // place to fill in, and a contact form whose section anchor `#kontakt`
    // the link dialog should offer.
    const site = await api<{ id: string }>("POST", "/api/v1/sites/", {
      name: "Edytor tekstu e2e",
      slug,
      default_locale: "pl",
    });
    const created = await api<{ id: string }>(
      "POST",
      `/api/v1/sites/${site.id}/pages/`,
      { name: "Edytor", key: "edytor" },
    );
    const draftUrl = `/api/v1/sites/pages/${created.id}/draft/`;
    await api("PUT", draftUrl, {
      expected_version: 0,
      blocks: [
        {
          block_type: "core.rich_text",
          schema_version: 4,
          data: { title: "Sekcja do pisania", content: seededContent },
        },
        {
          block_type: "core.contact_form",
          schema_version: 2,
          data: { title: "Napisz do nas" },
          presentation: { schemaVersion: 2, anchor: "kontakt" },
        },
      ],
      media_asset_ids: [],
    });

    await page.reload();
    await page.getByRole("tab", { name: "Treść", exact: true }).click();
    const editor = page.getByRole("textbox", {
      name: "Treść sekcji",
      exact: true,
    });
    // The field around it: its toolbar, its places to fill in, its status.
    const field = page.locator(".rich-text-editor").filter({ has: editor });
    await expect(editor).toContainText("Pierwszy akapit.");

    await test.step("typing appends to a paragraph; Ctrl+B makes a bold run", async () => {
      await editor.getByText("Pierwszy akapit.").click();
      await page.keyboard.press("End");
      await settle(page);
      await page.keyboard.type(" Dopisany tekst i ");
      await page.keyboard.press("Control+b");
      await page.keyboard.type("pogrubienie");
      await page.keyboard.press("Control+b");
      await page.keyboard.type(".");
      await expect(editor.locator("p").first()).toHaveText(
        "Pierwszy akapit. Dopisany tekst i pogrubienie.",
      );
      await expect(editor.locator("strong")).toHaveText("pogrubienie");
    });

    await test.step("a new H2 gets its anchor once, from its text", async () => {
      const anchor = editor.locator("h2 .rich-text-editor__anchor");
      await settle(page);
      await page.keyboard.press("Enter");
      await page.keyboard.press("Control+Alt+2");
      await page.keyboard.type("Nowy rozdział");
      await expect(editor.locator("h2")).toHaveText(/^Nowy rozdział/);
      // Shown after the write that follows a pause in typing.
      await expect(anchor).toHaveText("#nowy-rozdzial");
      // Links point at it: changing the heading's text keeps the anchor.
      await page.keyboard.type(" i plan");
      await expect(editor.locator("h2")).toHaveText(/^Nowy rozdział i plan/);
      await page.waitForTimeout(1_000); // past the next write
      await expect(anchor).toHaveText("#nowy-rozdzial");
    });

    await test.step("Tab nests a list item; a third level is refused", async () => {
      await editor.getByText("Punkt drugi").click();
      await page.keyboard.press("End");
      await settle(page);
      await page.keyboard.press("Tab");
      await expect(editor.locator("li li")).toHaveText(["Punkt drugi"]);
      await settle(page);
      await page.keyboard.press("Enter");
      await page.keyboard.type("Punkt trzeci");
      await settle(page);
      await page.keyboard.press("Tab");
      await settle(page);
      // Refused inside the editor: the caret stays, nothing moves.
      await expect(editor).toBeFocused();
      await expect(editor.locator("li li")).toHaveText([
        "Punkt drugi",
        "Punkt trzeci",
      ]);
      await expect(editor.locator("li li li")).toHaveCount(0);
      await expect(
        field.getByRole("button", { name: "Podpunkt (Tab)" }),
      ).toBeDisabled();
    });

    await test.step("F8 selects the place to fill in; typing replaces it", async () => {
      await expect(
        field.getByText("Zostało 1 miejsce do uzupełnienia."),
      ).toBeVisible();
      await page.keyboard.press("F8");
      await expect
        .poll(() => page.evaluate(() => window.getSelection()?.toString()))
        .toBe(MARKER);
      await page.keyboard.type("249");
      await expect(editor).toContainText("Cena: 249 zł.");
      await expect(editor).not.toContainText("Uzupełnij");
      await expect(
        field.getByText("Zostało 1 miejsce do uzupełnienia."),
      ).toHaveCount(0);
    });

    await test.step("the link dialog offers page anchors and links #kontakt", async () => {
      await page.keyboard.press("End");
      await settle(page);
      await page.keyboard.type(" Napisz do nas.");
      await page.keyboard.press("ArrowLeft");
      for (let step = 0; step < "Napisz do nas".length; step += 1)
        await page.keyboard.press("Shift+ArrowLeft");
      await expect
        .poll(() => page.evaluate(() => window.getSelection()?.toString()))
        .toBe("Napisz do nas");
      await settle(page);
      await page.keyboard.press("Control+k");
      const dialog = page.getByRole("dialog", { name: "Link (Ctrl+K)" });
      const place = dialog.getByLabel("Miejsce na tej stronie");
      // Section and heading anchors share one namespace on the page.
      await expect(place.locator("option")).toHaveText([
        "— wybierz —",
        "#kontakt",
        "#nowy-rozdzial",
      ]);
      await place.selectOption("kontakt");
      await expect(dialog.getByLabel("Adres linku")).toHaveValue("#kontakt");
      await dialog.getByRole("button", { name: "Wstaw link" }).click();
      await expect(dialog).toBeHidden();
      await expect(editor.locator('a[href="#kontakt"]')).toHaveText(
        "Napisz do nas",
      );
      await expect(editor).toBeFocused();
    });

    await test.step("a paste from Word keeps only the contract's nodes and marks", async () => {
      await page.keyboard.press("Control+End");
      await settle(page);
      await page.keyboard.press("Enter");
      await settle(page);
      await paste(page, wordHtml, wordText);
      await expect(
        field.getByText(
          "Wklejono 3 elementy. Obrazy ze schowka nie zostały zaimportowane — dodaj je jako ilustrację.",
        ),
      ).toBeVisible();
      await expect(editor.locator("strong", { hasText: "Ważne" })).toHaveCount(
        1,
      );
      await expect(editor.getByText("to nie")).toBeVisible();
      await expect(editor.locator("strong", { hasText: "to nie" })).toHaveCount(
        0,
      );
      await expect(editor.locator("em")).toHaveText(["drugi"]);
      await expect(editor.locator("ul").last()).toHaveText(
        /punkt z Worda\s*drugi punkt/,
      );
      // ProseMirror's own cursor helper after the heading's #anchor widget
      // is an image too; it is not content.
      await expect(
        editor.locator(
          "img:not(.ProseMirror-separator), [style], a[href^='javascript']",
        ),
      ).toHaveCount(0);
    });

    await test.step("full-screen writing lands in the same field", async () => {
      const look = (paragraph: Locator) =>
        paragraph.evaluate((node) => {
          const style = getComputedStyle(node);
          return `${style.fontFamily} / ${style.color}`;
        });
      const inPanel = await look(editor.locator("p").first());
      await field
        .getByRole("button", { name: "Pisz na pełnym ekranie: Treść sekcji" })
        .click();
      const fullScreen = page.getByRole("dialog", { name: "Treść sekcji" });
      const writing = fullScreen.getByRole("textbox", { name: "Treść sekcji" });
      await expect(writing).toBeFocused();
      // Written in the page's typography: the same paragraph leaves the
      // panel's font and looks like the section on the canvas.
      const written = await look(writing.locator("p").first());
      expect(written).not.toBe(inPanel);
      expect(written).toBe(
        await look(page.locator("[data-section-index='0'] p").first()),
      );
      await expect(
        page.getByText("Tekst jest otwarty na pełnym ekranie."),
      ).toBeVisible();
      await page.keyboard.press("Control+End");
      await settle(page);
      await page.keyboard.press("Enter");
      await page.keyboard.type("Tekst z pełnego ekranu.");
      await expect(writing).toContainText("Tekst z pełnego ekranu.");
      await fullScreen.getByRole("button", { name: "Gotowe" }).click();
      await expect(fullScreen).toBeHidden();
      await expect(editor.locator("p").last()).toHaveText(
        "Tekst z pełnego ekranu.",
      );
    });

    await test.step("Ctrl+Z is the page's undo; Ctrl+Shift+Z and Ctrl+Y redo", async () => {
      await editor.getByText("Tekst z pełnego ekranu.").click();
      await page.keyboard.press("Control+End");
      await settle(page);
      await page.keyboard.type(" Do cofnięcia.");
      await expect(editor).toContainText(
        "Tekst z pełnego ekranu. Do cofnięcia.",
      );
      const redo = page.getByRole("button", { name: "Ponów", exact: true });
      await expect(redo).toBeDisabled();
      // Each step resets the page form and mounts the section's fields
      // again: the caret has to come back into the new editor, or the next
      // shortcut goes nowhere. The old editor is marked to tell them apart.
      const step = async (keys: string, undone: boolean) => {
        await editor.evaluate((node) => {
          (node as Node & { e2eBefore?: true }).e2eBefore = true;
        });
        await page.keyboard.press(keys);
        if (undone) await expect(editor).not.toContainText("Do cofnięcia.");
        else
          await expect(editor.locator("p").last()).toHaveText(
            "Tekst z pełnego ekranu. Do cofnięcia.",
          );
        await expect(editor).toContainText("Tekst z pełnego ekranu.");
        // The page's history, the studio's own Undo/Redo: redo is offered
        // exactly after an undo.
        if (undone) await expect(redo).toBeEnabled();
        else await expect(redo).toBeDisabled();
        await settle(page);
        await expect(editor).toBeFocused();
        expect(
          await page.evaluate(
            () =>
              (document.activeElement as Node & { e2eBefore?: true }).e2eBefore,
          ),
        ).toBeUndefined();
      };
      await step("Control+z", true);
      await step("Control+Shift+z", false);
      await step("Control+z", true);
      await step("Control+y", false);
    });

    await test.step("saving stores exactly the contract's JSON", async () => {
      const saved = page.waitForResponse(
        (response) =>
          response.url().endsWith(draftUrl) &&
          response.request().method() === "PUT",
      );
      await page.getByRole("button", { name: "Zapisz stronę" }).click();
      expect([200, 201]).toContain((await saved).status());
      const draft = await api<Draft>("GET", draftUrl);
      expect(draft.blocks.map((block) => block.block_type)).toEqual([
        "core.rich_text",
        "core.contact_form",
      ]);
      const [text, form] = draft.blocks;
      expect(text.schema_version).toBe(4);
      expect(text.data.content).toEqual(expectedContent);
      expect(text.data.title).toBe("Sekcja do pisania");
      expect(text.data).not.toHaveProperty("aside");
      expect(form.presentation).toEqual({
        schemaVersion: 2,
        anchor: "kontakt",
      });
    });

    expect(errors).toEqual([]);
  });
});
