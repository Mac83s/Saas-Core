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

const SLOTS = new RegExp(SLOT.source, "g");
const MARK = "\u0000";

/**
 * The text without the sentences that hold a slot. A slot is marked before
 * the text is cut into sentences: its own words („np. czy przyjść…”) hold
 * full stops that must not cut it in two.
 */
export function withoutSlots(text: string): string {
  if (!SLOT.test(text)) return text;
  return text
    .replace(SLOTS, MARK)
    .split(/(?<=[.!?…])\s+/)
    .filter((sentence) => !sentence.includes(MARK))
    .join(" ")
    .trim();
}

const LEFT_OUT = Symbol("left out");

/**
 * How far a cleaning goes, mildest first:
 * - "keys" drops a value a slot emptied (an optional caption goes away
 *   instead of becoming "");
 * - "items" also drops a list item left with nothing;
 * - "holders" drops a list item that held such a value (an FAQ question whose
 *   answer was a slot, a testimonial that was only slots);
 * - "blank" leaves the emptied value as "" where the block allows it.
 */
type Reach = "keys" | "items" | "holders" | "blank";
const REACHES: readonly Reach[] = ["keys", "items", "holders", "blank"];

function emptied(value: string): boolean {
  return SLOT.test(value) && withoutSlots(value) === "";
}

function holdsEmptied(value: unknown): boolean {
  if (typeof value === "string") return emptied(value);
  if (Array.isArray(value)) return value.some(holdsEmptied);
  if (value !== null && typeof value === "object")
    return Object.values(value).some(holdsEmptied);
  return false;
}

const nothingLeft = (value: unknown) =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  Object.keys(value).length === 0;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

/**
 * A list item whose own list the cleaning emptied — a paragraph with no
 * words left, a list with no items: it goes with them.
 */
function hollow(before: unknown, after: unknown): boolean {
  if (!isRecord(before) || !isRecord(after)) return false;
  return Object.entries(before).some(([key, value]) => {
    const now = after[key];
    return (
      Array.isArray(value) &&
      value.length > 0 &&
      Array.isArray(now) &&
      now.length === 0
    );
  });
}

function clean(value: unknown, reach: Reach): unknown {
  if (typeof value === "string")
    return emptied(value)
      ? reach === "blank"
        ? ""
        : LEFT_OUT
      : withoutSlots(value);
  if (Array.isArray(value))
    return value
      .filter((item) => !(reach === "holders" && holdsEmptied(item)))
      .map((item) => [item, clean(item, reach)] as const)
      .filter(
        ([before, after]) =>
          after !== LEFT_OUT &&
          !(reach !== "keys" && (nothingLeft(after) || hollow(before, after))),
      )
      .map(([, after]) => after);
  if (value !== null && typeof value === "object") {
    const href = (value as { href?: unknown }).href;
    // A link to the sample contact goes with its label: an action, a row.
    if (typeof href === "string" && isTemplateContact(href)) return LEFT_OUT;
    const kept: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      const next = clean(item, reach);
      if (next === LEFT_OUT) continue;
      // A part left with nothing (an author who was only slots) goes too.
      if (reach !== "keys" && (nothingLeft(next) || hollow(item, next)))
        continue;
      kept[key] = next;
    }
    return kept;
  }
  return value;
}

/**
 * The blocks without their slots and sample contact, each one still valid:
 * a cleaning the block's schema refuses is tried a step further, and a block
 * no cleaning keeps valid — nothing but slots where words are required, a
 * testimonial nobody gave — is left out of the page. One block never takes
 * the whole page down, and a visitor never reads a slot (UX-038, 03.10).
 */
export function withoutTemplateLeftovers<T extends { data: unknown }>(
  blocks: readonly T[],
  valid: (block: T) => boolean = () => true,
): T[] {
  return blocks.flatMap((block) => {
    if (!holdsLeftover(block.data)) return [block];
    for (const reach of REACHES) {
      const cleaned = { ...block, data: clean(block.data, reach) };
      if (valid(cleaned)) return [cleaned];
    }
    return [];
  });
}

/** A slot or a link to the sample contact anywhere in the data. */
function holdsLeftover(value: unknown): boolean {
  if (typeof value === "string") return SLOT.test(value);
  if (Array.isArray(value)) return value.some(holdsLeftover);
  if (value !== null && typeof value === "object") {
    const href = (value as { href?: unknown }).href;
    if (typeof href === "string" && isTemplateContact(href)) return true;
    return Object.values(value).some(holdsLeftover);
  }
  return false;
}
