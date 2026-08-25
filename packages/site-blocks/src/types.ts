import type { ComponentType, ReactElement } from "react";

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonValue[] | JsonObject;
export type JsonObject = { [key: string]: JsonValue };

export interface SiteBlock<TData extends JsonObject = JsonObject> {
  readonly block_type: string;
  readonly schema_version: number;
  readonly data: TData;
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

export type RichTextV1Data = JsonObject & {
  text: string;
};

export type FeatureListV1Data = JsonObject & {
  title?: string;
  items: { title: string; text?: string }[];
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
  | "footer";

export type BlockFieldKind = "text" | "textarea" | "url" | "list";

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
  /** Present exactly when `kind` is `"list"`: the shape of a single entry. */
  readonly item?: readonly BlockFieldDefinition[];
}

export interface BlockCatalogEntry {
  readonly category: BlockCategory;
  /** Key under the panel's `Sites.blockCatalog` messages. */
  readonly labelKey: string;
  readonly fields: readonly BlockFieldDefinition[];
}

export interface BlockDefinition {
  readonly type: string;
  readonly latestVersion: number;
  readonly schemas: readonly BlockSchemaVersion[];
  readonly migrators: Readonly<Record<number, BlockMigrator>>;
  readonly component: ComponentType<{ data: JsonObject }>;
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
  readonly kind: "draft-preview";
  readonly versionId: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
}

export interface PublishedPageDocument {
  readonly kind: "publication";
  readonly publicationId: string;
  readonly snapshotHash: string;
  readonly blocks: readonly SiteBlock[];
  readonly designTokens: DesignTokensV1;
}

export interface PageTemplateLabel {
  readonly name: string;
  readonly description: string;
}

/** A versioned, immutable recipe: applying it copies these blocks into a new
 *  draft, and later edits to the page never touch the template (ADR-031). */
export interface PageTemplate {
  readonly id: string;
  readonly version: number;
  readonly category: "profile" | "landing" | "company";
  readonly labels: Readonly<Record<"pl" | "en", PageTemplateLabel>>;
  readonly requiredEntitlements?: readonly string[];
  readonly blocks: readonly SiteBlock[];
}

export interface BlockRegistry {
  readonly definitions: ReadonlyMap<string, BlockDefinition>;
  validate(block: SiteBlock): void;
  migrate(block: SiteBlock): SiteBlock;
  render(block: SiteBlock, key: string): ReactElement;
}
