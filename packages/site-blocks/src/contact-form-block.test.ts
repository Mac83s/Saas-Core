import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  renderDraftPreview,
  renderPublishedPage,
  sectionTemplateBlock,
  type DesignTokensV1,
  type PublishedPageDocument,
  type SiteBlock,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const tokens: DesignTokensV1 = {
  schemaVersion: 1,
  palette: "blue",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
};
const block: SiteBlock = {
  block_type: "core.contact_form",
  schema_version: 1,
  data: { title: "Contact", privacy_href: "/privacy" },
};
const document: PublishedPageDocument = {
  kind: "publication",
  publicationId: "publication-1",
  snapshotHash: "a".repeat(64),
  designTokens: tokens,
  blocks: [
    {
      block_type: "core.rich_text",
      schema_version: 1,
      data: { text: "Hello" },
    },
    block,
  ],
};

describe("publication contact forms", () => {
  it("supplies the immutable document position to the public adapter", () => {
    const adapter = vi.fn((_, position: number) =>
      createElement("form", { "data-position": position }, "Send"),
    );
    const markup = renderToStaticMarkup(
      renderPublishedPage(document, registry, adapter),
    );
    expect(adapter).toHaveBeenCalledExactlyOnceWith(block.data, 1);
    expect(markup).toContain('<form data-position="1">');
    expect(markup).not.toContain("disabled");
  });

  it("uses a disabled preview with no nested form or submit button in drafts", () => {
    const markup = renderToStaticMarkup(
      createElement(
        "form",
        null,
        renderDraftPreview(
          {
            kind: "draft-preview",
            versionId: "draft-1",
            blocks: [block],
            designTokens: tokens,
          },
          registry,
        ),
      ),
    );
    expect(markup.match(/<form/g)).toHaveLength(1);
    expect(markup).toContain("disabled");
    expect(markup).not.toContain('type="submit"');
    expect(markup).toContain("site-section__action");
  });

  it("keeps the live adapter inactive during inline editing, including optional label fallbacks", () => {
    const form = vi.fn();
    const editor = {
      text: vi.fn((path: readonly string[], value: string) => {
        expect(block.data).toHaveProperty(path.join("."), value);
        return value;
      }),
    };
    const markup = renderToStaticMarkup(
      registry.render(block, "form", editor, undefined, form),
    );
    expect(form).not.toHaveBeenCalled();
    expect(markup).not.toContain("<form");
    expect(markup).not.toContain("<a ");
  });

  it("validates all four layouts in both languages and keeps recipients out of public content", () => {
    const templates = coreSectionTemplates().filter(
      (item) => item.blockType === "core.contact_form",
    );
    expect(templates).toHaveLength(4);
    for (const template of templates)
      for (const locale of ["pl", "en"] as const) {
        const content = sectionTemplateBlock(template, locale, registry);
        expect(content.data.locale).toBe(locale);
        expect(() => registry.validate(content)).not.toThrow();
        expect(() =>
          registry.validate({
            ...content,
            data: { ...content.data, recipient_email: "private@example.com" },
          }),
        ).toThrow();
      }
    for (const privacy_href of [
      "javascript:alert(1)",
      "//outside.example",
      "data:text/html,test",
    ]) {
      expect(() =>
        registry.validate({ ...block, data: { ...block.data, privacy_href } }),
      ).toThrow();
    }
  });
});
