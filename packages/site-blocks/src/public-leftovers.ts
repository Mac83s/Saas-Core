/**
 * What a published page leaves out of a template it was built from (UX-038):
 * a sentence that still holds an owner's `[Uzupełnij: …]` slot, and a link to
 * the template's sample phone or e-mail. The panel's readiness card names
 * both before publishing; a visitor never reads „[Uzupełnij: …]” nor calls
 * +48 000 000 000. Drafts and previews keep everything — the owner fills it in
 * there.
 */

/** The same slot the backend counts (`content_protocol.tokens`). */
const SLOT = /\[(?:Uzupełnij|Fill in):[^\]]*\]/;
const TEMPLATE_PHONE = /^tel:(\+\d{2})?0{9,}$/;
const TEMPLATE_EMAIL = /^mailto:[^@]+@example\.(com|org|net)$/i;

export function isTemplateContact(href: string): boolean {
  return (
    TEMPLATE_PHONE.test(href.replace(/\s/g, "")) ||
    TEMPLATE_EMAIL.test(href.trim())
  );
}

/** The text without the sentences that hold a slot. */
export function withoutSlots(text: string): string {
  if (!SLOT.test(text)) return text;
  return text
    .split(/(?<=[.!?…])\s+/)
    .filter((sentence) => !SLOT.test(sentence))
    .join(" ")
    .trim();
}

const LEFT_OUT = Symbol("left out");

function clean(value: unknown): unknown {
  if (typeof value === "string") return withoutSlots(value);
  if (Array.isArray(value))
    return value.map(clean).filter((item) => item !== LEFT_OUT);
  if (value !== null && typeof value === "object") {
    const href = (value as { href?: unknown }).href;
    // A link to the sample contact goes with its label: an action, a row.
    if (typeof href === "string" && isTemplateContact(href)) return LEFT_OUT;
    const kept: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      const next = clean(item);
      if (next !== LEFT_OUT) kept[key] = next;
    }
    return kept;
  }
  return value;
}

export function withoutTemplateLeftovers<T extends { data: unknown }>(
  blocks: readonly T[],
): T[] {
  return blocks.map((block) => ({ ...block, data: clean(block.data) }));
}
