import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import schema from "@saas-core/contracts/site-blocks/core.contact_form.v2.schema.json";

import { CONTACT_FORM_FIELDS, contactFormFields } from "./contact-form-block";
import { coreSiteBlockManifest } from "./core-manifest";
import { createSiteBlockRegistry } from "./registry";
import type { JsonObject } from "./types";

const registry = createSiteBlockRegistry([coreSiteBlockManifest]);
const render = (data: JsonObject) =>
  renderToStaticMarkup(
    registry.render(
      { block_type: "core.contact_form", schema_version: 2, data },
      "form",
    ),
  );

describe("contact form v2", () => {
  it("covers every variant the contract allows and keeps a way to reply", () => {
    expect(Object.keys(CONTACT_FORM_FIELDS).sort()).toEqual(
      [...schema.properties.contact.enum].sort(),
    );
    for (const rules of Object.values(CONTACT_FORM_FIELDS))
      expect([rules.email, rules.phone]).toContain("required");
  });

  it("a v1 form migrates to v2 and asks for what it asked before", () => {
    const migrated = registry.migrate({
      block_type: "core.contact_form",
      schema_version: 1,
      data: { title: "Kontakt" },
    });
    expect(migrated).toMatchObject({
      schema_version: 2,
      data: { title: "Kontakt" },
    });
    expect(contactFormFields(migrated.data)).toEqual([
      { field: "name", rule: "required" },
      { field: "email", rule: "required" },
      { field: "phone", rule: "optional" },
      { field: "message", rule: "required" },
    ]);
    expect(render({ title: "Kontakt" })).toContain("Telefon (opcjonalnie)");
  });

  it("a call-back form asks for the phone first and marks the rest optional", () => {
    const markup = render({ title: "Oddzwonimy", contact: "callback" });
    expect(markup.indexOf("Telefon")).toBeLessThan(markup.indexOf("E-mail"));
    expect(markup).toContain("E-mail (opcjonalnie)");
    expect(markup).toContain("Wiadomość (opcjonalnie)");
    expect(markup).not.toContain("Telefon (opcjonalnie)");
  });

  it("an e-mail-only form has no phone field", () => {
    const markup = render({
      title: "Napisz",
      contact: "email_only",
      locale: "en",
    });
    expect(markup).not.toContain('type="tel"');
    expect(markup).toContain("Email");
  });
});
