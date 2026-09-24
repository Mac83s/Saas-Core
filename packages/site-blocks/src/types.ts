import type { SiteAppearance } from "./appearance";
import type { ComponentType, ReactElement, ReactNode } from "react";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

export interface SiteBlock<TData extends JsonObject = JsonObject> {
  readonly block_type: string;
  readonly schema_version: number;
  readonly data: TData;
  readonly decoration?: SectionDecorationV1;
  readonly presentation?: SectionPresentationV1 | SectionPresentationV2;
}

/** Shared allowlisted presentation, separate from the versioned content data. */
export type SectionDecorationV1 = {
  schemaVersion: 1;
  background?: "none" | "tint" | "gradient" | "grid" | "dots";
  frame?: "none" | "outline" | "accent" | "double";
  ornament?: "none" | "orbs" | "rings" | "wave" | "botanical" | "sparkles";
  placement?: "top_right" | "bottom_left" | "both";
  intensity?: "subtle" | "soft";
  motion?: "none" | "drift" | "breathe";
};

/** Second optional envelope, beside decoration: how wide the section's content
 *  runs inside the page frame and which palette surface it sits on. Decoration
 *  keeps ornaments; this carries no artwork. Absent means legacy rendering. */
export type SectionPresentationV1 = {
  schemaVersion: 1;
  inner?: "narrow" | "standard" | "wide" | "full";
  surface?: "default" | "muted" | "accent" | "inverse";
};

/** v2 adds a section anchor: buttons on the same page can point at `#anchor`.
 *  One namespace with rich-text heading anchors, unique on a page. */
export type SectionPresentationV2 = Omit<
  SectionPresentationV1,
  "schemaVersion"
> & {
  schemaVersion: 2;
  anchor?: string;
};

/** Visual directions a page can take (page presentation v2). */
export type PageStyle =
  | "editorial"
  | "product"
  | "studio"
  | "mosaic"
  | "premium"
  | "expert"
  | "organic"
  | "technical";

export type SiteFont =
  | "system"
  | "arial"
  | "georgia"
  | "trebuchet"
  | "verdana"
  | "inter"
  | "manrope"
  | "dm-sans"
  | "nunito"
  | "lora"
  | "playfair-display";

/** Stored with one page version. It never changes the header, footer,
 *  navigation or any other page; absent fields inherit the site appearance. */
export type PagePresentationV1 = {
  schemaVersion: 1;
  width?: "contained" | "full";
  headingFont?: SiteFont;
  bodyFont?: SiteFont;
};

export type PagePresentationV2 = Omit<PagePresentationV1, "schemaVersion"> & {
  schemaVersion: 2;
  style?: PageStyle;
};

export interface BlockRenderOptions {
  /** A draft never animates or exposes public controls. */
  preview?: boolean;
  locale?: "pl" | "en";
}

export type HeroV1Data = JsonObject & {
  heading: string;
  body?: string;
  ctaLabel?: string;
  ctaHref?: string;
};

export type HeroV2Data = JsonObject & {
  title: string;
  text?: string;
  action?: {
    label: string;
    href: string;
  };
};

export type HeroV3Data = HeroV2Data & {
  image?: {
    asset_id: string;
    alt: string;
  };
};

/** v6: the action may point at a section (`#anchor`) and a quieter second
 *  action sits beside it. */
export type HeroV6Data = HeroV3Data & {
  secondaryAction?: { label: string; href: string };
};

export type RichTextV1Data = JsonObject & {
  text: string;
};

/** One inline run. Marks are flags, links an allowlisted href; never HTML. */
export type RichTextSpan = {
  text: string;
  bold?: true;
  italic?: true;
  href?: string;
};
export type RichTextListItem = {
  content: RichTextSpan[];
  children?: {
    style: "bullet" | "ordered";
    items: { content: RichTextSpan[] }[];
  };
};
export type RichTextNode =
  | { type: "paragraph"; content: RichTextSpan[] }
  | { type: "heading"; level: 2 | 3 | 4; anchor: string; text: string }
  | {
      type: "list";
      style: "bullet" | "ordered";
      items: RichTextListItem[];
    }
  | {
      type: "quote";
      content: RichTextSpan[];
      author?: string;
      source?: string;
      href?: string;
    }
  | {
      type: "note";
      tone?: "info" | "tip" | "warning";
      title?: string;
      content: RichTextSpan[];
    }
  | {
      type: "figure";
      image: { asset_id: string; alt: string };
      caption?: string;
      width?: "column" | "wide";
    };
export type RichTextAsideNode = Extract<
  RichTextNode,
  { type: "paragraph" } | { type: "list" }
>;

export type RichTextV2Data = JsonObject & {
  layout?: "column" | "split_intro" | "facts_panel" | "chapters";
  title?: string;
  lead?: string;
  content: RichTextNode[];
  aside?: { title?: string; content: RichTextAsideNode[] };
};

/** v3 = v2 plus an optional call to action, an eyebrow, a side photograph and
 *  an author card; the sixteen added layouts arrange the same fields. */
export type RichTextV3Layout =
  | NonNullable<RichTextV2Data["layout"]>
  | "lead_statement"
  | "two_parts"
  | "side_photo"
  | "panorama"
  | "illustrated"
  | "margin_quote"
  | "summary_box"
  | "expert_note"
  | "alternating_chapters"
  | "timeline"
  | "numbered_sections"
  | "manifesto"
  | "problem_solution"
  | "howto"
  | "resources"
  | "essay_cta";

/** Spelled out: `Omit` over JsonObject's index signature would erase the
 *  named v2 fields. */
export type RichTextV3Data = JsonObject & {
  layout?: RichTextV3Layout;
  title?: string;
  lead?: string;
  content: RichTextNode[];
  aside?: RichTextV2Data["aside"];
  eyebrow?: string;
  image?: { asset_id: string; alt: string; caption?: string };
  author?: {
    name: string;
    role?: string;
    image?: { asset_id: string; alt: string };
  };
  action?: { label: string; href: string };
  secondaryAction?: { label: string; href: string };
};

/** Where a catalogue section sits on the visitor's path (catalogue v6). */
export type ConversionStage =
  "attention" | "interest" | "proof" | "objection" | "action";

export type FeatureListV1Data = JsonObject & {
  image?: { asset_id: string; alt: string };
  title?: string;
  items: { title: string; text?: string }[];
};

export type FeatureListV4Data = FeatureListV1Data & {
  layout?: string;
  lead?: string;
  note?: { title?: string; text: string };
};

export type QuoteV1Data = JsonObject & {
  layout?: "portrait";
  quote: string;
  author?: string;
  role?: string;
  source?: { label: string; href?: string };
  context?: string;
  image?: { asset_id: string; alt: string };
};

/** No price, stock or cart: those need real commerce capabilities. */
export type ProductV1Data = JsonObject & {
  layout?: "showcase";
  title: string;
  tagline?: string;
  text?: string;
  images?: { asset_id: string; alt: string; caption?: string }[];
  specs?: { label: string; value: string }[];
  uses?: { title: string; text?: string }[];
  action?: { label: string; href: string };
};

/** v2: actions may point at `#anchor`, plus a quieter second action. */
export type ProductV2Data = ProductV1Data & {
  secondaryAction?: { label: string; href: string };
};

export type FaqV1Data = JsonObject & {
  title?: string;
  items: { question: string; answer: string }[];
};

export type ContactV1Data = JsonObject & {
  title?: string;
  email?: string;
  phone?: string;
  address?: string;
};

export type ContactV2Data = ContactV1Data & {
  layout?: "classic" | "split" | "cards" | "band" | "photo" | "details";
  text?: string;
  hours?: string;
  action?: { label: string; href: string };
  image?: { asset_id: string; alt: string };
};

export type LinkListV1Data = JsonObject & {
  title?: string;
  text?: string;
  layout?: "buttons" | "icons" | "cards" | "list" | "split" | "band";
  links: { label: string; href: string; description?: string }[];
};

export type ContactFormV1Data = JsonObject & {
  title: string;
  text?: string;
  layout?: "split" | "centered" | "card" | "photo";
  locale?: "pl" | "en";
  submit_label?: string;
  success_message?: string;
  privacy_label?: string;
  privacy_href?: string;
  image?: { asset_id: string; alt: string };
};

/** Which contact details the form asks for (v2). Absent means `email`. */
export type ContactFormMode = "email" | "callback" | "full" | "email_only";
export type ContactFieldRule = "required" | "optional" | "hidden";
export type ContactFormV2Data = ContactFormV1Data & {
  contact?: ContactFormMode;
};

/** Runtime-only form adapter. A published snapshot never contains executable code. */
export type BlockFormRenderer = (data: ContactFormV2Data) => ReactNode;
export type PublishedFormRenderer = (
  data: ContactFormV2Data,
  blockPosition: number,
) => ReactNode;

export type TestimonialsV1Data = JsonObject & {
  title?: string;
  items: { quote: string; author: string; role?: string }[];
};

export type PricingV1Data = JsonObject & {
  title?: string;
  items: { name: string; price: string; description?: string }[];
};

export type BookingV1Data = JsonObject & {
  title: string;
  text?: string;
  action: { label: string; href: string };
};

export type FooterV1Data = JsonObject & {
  text: string;
  links?: { label: string; href: string }[];
};

export type EntryListV1Data = JsonObject & {
  title?: string;
  empty_text?: string;
  items: {
    title: string;
    path: string;
    excerpt?: string;
    published_at?: string;
  }[];
};

export type DesignTokensV1 = JsonObject & {
  schemaVersion: 1;
  palette: "neutral" | "blue" | "emerald";
  typography: "sans" | "serif";
  radius: "none" | "small" | "medium" | "large";
  spacing: "compact" | "comfortable" | "spacious";
};

export type BlockMigrator = (data: Readonly<JsonObject>) => JsonObject;

export interface BlockSchemaVersion {
  readonly version: number;
  readonly schema: object;
}

/** Catalogue categories from ADR-031. The panel groups and filters the section
 *  library by these; they are not part of the published data. */
export type BlockCategory =
  | "start"
  | "about"
  | "offer"
  | "trust"
  | "pricing"
  | "faq"
  | "contact"
  | "booking"
  | "footer"
  | "decorative";

/** `richText` binds a whole structured node array (core.rich_text v2
 *  `content`); the panel edits it with its own writing panel. */
export type BlockFieldKind =
  "text" | "textarea" | "url" | "list" | "media" | "richText" | "choice";

/** How one editable value inside a block is presented. Deliberately data, not a
 *  component: the same manifest is loaded by the public renderer, which must not
 *  pull the panel's UI package into a published page. */
export interface BlockFieldDefinition {
  /** Property path inside the block data — `["action", "label"]` for
   *  `data.action.label`. For a field inside a `list`, the path is relative to
   *  one item. */
  readonly path: readonly string[];
  readonly kind: BlockFieldKind;
  /** Key under the panel's `Sites.blockFields` messages. */
  readonly labelKey: string;
  /** Present on `kind: "media"`: the shape this picture is shown in, as
   *  `[width, height]`. The panel crops to it before sending, so a photo taken
   *  in portrait does not arrive as a letterboxed hero — the layout decides the
   *  frame, the operator decides what is inside it. */
  readonly aspect?: readonly [number, number];
  /** Present exactly when `kind` is `"list"`: the shape of a single entry. */
  readonly item?: readonly BlockFieldDefinition[];
  /** Present exactly when `kind` is `"choice"`: the allowed values; the first
   *  is what an absent value means. Labels live in the panel's messages. */
  readonly options?: readonly string[];
}

export interface BlockCatalogEntry {
  readonly category: BlockCategory;
  /** Key under the panel's `Sites.blockCatalog` messages. */
  readonly labelKey: string;
  readonly fields: readonly BlockFieldDefinition[];
}

/** An editor adapter is code supplied by the panel, never serialized block data. */
export type BlockTextRenderer = (
  path: readonly string[],
  value: string,
) => ReactNode;
export interface BlockEditor {
  readonly text: BlockTextRenderer;
}
/** Code-only media projection. Publications always use canonical public URLs. */
export type BlockImageRenderer = (image: {
  asset_id: string;
  alt: string;
}) => ReactNode;

export interface BlockComponentProps {
  data: JsonObject;
  /** Render options (publication vs preview, locale). Components use it for
   *  things only a publication may emit, such as heading ids. */
  options?: BlockRenderOptions;
  editor?: BlockEditor;
  imageRenderer?: BlockImageRenderer;
  formRenderer?: BlockFormRenderer;
}

export interface BlockDefinition {
  readonly type: string;
  readonly latestVersion: number;
  readonly schemas: readonly BlockSchemaVersion[];
  readonly migrators: Readonly<Record<number, BlockMigrator>>;
  readonly component: ComponentType<BlockComponentProps>;
  /** Absent for a block that exists only to render older publications and is no
   *  longer offered in the library. */
  readonly catalog?: BlockCatalogEntry;
}

export interface SiteBlockManifest {
  readonly moduleId: string;
  readonly namespace: string;
  readonly blocks: readonly BlockDefinition[];
}

export interface DraftPreviewDocument {
  readonly appearance?: SiteAppearance | null;
  readonly pagePresentation?: PagePresentationV1 | PagePresentationV2 | null;
  readonly kind: "draft-preview";
  readonly versionId: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
}

export interface NavigationLink {
  readonly page_id: string;
  readonly parent_page_id: string | null;
  readonly title: string;
  readonly path: string;
}

export interface IndexPagination {
  readonly page: number;
  readonly pages: number;
  readonly previous_path: string | null;
  readonly next_path: string | null;
}

export interface PaginationLabels {
  readonly label: string;
  readonly previous: string;
  readonly next: string;
  readonly position: (page: number, pages: number) => string;
}

export interface PublishedPageDocument {
  readonly locale?: "pl" | "en";
  readonly appearance?: SiteAppearance | null;
  readonly pagePresentation?: PagePresentationV1 | PagePresentationV2 | null;
  readonly kind: "publication";
  readonly publicationId: string;
  readonly snapshotHash: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
  readonly navigation?: readonly NavigationLink[];
  /** Accessible name for the menu, in the visitor's language. */
  readonly navigationLabel?: string;
  /** Present on a collection index. Without the links a reader reaches only
   *  the newest articles; the rest exist but nothing on the page leads there. */
  readonly pagination?: IndexPagination | null;
  readonly paginationLabels?: PaginationLabels;
}

export interface PageTemplateLabel {
  readonly name: string;
  readonly description: string;
}

export interface ApprovedTemplateMedia {
  readonly id: string;
  readonly source: string;
  readonly filename: string;
  readonly contentType: "image/jpeg" | "image/png" | "image/webp";
  readonly sha256: string;
}

/** A versioned, immutable recipe: applying it copies these blocks into a new
 *  draft, and later edits to the page never touch the template (ADR-031). */
export interface PageTemplate {
  readonly industries?: readonly string[];
  readonly sectionRefs?: readonly {
    position: number;
    id: string;
    version: number;
  }[];
  readonly id: string;
  readonly version: number;
  readonly category:
    "profile" | "landing" | "company" | "product" | "service" | "article";
  readonly labels: Readonly<Record<"pl" | "en", PageTemplateLabel>>;
  readonly requiredEntitlements?: readonly string[];
  readonly media?: readonly ApprovedTemplateMedia[];
  readonly localizedBlocks?: { readonly en: readonly SiteBlock[] };
  readonly mediaBindings?: readonly TemplateMediaBinding[];
  /** Recipe v4: copied into the imported page version. */
  readonly pagePresentation?: PagePresentationV1 | PagePresentationV2;
  /** Recipe v5: the page's goal and the path stage of every block. */
  readonly conversion?: {
    readonly goal: "inquiry" | "call" | "booking" | "email" | "visit";
    readonly stages: readonly ConversionStage[];
  };
  readonly blocks: readonly SiteBlock[];
}

/** Where an approved photo goes. `path` (recipe v4) addresses the image object
 *  inside the block data; the last segment is a key of an existing object or an
 *  index into an existing array no greater than its length. Absent: ["image"]. */
export interface TemplateMediaBinding {
  readonly blockPosition: number;
  readonly mediaId: string;
  readonly alt: Readonly<Record<"pl" | "en", string>>;
  readonly path?: readonly (string | number)[];
}

export interface BlockRegistry {
  readonly definitions: ReadonlyMap<string, BlockDefinition>;
  validate(block: SiteBlock): void;
  migrate(block: SiteBlock): SiteBlock;
  render(
    block: SiteBlock,
    key: string,
    editor?: BlockEditor,
    imageRenderer?: BlockImageRenderer,
    formRenderer?: BlockFormRenderer,
    options?: BlockRenderOptions,
  ): ReactElement;
}
