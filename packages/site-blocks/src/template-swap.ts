import { ensureUniqueAnchors, richTextAnchors } from "./rich-text";
import { coreSectionTemplates } from "./section-templates";
import type { BlockRegistry, SiteBlock } from "./types";

/** How a page's sections fit a new page template (F4-C). */
export interface TemplateSwapPlan {
  /** Per section of the template: the page section that takes its place, or
   *  `null` where the template's own sample content goes. */
  readonly slots: readonly (number | null)[];
  /** Page sections the template has no place for, in page order. */
  readonly unplaced: readonly number[];
}

/** What the import endpoints take: the template's sections with the page's
 *  own in their places, and the page's sections added after it. */
export interface TemplateSwap {
  readonly kept: readonly {
    readonly slot: number;
    readonly block: SiteBlock;
  }[];
  readonly appended: readonly SiteBlock[];
}

interface Fit {
  readonly type: string;
  readonly layout?: string;
  readonly role?: string;
  readonly stage?: string;
}

const catalogFit = new Map<string, { role: string; stage?: string }>();
for (const template of coreSectionTemplates()) {
  const key = `${template.blockType}|${template.layout}`;
  const known = catalogFit.get(key);
  catalogFit.set(key, {
    role: known?.role ?? template.composition.role,
    stage: known?.stage ?? template.conversion?.stage,
  });
}

/** A section's layout, and its role and path stage as the catalogue knows
 *  that layout. Both sides are read the same way: a page does not remember
 *  the recipe it came from, so a recipe's own per-position stages would not
 *  compare with anything. */
function fitOf(block: SiteBlock): Fit {
  const layout =
    typeof block.data.layout === "string" ? block.data.layout : undefined;
  const known =
    layout === undefined
      ? undefined
      : catalogFit.get(`${block.block_type}|${layout}`);
  return {
    type: block.block_type,
    layout,
    role: known?.role,
    stage: known?.stage,
  };
}

const same = (left?: string, right?: string) =>
  left !== undefined && left === right;

/** Which page section goes where in the new template. The type is the rule —
 *  data never crosses block types here; layout, role and path stage only
 *  decide between several sections of one type. Each pass walks the template
 *  in order and takes the first unused section that fits, so sections of one
 *  kind keep their order. Deterministic: the preview and the import agree. */
export function planTemplateSwap(
  current: readonly SiteBlock[],
  incoming: readonly SiteBlock[],
): TemplateSwapPlan {
  const have = current.map(fitOf);
  const want = incoming.map(fitOf);
  const slots: (number | null)[] = incoming.map(() => null);
  const used = new Set<number>();
  const passes: ((mine: Fit, theirs: Fit) => boolean)[] = [
    (mine, theirs) =>
      mine.type === theirs.type && same(mine.layout, theirs.layout),
    (mine, theirs) =>
      mine.type === theirs.type &&
      same(mine.role, theirs.role) &&
      same(mine.stage, theirs.stage),
    (mine, theirs) => mine.type === theirs.type && same(mine.role, theirs.role),
    (mine, theirs) => mine.type === theirs.type,
  ];
  for (const fits of passes)
    want.forEach((theirs, slot) => {
      if (slots[slot] !== null) return;
      const index = have.findIndex(
        (mine, candidate) => !used.has(candidate) && fits(mine, theirs),
      );
      if (index < 0) return;
      slots[slot] = index;
      used.add(index);
    });
  return {
    slots,
    unplaced: current.flatMap((_, index) => (used.has(index) ? [] : [index])),
  };
}

/** The page's own content in the template's section: the text, lists and
 *  photos stay, the look (layout, decoration, width and anchor) is the
 *  template's. A layout the content does not validate under keeps the
 *  section's own. */
export function keptSection(
  mine: SiteBlock,
  theirs: SiteBlock,
  registry: BlockRegistry,
): SiteBlock {
  const own = registry.migrate(mine);
  const design = registry.migrate(theirs);
  const look = {
    ...(design.decoration
      ? { decoration: structuredClone(design.decoration) }
      : {}),
    ...(design.presentation
      ? { presentation: structuredClone(design.presentation) }
      : {}),
  };
  const layout = design.data.layout;
  const candidate: SiteBlock = {
    block_type: own.block_type,
    schema_version: own.schema_version,
    data:
      typeof layout === "string"
        ? { ...structuredClone(own.data), layout }
        : structuredClone(own.data),
    ...look,
  };
  try {
    registry.validate(candidate);
    return candidate;
  } catch {
    return { ...candidate, data: structuredClone(own.data) };
  }
}

/** The request for the plan: kept sections in the template's look, the rest
 *  added after it when `appendUnplaced`. Anchors stay unique on the page — the
 *  template's own section anchors win (its buttons point at them), anything
 *  of the page's that collides is renamed, links inside it following. */
export function composeTemplateSwap(
  current: readonly SiteBlock[],
  incoming: readonly SiteBlock[],
  plan: TemplateSwapPlan,
  registry: BlockRegistry,
  appendUnplaced: boolean,
): TemplateSwap {
  const kept = plan.slots.flatMap((index, slot) =>
    index === null
      ? []
      : [
          {
            slot,
            block: keptSection(current[index]!, incoming[slot]!, registry),
          },
        ],
  );
  const appended = appendUnplaced
    ? plan.unplaced.map((index) => registry.migrate(current[index]!))
    : [];
  // The template's anchors as they will stand: its sample sections whole,
  // only the section anchor where the page's content takes the place.
  const keptSlots = new Set(kept.map(({ slot }) => slot));
  const taken = new Set(
    richTextAnchors(
      incoming.map((block, slot) =>
        keptSlots.has(slot) ? { ...block, data: {} } : block,
      ),
    ),
  );
  const unique = ensureUniqueAnchors(
    [...kept.map(({ block }) => withoutSectionAnchor(block)), ...appended],
    taken,
  );
  return {
    kept: kept.map(({ slot, block }, index) => ({
      slot,
      block: {
        ...unique[index]!,
        ...(block.presentation ? { presentation: block.presentation } : {}),
      },
    })),
    appended: unique.slice(kept.length),
  };
}

function withoutSectionAnchor(block: SiteBlock): SiteBlock {
  if (block.presentation?.schemaVersion !== 2) return block;
  const { anchor: _anchor, ...presentation } = block.presentation;
  return { ...block, presentation };
}
