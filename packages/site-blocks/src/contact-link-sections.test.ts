import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  coreSectionTemplates,
  coreSiteBlockManifest,
  createSiteBlockRegistry,
  replaceSectionLayout,
  sectionTemplateBlock,
  type SiteBlock,
} from "./index";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const photo = {
  asset_id: "019ff20d-a000-7000-8000-000000000099",
  alt: "Our real office",
};
const contact = {
  title: "Talk to our team",
  text: "Our own contact introduction",
  email: "team@example.test",
  phone: "+48 (123) 456-789",
  address: "12 Example Street\nExample City",
  hours: "Monday–Friday 9:00–17:00",
  image: photo,
  action: { label: "Find our office", href: "https://example.test/directions" },
};

describe("contact layouts", () => {
  it("keeps the original v1 markup and migrates without dropping or inventing data", () => {
    const block = {
      block_type: "core.contact",
      schema_version: 1,
      data: {
        title: "Contact",
        email: "hello@example.test",
        phone: "+48 (123) 456-789",
        address: "Example Street",
      },
    };
    const before = structuredClone(block);
    const html = renderToStaticMarkup(registry.render(block, "legacy"));
    expect(html).toBe(
      '<section class="site-block site-block--contact" data-block-type="core.contact"><h2>Contact</h2><address><a href="mailto:hello@example.test">hello@example.test</a><a href="tel:+48123456789">+48 (123) 456-789</a><p>Example Street</p></address></section>',
    );
    const migrated = registry.migrate(block);
    expect(migrated).toEqual({ ...block, schema_version: 2 });
    expect(renderToStaticMarkup(registry.render(migrated, "migrated"))).toBe(
      html,
    );
    expect(block).toEqual(before);
    expect(() =>
      registry.validate({ ...block, data: { ...block.data, layout: "split" } }),
    ).toThrow();
  });

  it("keeps every contact field and photo when replacing each of the six layouts", () => {
    const templates = coreSectionTemplates().filter(
      (item) => item.blockType === "core.contact",
    );
    expect(templates.map((item) => item.layout)).toEqual([
      "classic",
      "split",
      "cards",
      "band",
      "photo",
      "details",
    ]);
    const original: SiteBlock = {
      block_type: "core.contact",
      schema_version: 2,
      data: contact,
    };
    for (const template of templates) {
      const changed = replaceSectionLayout(original, template, registry);
      expect(changed.data).toEqual({ ...contact, layout: template.layout });
      const html = renderToStaticMarkup(registry.render(changed, template.id));
      expect(html).toContain(`site-contact--${template.layout}`);
      for (const value of [
        contact.title,
        contact.text,
        contact.email,
        contact.address,
        contact.hours,
        contact.action.label,
      ])
        expect(html).toContain(value);
      expect(html).toContain('href="tel:+48123456789"');
      expect(html).toContain(`src="/media/${photo.asset_id}"`);
      expect(html).toContain('alt="Our real office"');
      expect(html).not.toContain("<form");
    }
    expect(original.data).toEqual(contact);
  });

  it("renders new fields from an old editor draft even before a layout is selected", () => {
    const html = renderToStaticMarkup(
      registry.render(
        { block_type: "core.contact", schema_version: 2, data: contact },
        "new-fields",
      ),
    );
    expect(html).toContain(contact.text);
    expect(html).toContain(contact.hours);
    expect(html).toContain(contact.action.label);
    expect(html).toContain("site-contact--classic");
  });

  it("uses the supplied private photo adapter and never emits navigation in inline editing", () => {
    const calls: string[] = [];
    const html = renderToStaticMarkup(
      registry.render(
        {
          block_type: "core.contact",
          schema_version: 2,
          data: { ...contact, layout: "photo" },
        },
        "editor",
        {
          text: (path, value) => {
            calls.push(path.join("."));
            return h("button", { type: "button" }, value);
          },
        },
        (image) =>
          h("img", { src: "blob:private-contact-photo", alt: image.alt }),
      ),
    );
    expect(html).toContain('src="blob:private-contact-photo"');
    expect(html).not.toContain("/media/");
    expect(html).not.toContain("<a ");
    expect(html).toContain('class="site-section__action"');
    expect(calls).toEqual([
      "title",
      "text",
      "email",
      "phone",
      "address",
      "hours",
      "action.label",
    ]);
  });
});

describe("link and social layouts", () => {
  it("renders every link and description in all six layouts, including at the twelve-link limit", () => {
    const templates = coreSectionTemplates().filter(
      (item) => item.blockType === "core.link_list",
    );
    expect(templates.map((item) => item.layout)).toEqual([
      "buttons",
      "icons",
      "cards",
      "list",
      "split",
      "band",
    ]);
    const links = Array.from({ length: 12 }, (_, i) => ({
      label: `Resource ${i}`,
      href: `/resource-${i}`,
      description: `Description ${i}`,
    }));
    const original: SiteBlock = {
      block_type: "core.link_list",
      schema_version: 1,
      data: {
        title: "Useful destinations",
        text: "Choose a destination",
        links,
      },
    };
    for (const template of templates) {
      const changed = replaceSectionLayout(original, template, registry);
      expect(changed.data.links).toEqual(links);
      const html = renderToStaticMarkup(registry.render(changed, template.id));
      expect(html).toContain(`site-links--${template.layout}`);
      for (const link of links) {
        expect(html).toContain(link.label);
        expect(html).toContain(link.description);
        expect(html).toContain(`href="${link.href}"`);
      }
      expect(html).not.toContain("<iframe");
      expect(html).not.toContain("<script");
    }
    expect(() =>
      registry.validate({ ...original, data: { links: [] } }),
    ).toThrow();
    expect(() =>
      registry.validate({ ...original, data: { links: [...links, links[0]] } }),
    ).toThrow();
  });

  it.each([
    ["https://www.instagram.com/example", "instagram"],
    ["https://www.youtube.com/example", "youtube"],
    ["https://youtu.be/example", "youtube"],
    ["https://www.linkedin.com/company/example", "linkedin"],
    ["https://www.facebook.com/example", "facebook"],
    ["https://x.com/example", "x"],
    ["https://wa.me/123456789", "whatsapp"],
    ["mailto:hello@example.test", "mail"],
    ["tel:+48123456789", "phone"],
    ["/contact", "link"],
    ["https://instagram.com.evil.test/example", "link"],
    ["https://instagram.com@evil.test/example", "link"],
  ])("recognizes only known hostnames for %s", (href, expected) => {
    const html = renderToStaticMarkup(
      registry.render(
        {
          block_type: "core.link_list",
          schema_version: 1,
          data: {
            layout: "icons",
            links: [{ label: "Visible channel name", href }],
          },
        },
        "channel",
      ),
    );
    expect(html).toContain(`data-site-icon="${expected}"`);
    expect(html).toContain("Visible channel name");
    expect(html).toContain('aria-hidden="true"');
  });

  it.each([
    "javascript:alert(1)",
    "ssh://example.test",
    "http://example.test",
    "//evil.test",
    "data:text/html,test",
    "file:///etc/passwd",
  ])("rejects non-allowlisted link targets: %s", (href) => {
    expect(() =>
      registry.validate({
        block_type: "core.link_list",
        schema_version: 1,
        data: { links: [{ label: "Unsafe", href }] },
      }),
    ).toThrow();
    expect(() =>
      registry.validate({
        block_type: "core.contact",
        schema_version: 2,
        data: { action: { label: "Unsafe", href } },
      }),
    ).toThrow();
  });

  it("escapes labels and rejects payload-supplied artwork", () => {
    const block = {
      block_type: "core.link_list",
      schema_version: 1,
      data: {
        links: [
          {
            label: '<img src=x onerror="alert(1)">',
            href: "https://example.test",
          },
        ],
      },
    };
    const html = renderToStaticMarkup(registry.render(block, "safe-text"));
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(() =>
      registry.validate({
        ...block,
        data: {
          links: [{ label: "Icon", href: "/", svg: "<svg onload=alert(1)>" }],
        },
      }),
    ).toThrow();
  });

  it("keeps inline editing on the exact item and removes link navigation", () => {
    const template = coreSectionTemplates().find(
      (item) => item.id === "core.link_list_cards",
    )!;
    const block = sectionTemplateBlock(template, "en", registry);
    const paths: string[] = [];
    const html = renderToStaticMarkup(
      registry.render(block, "editor", {
        text: (path, value) => {
          paths.push(path.join("."));
          return h("button", { type: "button" }, value);
        },
      }),
    );
    expect(html).not.toContain("<a ");
    expect(paths).toContain("links.1.label");
    expect(paths).toContain("links.1.description");
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths.filter((path) => path.endsWith("href"))).toEqual([]);
  });
});
